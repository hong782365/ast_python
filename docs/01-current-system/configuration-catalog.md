# 可配置参数目录

## 概述

当前系统存在大量硬编码参数，为提高系统可维护性和适配不同部署环境，需要将这些参数提取为可配置项。本文档按优先级和功能模块详细列举所有可配置参数。

## 配置参数分级

### 🔴 高优先级 - 核心业务参数
必须提取的关键参数，影响系统核心功能和性能

### 🟡 中优先级 - 环境适配参数  
建议提取的环境相关参数，提升部署灵活性

### 🟢 低优先级 - 优化调试参数
可选提取的调试和优化参数，便于问题排查

## 🔴 高优先级参数

### 1. 音频处理核心参数

#### 音频格式参数
```python
# 当前硬编码位置: ast_youtube_demo.py:multiple_locations
AUDIO_CONFIG = {
    "CHUNK_SIZE": 640,              # PCM块大小(字节)
    "SAMPLE_RATE": 16000,           # 采样率(Hz)
    "BIT_DEPTH": 16,                # 位深度
    "CHANNELS": 1,                  # 声道数
    "CHUNK_DURATION_MS": 20,        # 每块时长(毫秒)
    "SEND_INTERVAL": 0.02,          # 发送间隔(秒)
    "TARGET_SAMPLE_RATE": 24000     # 目标采样率(Hz)
}
```

#### FFmpeg核心参数
```python
# 当前硬编码位置: ast_youtube_demo.py:695-720
FFMPEG_CONFIG = {
    "LOG_LEVEL": "verbose",          # 日志级别
    "FFLAGS": "nobuffer",           # 超低延迟标志
    "PRESET": "ultrafast",          # 编码预设
    "TUNE": "zerolatency",          # 零延迟调优
    "BUFFER_SIZE": "32k",           # 缓冲区大小
    "MAX_DELAY": "0",               # 最大延迟
    "THREADS": 1,                   # 线程数
    "PROBESIZE": "32",              # 探测大小
    "ANALYZEDURATION": "0"          # 分析时长
}
```

### 2. WebSocket连接参数

#### VolcEngine连接配置
```python
# 当前硬编码位置: ast_youtube_demo.py:480-520
VOLCENGINE_CONFIG = {
    "WS_URL": "wss://openspeech.bytedance.com/api/v2/ast",
    "MAX_SIZE": 1000000000,         # 最大消息大小(1GB)
    "PING_INTERVAL": None,          # 禁用自动ping
    "PING_TIMEOUT": None,           # 禁用ping超时
    "CLOSE_TIMEOUT": 10,            # 关闭超时(秒)
    "COMPRESSION": None,            # 禁用压缩
    "CONNECT_TIMEOUT": 30           # 连接超时(秒)
}
```

#### WebSocket转发配置
```python
# 当前硬编码位置: publisher.py:280-320
PUBLISH_WS_CONFIG = {
    "RECONNECT_INTERVAL": 5,        # 重连间隔(秒)
    "MAX_RECONNECT_ATTEMPTS": 10,   # 最大重连次数
    "PING_INTERVAL": 30,            # 心跳间隔(秒)
    "PING_TIMEOUT": 10,             # 心跳超时(秒)
    "CLOSE_TIMEOUT": 5,             # 关闭超时(秒)
    "QUEUE_SIZE": 1000              # 消息队列大小
}
```

### 3. 超时和延迟控制

#### 超时配置
```python
# 当前硬编码位置: ast_youtube_demo.py:multiple_locations
TIMEOUT_CONFIG = {
    "FFMPEG_START_TIMEOUT": 30,      # FFmpeg启动超时(秒)
    "FIRST_CHUNK_TIMEOUT": 30,       # 首个音频块超时(秒)
    "CHUNK_READ_TIMEOUT": 10,        # 音频块读取超时(秒)
    "SESSION_START_TIMEOUT": 10,     # 会话启动超时(秒)
    "SESSION_FINISH_TIMEOUT": 30,    # 会话结束超时(秒)
    "WS_SEND_TIMEOUT": 5,           # WebSocket发送超时(秒)
    "WS_RECV_TIMEOUT": 5,           # WebSocket接收超时(秒)
    "CLEANUP_TIMEOUT": 30           # 资源清理超时(秒)
}
```

