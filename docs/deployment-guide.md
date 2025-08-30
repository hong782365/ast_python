# StreamLingua Python 服务 Cloudflare Containers 部署指南

> **版本**: v1.0  
> **更新日期**: 2025-08-29  
> **适用项目**: StreamLingua 同声传译 Web 应用

---

## 🎯 部署概述

### 目标架构
```
NextJS (streamlingua.live) 
    ↓ HTTP API
ws-gateway (ws.streamlingua.live) 
    ↓ Container Management
Python Container (Cloudflare Containers)
    ↓ WebSocket Connection
ws-gateway (WebSocket Publisher)
    ↓ Audio Stream Broadcast  
Users (WebSocket Subscribers)
```

### 核心组件
- **Python Container**: 运行 `publisher.py` 服务
- **ws-gateway**: 扩展为容器管理 + WebSocket 路由
- **Dockerfile**: Python 环境和依赖打包

---

## 📋 前置准备

### 1. 环境要求
- **Node.js**: 20+ (用于 wrangler)
- **Docker**: 最新版本 (用于镜像构建)
- **Cloudflare 账户**: 付费计划 (支持 Containers)
- **wrangler CLI**: 最新版本

```bash
# 安装 wrangler
npm install -g wrangler@latest

# 验证版本 (需要支持 containers)
wrangler --version

# 登录 Cloudflare
wrangler auth login
```

### 2. 项目结构确认
```
📁 工作区/
├── 📁 s2s/ast_python/                    # Python 项目
│   ├── publisher.py                      # 主服务
│   ├── requirements.txt                  # Python 依赖
│   ├── youtube/cookie/youtube_hongc_cookies.txt  # YouTube cookies
│   ├── Dockerfile                        # 新建
│   └── docs/                             # 文档目录
│
└── 📁 nextjs/example/ws-gateway/         # Worker 项目
    ├── wrangler.jsonc                    # 需要修改
    ├── src/index.js                      # 需要扩展
    └── package.json                      # 需要更新依赖
```

---

## 🐳 Step 1: 创建 Python Dockerfile

### 在 Python 项目根目录创建 Dockerfile

**文件路径**: `/Users/weihongwang/Documents/workspace/s2s/ast_python/Dockerfile`

```dockerfile
FROM python:3.11-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置工作目录
WORKDIR /app

# 复制 YouTube cookies（关键文件）
COPY youtube/cookie/youtube_hongc_cookies.txt ./youtube/cookie/
RUN mkdir -p youtube/cookie

# 复制并安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 9000

# 启动命令
CMD ["python", "publisher.py"]
```

### 验证 Dockerfile

```bash
# 在 Python 项目目录测试构建
cd /Users/weihongwang/Documents/workspace/s2s/ast_python
docker build -t streamlingua-python:test .

# 测试运行（可选）
docker run -p 9000:9000 --env-file .env streamlingua-python:test
```

---

## ⚙️ Step 2: 配置 ws-gateway

### 2.1 修改 package.json

**文件路径**: `/Users/weihongwang/Documents/workspace/nextjs/example/ws-gateway/package.json`

```json
{
  "name": "ws-gateway",
  "version": "1.0.0",
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy"
  },
  "dependencies": {
    "@cloudflare/containers": "^1.0.0"
  },
  "devDependencies": {
    "wrangler": "^3.0.0"
  }
}
```

### 2.2 修改 wrangler.jsonc

**文件路径**: `/Users/weihongwang/Documents/workspace/nextjs/example/ws-gateway/wrangler.jsonc`

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "ws-gateway",
  "main": "src/index.js",
  "compatibility_date": "2025-08-16",
  "observability": {
    "enabled": true
  },
  
  // 容器配置
  "containers": [
    {
      "name": "python-service",
      "image": "../../../s2s/ast_python/Dockerfile",
      "tag": "v1.0.0",
      "port": 9000,
      "enableInternet": true
    }
  ],
  
  // Durable Objects 配置
  "durable_objects": {
    "bindings": [
      {
        "name": "WS_GATEWAY_ROOM",
        "class_name": "WSGatewayRoom"
      },
      {
        "name": "PYTHON_CONTAINER",
        "class_name": "PythonContainerManager"
      }
    ]
  },
  
  // 数据库迁移
  "migrations": [
    {
      "tag": "v1",
      "new_classes": ["WSGatewayRoom"]
    },
    {
      "tag": "v2", 
      "new_classes": ["PythonContainerManager"]
    }
  ],
  
  // 环境变量（敏感信息）
  "vars": {
    "PYTHON_SERVICE_VERSION": "v1.0.0"
  }
}
```

### 2.3 扩展 index.js

**文件路径**: `/Users/weihongwang/Documents/workspace/nextjs/example/ws-gateway/src/index.js`

在现有代码基础上添加容器管理功能：

```javascript
// 导入容器支持
import { Container, DurableObject } from '@cloudflare/containers';

