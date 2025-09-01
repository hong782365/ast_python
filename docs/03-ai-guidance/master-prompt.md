# AI重写主要提示词

## 概述

本文档提供AI工具重写`/python/ingest/start`接口的完整指导。目标是将1636行的单体文件重构为8个模块化组件，同时基于现有的`ast_demo.py`成熟WebSocket协议框架进行扩展，确保功能等价性和性能一致性。

## 🎯 重写目标和约束

### 核心目标
1. **模块化重构**: 将`ast_youtube_demo.py`(1636行)拆分为8个功能模块，每个模块<500行
2. **基于现有框架**: 复用`ast_demo.py`中成熟的VolcEngine WebSocket协议处理逻辑
3. **配置外化**: 提取所有硬编码参数，支持环境特定配置
4. **环境适配**: 统一处理本地开发和Cloudflare Containers的部署差异
5. **功能等价**: 重写后系统功能与现有系统100%一致

### 关键约束条件
```python
CRITICAL_CONSTRAINTS = {
    "功能等价性": "重写后的系统必须与现有系统功能完全一致",
    "性能要求": "端到端延迟不超过现有系统+10%", 
    "协议兼容": "必须与VolcEngine API保持100%协议兼容",
    "环境支持": "同时支持本地开发和Cloudflare Containers部署",
    "资源限制": "Cloudflare环境内存使用<90MB",
    "代码质量": "单个模块文件不超过500行，测试覆盖率>80%"
}
```

## 🔧 现有代码资产保护

### 必须保留的核心框架
**重要**: 以下来自`ast_demo.py`的成熟框架组件必须原样保留，不得修改：

#### 1. 协议数据结构 (ast_demo.py:37-74)
```python
# 这些数据类必须完全保留，确保与VolcEngine API兼容
@dataclass
class Audio:
    format: str = None
    rate: int = None
    bits: Optional[int] = None
    channel: Optional[int] = None
    binary_data: Optional[bytes] = None

@dataclass  
class TranslateRequestData:
    session_id: str
    event: str
    source_audio: Optional[Audio] = None
    target_audio: Optional[Audio] = None
    mode: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None

@dataclass
class TranslateResponseData:
    event: str
    session_id: str
    sequence: int
    text: str
    data: bytes
    message: str = None
```

#### 2. 核心协议函数 (ast_demo.py:88-140)
```python
# 这些函数必须逐行复制到新的协议模块中，保持100%一致
async def send_request(ws, request: TranslateRequestData):
    """发送请求到WebSocket服务器 - 完全复用ast_demo.py:88-112"""
    # [保持原始实现，逐行复制]

async def receive_message(ws) -> TranslateResponseData:
    """接收并解析服务器响应 - 完全复用ast_demo.py:115-129"""  
    # [保持原始实现，逐行复制]

async def build_http_headers(config, conn_id: str) -> Headers:
    """构建WebSocket连接头部 - 完全复用ast_demo.py:132-140"""
    # [保持原始实现，逐行复制]
```

### protobuf集成保护
```python
# 现有的protobuf导入和使用必须保持不变
from products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse
from common.events_pb2 import Type

# protobuf序列化和反序列化逻辑必须完全保留
request_data = TranslateRequest()
request_data.request_meta.SessionID = request.session_id
# [保持所有protobuf操作逻辑不变]
```

## 📁 目标模块结构

