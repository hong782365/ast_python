# 环境适配逻辑

## 概述

系统需要同时支持**本地开发环境**和**Cloudflare Containers**部署环境，两种环境在文件系统权限、资源限制、监控能力等方面存在显著差异。本文档详述环境检测机制和适配策略。

## 环境差异对比

### 权限和文件系统差异
| 特性 | 本地开发环境 | Cloudflare Containers |
|------|-------------|----------------------|
| 文件写入权限 | ✅ 完整读写权限 | ❌ 只读文件系统 |
| 临时文件创建 | ✅ `/tmp`, `/var/tmp` | ⚠️ 内存文件系统 |
| 日志文件写入 | ✅ 任意路径写入 | ❌ 禁止文件写入 |
| 进程监控文件 | ✅ `/proc`, `/sys` | ⚠️ 受限访问 |
| 外部命令执行 | ✅ 完整权限 | ⚠️ 沙箱限制 |

### 资源限制差异
| 资源类型 | 本地开发环境 | Cloudflare Containers |
|---------|-------------|----------------------|
| 内存限制 | 通常 > 8GB | ⚠️ < 100MB 严格限制 |
| CPU 核心 | 多核心可用 | ⚠️ 单核心或共享 |
| 网络带宽 | 本地网络速度 | ⚠️ CDN边缘节点限制 |
| 磁盘空间 | GB级别可用 | ❌ 无持久存储 |
| 进程数量 | 宽松限制 | ⚠️ 严格限制 |

## 环境检测机制

### 1. 检测逻辑实现

#### 环境标识符检测
```python
# 当前实现位置: ast_youtube_demo.py:90-120
def is_cloudflare_environment() -> bool:
    """检测是否运行在Cloudflare Containers环境"""
    cloudflare_indicators = [
        "CF_PAGES",           # Cloudflare Pages环境变量
        "CF_PAGES_URL",       # Cloudflare Pages URL
        "CF_WORKER",          # Worker环境标识
        "CF_RAY"              # Cloudflare Ray ID
    ]
    
    for indicator in cloudflare_indicators:
        if os.getenv(indicator):
            return True
    
    return False

# 扩展检测逻辑
def detect_environment() -> str:
    """详细环境类型检测"""
    if os.getenv("CF_PAGES"):
        return "cloudflare_pages"
    elif os.getenv("CF_WORKER"):  
        return "cloudflare_worker"
    elif os.getenv("DOCKER_CONTAINER"):
        return "docker"
    elif os.getenv("KUBERNETES_SERVICE_HOST"):
        return "kubernetes"
    elif os.path.exists("/.dockerenv"):
        return "docker_detected"
    else:
        return "local"
```

#### 权限能力检测
```python
def detect_capabilities() -> dict:
    """检测运行环境具体能力"""
    capabilities = {
        "file_write": False,
        "file_monitor": False,  
        "proc_access": False,
        "external_commands": False,
        "memory_profiling": False
    }
    
    # 文件写入能力检测
    try:
        test_file = "/tmp/test_write_permission"
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        capabilities["file_write"] = True
    except (PermissionError, OSError):
        capabilities["file_write"] = False
    
    # 文件监控能力检测
    try:
        import watchdog.observers
        capabilities["file_monitor"] = True
    except ImportError:
        capabilities["file_monitor"] = False
    
    # /proc访问能力检测
    capabilities["proc_access"] = os.path.exists("/proc/self/status")
    
    # 外部命令执行检测
    try:
        result = subprocess.run(["echo", "test"], 
                              capture_output=True, timeout=5)
        capabilities["external_commands"] = result.returncode == 0
    except (subprocess.TimeoutExpired, PermissionError, OSError):
        capabilities["external_commands"] = False
    
    return capabilities
```

### 2. 环境配置映射

