# Audio Stream Publisher 架构梳理

本文梳理从 `main.py` 启动 FastAPI 服务，到 `/python/ingest/start` 请求触发音频翻译，再到 `/python/ingest/stop` 结束会话的完整逻辑。重构后代码被划分为 `core/`、`streaming/`、`publisher/` 三个层次，本文按执行顺序说明各模块职责与协作方式。

## 1. 启动流程
- 入口脚本 `main.py`
  - 导入 `core.config`，调用 `setup_logging()` 配置日志后再加载 FastAPI 应用。
  - 直接运行脚本时使用 `uvicorn.run(app, host="0.0.0.0", port=9000)` 启动服务。
- 配置模块 `core/config.py`
  - 在导入阶段读取 `.env`，计算项目基准路径 (`BASE_DIR`)、protobuf 目录 (`PROTO_DIR`)、日志目录等，并确保 `PROTO_DIR` 已加入 `sys.path`。
  - 暴露 `APP_KEY`、`ACCESS_KEY` 等配置常量，以及 `setup_logging()`、`validate_config()`、`ensure_directories()` 等工具函数。
- 生命周期管理 `publisher/lifespan.py`
  - 在 FastAPI `startup`：验证环境变量、创建日志/FFmpeg/事件目录，获取 `streaming.get_manager()` 并执行 `warmup()`。
  - 在 `shutdown`：再次获取 `ytdlp_manager` 执行 `cleanup()`。

## 2. FastAPI 应用与路由
- `publisher/__init__.py`
  - 创建 FastAPI 实例 (`lifespan=lifespan`) 并挂载 `publisher/routes.py` 中定义的路由。
- `publisher/routes.py`
  - 定义 `/python/ingest/start`、`/python/ingest/stop`、`/python/health`、`/python/sessions` 四个接口。
  - 请求中通过 `get_publisher()` 获取全局的 `AudioStreamPublisher` 实例，并调用其方法处理业务。

## 3. 请求数据模型与会话结构
- `publisher/models.py`
  - 定义 Pydantic 请求/响应模型 `IngestStartRequest`、`IngestStartResponse`、`IngestStopRequest`、`IngestStopResponse`。
  - 定义会话数据类 `PublisherSession`（保存会话状态、后台任务、WebSocket 客户端引用等）。

## 4. 会话管理 (`publisher/session_manager.py`)
- `AudioStreamPublisher`
  - `start_publishing_session()`：
    - 检查单容器单会话约束；若同 `sessionId` 已运行则返回 202，否则创建新会话。
    - 启动后台任务 `_publish_audio_stream()` 并记录 `PublisherSession`。
  - `stop_publishing_session()`：
    - 将 `stop_event` 置为已触发，状态改为 `stopping`，并启动 `_grace_period_supervisor()` 处理宽限期和清理。
  - `_publish_audio_stream()`：
    - 构造 `streaming.models.Config`（使用 `core.config` 中的 `APP_KEY` 等），连接下游发布端 WebSocket（`WebSocketPublishClient`）。
    - 调用 `streaming.pipeline.translate_youtube_live_stream()` 获取音频/字幕流，并通过 `WebSocketPublishClient` 转发。
    - 依据异常情况更新会话状态（`completed`、`failed`、`stopped`）。
  - `_stream_translated_audio()`：消费 `StreamData`（`audio`/`subtitle`/`error`）并转发给发布端 WebSocket。
  - `_grace_period_supervisor()`、`_background_cleanup()`、`_cleanup_session()` 负责在停止时协调任务、关闭连接、释放资源。
- `get_publisher()`：懒加载单例，确保全局只存在一个 `AudioStreamPublisher`。

## 5. 发布端 WebSocket 客户端 (`publisher/websocket_client.py`)
- `WebSocketPublishClient` 封装与下游发布服务的 WebSocket 交互：
  - `connect()`：指数退避重连、建立 `ping` 心跳。
  - `send_audio_frame()` / `send_text_message()`：自动重连并重发失败的消息。
  - `disconnect()`：关闭心跳任务与 WebSocket，打印统计信息。

## 6. 流媒体流水线 (`streaming/`)
- `streaming/models.py`
  - 定义翻译域的基础数据结构：`Config`、`Audio`、`TranslateRequestData`、`TranslateResponseData`、`StreamData` 等。
- `streaming/logger.py`
  - `safe_serialize_protobuf()`、`log_protobuf_message()` 打印原始 protobuf；`ASTEventLogger` 记录会话事件到 `core.config.AST_EVENT_DIR`。
- `streaming/proto_helpers.py`
  - `connect_websocket_and_start_session()` 建立与翻译服务的 WebSocket 连接并发送 `StartSession`。
  - `send_request()`、`receive_message()` 负责 protobuf 序列化/反序列化。
- `streaming/silence_bridge.py`
  - `send_silence_until_ready()` 在真实 PCM 就绪前持续发送静音帧，保持翻译会话活跃。
- `streaming/pcm_reader.py`
  - `read_pcm_chunks()` 从 FFmpeg stdout 读取 640 字节 PCM 块，带有超时与首包监控。
- `streaming/streamer.py`
  - `YouTubeLiveStreamer` 通过 `streaming.ytdlp_manager.get_manager()` 提取直播流 URL，并启动 FFmpeg 拉流，负责日志/健康监控与清理。
- `streaming/ytdlp_manager.py`
  - `YtDlpManager` 管理 yt-dlp 线程池、预热、URL 提取和清理；`get_manager()` 提供惰性单例访问。
- `streaming/pipeline.py`
  - `translate_youtube_live_stream()` 协调上述组件：
    1. 并行建立翻译 WebSocket 与 FFmpeg 管道。
    2. 启动静音桥 `send_silence_until_ready()` 维持会话。
    3. 读取 `read_pcm_chunks()` 输出，丢弃首帧前的音频，随后发送真实 PCM。
    4. 接收翻译服务响应（字幕、TTS、系统事件），打包为 `StreamData` 供上层消费。
    5. 处理 `stop_event`、宽限期、异常与清理（`asyncio.shield` 保证关键任务完成）。

## 7. 停止与清理流程
- 接收 `/python/ingest/stop` 后，`AudioStreamPublisher.stop_publishing_session()` 触发：
  1. 设置 `stop_event`，状态改为 `stopping`。
  2. `_grace_period_supervisor()` 在配置的宽限期内等待后台任务自然结束，超时则取消。
  3. `_background_cleanup()` 依次断开发布端 WebSocket、等待任务/清理协程完成、调用 `_cleanup_session()` 释放资源，并最终从字典移除会话。
  4. `_cleanup_session()` 负责兜底取消任务、关闭 WebSocket。

## 8. 请求到响应的时序总览
```
客户端 -> /python/ingest/start
  └─> publisher/routes.start_ingest
       └─> AudioStreamPublisher.start_publishing_session
            ├─(检查并发/状态)
            ├─启动 _publish_audio_stream
            │    ├─创建 Config、连接发布端 WS
            │    ├─调用 streaming.pipeline.translate_youtube_live_stream
            │    │    ├─连接翻译 WS、启动 FFmpeg、静音桥
            │    │    ├─读取 PCM + 转发字幕/音频
            │    │    └─处理 stop_event 与清理
            │    └─根据 StreamData 转发音频/字幕
            └─返回 201/202/409
```
- `/python/ingest/stop` 触发 `stop_event` 并进入宽限期；`/python/sessions` 用于观察当前会话列表；`/python/health` 简单返回服务状态。

---

以上内容覆盖新架构下的主要模块、流程与协作关系，可据此定位具体实现位置并进行代码级验证。EOF
