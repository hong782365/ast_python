# publisher.py 请求与流处理整体梳理

本文按照时间顺序，梳理从 FastAPI 接收到 `/python/ingest/start` 请求开始，到 HTTP 响应返回以及后台 WebSocket 处理的完整流程。内容覆盖 `publisher.py` 及其依赖的 `ast_youtube_demo.py` 中涉及的所有关键逻辑，便于第二人审核。

## 1. 服务启动与生命周期管理
- 入口脚本位于 `publisher.py`，启动时会输出基础日志并通过 `dotenv.load_dotenv()` 读取环境变量。
- FastAPI 应用使用 `lifespan()` 上下文（`publisher.py:53`）控制生命周期：
  - 启动阶段异步调用 `ytdlp_manager.warmup()` 预热 YouTube 抓流能力，失败仅告警。
  - 关闭阶段调用 `ytdlp_manager.cleanup()`，确保资源释放。
- 关键环境变量：`APP_KEY`、`ACCESS_KEY`、`RESOURCE_ID`、`WS_URL`，缺失将导致启动任务失败。

## 2. HTTP 入口 `/python/ingest/start`
- 请求体模型 `IngestStartRequest`（`publisher.py:79`）包含 `sessionId`、`youtube_url`、`publishUrl`。
- 入参校验：
  - `youtube_url` 必须以 `http://` 或 `https://` 开头。
  - `publishUrl` 必须以 `ws://` 或 `wss://` 开头。
- 校验通过后调用全局单例 `publisher: AudioStreamPublisher` 的 `start_publishing_session()`。
- 根据返回的 `status_code` 构造响应：
  - 201：新建会话成功，返回 `IngestStartResponse`。
  - 202：会话已存在且仍在运行，通过 `JSONResponse` 返回，保持幂等。
  - 409：容器当前有其他会话运行，直接抛出 `HTTPException`。
- `start_ingest` 捕获过程中任何异常并返回 500。

## 3. 会话管理与状态机 (`AudioStreamPublisher`)
- `PublisherSession` 数据类（`publisher.py:102`）记录会话元数据：
  - `session_id`、`youtube_url`、`publish_url`、`status`、`created_at`。
  - 运行态引用：`task`（后台协程）、`stop_event`、`publisher_ws`（对下游 WebSocket 客户端的持有）。
- `start_publishing_session()` 核心逻辑：
  1. 维护活跃状态列表：`initializing`、`starting`、`connected_to_publisher`、`processing_audio`，用于判定并发限制。
  2. 如果 `session_id` 已存在：
     - 状态仍活跃，则直接返回 `(session_id, False, 202)` 幂等响应。
     - 状态非活跃，则执行 `_cleanup_session()` 清理后重新建立。
  3. 如果有其他 session 处于活跃状态，拒绝新建返回 409（单容器单会话约束）。
  4. 创建新的 `PublisherSession`，初始状态 `initializing`，携带 `asyncio.Event` 作为 `stop_event`。
  5. 使用 `asyncio.create_task()` 启动 `_publish_audio_stream(session)` 后台任务，并添加 `add_done_callback`，在任务结束后记录最终状态并触发后续清理。

## 4. 后台任务 `_publish_audio_stream`
- 任务执行路径：
  1. 更新状态为 `starting`，日志记录会话信息。
  2. 检查关键环境变量，缺失直接抛错。
  3. 构造翻译配置 `Config`（`ast_youtube_demo.Config`）。
  4. 初始化 `WebSocketPublishClient` 指向请求中的 `publishUrl`，调用 `connect()` 与外部发布端建联，成功后状态置为 `connected_to_publisher` 并保存引用到 `session.publisher_ws`。
  5. 状态更新为 `processing_audio`，调用 `_stream_translated_audio(config, session, ws_client)` 驱动翻译流。
