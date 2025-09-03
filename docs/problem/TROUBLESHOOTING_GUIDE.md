# WebSocket Publisher 文本帧转发功能开发与问题解决指南

## 项目概述

本文档记录了在 WebSocket Publisher 中增加原文和译文转发功能的完整开发过程，包括遇到的技术问题、分析过程和最终解决方案。

## 功能需求

**原始需求**：WebSocket Publisher 不仅转发音频流，同时转发原文和译文。

**技术要求**：
- 参考同声传译2.0-API接入文档
- 文本帧的 event 值为 650-655
- 与音频流一样，不做任何处理，直接转发文本帧

**文本帧事件类型**：
- 650: SourceSubtitleStart (原文开始)
- 651: SourceSubtitleResponse (原文数据) 
- 652: SourceSubtitleEnd (原文结束)
- 653: TranslationSubtitleStart (译文开始)
- 654: TranslationSubtitleResponse (译文数据)
- 655: TranslationSubtitleEnd (译文结束)

## 初始实现方案

### 1. 修改 `ast_youtube_demo.py`

**目标**：修改 `translate_youtube_live_stream` 函数，使其返回音频和文本帧的组合数据

**关键修改**：
```python
# 旧版本：只返回音频数据
async for audio_chunk in translate_youtube_live_stream():
    yield audio_chunk

# 新版本：返回数据帧结构
async for data_frame in translate_youtube_live_stream():
    if data_frame['type'] == 'audio':
        # 音频帧：{'type': 'audio', 'data': bytes}
    elif data_frame['type'] == 'text':
        # 文本帧：{'type': 'text', 'event': int, 'text': str, ...}
```

**实现细节**：
- 统一数据队列处理音频和文本帧
- 处理 event 650-655 的文本帧事件
- 保持原有音频处理逻辑不变

### 2. 更新 `WebSocketPublishClient` 类

**目标**：支持发送文本帧（JSON 格式）

**新增方法**：
```python
async def send_text_frame(self, text_frame: dict):
    """发送文本帧（JSON 格式）"""
    text_message = json.dumps(text_frame)
    await self.websocket.send(text_message)
```

### 3. 修改 Publisher 主逻辑

**目标**：处理音频和文本帧的转发

**实现逻辑**：
```python
if data_frame.get('type') == 'audio':
    await ws_client.send_audio_frame(data_frame['data'])
elif data_frame.get('type') == 'text':
    await ws_client.send_text_frame(data_frame)
```

## 遇到的问题

### 问题现象

实现功能后，测试时出现以下错误：

1. **第一次测试**：成功
2. **第二次测试**：`no close frame received or sent` (WebSocket 1006 错误)
3. **第三次测试**：`Client closed request / context cancelled`

### 初步分析与错误假设

**ChatGPT 分析结论**：
> 更像是Python 端在引入"文本消息"后，内部协程竞争/并发 send/recv 导致同传或 publish 的一侧崩溃，随后连带另一侧"发送 PCM"也跟着失败。

**错误假设**：并发 WebSocket send 操作导致协议错误

## 错误的解决尝试

### 方案1：添加发送锁

**思路**：使用 `asyncio.Lock` 串行化所有 WebSocket 发送操作

```python
class WebSocketPublishClient:
    def __init__(self):
        self.send_lock = asyncio.Lock()
    
    async def send_audio_frame(self, audio_chunk: bytes):
        async with self.send_lock:
            await self.websocket.send(audio_chunk)
    
    async def send_text_frame(self, text_frame: dict):
        async with self.send_lock:
            await self.websocket.send(json.dumps(text_frame))
```

**结果**：问题依然存在

### 方案2：消息队列 + 专用发送协程

**思路**：采用生产者-消费者模式，完全消除并发发送

```python
class WebSocketPublishClient:
    def __init__(self):
        self.send_queue = asyncio.Queue()
        self.sender_task = None
    
    async def _sender_loop(self):
        """专用发送协程，串行处理所有发送"""
        while self.is_running:
            message = await self.send_queue.get()
            await self.websocket.send(message['data'])
            await asyncio.sleep(0)  # 让出事件循环控制权
    
    async def send_audio_frame(self, audio_chunk: bytes):
        await self.send_queue.put({'type': 'audio', 'data': audio_chunk})
    
    async def send_text_frame(self, text_frame: dict):
        text_message = json.dumps(text_frame)
        await self.send_queue.put({'type': 'text', 'data': text_message})
```

**结果**：问题依然存在

## 问题根因发现

### 添加详细监控日志

为了找到真正的问题原因，添加了全面的监控日志系统：

**监控内容**：
- 连接状态和时序
- 数据流统计（音频/文本帧数量）
- 队列状态和积压警告
- WebSocket 发送时间
- 错误详情和堆栈跟踪

**关键日志配置**：
```python
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
)
```

### 真正的问题根因

通过详细的监控日志分析，发现了真正的问题：

**关键时间线**：
```
23:58:09.419 - 翻译会话启动成功
23:58:19.384 - 开始发送 PCM 音频块（延迟 10 秒！）
23:58:19.894 - 收到 SessionFailed 错误
```