#### 环境特定配置
```python
# 当前实现位置: ast_youtube_demo.py:multiple_locations
ENVIRONMENT_CONFIGS = {
    "local": {
        "logging": {
            "file_enabled": True,
            "stderr_enabled": True,
            "file_path": "logs/",
            "log_prefix": "",
            "log_level": "DEBUG"
        },
        "monitoring": {
            "file_monitoring": True,
            "process_monitoring": True,
            "memory_profiling": True,
            "performance_metrics": True
        },
        "timeouts": {
            "silence_timeout": 8,        # FFmpeg本地启动较快
            "ffmpeg_start_timeout": 15,
            "first_chunk_timeout": 20
        },
        "resources": {
            "memory_limit": None,        # 无严格限制
            "max_sessions": 50,
            "thread_pool_size": 8
        }
    },
    
    "cloudflare": {
        "logging": {
            "file_enabled": False,       # 禁止文件写入
            "stderr_enabled": True,      # 仅stderr输出
            "file_path": None,
            "log_prefix": "CLOUDFLARE_", # 特殊前缀标识
            "log_level": "INFO"          # 减少日志量
        },
        "monitoring": {
            "file_monitoring": False,    # 无文件监控
            "process_monitoring": False, # 无进程监控文件
            "memory_profiling": False,   # 禁用内存分析
            "performance_metrics": True  # 仅基础指标
        },
        "timeouts": {
            "silence_timeout": 18,       # Cloudflare冷启动更慢
            "ffmpeg_start_timeout": 30,
            "first_chunk_timeout": 30
        },
        "resources": {
            "memory_limit": "90MB",      # 严格内存限制
            "max_sessions": 5,           # 降低并发数
            "thread_pool_size": 2        # 减少线程使用
        }
    }
}
```

## 日志系统适配

### 1. 本地环境日志策略

#### 文件日志配置
```python
# 当前实现位置: ast_youtube_demo.py:60-90
class LocalLoggingAdapter:
    def __init__(self):
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # 应用程序日志
        self.app_logger = self._setup_file_logger(
            "app", "logs/application.log"
        )
        
        # FFmpeg日志
        self.ffmpeg_logger = self._setup_file_logger(
            "ffmpeg", "logs/ffmpeg.log"
        )
        
        # WebSocket协议日志
        self.protocol_logger = self._setup_file_logger(
            "protocol", "logs/websocket_protocol.log"
        )
    
    def _setup_file_logger(self, name: str, filepath: str):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        
        # 文件处理器 - 支持轮转
        file_handler = RotatingFileHandler(
            filepath, 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        
        # 详细格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        return logger
```

### 2. Cloudflare环境日志策略

#### stderr日志输出
```python
# 当前实现位置: ast_youtube_demo.py:100-130
class CloudflareLoggingAdapter:
    def __init__(self):
        self.stderr_logger = logging.getLogger("cloudflare_app")
        self.stderr_logger.setLevel(logging.INFO)
        
        # 仅stderr处理器
        stderr_handler = logging.StreamHandler(sys.stderr)
        
        # Cloudflare特定格式化器
        formatter = logging.Formatter(
            'CLOUDFLARE_%(levelname)s: %(asctime)s - %(message)s'
        )
        stderr_handler.setFormatter(formatter)
        self.stderr_logger.addHandler(stderr_handler)
        
        # 禁用其他所有日志处理器
        logging.getLogger().handlers = []
        
    def log_with_context(self, level: str, message: str, **context):
        """带上下文的日志记录"""
        context_str = " | ".join([f"{k}={v}" for k, v in context.items()])
        full_message = f"{message} | {context_str}" if context else message
        
        # 添加环境标识前缀
        prefixed_message = f"CLOUDFLARE_{level.upper()}: {full_message}"
        
        getattr(self.stderr_logger, level.lower())(prefixed_message)
```

### 3. 统一日志接口

#### 环境无关日志器
```python
class AdaptiveLogger:
    def __init__(self):
        self.environment = detect_environment()
        
        if self.environment == "cloudflare":
            self.adapter = CloudflareLoggingAdapter()
        else:
            self.adapter = LocalLoggingAdapter()
    
    def info(self, message: str, **kwargs):
        if hasattr(self.adapter, 'log_with_context'):
            self.adapter.log_with_context('info', message, **kwargs)
        else:
            self.adapter.app_logger.info(f"{message} | {kwargs}")
    
    def error(self, message: str, **kwargs):
        if hasattr(self.adapter, 'log_with_context'):
            self.adapter.log_with_context('error', message, **kwargs)
        else:
            self.adapter.app_logger.error(f"{message} | {kwargs}")
    
    def debug(self, message: str, **kwargs):
        # Cloudflare环境跳过debug级别日志
        if self.environment == "cloudflare":
            return
            
        if hasattr(self.adapter, 'log_with_context'):
            self.adapter.log_with_context('debug', message, **kwargs)
        else:
            self.adapter.app_logger.debug(f"{message} | {kwargs}")

# 全局日志器实例
logger = AdaptiveLogger()
```

