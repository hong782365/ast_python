# StreamLingua Python 服务 Cloudflare Containers 部署指南

> **版本**: v2.0  
> **更新日期**: 2025-08-30  
> **适用项目**: StreamLingua 同声传译 Web 应用  
> **架构**: 独立 Workers + Service Bindings

---

## 🎯 部署概述

### 目标架构 (更新)
```
NextJS (streamlingua.live)
    ↓ HTTP API
ast_python_workers (inner.streamlingua.live)
    ↓ Container Management
Python Container (Cloudflare Containers)
    ↓ WebSocket Connection
ws-gateway (ws.streamlingua.live)
    ↓ Audio Stream Broadcast
Users (WebSocket Subscribers)
```

### 核心组件
- **Python Container**: 运行 `publisher.py` 服务
- **ast_python_workers**: 专门管理 Python 容器的 Workers
- **ws-gateway**: 专注于 WebSocket 路由功能
- **Service Bindings**: 未来优化服务间通信

---

## 📋 前置准备

### 1. 环境要求
- **Node.js**: 20+ (用于 wrangler)
- **Docker Desktop**: 最新版本 (必需，用于本地构建镜像)
- **Cloudflare 账户**: 付费计划 (支持 Containers)
- **wrangler CLI**: 最新版本

```bash
# 安装 Docker Desktop (必需)
# macOS:
brew install --cask docker

# 或从官网下载: https://www.docker.com/products/docker-desktop/

# 启动 Docker Desktop (必须运行)
open -a Docker

# 验证 Docker 运行状态 (必需步骤)
docker version
docker ps

# 安装 wrangler
npm install -g wrangler@latest

# 验证版本 (需要支持 containers)
wrangler --version

# 登录 Cloudflare
wrangler auth login
```

### 2. 项目结构确认 (更新)
```
📁 工作区/
├── 📁 s2s/ast_python/                    # Python 项目
│   ├── publisher.py                      # 主服务
│   ├── requirements.txt                  # Python 依赖
│   ├── youtube/cookie/youtube_hongc_cookies.txt  # YouTube cookies
│   ├── Dockerfile                        # 新建
│   └── docs/                             # 文档目录
│
├── 📁 nextjs/example/ws-gateway/         # WebSocket Worker 项目 (保持不变)
│   ├── wrangler.jsonc                    # 无需修改
│   ├── src/index.js                     # 无需修改
│   └── package.json                     # 无需修改
│
└── 📁 ast_python_workers/                # 新建：Python 容器管理 Worker
    ├── wrangler.jsonc                    # 新建
    ├── src/index.js                     # 新建
    └── package.json                     # 新建
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
# 确保 Docker Desktop 正在运行
docker version

# 在 Python 项目目录测试构建
cd /Users/weihongwang/Documents/workspace/s2s/ast_python
docker build -t streamlingua-python:test .

# 验证镜像构建成功
docker images | grep streamlingua-python

# 测试运行（可选，需要 .env 文件）
docker run -p 9000:9000 --env-file .env streamlingua-python:test
```

**⚠️ 重要提醒**:
- **Docker Desktop 必须在后台运行**，否则 wrangler deploy 会失败
- 首次构建可能需要较长时间（下载基础镜像）
- 镜像大小限制为 2GB

---

## ⚙️ Step 2: 创建 ast_python_workers 项目

### 2.1 创建项目目录

```bash
# 创建新的 Workers 项目目录
mkdir -p /Users/weihongwang/Documents/workspace/ast_python_workers
cd /Users/weihongwang/Documents/workspace/ast_python_workers
```

### 2.2 创建 package.json

**文件路径**: `/Users/weihongwang/Documents/workspace/ast_python_workers/package.json`

```json
{
  "name": "ast-python-workers",
  "version": "1.0.0",
  "description": "Cloudflare Workers for managing StreamLingua Python containers",
  "main": "src/index.js",
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "tail": "wrangler tail"
  },
  "dependencies": {
    "@cloudflare/containers": "^1.0.0"
  },
  "devDependencies": {
    "wrangler": "^3.0.0"
  },
  "author": "StreamLingua Team",
  "license": "MIT"
}
```

### 2.3 创建 wrangler.jsonc

**文件路径**: `/Users/weihongwang/Documents/workspace/ast_python_workers/wrangler.jsonc`

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "ast-python-service",
  "main": "src/index.js",
  "compatibility_date": "2025-08-30",
  "observability": {
    "enabled": true
  },
  
  // 容器配置
  "containers": [
    {
      "name": "python-service",
      "image": "../s2s/ast_python/Dockerfile",
      "tag": "v1.0.0",
      "port": 9000,
      "enableInternet": true
    }
  ],
  
  // Durable Objects 配置
  "durable_objects": {
    "bindings": [
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
      "new_classes": ["PythonContainerManager"]
    }
  ],
  
  // 自定义域名路由
  "routes": [
    {
      "pattern": "inner.streamlingua.live/*",
      "zone_name": "streamlingua.live"
    }
  ],
  
  // 环境变量（非敏感信息）
  "vars": {
    "SERVICE_NAME": "StreamLingua Python Service",
    "SERVICE_VERSION": "v1.0.0"
  }
}
```

### 2.4 创建 src/index.js

**文件路径**: `/Users/weihongwang/Documents/workspace/ast_python_workers/src/index.js`

```javascript
// StreamLingua Python 容器管理 Workers
import { Container, DurableObject } from '@cloudflare/containers';