### 完整目录结构
```
ast_python/
├── core/                           # 核心业务逻辑层
│   ├── __init__.py
│   ├── session_manager.py          # 会话生命周期管理 (~300行)
│   ├── audio_pipeline.py           # 音频处理管线协调 (~400行)
│   ├── publisher_client.py         # WebSocket转发客户端 (~250行)
│   └── event_processor.py          # 事件处理和转换 (~300行)
│
├── infrastructure/                 # 基础设施层
│   ├── __init__.py
│   ├── ffmpeg_manager.py           # FFmpeg进程管理 (~350行)
│   ├── ytdlp_manager.py            # yt-dlp管理器 (~250行)
│   ├── websocket_client.py         # WebSocket基础客户端 (~300行)
│   └── volcengine_client.py        # VolcEngine协议客户端 (~450行)
│
├── adapters/                       # 环境适配层
│   ├── __init__.py
│   ├── environment_detector.py     # 环境检测器 (~200行)
│   ├── logging_adapter.py          # 日志适配器 (~300行)
│   └── resource_manager.py         # 资源管理器 (~250行)
│
├── config/                         # 配置管理层
│   ├── __init__.py
│   ├── config_loader.py            # 配置加载器 (~200行)
│   ├── settings.py                 # 配置数据类 (~300行)
│   └── validation.py               # 配置验证器 (~200行)
│
├── protocols/                      # 协议层 (基于ast_demo.py)
│   ├── __init__.py
│   ├── volcengine_protocol.py      # VolcEngine协议处理 (~400行)
│   └── message_converter.py        # 消息转换器 (~250行)
│
├── api/                           # API接口层
│   ├── __init__.py
│   ├── endpoints.py               # FastAPI端点 (~350行)
│   └── models.py                  # API数据模型 (~200行)
│
└── utils/                         # 工具模块
    ├── __init__.py
    ├── async_utils.py             # 异步工具 (~150行)
    ├── file_utils.py              # 文件工具 (~150行)
    └── timing_utils.py            # 时间工具 (~100行)
```

## 🔧 关键实现指南

### 1. protocols/volcengine_protocol.py 实现
这是最关键的模块，必须基于`ast_demo.py`框架：

```python
"""
VolcEngine协议处理模块
基于ast_demo.py的成熟协议框架进行封装和扩展

CRITICAL: 以下函数必须从ast_demo.py逐行复制，保持100%一致
"""

import os
import uuid
import websockets
from websockets import Headers
from typing import Optional
from dataclasses import dataclass

# 导入protobuf生成的类型 (保持与ast_demo.py一致)
from products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse
from common.events_pb2 import Type

# 数据结构定义 (从ast_demo.py:37-74完全复制)
@dataclass
class Audio:
    format: str = None
    rate: int = None
    bits: Optional[int] = None
    channel: Optional[int] = None
    binary_data: Optional[bytes] = None

@dataclass
class TranslateRequestData:
    session_id: str
    event: str
    source_audio: Optional[Audio] = None
    target_audio: Optional[Audio] = None
    mode: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None

@dataclass
class TranslateResponseData:
    event: str
    session_id: str
    sequence: int
    text: str
    data: bytes
    message: str = None

# 核心协议函数 (从ast_demo.py逐行复制)
async def send_request(ws, request: TranslateRequestData):
    """
    发送请求到WebSocket服务器
    CRITICAL: 完全复用ast_demo.py:88-112的实现，逐行复制
    """
    request_data = TranslateRequest()
    request_data.request_meta.SessionID = request.session_id
    
    if request.event == "Type_StartSession":
        request_data.event = Type.StartSession
    elif request.event == "Type_TaskRequest":
        request_data.event = Type.TaskRequest
    elif request.event == "Type_FinishSession":
        request_data.event = Type.FinishSession
        
    request_data.user.uid = "ast_py_client"
    request_data.user.did = "ast_py_client"
    
    request_data.source_audio.format = "wav"
    request_data.source_audio.rate = 16000
    request_data.source_audio.bits = 16
    request_data.source_audio.channel = 1
    if request.source_audio and request.source_audio.binary_data:
        request_data.source_audio.binary_data = request.source_audio.binary_data
        
    request_data.target_audio.format = "ogg_opus"
    request_data.target_audio.rate = 24000
    
    request_data.request.mode = "s2s"
    request_data.request.source_language = "zh"
    request_data.request.target_language = "en"
    
    await ws.send(request_data.SerializeToString())

async def receive_message(ws) -> TranslateResponseData:
    """
    接收并解析服务器响应
    CRITICAL: 完全复用ast_demo.py:115-129的实现，逐行复制
    """
    response = await ws.recv()
    response_data = TranslateResponse()
    response_data.ParseFromString(response)
    
    return TranslateResponseData(
        event=response_data.event,
        session_id=response_data.response_meta.SessionID,
        sequence=response_data.response_meta.Sequence,
        text=response_data.text,
        data=response_data.data,
        message=response_data.response_meta.Message
    )

async def build_http_headers(config, conn_id: str) -> Headers:
    """
    构建WebSocket连接头部
    CRITICAL: 完全复用ast_demo.py:132-140的实现，逐行复制
    """
    headers = Headers({
        "X-Api-App-Key": config.app_key,
        "X-Api-Access-Key": config.access_key,
        "X-Api-Resource-Id": config.resource_id,
        "X-Api-Connect-Id": conn_id
    })
    return headers
```

