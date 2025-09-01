# VolcEngine API协议详述

## 协议概述

VolcEngine同声传译API采用**WebSocket双向通信**模式，基于Protocol Buffers序列化，实现实时音频流的收发处理。协议设计支持会话生命周期管理、音频数据传输、翻译结果接收等核心功能。

## WebSocket连接协议

### 1. 连接建立

#### 连接URL格式
```
wss://openspeech.bytedance.com/api/v2/ast
```

#### 认证头部
```python
headers = {
    "X-Api-App-Key": app_key,        # 应用标识
    "X-Api-Access-Key": access_key,  # 访问密钥  
    "X-Api-Resource-Id": resource_id, # 资源ID
    "X-Api-Connect-Id": connect_id   # 连接唯一标识(UUID)
}
```

#### 连接参数
```python
websocket_config = {
    "max_size": 1000000000,  # 最大消息大小(1GB)
    "ping_interval": None,   # 禁用自动ping
    "ping_timeout": None     # 禁用ping超时
}
```

### 2. 连接响应头部

成功连接后，服务端返回关键头部：
```python
log_id = conn.response.headers.get('X-Tt-Logid')  # 日志追踪ID
```

## Protobuf消息协议

### 1. 请求消息结构

#### TranslateRequest主结构
```protobuf
message TranslateRequest {
    RequestMeta request_meta = 1;    // 请求元数据
    Type event = 2;                  // 事件类型
    User user = 3;                   // 用户信息
    Audio source_audio = 4;          // 源音频
    Audio target_audio = 5;          // 目标音频格式
    ReqParams request = 6;           // 请求参数
}
```

#### RequestMeta结构
```protobuf
message RequestMeta {
    string SessionID = 1;    // 会话ID
    int32 Sequence = 2;      // 序列号(自动递增)
    string Message = 3;      // 附加消息
}
```

#### User结构  
```protobuf
message User {
    string uid = 1;    // 用户ID(固定值: "ast_py_client")
    string did = 2;    // 设备ID(固定值: "ast_py_client")
}
```

#### Audio结构
```protobuf
message Audio {
    string format = 1;      // 音频格式
    int32 rate = 2;         // 采样率
    int32 bits = 3;         // 位深度
    int32 channel = 4;      // 声道数
    bytes binary_data = 5;  // 音频二进制数据
}
```

#### ReqParams结构
```protobuf
message ReqParams {
    string mode = 1;              // 模式(固定值: "s2s")
    string source_language = 2;   // 源语言
    string target_language = 3;   // 目标语言
}
```

### 2. 响应消息结构

#### TranslateResponse主结构
```protobuf
message TranslateResponse {
    ResponseMeta response_meta = 1;  // 响应元数据
    Type event = 2;                  // 事件类型
    string text = 3;                 // 文本内容
    bytes data = 4;                  // 音频数据
}
```

#### ResponseMeta结构
```protobuf
message ResponseMeta {
    string SessionID = 1;    // 会话ID
    int32 Sequence = 2;      // 序列号
    string Message = 3;      // 错误或状态消息
}
```

## 事件类型定义

### 1. 请求事件类型
```protobuf
enum Type {
    StartSession = 100;     // 启动会话
    TaskRequest = 101;      // 音频任务请求
    FinishSession = 102;    // 结束会话
}
```

### 2. 响应事件类型
```protobuf
enum Type {
    // 会话控制事件
    SessionStarted = 150;        // 会话启动确认
    SessionFinished = 152;       // 会话正常结束
    SessionFailed = 153;         // 会话失败
    SessionCanceled = 154;       // 会话取消

    // TTS音频事件
    TTSSentenceEnd = 351;        // TTS句子结束(含音频数据)
    
    // 字幕事件
    SourceSubtitleStart = 650;   // 源语言字幕开始
    SourceSubtitleUpdate = 651;  // 源语言字幕更新
    SourceSubtitleEnd = 652;     // 源语言字幕结束
    
    TranslationSubtitleStart = 653;  // 译文字幕开始  
    TranslationSubtitleUpdate = 654; // 译文字幕更新
    TranslationSubtitleEnd = 655;    // 译文字幕结束
}
```

