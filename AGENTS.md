# AGENTS.md

本文档基于 2025 年 AGENTS.md 标准，为 AI 编程助手提供项目工作指南。

## 沟通偏好
- **语言**: 与用户沟通时使用中文
- **风格**: 简洁直接，避免冗余解释
- **日志记录**: 使用结构化日志，包含足够的上下文信息

## 项目概述
YouTube 实时音频翻译发布服务，提供：
- YouTube 直播音频流实时抓取
- 字节跳动同声传译服务集成  
- WebSocket 实时音频/字幕发布
- FastAPI + asyncio 异步架构

## 开发环境设置

### 依赖安装
```bash
pip install -r requirements.txt
```

### 环境变量配置
创建 `.env` 文件：
```bash
APP_KEY=your_app_key
ACCESS_KEY=your_access_key
RESOURCE_ID=your_resource_id
WS_URL=wss://your-translation-service.com
FINISH_GRACE_TIMEOUT=30.0
```

### 启动服务
```bash
# 开发环境
python main.py

# 或使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 9000 --reload
```

## 项目架构（重构后）

### 三层模块结构
- **core/**: 基础设施层 (config, 环境变量)
- **streaming/**: 流媒体处理域 (YouTube, FFmpeg, 翻译协议)  
- **publisher/**: Web API 服务域 (FastAPI, WebSocket)

### 依赖方向
```
core → streaming/publisher
```

### 关键设计原则
- 职责单一、依赖清晰
- 配置集中 (core.config)
- 异步优先 (asyncio)
- 懒加载单例模式

## 代码风格约定

### 导入顺序
```python
# 1. 标准库
import asyncio
import logging

# 2. 第三方库  
import websockets
from fastapi import FastAPI

# 3. 项目模块
from core.config import BASE_DIR
from .models import Config
```

### 异步编程
- 所有 I/O 操作使用 async/await
- 使用 `asyncio.create_task()` 创建并发任务
- 使用 `asyncio.shield()` 保护清理代码

### 错误处理
- 使用具体异常类型，避免裸露的 `Exception`
- 记录完整的错误上下文和堆栈跟踪
- 实现优雅降级和资源清理

### 类型注解
```python
async def translate_stream(url: str, duration: Optional[int] = None) -> AsyncGenerator[StreamData, None]:
```

## 构建命令

### 健康检查
```bash
curl http://localhost:9000/python/health
```

## API 端点
- `POST /python/ingest/start` - 开始翻译会话
- `POST /python/ingest/stop` - 停止翻译会话
- `GET /python/health` - 健康检查  
- `GET /python/sessions` - 活跃会话列表

## 贡献指南

### 提交消息格式
```
类型(作用域): 简短描述

详细说明（如需要）

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### Pull Request 指南
- 保持单一职责原则
- 包含适当的测试覆盖
- 更新相关文档
- 确保不破坏现有 API 兼容性

### 代码审查重点
- 异步任务协调逻辑正确性
- 资源清理的完整性
- WebSocket 连接管理
- 错误处理覆盖度

## 项目特定注意事项

### 关键约束
- 单容器单会话限制
- FFmpeg 进程生命周期管理
- WebSocket 连接自动重连机制
- 静音桥防止翻译服务超时

### 性能考虑
- yt-dlp 预热机制减少首次延迟
- PCM 数据流 80ms 帧率同步
- 宽限期机制确保优雅停止

### 安全要求
- API 密钥通过环境变量管理
- 不在日志中暴露敏感信息
- cookie 文件路径安全性

### 故障排查策略
- **统一控制台日志**: 所有组件输出到 stdout/stderr
- **结构化日志格式**: JSON 格式便于解析和过滤
- **日志组件标识**: 
  - `ast.ffmpeg`: FFmpeg 处理日志
  - `ast.ytdlp`: YouTube 流提取日志
  - `ast.event`: 翻译事件JSON日志
  - `ast.session`: 会话管理日志

## 相关文档
- 详细架构流程: `doc/publisher_flow.md`
- Claude 专用指南: `CLAUDE.md`
- protobuf 定义: `protos/`
- 同声传译API文档: `doc/同声传译2.0-API接入文档.md`