### 2. core/session_manager.py 实现
会话管理器负责协调整个音频翻译流程：

```python
"""
会话管理器模块
负责管理音频翻译会话的完整生命周期
基于现有publisher.py的会话管理逻辑进行模块化重构
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional
from datetime import datetime

class SessionStatus(Enum):
    """会话状态枚举 - 与现有系统保持一致"""
    INITIALIZING = "initializing"
    STARTING = "starting" 
    CONNECTED_TO_PUBLISHER = "connected_to_publisher"
    PROCESSING_AUDIO = "processing_audio"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

@dataclass
class Session:
    """会话数据结构 - 基于现有PublisherSession扩展"""
    session_id: str
    youtube_url: str
    publish_url: str
    status: SessionStatus = SessionStatus.INITIALIZING
    task: Optional[asyncio.Task] = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    
    # 组件引用
    audio_pipeline: Optional['AudioPipeline'] = None
    volcengine_client: Optional['VolcEngineClient'] = None
    publisher_client: Optional['PublisherClient'] = None
    
    # 指标数据
    start_time: datetime = field(default_factory=datetime.now)
    audio_chunks_processed: int = 0
    bytes_processed: int = 0

class SessionManager:
    """
    会话管理器
    基于现有publisher.py:AudioStreamPublisher的逻辑重构
    """
    
    def __init__(self, max_concurrent_sessions: int = 10):
        self.sessions: Dict[str, Session] = {}
        self.max_concurrent_sessions = max_concurrent_sessions
        self.semaphore = asyncio.Semaphore(max_concurrent_sessions)
        self.logger = logging.getLogger(__name__)
    
    async def start_publishing_session(self, 
                                     session_id: str, 
                                     youtube_url: str, 
                                     publish_url: str) -> tuple[str, bool]:
        """
        启动发布会话 (幂等操作)
        基于现有publisher.py:start_publishing_session逻辑
        
        Returns:
            (session_id, is_new_session)
        """
        # 幂等性检查 - 与现有逻辑保持一致
        if session_id in self.sessions:
            existing_session = self.sessions[session_id]
            if existing_session.status in [
                SessionStatus.INITIALIZING, 
                SessionStatus.STARTING,
                SessionStatus.CONNECTED_TO_PUBLISHER, 
                SessionStatus.PROCESSING_AUDIO
            ]:
                self.logger.info(f"Session {session_id} already running")
                return session_id, False
            else:
                # 清理非活跃会话
                await self._cleanup_session(session_id)
        
        # 并发控制
        if len(self.sessions) >= self.max_concurrent_sessions:
            raise Exception("Maximum concurrent sessions reached")
        
        # 创建新会话
        session = Session(
            session_id=session_id,
            youtube_url=youtube_url,
            publish_url=publish_url
        )
        
        self.sessions[session_id] = session
        
        # 启动会话处理任务
        session.task = asyncio.create_task(
            self._run_session(session)
        )
        
        self.logger.info(f"Started new session {session_id}")
        return session_id, True
    
    async def _run_session(self, session: Session):
        """
        运行单个会话的主循环
        基于现有ast_youtube_demo.py的主要业务逻辑重构
        """
        try:
            await self.semaphore.acquire()
            session.status = SessionStatus.STARTING
            
            # 1. 并行初始化组件 (ast_youtube_demo.py:480-600)
            from core.audio_pipeline import AudioPipeline
            from infrastructure.volcengine_client import VolcEngineClient  
            from core.publisher_client import PublisherClient
            
            session.audio_pipeline = AudioPipeline()
            session.volcengine_client = VolcEngineClient()
            session.publisher_client = PublisherClient(session.publish_url)
            
            # 并行初始化任务
            init_tasks = [
                session.audio_pipeline.initialize(session.youtube_url),
                session.volcengine_client.initialize(),
                session.publisher_client.initialize()
            ]
            
            init_results = await asyncio.gather(*init_tasks, return_exceptions=True)
            
            # 检查初始化结果
            for i, result in enumerate(init_results):
                if isinstance(result, Exception):
                    raise Exception(f"Component {i} initialization failed: {result}")
            
            session.status = SessionStatus.CONNECTED_TO_PUBLISHER
            
            # 2. 启动音频处理管线 (ast_youtube_demo.py:650-800)
            await self._process_audio_stream(session)
            
            session.status = SessionStatus.COMPLETED
            
        except Exception as e:
            session.status = SessionStatus.FAILED
            self.logger.error(f"Session {session.session_id} failed: {e}")
        finally:
            await self._cleanup_session(session.session_id)
            self.semaphore.release()
    
    async def _process_audio_stream(self, session: Session):
        """
        处理音频流 - 核心业务逻辑
        基于ast_youtube_demo.py:850-1200的音频处理逻辑
        """
        session.status = SessionStatus.PROCESSING_AUDIO
        
        # 启动音频处理管线
        audio_stream = session.audio_pipeline.start_processing()
        
        # 启动WebSocket接收任务
        receive_task = asyncio.create_task(
            self._receive_and_forward(session)
        )
        
        try:
            # 音频流处理循环
            async for pcm_chunk in audio_stream:
                if session.stop_event.is_set():
                    break
                    
                # 发送音频块到VolcEngine
                await session.volcengine_client.send_audio_chunk(pcm_chunk)
                
                # 更新指标
                session.audio_chunks_processed += 1
                session.bytes_processed += len(pcm_chunk)
                
        finally:
            # 清理任务
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
    
    async def _receive_and_forward(self, session: Session):
        """
        接收翻译结果并转发
        基于ast_youtube_demo.py:1050-1200的事件处理逻辑
        """
        async for response in session.volcengine_client.start_receiving():
            if session.stop_event.is_set():
                break
                
            # 处理不同类型的响应事件
            if response.event in [Type.SourceSubtitleEnd, Type.TranslationSubtitleEnd]:
                # 字幕事件处理
                subtitle_json = self._convert_subtitle_event(response)
                await session.publisher_client.send_text_message(subtitle_json)
                
            elif response.event == Type.TTSSentenceEnd:
                # TTS音频事件处理  
                await session.publisher_client.send_audio_frame(response.data)
    
    def _convert_subtitle_event(self, response) -> str:
        """
        转换字幕事件为JSON格式
        基于ast_youtube_demo.py的事件转换逻辑
        """
        from protocols.message_converter import volcengine_event_to_json
        return volcengine_event_to_json(response)
```