## 会话生命周期协议

### 1. 会话启动流程
```python
# 1. 构建启动请求
start_request = TranslateRequest()
start_request.request_meta.SessionID = session_id
start_request.event = Type.StartSession
start_request.user.uid = "ast_py_client"  
start_request.user.did = "ast_py_client"

# 源音频格式配置
start_request.source_audio.format = "wav"
start_request.source_audio.rate = 16000
start_request.source_audio.bits = 16
start_request.source_audio.channel = 1

# 目标音频格式配置
start_request.target_audio.format = "ogg_opus"
start_request.target_audio.rate = 24000

# 翻译参数配置
start_request.request.mode = "s2s"
start_request.request.source_language = "zh"  # 中文
start_request.request.target_language = "en"  # 英文

# 2. 发送请求
await ws.send(start_request.SerializeToString())

# 3. 等待响应确认
response = await ws.recv()
resp = TranslateResponse()
resp.ParseFromString(response)

# 4. 验证启动成功
if resp.event == Type.SessionStarted:
    # 会话启动成功，可以发送音频数据
    pass
else:
    # 启动失败，检查错误信息
    logging.error(f"Session start failed: {resp.response_meta.Message}")
```

### 2. 音频数据传输流程
```python
# 1. 构建音频数据请求
chunk_request = TranslateRequest()
chunk_request.request_meta.SessionID = session_id
chunk_request.event = Type.TaskRequest

# 2. 设置音频数据
chunk_request.source_audio.binary_data = pcm_chunk  # 640字节PCM数据

# 3. 发送音频块
await ws.send(chunk_request.SerializeToString())

# 4. 接收翻译结果
while True:
    response = await ws.recv()
    resp = TranslateResponse()
    resp.ParseFromString(response)
    
    # 处理不同类型的响应
    if resp.event == Type.TTSSentenceEnd:
        # 处理TTS音频数据
        tts_audio_data = resp.data
    elif resp.event in [Type.SourceSubtitleEnd, Type.TranslationSubtitleEnd]:
        # 处理字幕文本
        subtitle_text = resp.text
```

### 3. 会话结束流程
```python
# 1. 构建结束请求
finish_request = TranslateRequest()
finish_request.request_meta.SessionID = session_id
finish_request.event = Type.FinishSession

# 2. 发送结束请求
await ws.send(finish_request.SerializeToString())

# 3. 等待结束确认
while True:
    response = await ws.recv()
    resp = TranslateResponse()
    resp.ParseFromString(response)
    
    if resp.event == Type.SessionFinished:
        # 会话正常结束
        break
    elif resp.event == Type.SessionFailed:
        # 会话异常结束
        logging.error(f"Session failed: {resp.response_meta.Message}")
        break
```

## 音频格式规范

### 1. 源音频要求
```python
source_audio_spec = {
    "format": "wav",           # 固定为wav格式
    "sample_rate": 16000,      # 16kHz采样率
    "bit_depth": 16,           # 16位量化
    "channels": 1,             # 单声道
    "chunk_size": 640,         # 每块640字节
    "duration_per_chunk": 20,  # 每块20毫秒
    "encoding": "pcm_s16le"    # 小端16位PCM
}
```

### 2. 目标音频配置
```python
target_audio_spec = {
    "format": "ogg_opus",    # Opus编码格式
    "sample_rate": 24000,    # 24kHz采样率
    "bit_depth": 16,         # 16位量化(Opus内部)
    "channels": 1,           # 单声道
    "variable_bitrate": True # 可变比特率
}
```

### 3. 音频数据流特征
```python
audio_stream_characteristics = {
    "send_interval": 0.02,     # 20毫秒发送间隔
    "frames_per_second": 50,   # 每秒50帧
    "bytes_per_frame": 640,    # 每帧640字节
    "total_bandwidth": 256,    # 总带宽256kbps(16kHz×16bit×1ch)
    "latency_budget": 100      # 延迟预算100毫秒
}
```

## 错误处理协议

### 1. 错误事件类型
```python
error_events = {
    Type.SessionFailed: "会话处理失败",
    Type.SessionCanceled: "会话被取消"
}
```