// 辅助函数：生成时间戳
function getTimestamp() {
  return new Date().toISOString();
}

// Python 容器管理的 Durable Object
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
    
    console.log(`[${getTimestamp()}] Container request: ${url.pathname}`);
    
    // 健康检查
    if (url.pathname === '/health') {
      return new Response(JSON.stringify({
        service: 'StreamLingua Python Container',
        status: 'healthy',
        container_running: this.container.running,
        timestamp: Date.now()
      }), {
        headers: { 
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }
    
    // 确保容器运行
    if (!this.container.running) {
      console.log(`[${getTimestamp()}] Starting Python container...`);
      
      try {
        await this.container.start();
        
        // 等待容器就绪（最多60秒）
        let attempts = 0;
        while (!this.container.running && attempts < 60) {
          await new Promise(resolve => setTimeout(resolve, 1000));
          attempts++;
        }
        
        if (!this.container.running) {
          console.error(`[${getTimestamp()}] Container failed to start after ${attempts} attempts`);
          return new Response(JSON.stringify({
            error: 'Container failed to start',
            attempts: attempts
          }), { 
            status: 500,
            headers: { 'Content-Type': 'application/json' }
          });
        }
        
        console.log(`[${getTimestamp()}] Python container started successfully in ${attempts} seconds`);
        
      } catch (error) {
        console.error(`[${getTimestamp()}] Container start error:`, error);
        return new Response(JSON.stringify({
          error: 'Container start failed',
          message: error.message
        }), { 
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }
    
    // 转发请求到 Python 容器
    try {
      console.log(`[${getTimestamp()}] Forwarding request to container`);
      const response = await this.container.fetch(request);
      console.log(`[${getTimestamp()}] Container response status: ${response.status}`);
      
      return response;
      
    } catch (error) {
      console.error(`[${getTimestamp()}] Container fetch error:`, error);
      return new Response(JSON.stringify({
        error: 'Container communication failed',
        message: error.message
      }), { 
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  }
}

// 主 Worker 入口
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    
    console.log(`[${getTimestamp()}] Incoming request: ${url.pathname}`);
    
    // CORS 预检请求处理
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 200,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Authorization',
          'Access-Control-Max-Age': '86400',
        }
      });
    }
    
    // 根路径健康检查
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(JSON.stringify({
        service: env.SERVICE_NAME || "StreamLingua Python Service",
        version: env.SERVICE_VERSION || "v1.0.0",
        timestamp: Date.now(),
        endpoint: url.hostname
      }), {
        headers: { 
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

    // 所有其他请求转发到 Python 容器
    // 使用固定 ID 确保只有一个常驻容器
    const containerId = env.PYTHON_CONTAINER.idFromName("main-container");
    const containerObj = env.PYTHON_CONTAINER.get(containerId);
    
    return containerObj.fetch(request);
  }
};
```

---

## 🚀 Step 3: 部署流程

### 3.1 安装依赖

```bash
cd /Users/weihongwang/Documents/workspace/ast_python_workers

# 安装依赖
npm install

# 验证 wrangler 配置
wrangler config check
```

### 3.2 设置环境变量

```bash
# 进入 ast_python_workers 目录
cd /Users/weihongwang/Documents/workspace/ast_python_workers

# 设置 Python 服务需要的敏感环境变量
wrangler secret put APP_KEY
wrangler secret put ACCESS_KEY  
wrangler secret put RESOURCE_ID
wrangler secret put WS_URL

# 列出所有密钥确认
wrangler secret list
```

### 3.3 首次部署

```bash
# 在 ast_python_workers 目录执行部署
cd /Users/weihongwang/Documents/workspace/ast_python_workers

# 部署（会在本地构建镜像，然后上传）
wrangler deploy

# 实际执行过程：
# 1. 🐳 在本地构建 Docker 镜像 (需要 Docker 运行)
# 2. 📤 推送镜像到 Cloudflare 容器注册表
# 3. 🚀 部署 Worker 代码到全球节点
# 4. 🔗 配置容器与 Worker 的关联

# 预期输出：
# ✨ Building container image locally...
# 🏗️ Docker build completed successfully  
# 📤 Pushing to registry.cloudflare.com...
# 🚀 Deploying Worker with containers...
# ✅ Successfully deployed to https://inner.streamlingua.live
```

### 3.4 验证部署

```bash
# 测试健康检查
curl https://inner.streamlingua.live/health

# 期望返回：
# {
#   "service": "StreamLingua Python Service",
#   "version": "v1.0.0",
#   "timestamp": 1693304400000,
#   "endpoint": "inner.streamlingua.live"
# }

# 测试容器健康状态 
curl https://inner.streamlingua.live/health

# 期望返回：
# {
#   "service": "StreamLingua Python Container",
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

**更新后**（通过 ast_python_workers 调用）：
```javascript
const response = await fetch('https://inner.streamlingua.live/ingest/start', {
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

### NextJS 环境变量配置

**更新 NextJS 项目的环境变量**：
```bash
# .env.local or .env.production
NEXT_PUBLIC_PYTHON_SERVICE_URL=https://inner.streamlingua.live
NEXT_PUBLIC_WS_GATEWAY_URL=wss://ws.streamlingua.live
```

### 示例：完整的调用函数

```javascript
// utils/pythonService.js
const PYTHON_SERVICE_URL = process.env.NEXT_PUBLIC_PYTHON_SERVICE_URL || 'https://inner.streamlingua.live';

export async function startTranslation(sessionId, youtubeUrl, token) {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/ingest/start`, {
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

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();
    console.log('Translation started:', result);
    return result;
    
  } catch (error) {
    console.error('Failed to start translation:', error);
    throw error;
  }
}

export async function stopTranslation(sessionId) {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/ingest/stop`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        sessionId: sessionId
      })
    });

    const result = await response.json();
    console.log('Translation stopped:', result);
    return result;
    
  } catch (error) {
    console.error('Failed to stop translation:', error);
    throw error;
  }
}