**根本原因**：
1. **YouTube HLS 流启动延迟**：需要 10-15 秒来建立音频流
2. **翻译服务严格超时**：10 秒内没收到音频数据就关闭会话
3. **时序冲突**：音频流启动时间 > 翻译服务超时时间

**错误信息**：`[Timeout waiting next packet] waiting next packet timeout, session has ended`

**重要发现**：问题与并发发送无关，而是 YouTube 直播流的固有延迟导致的超时问题！

## 最终解决方案

### 音频预缓冲机制

**核心思路**：延迟建立翻译连接，等音频流稳定后再连接翻译服务

**实现步骤**：

1. **启动 YouTube 流并预缓冲**：
```python
# 预缓冲音频避免翻译服务超时
logging.info("Pre-buffering audio to avoid translation service timeout...")
audio_buffer = []
buffer_start_time = time.time()

# 缓冲音频直到有足够数据（至少5秒）
async for chunk in read_pcm_chunks(pcm_stream):
    audio_buffer.append(chunk)
    buffer_duration = time.time() - buffer_start_time
    
    if len(audio_buffer) >= 50 or buffer_duration >= 15:
        logging.info(f"Audio buffer ready: {len(audio_buffer)} chunks in {buffer_duration:.1f}s")
        break
```

2. **连接翻译服务**：
```python
# 现在连接翻译服务，此时已有缓冲音频可立即发送
conn = await websockets.connect(conf.ws_url, ...)
# 启动翻译会话
await send_request(conn, start_request)
```

3. **发送缓冲数据 + 实时流**：
```python
async def send_pcm_chunks():
    # 首先发送所有缓冲的音频块
    for chunk in audio_buffer:
        chunk_request = TranslateRequestData(...)
        await send_request(conn, chunk_request)
        await asyncio.sleep(0.01)  # 快速发送缓冲数据
    
    # 继续处理实时音频流
    async for chunk in read_pcm_chunks(pcm_stream):
        chunk_request = TranslateRequestData(...)
        await send_request(conn, chunk_request)
        await asyncio.sleep(0.02)  # 正常速率
```

### 新的时序流程

**优化后的时序**：
```
00:00 - 启动 YouTube 流，开始缓冲
00:10 - 音频缓冲就绪（50个音频块）
00:10 - 连接翻译服务
00:10 - 立即发送缓冲数据（避免超时）
00:11+ - 继续处理实时音频和文本流
```

## 解决效果

### 问题解决

✅ **完全解决了以下错误**：
- `[Timeout waiting next packet] waiting next packet timeout`
- `no close frame received or sent` (WebSocket 1006)
- `Client closed request / context cancelled`
- 翻译服务会话异常终止

### 功能实现

✅ **成功实现了所有需求**：
- 音频流转发（保持原有功能）
- 文本帧转发（新增功能）
- 原文和译文的完整传输
- 事件类型 650-655 的正确处理

## 技术总结

### 关键经验

1. **问题分析的重要性**：
   - 详细的监控日志是定位问题的关键
   - 不要过早假设问题原因
   - 时序分析比代码逻辑分析更重要

2. **异步编程最佳实践**：
   - 消息队列模式确实有效（虽然这次不是根因）
   - 事件循环让权 (`await asyncio.sleep(0)`) 很重要
   - 详细的错误处理和状态监控必不可少

3. **外部服务集成注意事项**：
   - 了解外部服务的超时机制
   - 考虑网络延迟和缓冲需求
   - 设计合适的重试和容错机制

### 架构改进

**最终架构**：
```
YouTube HLS Stream -> Audio Buffer -> Translation Service
                                   -> Audio + Text Frames
                                   -> WebSocket Publisher
                                   -> Message Queue
                                   -> Dedicated Sender
                                   -> Client WebSocket
```

**关键组件**：
- **音频预缓冲**：解决启动延迟问题
- **消息队列**：保证发送顺序和稳定性
- **专用发送协程**：避免并发冲突
- **详细监控**：便于问题诊断

## 文件清单

### 修改的文件

1. **`ast_youtube_demo.py`**
   - 添加音频预缓冲机制
   - 修改数据帧格式（音频+文本）
   - 增强监控日志

2. **`publisher.py`**
   - 实现消息队列发送机制
   - 添加文本帧处理
   - 增强错误处理和监控

### 核心代码片段

**数据帧格式**：
```python
# 音频帧
{
    'type': 'audio',
    'data': bytes  # PCM 音频数据
}

# 文本帧
{
    'type': 'text',
    'event': int,      # 650-655 事件代码
    'text': str,       # 文本内容
    'start_time': int, # 开始时间（可选）
    'end_time': int    # 结束时间（可选）
}
```

## 后续建议

### 监控和维护

1. **保持详细日志**：生产环境建议保留 INFO 级别的关键日志
2. **监控指标**：
   - 音频缓冲时间
   - 翻译服务响应时间
   - 队列积压情况
   - WebSocket 连接稳定性

### 可能的优化

1. **自适应缓冲**：根据网络状况动态调整缓冲大小
2. **健康检查**：定期检查各组件状态
3. **故障恢复**：实现自动重连和状态恢复机制

---

*文档创建时间：2025-08-20*  
*问题解决耗时：约4小时*  
*关键突破点：详细监控日志 + 时序分析*