## 监控系统适配

### 1. 本地环境监控

#### 文件监控实现
```python
# 当前实现位置: ast_youtube_demo.py:1450-1500
class LocalMonitoring:
    def __init__(self):
        self.file_monitor = None
        self.process_monitor = None
        self.setup_monitoring()
    
    def setup_monitoring(self):
        """设置本地环境监控"""
        # FFmpeg日志文件监控
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        
        class FFmpegLogHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.src_path.endswith('ffmpeg_stderr.log'):
                    self.process_ffmpeg_log_update(event.src_path)
        
        self.file_monitor = Observer()
        self.file_monitor.schedule(
            FFmpegLogHandler(), 
            path="logs/", 
            recursive=False
        )
        self.file_monitor.start()
        
        # 进程健康监控
        self.process_monitor = ProcessMonitor()
        self.process_monitor.start_monitoring()
    
    def process_ffmpeg_log_update(self, log_path: str):
        """处理FFmpeg日志更新"""
        try:
            with open(log_path, 'r') as f:
                # 读取最新日志行
                f.seek(-1024, os.SEEK_END)  # 最后1KB
                new_lines = f.readlines()
                
                for line in new_lines:
                    if "error" in line.lower() or "fatal" in line.lower():
                        logger.error(f"FFmpeg error detected: {line.strip()}")
                        
        except Exception as e:
            logger.warning(f"Log monitoring error: {e}")
```

### 2. Cloudflare环境监控

#### 无文件监控实现
```python
class CloudflareMonitoring:
    def __init__(self):
        self.health_checker = None
        self.setup_monitoring()
    
    def setup_monitoring(self):
        """设置Cloudflare环境监控（无文件依赖）"""
        # 仅进程存活状态检查
        self.health_checker = HealthChecker(
            check_interval=5,
            timeout=2,
            file_monitoring=False
        )
        self.health_checker.start()
    
    async def check_ffmpeg_health(self, process: subprocess.Popen):
        """检查FFmpeg进程健康状态（无文件访问）"""
        try:
            # 仅检查进程状态
            if process.poll() is not None:
                logger.error("CLOUDFLARE_ERROR: FFmpeg process terminated unexpectedly")
                return False
            
            # 检查进程响应（通过stdin写入测试）
            try:
                process.stdin.write(b'')
                process.stdin.flush()
                return True
            except BrokenPipeError:
                logger.error("CLOUDFLARE_ERROR: FFmpeg process pipe broken")
                return False
                
        except Exception as e:
            logger.error(f"CLOUDFLARE_ERROR: Health check failed: {e}")
            return False
```

## FFmpeg进程适配

### 1. 本地环境FFmpeg配置

#### 完整参数和文件日志
```python
# 当前实现位置: ast_youtube_demo.py:695-720
def build_local_ffmpeg_command(youtube_url: str) -> List[str]:
    """构建本地环境FFmpeg命令"""
    log_file = f"logs/ffmpeg_{int(time.time())}.log"
    
    cmd = [
        "ffmpeg", 
        "-hide_banner", 
        "-loglevel", "verbose",           # 详细日志级别
        "-report",                       # 生成详细报告
        "-fflags", "+nobuffer+fastseek", # 优化标志
        "-flags", "low_delay",
        "-i", youtube_url,
        "-ac", "1",                      # 单声道
        "-ar", "16000",                  # 16kHz采样率
        "-acodec", "pcm_s16le",         # PCM编码
        "-f", "s16le",                   # 输出格式
        "-bufsize", "32k",               # 缓冲区大小
        "-preset", "ultrafast",          # 最快预设
        "-tune", "zerolatency",          # 零延迟调优
        "pipe:1"                         # 输出到stdout
    ]
    
    return cmd, log_file
```

### 2. Cloudflare环境FFmpeg配置

