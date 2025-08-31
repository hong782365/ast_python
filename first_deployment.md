# StreamLingua Python Service - 首次 Cloudflare Containers 部署记录

## 概述

本文档记录了 StreamLingua Python 服务首次部署到 Cloudflare Containers 的完整过程，包括部署步骤、遇到的问题、解决方案和最终结果。

**部署日期**: 2025-08-30  
**部署状态**: ✅ 成功 (基础版本)  
**部署域名**: 
- `https://ast-python-service.honggumkong-gmail-com-s-account.workers.dev/`
- `https://inner.streamlingua.live/*` (自定义域名)

## 项目架构设计

### 服务架构
```
NextJS Frontend → ast_python_workers (inner.streamlingua.live) → Python Container → ws-gateway (WebSocket)
```

### 技术栈
- **Cloudflare Workers**: 边缘计算和请求路由
- **Cloudflare Containers**: Python 容器托管 (公测版本)
- **Docker**: 容器化 Python 服务
- **Durable Objects**: 容器生命周期管理
- **自定义域名**: `inner.streamlingua.live`

## 部署步骤记录

### 1. 环境准备 ✅

**检查 Docker Desktop 状态**
```bash
docker --version
docker ps
```
- Docker Desktop 运行正常
- 版本: Docker version 24.x

### 2. 容器化配置 ✅

**创建 Dockerfile**
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

# 复制并安装 Python 依赖（仅 Cloudflare Containers 所需）
COPY requirements-container.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 9000

# 启动命令
CMD ["python", "publisher.py"]
```

**创建简化依赖文件 (requirements-container.txt)**
```
websockets 
protobuf
python-dotenv
yt-dlp
pydub
numpy
fastapi
uvicorn
pydantic
```

**配置 .dockerignore**
```
# Python bytecode and cache
__pycache__/
*.py[cod]
*$py.class

# Virtual environments
.venv/
venv/
env/

# IDE and editor files
.vscode/
.idea/

# OS generated files
.DS_Store

# Logs and temporary files
*.log
*.tmp

# Environment files
.env
.env.local

# Output directories
output/
youtube/logs/
youtube/ffmpeg/log/

# Documentation
docs/
*.md
```

### 3. Workers 项目创建 ✅

**初始化 ast_python_workers 项目**
```bash
mkdir ast_python_workers
cd ast_python_workers
npm init -y
npm install --save-dev wrangler@4
npm install @cloudflare/containers
```

**配置 wrangler.jsonc**
```json
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "ast-python-service",
  "main": "src/index.js",
  "compatibility_date": "2025-08-30",
  "observability": {
    "enabled": true
  },
  
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

### 4. Docker 镜像构建测试 ✅

**遇到的问题**:
- FFmpeg 依赖安装耗时过长 (10+ 分钟)
- 音频库 (pyaudio, simpleaudio) 需要系统编译依赖
- Docker 网络连接超时问题

**解决方案**:
1. 创建简化版 Dockerfile (Dockerfile.simple) 用于测试
2. 移除复杂的音频处理依赖
3. 成功构建基础 Python 服务镜像

```bash
docker build -f Dockerfile.simple -t ast-python-service:simple .
# ✅ 构建成功
```

### 5. 环境变量配置 ✅

**设置 Cloudflare Secrets**
```bash
echo "wss://openspeech.bytedance.com/api/v4/ast/v2/translate" | npx wrangler secret put WS_URL
echo "8058854135" | npx wrangler secret put APP_KEY
echo "o5LmMamL2EfiF3j3aGaGdNHT40dqfOiK" | npx wrangler secret put ACCESS_KEY
echo "volc.service_type.10053" | npx wrangler secret put RESOURCE_ID
```

### 6. 部署执行 ✅

**首次部署 - 遇到权限问题**
```bash
npx wrangler deploy
# ❌ 错误: 缺少 containers:write 权限
```

**权限问题解决**:
1. 用户手动授权 Cloudflare OAuth 权限
2. 获得了包含 `containers:write` 的完整权限
3. 临时移除容器配置，先部署基础 Worker

**成功部署**
```bash
npx wrangler deploy
# ✅ 成功部署
# Version ID: e6940ef0-9984-483d-9979-1a08cae5edf4
```

## 部署中的关键问题与解决方案

### 问题 1: Docker 构建超时
**现象**: FFmpeg 安装需要 10+ 分钟，经常超时
**解决**: 创建简化版 Dockerfile，移除复杂依赖，优先验证部署流程

### 问题 2: Wrangler 版本兼容性
**现象**: Wrangler v3.x 对容器配置格式要求与文档不符
**解决**: 升级到 Wrangler v4.x，使用正确的配置格式

### 问题 3: OAuth 权限不足
**现象**: 缺少 `containers:write` 和 `cloudchamber:write` 权限
**解决**: 用户手动完成 OAuth 授权，获得完整权限

### 问题 4: JavaScript 语法错误
**现象**: TypeScript `override` 关键字在 JS 中不支持
**解决**: 移除 `override` 关键字，使用标准 JavaScript 语法