- 异常与收尾：
  - 捕获 `asyncio.CancelledError`，说明 stop 或超时触发，状态置为 `stopped` 并重新抛出以保持协程取消语义。
  - 其他异常记录为失败，状态置为 `failed`。
  - `finally` 块仅在状态不为 `failed`/`stopped` 时把会话标记为 `completed`，避免覆盖异常状态。

## 5. 发布端 WebSocket (`WebSocketPublishClient`)
- 负责与外部消费者（`publishUrl`）的 WebSocket 交互，确保音频/字幕对外转发。
- `connect()`（`publisher.py:493`）：
  - 使用 `websockets.connect()`，设置 `ping_interval=20`、`ping_timeout=10`、`max_size=1GB`。
  - 失败时指数退避重试（最多 10 次）并记录日志。
  - 成功后启动 `_heartbeat_loop()`，每 30s 发送一次 `ping` 保活，重置计数器、记录开始时间。
- `send_audio_frame()`：
  - 若连接不存在则尝试重连。
  - 发送二进制 PCM 帧，统计 `frame_count`，每 100 帧打印速率。
  - 捕获 `ConnectionClosed`/`WebSocketException` 时自动重连并重试发送。
- `send_text_message()`：
  - 同样具有断线重连机制，用于发送字幕或系统事件（JSON 字符串）。
- `disconnect()`：
  - 取消心跳任务，关闭 WebSocket。
  - 汇报会话持续时间、发送帧数与平均速率。

## 6. 流水线核心：`translate_youtube_live_stream`
该协程生成器位于 `ast_youtube_demo.py:1491`，负责：
1. 从 YouTube 抓取音频流（FFmpeg）并读为 PCM 数据。
2. 与字节跳动同声传译服务通过 WebSocket 交互，发送音频请求并接收音频 + 字幕响应。
3. 根据直播校验结果控制是否向下游发布真实音频，必要时输出错误。

### 6.1 并行初始化阶段
- **Phase 1：翻译服务建联**
  - 调用 `connect_websocket_and_start_session()`（`ast_youtube_demo.py:1293`）：
    - 构造鉴权头（`X-Api-App-Key` 等），连接 `WS_URL`。
    - 随机生成 `session_id`，发送 `Type_StartSession` 请求（protobuf），等待 `Type.SessionStarted`。
    - 返回 `(conn, session_id, log_id, ws_connect_duration)`。
- **Phase 2：后台任务并行启动**
  - `ffmpeg_task = streamer.start_streaming_pipeline()`：
    - `YouTubeLiveStreamer` 负责：
      - 通过 `YtDlpManager.extract_stream_url()` 提取直播音频直链（线程池执行，支持 warmup）。
      - 根据环境（Cloudflare/本地）选择日志策略。
      - 组装 FFmpeg 命令，启用低延迟参数（`-fflags nobuffer` 等），从直链抓流输出 16kHz mono PCM；记录 `ffmpeg_process`、`pcm_stream` 及 spawn 时间；启动日志/健康监控。
  - `live_check_task = ytdlp_manager.check_live_status()`：
    - 使用 yt-dlp 轻量查询直播状态，返回 `is_live`、`live_status`、`title` 等。
- **Phase 3：等待翻译 WebSocket 准备就绪**
  - 先等待 Phase 1 完成，以便尽快发送静音桥数据。
  - 创建两个同步原语：`audio_ready_event`（首帧 PCM 就绪）、`live_check_passed_event`（直播检查通过）。
  - 创建 `stream_queue`（给调用方的数据缓冲）与 `finished` 事件。

### 6.2 静音桥与两阶段门控
- Phase 4 中立即启动 `send_silence_until_ready_with_live_check()`（`ast_youtube_demo.py:1159`）：
  - 每 20ms 向翻译服务发送 640 字节静音帧 (`Type_TaskRequest`)，直到 **首帧 PCM 就绪** 且 **直播检查通过** 或达到超时。
  - 期间持续记录帧数与耗时；若超时会记录最终状态。