#### 简化参数和stderr输出
```python
def build_cloudflare_ffmpeg_command(youtube_url: str) -> List[str]:
    """构建Cloudflare环境FFmpeg命令"""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",            # 仅错误日志
        "-fflags", "+nobuffer",          # 基础优化标志
        "-i", youtube_url,
        "-ac", "1",
        "-ar", "16000", 
        "-acodec", "pcm_s16le",
        "-f", "s16le",
        "-preset", "ultrafast",          # 最快处理
        "pipe:1"
    ]
    
    # 无日志文件，直接stderr输出
    return cmd, None
```

### 3. 环境自适应FFmpeg管理

#### 统一FFmpeg管理器
```python
class AdaptiveFFmpegManager:
    def __init__(self):
        self.environment = detect_environment() 
        self.capabilities = detect_capabilities()
        
    async def start_ffmpeg_process(self, youtube_url: str):
        """环境自适应的FFmpeg进程启动"""
        if self.environment == "cloudflare":
            cmd, log_file = build_cloudflare_ffmpeg_command(youtube_url)
            return await self._start_cloudflare_ffmpeg(cmd)
        else:
            cmd, log_file = build_local_ffmpeg_command(youtube_url)  
            return await self._start_local_ffmpeg(cmd, log_file)
    
    async def _start_local_ffmpeg(self, cmd: List[str], log_file: str):
        """本地环境FFmpeg启动"""
        stderr_log = open(log_file, 'w') if log_file else None
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_log or asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE
        )
        
        # 启动文件监控任务
        if stderr_log and self.capabilities["file_monitor"]:
            asyncio.create_task(self._monitor_log_file(log_file))
        
        return process, stderr_log
    
    async def _start_cloudflare_ffmpeg(self, cmd: List[str]):
        """Cloudflare环境FFmpeg启动"""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,  # 捕获stderr用于监控
            stdin=asyncio.subprocess.PIPE
        )
        
        # 启动stderr监控任务
        asyncio.create_task(self._monitor_stderr_stream(process.stderr))
        
        return process, None
    
    async def _monitor_stderr_stream(self, stderr_stream):
        """监控stderr流（Cloudflare环境）"""
        try:
            while True:
                line = await stderr_stream.readline()
                if not line:
                    break
                    
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    # 输出到stderr，带Cloudflare前缀
                    print(f"CLOUDFLARE_FFMPEG: {line_str}", file=sys.stderr)
                    
                    # 检查错误关键词
                    if any(keyword in line_str.lower() 
                           for keyword in ['error', 'fatal', 'failed']):
                        logger.error(f"CLOUDFLARE_FFMPEG_ERROR: {line_str}")
                        
        except Exception as e:
            logger.error(f"CLOUDFLARE_ERROR: stderr monitoring failed: {e}")
```

## 资源限制适配

### 1. 内存使用优化

#### Cloudflare内存限制处理
```python
class MemoryManager:
    def __init__(self):
        self.environment = detect_environment()
        self.memory_limit = self._get_memory_limit()
        self.current_usage = 0
        
    def _get_memory_limit(self) -> int:
        """获取内存限制"""
        if self.environment == "cloudflare":
            return 90 * 1024 * 1024  # 90MB for Cloudflare
        else:
            return None  # 无限制
    
    def check_memory_usage(self) -> bool:
        """检查内存使用情况"""
        if not self.memory_limit:
            return True
            
        try:
            import psutil
            current = psutil.Process().memory_info().rss
            usage_percent = (current / self.memory_limit) * 100
            
            if usage_percent > 80:  # 80%阈值
                logger.warning(f"Memory usage high: {usage_percent:.1f}%")
                
            if usage_percent > 95:  # 95%紧急阈值
                logger.error("CLOUDFLARE_ERROR: Memory limit exceeded")
                return False
                
            return True
        except ImportError:
            # psutil不可用时跳过检查
            return True
    
    def optimize_for_low_memory(self):
        """低内存环境优化"""
        if self.environment == "cloudflare":
            # 强制垃圾回收
            import gc
            gc.collect()
            
            # 减少缓冲区大小
            # 降低并发会话数
            # 清理不必要的对象引用
```