#### 静音桥接参数
```python
# 当前硬编码位置: ast_youtube_demo.py:680-690
SILENCE_BRIDGE_CONFIG = {
    "SILENCE_TIMEOUT_LOCAL": 8,      # 本地环境超时(秒)
    "SILENCE_TIMEOUT_CLOUDFLARE": 18, # Cloudflare环境超时(秒)
    "SILENCE_INTERVAL": 0.02,        # 静音帧发送间隔(秒)
    "SILENCE_CHUNK_SIZE": 640        # 静音块大小(字节)
}
```

### 4. 翻译服务参数

#### 语言配置
```python
# 当前硬编码位置: ast_youtube_demo.py:540-550
TRANSLATION_CONFIG = {
    "SOURCE_LANGUAGE": "zh",         # 源语言代码
    "TARGET_LANGUAGE": "en",         # 目标语言代码
    "TRANSLATION_MODE": "s2s",       # 翻译模式
    "SOURCE_AUDIO_FORMAT": "wav",    # 源音频格式
    "TARGET_AUDIO_FORMAT": "ogg_opus" # 目标音频格式
}
```

## 🟡 中优先级参数

### 1. 环境适配参数

#### 环境检测配置
```python
# 当前硬编码位置: ast_youtube_demo.py:90-120
ENVIRONMENT_CONFIG = {
    "CLOUDFLARE_ENV_VARS": ["CF_PAGES", "CF_PAGES_URL"],  # 环境变量检测
    "LOG_FILE_ENABLED": True,        # 是否启用文件日志
    "LOG_PREFIX_CLOUDFLARE": "CLOUDFLARE_", # Cloudflare日志前缀
    "STDERR_LOGGING": False,         # 是否使用stderr日志
    "FILE_MONITORING": True,         # 是否启用文件监控
    "HEALTH_CHECK_INTERVAL": 5       # 健康检查间隔(秒)
}
```

### 2. 进程管理参数

#### FFmpeg进程配置
```python
# 当前硬编码位置: ast_youtube_demo.py:620-670
PROCESS_CONFIG = {
    "FFMPEG_HEALTH_CHECK_INTERVAL": 5,  # 健康检查间隔(秒)
    "PROCESS_TERMINATE_TIMEOUT": 10,    # 进程终止超时(秒)  
    "PROCESS_KILL_TIMEOUT": 5,          # 强制杀死超时(秒)
    "STDOUT_BUFFER_SIZE": 8192,         # 标准输出缓冲区
    "STDERR_BUFFER_SIZE": 8192,         # 标准错误缓冲区
    "MAX_RESTART_ATTEMPTS": 3           # 最大重启尝试次数
}
```

#### yt-dlp管理器配置
```python
# 当前硬编码位置: ast_youtube_demo.py:150-200
YTDLP_CONFIG = {
    "THREAD_POOL_SIZE": 4,           # 线程池大小
    "EXTRACTION_TIMEOUT": 60,        # 提取超时(秒)
    "RETRY_ATTEMPTS": 3,             # 重试次数
    "RETRY_DELAY": 2,                # 重试延迟(秒)
    "CACHE_SIZE": 100,               # 缓存大小
    "USER_AGENT": "Mozilla/5.0...",  # User-Agent字符串
    "COOKIES_ENABLED": False         # 是否启用Cookies
}
```

### 3. 日志和监控配置

