# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 沟通偏好
- **语言**: 与用户沟通时使用中文

## 项目概述
本项目是一个 YouTube 实时音频翻译发布服务，提供以下核心功能：
- 实时抓取 YouTube 直播音频流
- 通过字节跳动同声传译服务进行实时翻译
- 将翻译后的音频和字幕通过 WebSocket 发布到指定端点
- 支持会话管理、状态监控和优雅停止

## 技术栈
- **主要语言**: Python 3.11+
- **Web框架**: FastAPI + Uvicorn
- **流媒体处理**: FFmpeg + yt-dlp
- **通信协议**: WebSocket (websockets库)
- **序列化**: Protocol Buffers (protobuf)
- **配置管理**: python-dotenv
- **容器化**: Docker
- **其他依赖**: asyncio, logging, pathlib

## 项目架构 (2025年重构后)

### 三层模块化架构
```
ast_python/
├── core/                    # 核心基础设施层
│   ├── config.py           # 统一配置、环境变量、路径管理
│   └── __init__.py
├── streaming/              # 流媒体处理域
│   ├── pipeline.py         # 主翻译流程协调
│   ├── ytdlp_manager.py    # YouTube流提取管理
│   ├── streamer.py         # FFmpeg流媒体处理
│   ├── models.py           # 数据结构定义
│   ├── logger.py           # 事件日志记录
│   ├── proto_helpers.py    # protobuf通信辅助
│   ├── pcm_reader.py       # PCM音频数据读取
│   ├── silence_bridge.py   # 静音桥接处理
│   └── __init__.py
├── publisher/              # Web API服务域
│   ├── routes.py           # API路由定义
│   ├── session_manager.py  # 会话生命周期管理
│   ├── websocket_client.py # 发布端WebSocket客户端
│   ├── models.py           # API数据模型
│   ├── lifespan.py         # 应用生命周期管理
│   └── __init__.py
└── main.py                 # 统一应用入口
```

### 核心设计原则
- **职责单一**: 每个模块专注特定功能域
- **依赖清晰**: core → streaming/publisher，避免循环依赖
- **配置集中**: 所有配置通过 core.config 统一管理
- **异步优先**: 全面使用 asyncio 进行并发处理

## 环境配置
项目需要以下环境变量（通过 .env 文件配置）：
```bash
# 字节跳动同声传译服务配置
APP_KEY=your_app_key
ACCESS_KEY=your_access_key  
RESOURCE_ID=your_resource_id
WS_URL=wss://your-translation-service.com

# 可选配置
FINISH_GRACE_TIMEOUT=30.0    # FinishSession宽限期（秒）
```

## 开发指南

### 启动服务
```bash
# 开发环境启动
python main.py

# 或使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 9000 --reload

# Docker启动
docker build -t ast-publisher .
docker run -p 9000:9000 --env-file .env ast-publisher
```

### API端点
- `POST /python/ingest/start` - 开始音频采集会话
- `POST /python/ingest/stop` - 停止音频采集会话  
- `GET /python/health` - 健康检查
- `GET /python/sessions` - 查看活跃会话

### 代码约定
- **导入顺序**: 标准库 → 第三方库 → 项目模块
- **异步函数**: 所有I/O操作使用async/await
- **错误处理**: 使用具体的异常类型，避免裸露的Exception
- **日志记录**: 使用结构化日志，包含足够的上下文信息
- **类型提示**: 为所有公共接口提供类型注解

### 关键流程
1. **会话启动**: API接收请求 → 创建会话 → 启动后台任务
2. **音频处理**: yt-dlp提取URL → FFmpeg转换PCM → 发送到翻译服务
3. **结果发布**: 接收翻译结果 → 通过WebSocket转发到客户端
4. **会话清理**: 优雅停止 → 资源清理 → 状态更新

### 测试策略
- 使用公开的YouTube直播进行集成测试
- 模拟网络异常和服务中断场景
- 验证会话管理和资源清理的正确性

## 故障排查
- **FFmpeg日志**: `youtube/ffmpeg/log/` 目录
- **翻译事件日志**: `youtube/ast_event/` 目录  
- **yt-dlp调试日志**: `youtube/logs/yt-dlp-debug.log`
- **应用日志**: 控制台输出或容器日志

## 重要文件
- `ffmpeg_utils.py` - FFmpeg工具函数
- `protos/` - Protocol Buffers定义
- `python_protogen/` - 生成的protobuf Python代码
- `youtube/cookie/` - YouTube认证cookies
- `doc/publisher_flow.md` - 详细的流程文档
- `doc/同声传译2.0-API接入文档.md` - 同声传译API文档

## 开发注意事项
- 重构后保持所有API接口向后兼容
- 异步任务协调逻辑较复杂，修改时需特别谨慎
- WebSocket连接管理包含自动重连和心跳机制
- 一个容器实例同时只能处理一个翻译会话