// 新增：Python 容器管理的 Durable Object
export class PythonContainerManager extends DurableObject {
  constructor(state, env) {
    super(state, env);
    this.container = new Container('python-service', {
      image: 'python-service',
      port: 9000,
      sleepAfter: 0,  // 常驻运行，不自动休眠
      enableInternet: true
    });
  }

  async fetch(request) {
    const url = new URL(request.url);
    
    // 健康检查
    if (url.pathname === '/health') {
      return new Response(JSON.stringify({
        status: 'healthy',
        container_running: this.container.running,
        timestamp: Date.now()
      }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    // 确保容器运行
    if (!this.container.running) {
      console.log('Starting Python container...');
      await this.container.start();
      
      // 等待容器就绪（最多30秒）
      let attempts = 0;
      while (!this.container.running && attempts < 30) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        attempts++;
      }
      
      if (!this.container.running) {
        return new Response('Container failed to start', { status: 500 });
      }
      
      console.log('Python container started successfully');
    }
    
    // 转发请求到 Python 容器
    try {
      return await this.container.fetch(request);
    } catch (error) {
      console.error('Container fetch error:', error);
      return new Response('Container error: ' + error.message, { status: 500 });
    }
  }
}

// 保持原有的 WSGatewayRoom 类不变
export class WSGatewayRoom {
  // ... 现有的 WebSocket 管理逻辑保持不变 ...
}

// 修改主 Worker，添加容器路由
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    
    // 健康检查
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(JSON.stringify({
        service: "WSGateway + Python Container Manager",
        timestamp: Date.now(),
        version: env.PYTHON_SERVICE_VERSION || "unknown"
      }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 新增：Python 容器路由
    if (url.pathname.startsWith("/python/") || url.pathname.startsWith("/ingest/")) {
      const containerId = env.PYTHON_CONTAINER.idFromName("main-container");
      const containerObj = env.PYTHON_CONTAINER.get(containerId);
      return containerObj.fetch(request);
    }

    // 原有的 WebSocket 处理逻辑保持不变
    if (url.pathname.startsWith("/ws/")) {
      const sessionId = url.searchParams.get("sessionId");
      
      if (!sessionId) {
        return new Response("Missing sessionId parameter", { status: 400 });
      }

      const durableObjectId = env.WS_GATEWAY_ROOM.idFromName(sessionId);
      const durableObject = env.WS_GATEWAY_ROOM.get(durableObjectId);
      
      return durableObject.fetch(request);
    }

    return new Response("Not found", { status: 404 });
  }
};
```

---

## 🚀 Step 3: 部署流程

### 3.1 安装依赖

```bash
cd /Users/weihongwang/Documents/workspace/nextjs/example/ws-gateway

# 安装新依赖
npm install @cloudflare/containers

# 验证 wrangler 配置
wrangler config check
```

### 3.2 设置环境变量

```bash
# 设置 Python 服务需要的敏感环境变量
wrangler secret put APP_KEY
wrangler secret put ACCESS_KEY  
wrangler secret put RESOURCE_ID
wrangler secret put WS_URL

# 设置 WebSocket 共享密钥
wrangler secret put WS_SHARED_SECRET

# 列出所有密钥确认
wrangler secret list
```

### 3.3 首次部署

```bash
# 在 ws-gateway 目录执行部署
cd /Users/weihongwang/Documents/workspace/nextjs/example/ws-gateway

# 部署（会自动构建 Python 镜像）
wrangler deploy

# 预期输出：
# ✨ Uploading container image...
# 🏗️ Building Python service container...  
# 📤 Uploading to Cloudflare Container Registry...
# 🚀 Deploying Worker with containers...
# ✅ Successfully deployed to https://ws-gateway.your-account.workers.dev
```

### 3.4 验证部署

```bash
# 测试健康检查
curl https://ws.streamlingua.live/health

# 期望返回：
# {
#   "service": "WSGateway + Python Container Manager",
#   "timestamp": 1693304400000,
#   "version": "v1.0.0"
# }

# 测试容器健康状态
curl https://ws.streamlingua.live/python/health

# 期望返回：
# {
#   "status": "healthy", 
#   "container_running": true,
#   "timestamp": 1693304400000
# }
```

---

## 🔄 Step 4: 更新 NextJS 调用

### 修改 NextJS 中的 API 调用

**更新前**（假设之前直接调用 Python 服务）：
```javascript
const response = await fetch('http://localhost:9000/ingest/start', {
  method: 'POST',
  // ...
});
```

**更新后**（通过 ws-gateway 调用）：
```javascript
const response = await fetch('https://ws.streamlingua.live/ingest/start', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    sessionId: sessionId,
    youtube_url: youtubeUrl,
    publishUrl: `wss://ws.streamlingua.live/ws/publish?sessionId=${sessionId}&token=${token}`
  })
});
```

---

## 🔧 Step 5: 更新和维护

### 5.1 更新 Python 代码

当需要更新 Python 服务时：

```bash
cd /Users/weihongwang/Documents/workspace/nextjs/example/ws-gateway