#### 日志配置
```python
# 当前硬编码位置: ast_youtube_demo.py:60-90
LOGGING_CONFIG = {
    "LOG_LEVEL": "INFO",             # 日志级别
    "LOG_FORMAT": "%(asctime)s - %(levelname)s - %(message)s",
    "LOG_DATE_FORMAT": "%Y-%m-%d %H:%M:%S",
    "LOG_FILE_MAX_SIZE": "10MB",     # 单文件最大大小
    "LOG_FILE_BACKUP_COUNT": 5,      # 备份文件数量
    "LOG_FILE_ROTATION": "daily",    # 轮转策略
    "CONSOLE_LOG_ENABLED": True,     # 控制台日志
    "FILE_LOG_ENABLED": True         # 文件日志
}
```

#### 监控配置
```python
# 当前硬编码位置: ast_youtube_demo.py:1450-1500
MONITORING_CONFIG = {
    "METRICS_COLLECTION_INTERVAL": 30,  # 指标收集间隔(秒)
    "MEMORY_USAGE_THRESHOLD": 80,       # 内存使用阈值(%)
    "CPU_USAGE_THRESHOLD": 80,          # CPU使用阈值(%)
    "ERROR_RATE_THRESHOLD": 5,          # 错误率阈值(%)
    "LATENCY_THRESHOLD": 10,            # 延迟阈值(秒)
    "ALERT_ENABLED": True,              # 是否启用告警
    "HEALTH_CHECK_ENABLED": True        # 是否启用健康检查
}
```

### 4. 缓存和队列配置

#### 会话管理配置
```python
# 当前硬编码位置: publisher.py:50-100
SESSION_CONFIG = {
    "MAX_CONCURRENT_SESSIONS": 10,   # 最大并发会话数
    "SESSION_TIMEOUT": 3600,         # 会话超时(秒)
    "SESSION_CLEANUP_INTERVAL": 300, # 清理间隔(秒)
    "INACTIVE_SESSION_TIMEOUT": 600, # 非活跃会话超时(秒)
    "SESSION_MEMORY_LIMIT": "50MB",  # 单会话内存限制
    "TOTAL_MEMORY_LIMIT": "500MB"    # 总内存限制
}
```

## 🟢 低优先级参数

### 1. 调试参数

#### 调试和测试配置
```python
# 当前硬编码位置: ast_youtube_demo.py:1550-1600
DEBUG_CONFIG = {
    "VERBOSE_LOGGING": False,        # 详细日志
    "PERFORMANCE_PROFILING": False,  # 性能分析
    "MEMORY_PROFILING": False,       # 内存分析
    "NETWORK_DEBUGGING": False,      # 网络调试
    "AUDIO_DUMP_ENABLED": False,     # 音频数据转储
    "PROTOCOL_DUMP_ENABLED": False,  # 协议数据转储
    "TIMING_STATISTICS": False       # 计时统计
}
```

### 2. 优化参数

#### 性能优化配置
```python
# 当前硬编码位置: ast_youtube_demo.py:various_locations
PERFORMANCE_CONFIG = {
    "ASYNC_TASK_POOL_SIZE": 20,      # 异步任务池大小
    "IO_BUFFER_SIZE": 65536,         # I/O缓冲区大小
    "BATCH_PROCESSING_SIZE": 10,     # 批处理大小
    "PREFETCH_BUFFER_SIZE": 5,       # 预取缓冲区大小
    "COMPRESSION_LEVEL": 6,          # 压缩级别
    "MEMORY_POOL_SIZE": "100MB",     # 内存池大小
    "GC_THRESHOLD": 100              # 垃圾回收阈值
}
```

## 配置文件结构设计

### 1. 主配置文件 (config.yaml)
```yaml
# 核心业务配置
audio:
  chunk_size: 640
  sample_rate: 16000
  send_interval: 0.02

websocket:
  volcengine:
    max_size: 1000000000
    ping_interval: null
  publish:
    reconnect_interval: 5
    max_reconnect_attempts: 10

timeout:
  ffmpeg_start: 30
  first_chunk: 30
  session_start: 10

translation:
  source_language: "zh"
  target_language: "en"
  mode: "s2s"

# 环境适配配置  
environment:
  cloudflare_detection: true
  log_file_enabled: true
  stderr_logging: false

# 扩展配置
logging:
  level: "INFO"
  file_max_size: "10MB"
  
monitoring:
  metrics_interval: 30
  health_check_enabled: true
```