### 2. 错误信息获取
```python
def handle_error_response(resp: TranslateResponse):
    if resp.event in [Type.SessionFailed, Type.SessionCanceled]:
        error_code = resp.response_meta.Sequence
        error_message = resp.response_meta.Message
        session_id = resp.response_meta.SessionID
        
        logging.error(
            f"Session error - ID:{session_id}, "
            f"Code:{error_code}, Message:{error_message}"
        )
        return True
    return False
```

### 3. 常见错误场景
```python
common_errors = {
    "authentication_failed": "认证头部无效或过期",
    "session_timeout": "会话空闲时间超过限制",
    "audio_format_error": "音频格式不符合规范",
    "rate_limit_exceeded": "请求频率超过限制",
    "service_unavailable": "服务暂时不可用"
}
```

## 实时性能约束

### 1. 延迟要求
```python
latency_constraints = {
    "connection_setup": "< 2秒",        # 连接建立延迟
    "session_start": "< 1秒",          # 会话启动延迟  
    "audio_processing": "< 3秒",       # 音频处理延迟
    "end_to_end": "< 5秒",            # 端到端延迟
    "cleanup_timeout": "< 30秒"        # 资源清理超时
}
```

### 2. 吞吐量限制
```python
throughput_limits = {
    "concurrent_sessions": 10,         # 并发会话数限制
    "audio_chunk_rate": 50,           # 音频块发送率(每秒)
    "max_session_duration": 3600,     # 最大会话时长(秒)
    "max_message_size": 10240,        # 最大消息大小(字节)
    "max_audio_chunk": 1024           # 最大音频块(字节)
}
```

### 3. 资源限制
```python
resource_constraints = {
    "memory_per_session": "5-10MB",    # 每会话内存使用
    "websocket_buffer": "1MB",         # WebSocket缓冲区
    "protobuf_overhead": "< 5%",       # Protobuf序列化开销
    "connection_pool": 100,            # 连接池大小
    "timeout_detection": "10秒"        # 超时检测间隔
}
```

## 协议版本兼容性

### 1. 当前协议版本
```python
protocol_version = {
    "api_version": "v2",              # API版本
    "protobuf_version": "3.x",        # Protobuf版本
    "websocket_version": "13",        # WebSocket协议版本
    "endpoint_stability": "stable"     # 端点稳定性级别
}
```

### 2. 向后兼容性
```python
compatibility_matrix = {
    "message_format": "严格兼容",      # 消息格式
    "event_types": "向后兼容",        # 事件类型  
    "audio_formats": "严格限制",      # 音频格式
    "authentication": "可能变更",      # 认证方式
    "error_codes": "保持稳定"         # 错误码
}
```

## 监控和调试

### 1. 关键监控指标
```python
monitoring_metrics = {
    "connection_success_rate": "连接成功率",
    "session_completion_rate": "会话完成率", 
    "average_latency": "平均延迟",
    "error_rate_by_type": "分类错误率",
    "throughput_per_session": "每会话吞吐量"
}
```

### 2. 调试信息提取
```python
def extract_debug_info(response: TranslateResponse):
    debug_info = {
        "log_id": conn.response.headers.get('X-Tt-Logid'),
        "session_id": response.response_meta.SessionID,
        "sequence": response.response_meta.Sequence,
        "event_type": response.event,
        "message": response.response_meta.Message,
        "data_length": len(response.data) if response.data else 0,
        "text_content": response.text if response.text else ""
    }
    return debug_info
```

## 最佳实践

### 1. 连接管理
- 使用连接池避免频繁建立连接
- 实现指数退避重连机制
- 设置合理的超时和心跳参数

### 2. 错误处理
- 实现完整的错误事件处理
- 记录详细的错误上下文信息
- 设计优雅的降级策略

### 3. 性能优化
- 批量处理音频数据减少消息频率
- 使用异步I/O提高并发性能
- 实现智能缓冲和流控制

### 4. 安全考虑
- 定期轮换认证密钥
- 验证所有输入数据格式
- 实现速率限制和防护机制

---

**文档版本**: v1.0.0  
**关联文档**: [实现分析](implementation-analysis.md) | [配置参数目录](configuration-catalog.md)  
**最后更新**: 2025-01-XX