- `read_pcm_chunks()`（`ast_youtube_demo.py:1357`）负责读取 FFmpeg 输出：
  - 对首帧设置 30s 超时，其余帧 10s 超时，连续超时 3 次判定断流。
  - 首帧到达时触发 `audio_ready_event`，并输出性能日志。

### 6.3 PCM 发送任务
- `send_pcm_chunks()` 闭包在 Phase 4 定义，于 Phase 6 启动：
  - 首先确认 FFmpeg 仍存活，否则直接结束。
  - 迭代 `read_pcm_chunks()` 输出：
    - 若外部 `stop_event` 被置位，则记录后跳出循环，准备结束流程。
    - 在两阶段门控未全部满足前丢弃真实音频，以保持管道畅通。
    - 条件满足后，将 PCM chunk 封装为 `TranslateRequestData(event="Type_TaskRequest")`，通过 `send_request()` 序列化为 protobuf 并发送。
    - 借助 `ASTEventLogger`（`ast_youtube_demo.py:198`）记录关键事件，控制日志频率。
  - 循环结束后（自然停止或 stop 信号）发送一次 `Type_FinishSession` 请求，确保翻译服务进入收尾阶段。

### 6.4 响应接收与出队
- `receive_responses()` 闭包与 Phase 6 同时启动：
  - 根据 `stop_event` 启动宽限期计时，在 2s 超时窗口内等待翻译服务响应。
  - 使用 `receive_message()` 解包 protobuf，转换为 `TranslateResponseData`。
  - 处理事件：
    - `SessionFailed`/`SessionCanceled`：记失败，置 `finished`。
    - `SessionFinished`：正常结束。
    - 字幕事件（650-655）：调用 `map_event_to_subtitle_json()` 生成 JSON，压入 `stream_queue`。
    - 若 `resp.data` 非空（TTS PCM），压入 `StreamData(data_type="audio")`。
    - 对 `UsageResponse`/`SessionFinished` 额外生成 `system_event` JSON，带出计费信息。
  - 所有响应事件均交给 `ASTEventLogger` 记录。

### 6.5 直播校验与数据产出
- Phase 5 等待 FFmpeg 打开后立即启动发送/接收任务（Phase 6）。
- Phase 7 等待 `live_check_task` 完成，执行 `is_live_valid()`：
  - 允许状态：`is_live=True` 或 `live_status == "is_live"`。
  - 其他状态映射为错误码（如 `LIVE_NOT_STARTED`、`LIVE_ENDED` 等）。
- 若校验失败：
  - 取消静音桥、发送、接收任务，调用 `build_error_json()` 组装错误描述。
  - 再次发送 `FinishSession`，关闭翻译 WebSocket。
  - `yield StreamData(data_type="error", content=<error_json>)`，终止生成器。
- 校验通过：
  - 设置 `live_check_passed_event`，允许真实音频发送。
  - 主循环持续 `await stream_queue.get()`：
    - 若拿到 1s 内的音频/字幕数据即 `yield` 给调用方。
    - 1s 超时则继续等待，直到 `finished` 被置位。
  - `finally` 中用 `asyncio.shield` 确保：
    - 等待静音桥、发送、接收任务退出，捕获异常。
    - 调用 `conn.close()` 关闭翻译 WebSocket。
- 整个 `try`/`finally` 结束后进行资源清理。

### 6.6 生成给上游的 `StreamData`
- `StreamData`（`ast_youtube_demo.StreamData`）类型：
  - `data_type="audio"`：二进制 PCM，供 `WebSocketPublishClient.send_audio_frame()` 直接转发。
  - `data_type="subtitle"`：JSON 字符串，包含源/译字幕、系统消息等。
  - `data_type="error"`：直播校验失败时的 JSON 描述。

