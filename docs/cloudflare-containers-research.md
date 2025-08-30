# Cloudflare Containers 调研文档

> **调研日期**: 2025-08-29  
> **项目**: StreamLingua 同声传译 Web 应用  
> **目标**: 将 Python 翻译服务部署到 Cloudflare Containers

---

## 📊 Executive Summary

**结论**: Cloudflare Containers **完全适合**我们的 Python 同声传译项目部署，支持所有必要的网络通信模式。

**关键发现**:
- ✅ 支持 HTTP 出站连接（yt-dlp, FFmpeg）
- ✅ 支持 WebSocket 出站连接（连接 ws-gateway）
- ✅ 支持所有必要的 Python 库和系统工具
- ✅ 成本可控，按需计费
- ⚠️ 必须通过 Workers + Durable Objects 架构

---

## 🏗️ 架构分析

### 1. Cloudflare Containers 概述

**发布时间**: 2025年6月公测发布  
**核心特性**: 全球容器部署，与 Workers 深度集成，基于 Durable Objects

**官方描述**:
> "Simple, scalable, and global: Containers are coming to Cloudflare Workers in June 2025"

**参考链接**:
- [Cloudflare Containers 官方发布](https://blog.cloudflare.com/cloudflare-containers-coming-2025/)
- [Cloudflare Containers 文档](https://developers.cloudflare.com/containers/)

### 2. 网络架构设计

#### 入站流量架构（强制要求）
```
外部请求 → Worker → Durable Object → Container Instance
```

**设计原理**:
> "Incoming requests are initially handled by the Worker, then passed to a container-enabled Durable Object"

**限制**:
- ❌ 无法直接访问容器
- ❌ 不支持直接 TCP/UDP 连接
- ✅ 必须通过 Workers 层

**参考**: [Architecture Documentation](https://developers.cloudflare.com/containers/architecture/)

#### 出站流量架构（灵活选择）
```
Container → 直接连接外部服务
Container → 可选通过 Worker 代理
```

**核心发现**:
- ✅ 容器可以直接访问外部 HTTP/HTTPS 服务
- ✅ 容器可以发起 WebSocket 连接
- 🔧 可选择通过 Workers 代理出站流量

### 3. 为什么这样设计？

#### 入站控制的原因
1. **安全控制**: 统一的认证、授权、速率限制
2. **API Gateway**: 路由、缓存、负载均衡
3. **平台锁定**: 强制使用 Cloudflare 生态
4. **简化管理**: 无需管理传统的负载均衡器

#### 出站开放的原因
1. **实用性**: 容器需要访问外部服务（数据库、API）
2. **兼容性**: 现有应用无需大改就能迁移
3. **性能**: 直连外部服务，减少延迟
4. **灵活性**: 开发者可选择是否通过 Worker 代理

**战略分析**:
> "This architecture represents a thoughtful strategic choice by Cloudflare that builds a powerful but relatively closed ecosystem"

---

## 🌐 网络连接支持情况

### 1. HTTP/HTTPS 出站连接

**✅ 完全支持**

**验证内容**:
- Python `requests` 库
- `urllib` 标准库
- `yt-dlp` YouTube 视频获取
- `FFmpeg` HLS 流下载
- 第三方 API 调用

**配置要求**:
```javascript
export class PythonContainer extends Container {
  enableInternet = true;  // 关键配置
  defaultPort = 9000;
}
```

**参考**: [Container Networking](https://developers.cloudflare.com/containers/platform-details/)

### 2. WebSocket 出站连接

**✅ 完全支持**

**验证场景**:
- Python WebSocket 客户端连接外部服务
- 连接到 ws-gateway 的发布端点
- 连接到 VolcEngine 同传 API

**重要限制**:
- **连接超时**: 100秒无活动自动断开
- **解决方案**: 心跳机制（每90秒发送ping）

**代码示例**:
```python
# 现有的心跳机制已满足要求
async def _heartbeat_loop(self):
    while self.websocket:
        await asyncio.sleep(30)  # 每30秒心跳
        await self.websocket.ping()
```

**参考**: [WebSocket Support](https://developers.cloudflare.com/containers/examples/websocket/)

### 3. 网络访问控制

**enableInternet 参数**:
- `true`: 允许所有出站连接
- `false`: 仅允许通过 Worker 代理的连接

**引用**:
> "When setting up a container, you can toggle Internet access off and ensure that outgoing requests pass through Workers"

---

## 💰 成本分析

### 定价模型（2025年）

**计费方式**: 按 10ms 增量，仅活跃运行时计费（Scale-to-Zero）

**费用结构**:
- **内存**: $0.0000025/GiB-秒（包含25 GiB-小时）
- **CPU**: $0.000020/vCPU-秒（包含375 vCPU-分钟）
- **磁盘**: $0.00000007/GB-秒（包含200 GB-小时）
- **网络**: 北美/欧洲 $0.025/GB（包含1TB）

### 实例类型
- **dev**: 256MB RAM + 1/16 vCPU
- **basic**: 1GB RAM + 0.25 vCPU  
- **standard**: 4GB RAM + 0.5 vCPU

### 成本估算（basic 实例）
- **1小时运行**: 约 $0.27
- **1个常驻实例/月**: 约 $20
- **每30分钟会话**: 约 $0.135

**对比优势**: Scale-to-Zero 模式，无会话时不收费

**参考**: [Pricing Documentation](https://developers.cloudflare.com/containers/pricing/)

---

## 🚫 限制和约束

### 1. 架构限制
- ❌ 必须通过 Workers + Durable Objects
- ❌ 无法直接公网访问
- ❌ 不支持 TCP/UDP 直连

### 2. 资源限制
- **总内存**: 40GB 并发实例限制
- **总CPU**: 40 vCPU 并发实例限制
- **架构**: 仅支持 linux/amd64

### 3. 功能限制
- **自动扩缩**: 目前不支持，需手动管理
- **存储**: 全部为临时存储，容器重启后丢失
- **冷启动**: 2-3秒（取决于镜像大小）

### 4. 网络限制
- **WebSocket 超时**: 100秒无活动断开
- **连接数**: Workers 出站连接限制为6个

**参考**: [Beta Info & Roadmap](https://developers.cloudflare.com/containers/beta-info/)

---

## 🔧 技术可行性分析

### 对 StreamLingua 项目的影响

#### ✅ 支持的功能
1. **yt-dlp YouTube 获取**: HTTP 出站连接支持
2. **FFmpeg 音频下载**: HTTP/HLS 流下载支持
3. **VolcEngine 同传 API**: WebSocket 出站连接支持
4. **ws-gateway 连接**: WebSocket 发布端点连接
5. **Cookie 文件**: 可打包到镜像中
6. **Python 生态**: 完整的 Python 3.11 环境

#### ⚠️ 需要注意的点
1. **心跳保活**: WebSocket 连接需要定期 ping（已实现）
2. **容器管理**: 需要通过 ws-gateway 扩展管理
3. **环境变量**: 敏感信息通过 Cloudflare 环境变量

#### 🔄 无需修改的代码
- `publisher.py` 核心逻辑
- WebSocket 客户端代码
- yt-dlp 和 FFmpeg 调用
- Cookie 认证机制

---

## 🎯 最终建议

### 推荐架构

**扩展 ws-gateway 方案**:
```
NextJS → ws-gateway (扩展) → Python Container
           ↓
    WebSocket 路由 + 容器管理
```

**优势**:
- 复用现有基础设施
- 统一域名管理
- 简化架构
- 成本最优

### 部署策略

**常驻容器策略**:
- 1个 basic 实例常驻（避免冷启动）
- 按需启动额外实例
- 使用版本标签控制镜像构建

### 风险评估

**低风险**:
- ✅ 技术完全可行
- ✅ 成本可控
- ✅ 现有代码改动最小

**需要验证**:
- 🔍 YouTube 访问的稳定性（反爬机制）
- 🔍 长时间运行的稳定性
- 🔍 全球部署的延迟表现

---

## 📚 参考资料

### 官方文档
1. [Cloudflare Containers Overview](https://developers.cloudflare.com/containers/)
2. [Getting Started Guide](https://developers.cloudflare.com/containers/get-started/)
3. [Architecture Documentation](https://developers.cloudflare.com/containers/architecture/)
4. [WebSocket Example](https://developers.cloudflare.com/containers/examples/websocket/)
5. [Pricing Information](https://developers.cloudflare.com/containers/pricing/)
6. [FAQ](https://developers.cloudflare.com/containers/faq/)

### 技术博客
7. [Cloudflare Containers Launch](https://blog.cloudflare.com/cloudflare-containers-coming-2025/)
8. [Container Platform Preview](https://blog.cloudflare.com/container-platform-preview/)
9. [Containers Beta Announcement](https://blog.cloudflare.com/containers-are-available-in-public-beta-for-simple-global-and-programmable/)

### 分析文章
10. [Cloudflare Containers Technical Analysis](https://www.ubitools.com/cloudflare-containers/)
11. [InfoQ: Cloudflare Launches Containers](https://www.infoq.com/news/2025/06/cloudflare-containers-beta/)

### GitHub 资源
12. [Cloudflare Containers GitHub](https://github.com/cloudflare/containers)

---

## 📝 调研总结

**日期**: 2025-08-29  
**调研人**: Claude Code  
**结论**: **推荐部署** - Cloudflare Containers 完全满足 StreamLingua 项目需求

**关键成功因素**:
1. enableInternet = true 配置
2. 扩展 ws-gateway 作为容器管理层
3. 保持现有代码逻辑不变
4. 常驻容器避免冷启动延迟

**下一步**: 实施部署方案