### 3. 配置外化实现
将所有硬编码参数提取为配置：

```python
# config/settings.py
from pydantic import BaseSettings, validator
from typing import Optional

class AudioConfig(BaseSettings):
    """音频处理配置"""
    chunk_size: int = 640              # PCM块大小
    sample_rate: int = 16000           # 采样率 
    channels: int = 1                  # 声道数
    bit_depth: int = 16               # 位深度
    send_interval: float = 0.02        # 发送间隔(20ms)
    target_sample_rate: int = 24000    # 目标采样率
    
    @validator('chunk_size')
    def validate_chunk_size(cls, v):
        if v % 320 != 0 or v < 320 or v > 1280:
            raise ValueError('chunk_size must be multiple of 320')
        return v

class VolcEngineConfig(BaseSettings):
    """VolcEngine服务配置"""
    ws_url: str = "wss://openspeech.bytedance.com/api/v2/ast"
    app_key: str
    access_key: str  
    resource_id: str
    source_language: str = "zh"
    target_language: str = "en"
    mode: str = "s2s"
    
    # WebSocket连接配置
    max_size: int = 1000000000
    ping_interval: Optional[int] = None
    ping_timeout: Optional[int] = None

class TimeoutConfig(BaseSettings):
    """超时配置"""
    ffmpeg_start_timeout: int = 30
    first_chunk_timeout: int = 30  
    chunk_read_timeout: int = 10
    session_start_timeout: int = 10
    session_finish_timeout: int = 30
    silence_timeout_local: int = 8
    silence_timeout_cloudflare: int = 18

class GlobalConfig(BaseSettings):
    """全局配置"""
    audio: AudioConfig = AudioConfig()
    volcengine: VolcEngineConfig = VolcEngineConfig()
    timeout: TimeoutConfig = TimeoutConfig()
    
    class Config:
        env_file = '.env'
        env_nested_delimiter = '__'  # 支持 AUDIO__CHUNK_SIZE 格式
```