export async function checkServiceHealth() {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/health`);
    const result = await response.json();
    return result;
  } catch (error) {
    console.error('Service health check failed:', error);
    return { status: 'error', message: error.message };
  }
}
```

---

## 🔧 Step 5: 更新和维护

### 5.1 更新 Python 代码

当需要更新 Python 服务时：

```bash
cd /Users/weihongwang/Documents/workspace/ast_python_workers

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
cd /Users/weihongwang/Documents/workspace/ast_python_workers
wrangler tail

# 查看容器状态
curl https://inner.streamlingua.live/health

# 查看活跃会话
curl https://inner.streamlingua.live/sessions
```

### 5.3 故障排除

**常见问题**：

1. **Docker 相关问题**
   ```bash
   # Docker 未运行
   # 错误：Cannot connect to the Docker daemon
   # 解决：确保 Docker Desktop 正在运行
   open -a Docker
   docker version
   
   # Docker 空间不足
   # 错误：no space left on device
   # 解决：清理 Docker 资源
   docker system prune -a
   docker volume prune
   
   # Docker 权限问题
   # 错误：permission denied
   # 解决：确保用户在 docker 组中
   sudo usermod -aG docker $USER
   ```

2. **镜像构建失败**
   ```bash
   # 检查镜像构建日志
   wrangler deploy --verbose
   
   # 本地测试 Dockerfile
   cd /Users/weihongwang/Documents/workspace/s2s/ast_python
   docker build -t test-image .
   
   # 检查镜像大小（限制 2GB）
   docker images | grep test-image
   
   # 如果镜像过大，优化 Dockerfile
   # 使用 .dockerignore 文件排除不需要的文件
   ```

3. **镜像推送失败**
   ```bash
   # 网络连接问题
   # 确保可以访问 registry.cloudflare.com
   curl -I https://registry.cloudflare.com
   
   # 认证问题
   # 重新登录 Cloudflare
   wrangler auth login
   
   # 手动推送镜像测试
   wrangler containers push python-service
   ```

4. **网络连接问题**
   ```bash
   # 确认 enableInternet 配置
   # 检查环境变量设置
   wrangler secret list
   ```

5. **WebSocket 连接断开**
   ```bash
   # 检查心跳机制
   # 确认 100 秒超时处理
   ```

6. **容器启动超时**
   ```bash
   # 容器启动时间过长（>60秒）
   # 可能原因：
   # - Python 依赖安装时间长
   # - 镜像过大导致拉取缓慢
   # - 容器初始化逻辑复杂
   
   # 解决方案：
   # - 优化 Dockerfile，使用多阶段构建
   # - 减少 requirements.txt 中的依赖
   # - 预热常用的 Python 库
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
- [ ] **Docker Desktop 已安装并运行** (必需)
- [ ] Python 项目 Dockerfile 创建完成
- [ ] ast_python_workers 项目创建完成
- [ ] wrangler.jsonc 配置正确
- [ ] 环境变量和密钥设置完成
- [ ] 本地 Docker 镜像构建测试通过

### 部署中检查  
- [ ] `wrangler deploy` 执行成功
- [ ] **Docker 镜像本地构建成功**
- [ ] **镜像推送到 Cloudflare 注册表成功**
- [ ] Worker 部署到正确域名 (inner.streamlingua.live)
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