## 7. 停止流程与清理
- HTTP `/python/ingest/stop` 调用 `stop_publishing_session()`：
  - 如果找不到会话返回 True（幂等）。
  - 将 `stop_event` 置位，状态更新为 `stopping`，异步启动 `_grace_period_supervisor()`。
- `_grace_period_supervisor()`：
  - 读取环境变量 `FINISH_GRACE_TIMEOUT`（默认 30s）。
  - `await session.task` 等待后台任务自然结束；超时则取消任务并标记 `stopped`。
  - 无论成功与否都会执行 `_background_cleanup()`。
- `_background_cleanup()`：分阶段清理资源：
  1. 立即触发关键断连：调用 `publisher_ws.disconnect()`（通过 `asyncio.create_task` 并行执行）。
  2. 最多等待 3s 让主任务退出；随后等待最多 5s 等所有清理任务完成。
  3. 调用 `_cleanup_session()` 做兜底清理，然后把会话从 `sessions` 字典移除。
  4. 如果任一阶段出错，仍会尝试 `_cleanup_session()` 并最终移除字典条目。
- `_cleanup_session()` 负责：
  - 取消仍在运行的任务（1s 超时）。
  - 断开 `publisher_ws`。
  - 不移除字典条目，交由 `_background_cleanup()` 统一处理，避免竞态。

## 8. HTTP 响应与其他接口
- `/python/ingest/start`：请求返回时后台任务尚在运行，调用方只得到会话是否成功建起的结果。
- `/python/ingest/stop`：幂等地触发后台停止流程，始终返回成功。
- `/python/health`：简单健康检查。
- `/python/sessions`：返回当前 `publisher.sessions` 中的会话列表（即使部分状态已结束但尚未被清理线程移除）。

## 9. 关键依赖与对象关系
- `AudioStreamPublisher` 单例维护所有会话和任务引用。
- `YouTubeLiveStreamer` 封装 yt-dlp + FFmpeg 管道，同时管理日志、健康监控与资源释放。
- `YtDlpManager` 负责提取直播流直链、检查直播状态，生命周期由 FastAPI `lifespan` 保证。
- `WebSocketPublishClient` 对接外部发布端；翻译服务的 WebSocket 由 `translate_youtube_live_stream` 内部维护。
- `ASTEventLogger` 统一记录翻译请求/响应事件，方便排查。

## 10. 请求到响应的整体时序概览
1. 客户端调用 `/python/ingest/start`，通过模型校验。
2. `AudioStreamPublisher.start_publishing_session()` 检查并发限制，初始化 `PublisherSession`，启动 `_publish_audio_stream`。
3. HTTP 立即返回成功 (201/202)；后台任务继续执行。
4. `_publish_audio_stream`：
   - 建立与 `publishUrl` 的 WebSocket 连接。
   - 调用 `translate_youtube_live_stream` 获取 `StreamData` 序列。
5. `translate_youtube_live_stream` 内部：
   - 并行建立翻译服务会话、启动 FFmpeg 拉流、检查直播状态。
   - 静音桥保持翻译会话存活，首包到达后与直播校验一起决定是否发送真实音频。
   - 不断读取翻译响应，依次 `yield` 音频/字幕/系统事件。
6. `_stream_translated_audio` 消费 `StreamData`：
   - 音频通过 `WebSocketPublishClient.send_audio_frame()` 转发到外部。
   - 字幕与系统消息通过 `send_text_message()` 发送。
   - 错误数据直接透传，标记会话失败。
7. 会话停止或完成后，`stop_event`、`FinishSession`、`finished` 事件协同结束所有协程，关闭双方 WebSocket，释放 FFmpeg。
8. `_grace_period_supervisor` 和 `_background_cleanup` 负责兜底清理，最终从会话字典移除。

---

以上为 `publisher.py` 及其依赖的主要逻辑流转，涵盖请求入口、后台流水线、对外 WebSocket 发送、直播校验、停止与清理的全过程。若需要检查具体实现，可对照文中标注的函数与文件位置进行代码级验证。