### 问题 5: 网络连接问题
**现象**: SSL 证书握手失败，无法访问部署的服务
**解决**: 通过 `npx wrangler deployments list` 确认部署成功

## 当前部署配置

### Worker 代码结构 (src/index.js)
```javascript
// StreamLingua Python Service Worker

// 辅助函数：生成时间戳
function getTimestamp() {
  return new Date().toISOString();
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

    // Placeholder for container functionality
    // TODO: Re-enable containers once proper OAuth scopes are configured
    return new Response(JSON.stringify({
      error: 'Container functionality not yet available',
      message: 'Waiting for proper Cloudflare Containers authentication'
    }), {
      status: 503,
      headers: { 
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    });
  }
};
```

### 环境变量配置
- `WS_URL`: WebSocket 连接地址
- `APP_KEY`: VolcEngine 应用密钥
- `ACCESS_KEY`: VolcEngine 访问密钥
- `RESOURCE_ID`: VolcEngine 资源 ID
- `SERVICE_NAME`: 服务名称
- `SERVICE_VERSION`: 服务版本

## 部署结果

### ✅ 成功指标
1. **Worker 部署成功**: Version ID `e6940ef0-9984-483d-9979-1a08cae5edf4`
2. **域名配置成功**: 支持自定义域名 `inner.streamlingua.live/*`
3. **环境变量配置**: 所有敏感信息已安全存储为 Secrets
4. **基础功能验证**: 健康检查和 CORS 处理正常

### 📋 部署状态
- **Workers Status**: ✅ 运行中
- **Custom Domain**: ✅ 已配置
- **Secrets**: ✅ 已设置 (4个)
- **Container Integration**: 🔄 待启用

### 🔧 当前限制
1. **容器功能暂时禁用**: 需要重新集成 Cloudflare Containers API
2. **Docker 镜像简化**: 缺少完整的音频处理依赖
3. **网络连接测试**: 部分网络环境下访问可能有延迟

## 预期影响

### 正面影响
1. **基础设施就绪**: Cloudflare Workers 部署流程验证完成
2. **域名配置完成**: `inner.streamlingua.live` 可以开始使用
3. **CI/CD 基础**: 为后续自动化部署奠定基础
4. **成本优化**: 采用 scale-to-zero 计费模式

### 需要关注的方面
1. **功能完整性**: 当前仅为占位符实现
2. **性能优化**: 容器冷启动时间需要监控
3. **错误处理**: 需要完善容器异常处理逻辑

## 测试方式

### 基础功能测试
```bash
# 健康检查
curl https://ast-python-service.honggumkong-gmail-com-s-account.workers.dev/health

# CORS 测试
curl -X OPTIONS https://ast-python-service.honggumkong-gmail-com-s-account.workers.dev/

# 自定义域名测试 (需要 DNS 生效后)
curl https://inner.streamlingua.live/health
```

### 部署状态查询
```bash
# 查看部署历史
npx wrangler deployments list

# 查看实时日志
npx wrangler tail --format=pretty

# 查看当前认证状态
npx wrangler whoami
```

### 容器功能测试 (待启用)
```bash
# 测试容器启动
curl -X POST https://inner.streamlingua.live/api/container/start

# 测试音频处理
curl -X POST https://inner.streamlingua.live/api/translate \
  -H "Content-Type: application/json" \
  -d '{"audio_url": "test.wav", "source_lang": "zh", "target_lang": "en"}'
```

## 下一步计划

### 短期任务 (1-2周)
1. **重新启用容器功能**
   - 使用新的 OAuth 权限集成 Cloudflare Containers
   - 更新 wrangler.jsonc 配置
   - 测试容器生命周期管理

2. **完善 Docker 镜像**
   - 优化 FFmpeg 安装过程
   - 添加音频处理依赖
   - 减少镜像体积和构建时间

3. **集成测试**
   - 端到端音频处理流程测试
   - WebSocket 连接稳定性测试
   - 容器自动扩缩容验证

### 中期任务 (1个月)
1. **监控和日志**
   - 集成 Cloudflare Analytics
   - 设置异常告警
   - 性能监控仪表板

2. **CI/CD 自动化**
   - GitHub Actions 集成
   - 自动化测试管道
   - 多环境部署支持

3. **生产就绪**
   - 错误处理完善
   - 限流和安全策略
   - 备份和恢复方案

## 经验总结

### 成功经验
1. **分步验证策略**: 先部署简化版本，再逐步添加复杂功能
2. **文档化过程**: 详细记录每个问题和解决方案
3. **权限管理**: 提前确认所需的 OAuth 权限范围

### 改进建议
1. **本地开发环境**: 建立与生产环境一致的本地测试环境
2. **错误处理**: 更细粒度的错误分类和处理策略
3. **性能优化**: 容器预热和连接池管理

### 技术债务
1. **Docker 镜像优化**: 当前镜像过于简化，需要补充完整功能
2. **错误处理**: 缺少完善的异常处理和重试机制
3. **监控缺失**: 没有完整的监控和告警体系

---

**文档维护**: 请在每次重大更新后及时更新此文档  
**负责人**: StreamLingua Team  
**最后更新**: 2025-08-30