### 2. 并发控制适配

#### 环境相关并发限制
```python
class ConcurrencyManager:
    def __init__(self):
        self.environment = detect_environment()
        self.limits = self._get_concurrency_limits()
        self.active_sessions = 0
        self.semaphore = asyncio.Semaphore(self.limits["max_sessions"])
    
    def _get_concurrency_limits(self) -> dict:
        """获取并发限制"""
        if self.environment == "cloudflare":
            return {
                "max_sessions": 3,           # 最大并发会话数
                "max_tasks_per_session": 5,  # 每会话最大任务数
                "thread_pool_size": 2,       # 线程池大小
                "connection_pool_size": 5    # 连接池大小
            }
        else:
            return {
                "max_sessions": 20,
                "max_tasks_per_session": 10,
                "thread_pool_size": 8,
                "connection_pool_size": 50
            }
    
    async def acquire_session_slot(self):
        """获取会话槽位"""
        await self.semaphore.acquire()
        self.active_sessions += 1
        
        logger.info(f"Session acquired. Active: {self.active_sessions}")
        
    def release_session_slot(self):
        """释放会话槽位"""
        self.semaphore.release()
        self.active_sessions = max(0, self.active_sessions - 1)
        
        logger.info(f"Session released. Active: {self.active_sessions}")
```

## 错误处理适配

### 1. 环境特定错误处理

#### Cloudflare错误标记
```python
class AdaptiveErrorHandler:
    def __init__(self):
        self.environment = detect_environment()
    
    def handle_error(self, error: Exception, context: str = ""):
        """环境适配的错误处理"""
        error_message = str(error)
        
        if self.environment == "cloudflare":
            # Cloudflare环境：特殊前缀，stderr输出
            prefixed_message = f"CLOUDFLARE_ERROR: {context}: {error_message}"
            print(prefixed_message, file=sys.stderr)
            
            # 检查是否是资源限制相关错误
            if self._is_resource_limit_error(error):
                self._handle_resource_limit_error(error)
                
        else:
            # 本地环境：详细日志文件记录
            logger.error(f"LOCAL_ERROR: {context}: {error_message}", exc_info=True)
    
    def _is_resource_limit_error(self, error: Exception) -> bool:
        """检查是否是资源限制错误"""
        resource_keywords = [
            "memory", "limit", "exceeded", "quota", 
            "timeout", "connection", "refused"
        ]
        error_str = str(error).lower()
        return any(keyword in error_str for keyword in resource_keywords)
    
    def _handle_resource_limit_error(self, error: Exception):
        """处理资源限制错误"""
        logger.error("CLOUDFLARE_RESOURCE_LIMIT: Triggering resource cleanup")
        
        # 触发资源清理
        import gc
        gc.collect()
        
        # 降低并发度
        # 清理缓存
        # 重启关键服务
```

## 部署配置模板

### 1. 本地开发配置模板
```yaml
# config.local.yaml
environment:
  type: "local"
  
logging:
  file_enabled: true
  file_path: "logs/"
  stderr_enabled: true
  log_level: "DEBUG"
  
monitoring:
  file_monitoring: true
  process_monitoring: true
  memory_profiling: true
  
resources:
  memory_limit: null
  max_sessions: 20
  thread_pool_size: 8
  
ffmpeg:
  log_level: "verbose"
  log_to_file: true
  optimization_level: "debug"
```

### 2. Cloudflare部署配置模板
```yaml
# config.cloudflare.yaml  
environment:
  type: "cloudflare"
  
logging:
  file_enabled: false
  stderr_enabled: true
  log_level: "INFO"
  log_prefix: "CLOUDFLARE_"
  
monitoring:
  file_monitoring: false
  process_monitoring: false
  memory_profiling: false
  
resources:
  memory_limit: "90MB"
  max_sessions: 3
  thread_pool_size: 2
  
ffmpeg:
  log_level: "error"
  log_to_file: false
  optimization_level: "production"
  
timeout:
  silence_timeout: 18
  ffmpeg_start_timeout: 30
```

---

**文档版本**: v1.0.0  
**关联文档**: [配置参数目录](configuration-catalog.md) | [实现分析](implementation-analysis.md)  
**最后更新**: 2025-01-XX