### 4. 环境适配实现
统一处理本地和Cloudflare环境差异：

```python
# adapters/environment_detector.py  
import os
import subprocess
from typing import Dict, Any

def detect_environment() -> str:
    """
    检测运行环境类型
    基于ast_youtube_demo.py:90-120的环境检测逻辑
    """
    if os.getenv("CF_PAGES"):
        return "cloudflare_pages"
    elif os.getenv("CF_WORKER"):
        return "cloudflare_worker" 
    elif os.getenv("DOCKER_CONTAINER"):
        return "docker"
    elif os.path.exists("/.dockerenv"):
        return "docker_detected"
    else:
        return "local"

def is_cloudflare_environment() -> bool:
    """
    检查是否为Cloudflare环境
    完全复用ast_youtube_demo.py的检测逻辑
    """
    cloudflare_indicators = ["CF_PAGES", "CF_PAGES_URL"]
    return any(os.getenv(indicator) for indicator in cloudflare_indicators)

def get_environment_config() -> Dict[str, Any]:
    """
    获取环境特定配置
    基于ast_youtube_demo.py的环境适配逻辑
    """
    env = detect_environment()
    
    if env.startswith("cloudflare"):
        return {
            "logging": {
                "file_enabled": False,
                "stderr_enabled": True,
                "log_prefix": "CLOUDFLARE_",
                "log_level": "INFO"
            },
            "timeouts": {
                "silence_timeout": 18,
                "ffmpeg_start_timeout": 30
            },
            "resources": {
                "memory_limit": "90MB",
                "max_sessions": 3
            }
        }
    else:
        return {
            "logging": {
                "file_enabled": True,
                "stderr_enabled": True,
                "log_prefix": "",
                "log_level": "DEBUG"
            },
            "timeouts": {
                "silence_timeout": 8,
                "ffmpeg_start_timeout": 15
            },
            "resources": {
                "memory_limit": None,
                "max_sessions": 20
            }
        }
```

## 🚨 关键实现要求

### 1. 音频处理参数严格保持
```python
CRITICAL_AUDIO_PARAMETERS = {
    "chunk_size": 640,              # 必须精确为640字节
    "sample_rate": 16000,           # 必须为16kHz
    "channels": 1,                  # 必须为单声道
    "bit_depth": 16,               # 必须为16位
    "send_interval": 0.02,          # 必须为20ms间隔
    "audio_format": "pcm_s16le"     # 必须为小端16位PCM
}
```

### 2. 静音桥接机制保持
```python
# core/audio_pipeline.py中必须实现的静音桥接逻辑
async def setup_silence_bridge(self):
    """
    静音桥接协调机制
    基于ast_youtube_demo.py:680-690的实现逻辑
    """
    from adapters.environment_detector import detect_environment
    
    # 环境适配超时 - 保持现有逻辑
    env = detect_environment()
    timeout = 18 if env.startswith("cloudflare") else 8
    
    silence_chunk = b'\x00' * self.config.chunk_size  # 640字节静音
    
    try:
        # 等待真实音频就绪或超时
        await asyncio.wait_for(
            self.audio_ready_event.wait(),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        self.logger.warning("Silence bridge timeout - continuing")
```