### 2. 环境特定配置

#### 本地开发环境 (config.local.yaml)
```yaml
environment:
  log_file_enabled: true
  file_monitoring: true
  stderr_logging: false

timeout:
  silence_timeout: 8
  
debug:
  verbose_logging: true
  audio_dump_enabled: true
```

#### Cloudflare环境 (config.cloudflare.yaml)  
```yaml
environment:
  log_file_enabled: false
  file_monitoring: false
  stderr_logging: true
  log_prefix: "CLOUDFLARE_"

timeout:
  silence_timeout: 18

session:
  total_memory_limit: "100MB"

process:
  max_restart_attempts: 1
```

### 3. 配置加载优先级
```python
config_loading_priority = [
    "config.yaml",                    # 基础配置
    f"config.{environment}.yaml",     # 环境特定配置
    "config.local.yaml",              # 本地覆盖配置
    "environment_variables",          # 环境变量覆盖
    "command_line_arguments"          # 命令行参数覆盖
]
```

## 配置验证规则

### 1. 参数范围验证
```python
VALIDATION_RULES = {
    "audio.chunk_size": {"min": 320, "max": 1280, "step": 320},
    "audio.sample_rate": {"values": [8000, 16000, 24000, 48000]},
    "timeout.ffmpeg_start": {"min": 5, "max": 300},
    "websocket.publish.max_reconnect_attempts": {"min": 0, "max": 100},
    "session.max_concurrent_sessions": {"min": 1, "max": 50}
}
```

### 2. 依赖关系验证
```python
DEPENDENCY_RULES = {
    "chunk_size_duration_consistency": {
        "rule": "chunk_size == sample_rate * channels * bit_depth * duration / 8",
        "params": ["audio.chunk_size", "audio.sample_rate", "audio.channels", "audio.bit_depth"]
    },
    "timeout_hierarchy": {
        "rule": "session_start_timeout < session_finish_timeout",
        "params": ["timeout.session_start", "timeout.session_finish"]
    }
}
```

## 配置迁移策略

### 1. 提取步骤
1. **识别阶段**: 扫描代码中的硬编码常量
2. **分类阶段**: 按功能模块和优先级分类
3. **提取阶段**: 创建配置文件和加载逻辑
4. **替换阶段**: 用配置变量替换硬编码值
5. **验证阶段**: 确保功能完整性和性能一致性

### 2. 向后兼容性
```python
def get_config_value(key: str, default=None):
    """向后兼容的配置获取"""
    # 1. 尝试从新配置系统获取
    if hasattr(config, key):
        return getattr(config, key)
    
    # 2. 尝试从环境变量获取  
    env_key = key.upper().replace('.', '_')
    env_value = os.getenv(env_key)
    if env_value:
        return env_value
        
    # 3. 返回硬编码默认值(向后兼容)
    return default
```

### 3. 测试验证
```python
# 配置参数完整性测试
def test_config_completeness():
    """确保所有硬编码值都有对应配置"""
    hardcoded_values = scan_hardcoded_constants()
    config_values = load_all_config_keys()
    missing = set(hardcoded_values) - set(config_values)
    assert len(missing) == 0, f"Missing config for: {missing}"

# 配置参数有效性测试  
def test_config_validation():
    """确保配置参数符合业务规则"""
    config = load_config()
    validation_errors = validate_config(config)
    assert len(validation_errors) == 0, f"Config errors: {validation_errors}"
```

---

**文档版本**: v1.0.0  
**关联文档**: [实现分析](implementation-analysis.md) | [环境适配](environment-adaptation.md)  
**最后更新**: 2025-01-XX