# 方法1：更新版本标签（推荐）
# 编辑 wrangler.jsonc，修改 tag: "v1.0.1"
# 然后部署
wrangler deploy

# 方法2：强制重建
wrangler deploy --force
```

### 5.2 监控和日志

```bash
# 查看 Worker 日志
wrangler tail

# 查看容器状态
curl https://ws.streamlingua.live/python/health

# 查看活跃会话
curl https://ws.streamlingua.live/python/sessions
```

### 5.3 故障排除

**常见问题**：

1. **容器启动失败**
   ```bash
   # 检查镜像构建日志
   wrangler deploy --verbose
   
   # 本地测试 Dockerfile
   cd /path/to/python/project
   docker build -t test-image .
   ```

2. **网络连接问题**
   ```bash
   # 确认 enableInternet 配置
   # 检查环境变量设置
   wrangler secret list
   ```

3. **WebSocket 连接断开**
   ```bash
   # 检查心跳机制
   # 确认 100 秒超时处理
   ```

---

## 📊 Step 6: 性能监控

### 6.1 关键指标

**容器指标**：
- 容器启动时间（目标：<5秒）
- 内存使用率（监控峰值）
- CPU 使用率（监控持续负载）
- WebSocket 连接数量

**业务指标**：
- 翻译延迟（目标：<3秒）
- 会话成功率（目标：>99%）
- 用户并发数

### 6.2 监控工具

```bash
# Cloudflare Analytics
# 在 Cloudflare Dashboard 查看 Workers Analytics

# 自定义监控
curl -s https://ws.streamlingua.live/python/health | jq '.container_running'

# 会话状态监控
curl -s https://ws.streamlingua.live/python/sessions | jq '.sessions | length'
```

---

## 🔒 Step 7: 安全配置

### 7.1 环境变量安全

```bash
# 敏感信息使用 wrangler secrets
wrangler secret put APP_KEY
wrangler secret put ACCESS_KEY
wrangler secret put RESOURCE_ID
wrangler secret put WS_SHARED_SECRET

# 非敏感配置使用 vars
# 在 wrangler.jsonc 中配置
```

### 7.2 访问控制

```javascript
// 在容器管理中添加简单的认证
export class PythonContainerManager extends DurableObject {
  async fetch(request) {
    // 验证来源（可选）
    const origin = request.headers.get('Origin');
    if (origin && !origin.includes('streamlingua.live')) {
      return new Response('Unauthorized', { status: 403 });
    }
    
    // ... 现有逻辑
  }
}
```

---

## 📝 部署检查清单

### 部署前检查
- [ ] Python 项目 Dockerfile 创建完成
- [ ] ws-gateway wrangler.jsonc 配置更新
- [ ] ws-gateway index.js 容器管理代码添加
- [ ] 环境变量和密钥设置完成
- [ ] 本地 Docker 测试通过

### 部署中检查  
- [ ] `wrangler deploy` 执行成功
- [ ] 容器镜像上传完成
- [ ] Worker 部署到正确域名
- [ ] 健康检查接口响应正常

### 部署后验证
- [ ] `/health` 端点返回正确状态
- [ ] `/python/health` 显示容器运行中
- [ ] NextJS 能成功调用 `/ingest/start`
- [ ] WebSocket 连接建立正常
- [ ] 端到端翻译流程测试通过

---

## 🔄 回滚计划

### 快速回滚

如果部署出现问题：

```bash
# 回滚到之前版本
wrangler rollback

# 或者重新部署已知正常的版本
# 修改 wrangler.jsonc 中的 tag 到之前版本
# 然后重新部署
wrangler deploy
```

### 降级到原架构

如果需要完全回到原来的部署方式：

1. 修改 NextJS 调用地址回到原来的服务
2. 停用 ws-gateway 的容器功能
3. 重新启动独立的 Python 服务

---

## 📞 支持和联系

### 文档更新
- **调研文档**: `docs/cloudflare-containers-research.md`
- **部署文档**: `docs/deployment-guide.md` (本文档)

### 问题反馈
- Cloudflare Containers: [GitHub Issues](https://github.com/cloudflare/containers/issues)
- 项目问题: 内部 Issue Tracker

---

**部署文档完成** ✅  
**最后更新**: 2025-08-29  
**版本**: v1.0