### 3. WebSocket事件处理保持
```python
# 必须处理的VolcEngine事件类型
REQUIRED_EVENT_HANDLING = {
    Type.SessionStarted: "会话启动确认",
    Type.SessionFinished: "会话正常结束", 
    Type.SessionFailed: "会话处理失败",
    Type.SourceSubtitleStart: "源语言字幕开始",
    Type.SourceSubtitleEnd: "源语言字幕结束",
    Type.TranslationSubtitleStart: "译文字幕开始", 
    Type.TranslationSubtitleEnd: "译文字幕结束",
    Type.TTSSentenceEnd: "TTS句子结束(含音频)"
}
```

## 📋 实现清单

### 阶段1: 协议层迁移
- [ ] 创建`protocols/volcengine_protocol.py`，逐行复制`ast_demo.py`核心函数
- [ ] 创建`protocols/message_converter.py`，实现事件转换逻辑
- [ ] 验证协议兼容性，确保与VolcEngine API 100%兼容

### 阶段2: 基础组件实现
- [ ] 实现`infrastructure/ffmpeg_manager.py`，迁移FFmpeg进程管理
- [ ] 实现`infrastructure/ytdlp_manager.py`，迁移yt-dlp管理逻辑
- [ ] 实现`infrastructure/volcengine_client.py`，基于协议层扩展客户端

### 阶段3: 核心业务逻辑
- [ ] 实现`core/session_manager.py`，重构会话生命周期管理
- [ ] 实现`core/audio_pipeline.py`，重构音频处理管线和静音桥接
- [ ] 实现`core/event_processor.py`，重构事件处理和转换逻辑

### 阶段4: 配置和适配
- [ ] 实现配置管理系统，外化所有硬编码参数
- [ ] 实现环境适配器，统一本地和Cloudflare环境差异
- [ ] 实现日志适配器，支持环境特定的日志策略

### 阶段5: API集成
- [ ] 重构FastAPI端点，集成新的模块化组件
- [ ] 实现完整的错误处理和状态管理
- [ ] 添加监控指标和健康检查

## 🧪 验证要求

### 功能验证
- API接口响应格式与现有系统100%一致
- 端到端音频翻译流程正常工作
- 幂等性操作行为完全相同
- 错误处理机制等价

### 性能验证  
- 端到端延迟不超过现有系统+10%
- 内存使用在Cloudflare环境<90MB
- 并发处理能力不低于现有系统
- 音频处理无丢包和延迟增加

### 代码质量验证
- 单元测试覆盖率>80%
- 每个模块文件<500行代码
- 无循环依赖
- 静态代码分析通过

## ⚠️ 注意事项

### 不要做的事情
1. **不要修改协议逻辑**: `ast_demo.py`中的协议处理函数必须原样保留
2. **不要改变音频参数**: 640字节块大小、16kHz采样率等参数不得修改
3. **不要破坏幂等性**: 会话启动的幂等行为必须保持一致
4. **不要忽略环境适配**: 必须同时支持本地和Cloudflare环境
5. **不要跳过测试**: 每个模块都必须有充分的单元测试

### 必须做的事情
1. **必须保持功能等价**: 重构后系统行为与原系统完全一致
2. **必须复用现有框架**: 基于`ast_demo.py`的成熟协议框架扩展
3. **必须外化配置**: 提取所有硬编码参数为可配置项
4. **必须环境适配**: 实现统一的环境差异处理
5. **必须完整测试**: 实现全面的测试覆盖和验证

---

**文档版本**: v1.0.0  
**关联文档**: [模块拆分方案](../02-refactoring/module-breakdown.md) | [配置参数目录](../01-current-system/configuration-catalog.md)  
**最后更新**: 2025-01-XX