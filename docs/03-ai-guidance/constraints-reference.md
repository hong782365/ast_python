# 约束条件速查

## 概述

本文档为AI工具提供快速查阅的约束条件参考，包含所有必须遵守的硬性约束、技术限制和业务规则。这些约束条件是重构成功的关键保障，任何违反都可能导致系统功能异常或性能下降。

## 🚨 硬性约束 (CRITICAL CONSTRAINTS)

### 功能等价性约束
```python
FUNCTIONAL_EQUIVALENCE = {
    "API_COMPATIBILITY": "所有HTTP端点响应格式与现有系统100%一致",
    "BUSINESS_LOGIC": "端到端音频翻译流程行为完全相同",
    "ERROR_HANDLING": "错误场景和异常处理逻辑等价",
    "SESSION_MANAGEMENT": "会话状态变更和幂等性行为一致",
    "DATA_FORMAT": "输入输出数据格式保持不变"
}
```

**验证标准**: 新旧系统并行运行测试，响应差异为0

### 协议兼容性约束
```python
PROTOCOL_COMPATIBILITY = {
    "VOLCENGINE_API": "与VolcEngine WebSocket API保持100%协议兼容",
    "PROTOBUF_FORMAT": "protobuf消息序列化格式不得改变",
    "EVENT_TYPES": "所有VolcEngine事件类型处理逻辑保持一致",
    "AUTHENTICATION": "WebSocket认证头部格式严格保持",
    "MESSAGE_FLOW": "消息收发时序和状态机保持不变"
}
```

**验证标准**: 与VolcEngine API通信无任何协议错误

### 性能约束
```python
PERFORMANCE_CONSTRAINTS = {
    "LATENCY_OVERHEAD": "端到端延迟增加不超过10%",
    "MEMORY_USAGE": "Cloudflare环境总内存使用<90MB",
    "THROUGHPUT": "并发处理能力不低于现有系统",
    "STARTUP_TIME": "系统启动时间不超过现有系统+20%",
    "RESOURCE_EFFICIENCY": "CPU和网络使用效率不显著下降"
}
```

**验证标准**: 性能基准测试全部达标

## 🔧 技术约束 (TECHNICAL CONSTRAINTS)

### 音频处理参数约束
```python
AUDIO_PARAMETERS = {
    # 以下参数值严禁修改，任何改动都会导致协议不兼容
    "CHUNK_SIZE": 640,              # PCM块大小，必须精确640字节
    "SAMPLE_RATE": 16000,           # 采样率，必须16kHz
    "BIT_DEPTH": 16,                # 位深度，必须16位
    "CHANNELS": 1,                  # 声道数，必须单声道
    "SEND_INTERVAL": 0.02,          # 发送间隔，必须20毫秒
    "AUDIO_FORMAT": "pcm_s16le",    # 音频格式，必须小端16位PCM
    "TARGET_SAMPLE_RATE": 24000,    # TTS输出采样率，必须24kHz
    "TARGET_FORMAT": "ogg_opus"     # TTS输出格式，必须Opus编码
}
```

**约束说明**: 这些参数与VolcEngine API协议严格绑定，任何修改都会导致协议错误

### WebSocket通信约束
```python
WEBSOCKET_CONSTRAINTS = {
    "CONNECTION_PARAMS": {
        "max_size": 1000000000,     # 最大消息大小1GB，不得修改
        "ping_interval": None,      # 必须禁用自动ping
        "ping_timeout": None,       # 必须禁用ping超时
        "compression": None         # 必须禁用压缩
    },
    
    "AUTHENTICATION_HEADERS": {
        "X-Api-App-Key": "必须字段",
        "X-Api-Access-Key": "必须字段", 
        "X-Api-Resource-Id": "必须字段",
        "X-Api-Connect-Id": "必须字段，UUID格式"
    },
    
    "MESSAGE_FORMAT": {
        "serialization": "protobuf",     # 必须使用protobuf序列化
        "event_mapping": "保持现有Type枚举映射",
        "binary_handling": "音频数据必须二进制传输"
    }
}
```

### 环境约束
```python
ENVIRONMENT_CONSTRAINTS = {
    "LOCAL_DEVELOPMENT": {
        "file_permissions": "完整读写权限",
        "log_output": "文件+控制台双输出",
        "resource_limits": "无严格限制",
        "monitoring": "完整监控能力"
    },
    
    "CLOUDFLARE_CONTAINERS": {
        "file_permissions": "只读文件系统，禁止文件写入",
        "log_output": "仅stderr输出，必须CLOUDFLARE_前缀",
        "memory_limit": "严格90MB限制",
        "process_limit": "进程数量受限",
        "network_proxy": "可能需要HTTP_PROXY支持",
        "monitoring": "无文件监控能力"
    }
}
```

## 📦 代码资产保护约束

### ast_demo.py框架保护
```python
AST_DEMO_PRESERVATION = {
    "MUST_PRESERVE_FUNCTIONS": {
        "send_request": "ast_demo.py:88-112，必须逐行复制",
        "receive_message": "ast_demo.py:115-129，必须逐行复制", 
        "build_http_headers": "ast_demo.py:132-140，必须逐行复制"
    },
    
    "MUST_PRESERVE_DATA_STRUCTURES": {
        "Audio": "ast_demo.py:47-52，完整保留",
        "TranslateRequestData": "ast_demo.py:55-63，完整保留",
        "TranslateResponseData": "ast_demo.py:66-73，完整保留"
    },
    
    "MUST_PRESERVE_IMPORTS": {
        "protobuf_imports": "所有protobuf相关导入保持不变",
        "websockets_imports": "websockets库使用方式保持一致",
        "event_types": "common.events_pb2.Type枚举使用保持一致"
    }
}
```

**保护策略**: 这些代码经过验证稳定可靠，任何修改都可能引入bug

### 业务逻辑保护  
```python
BUSINESS_LOGIC_PRESERVATION = {
    "SESSION_IDEMPOTENCY": {
        "description": "会话启动幂等性逻辑",
        "source": "publisher.py:80-120",
        "requirement": "完全保持现有幂等判断逻辑"
    },
    
    "SILENCE_BRIDGING": {
        "description": "静音桥接协调机制",
        "source": "ast_youtube_demo.py:680-690",
        "requirement": "保持环境适配超时逻辑(本地8s，Cloudflare18s)"
    },
    
    "EVENT_MAPPING": {
        "description": "VolcEngine事件到JSON的转换",
        "source": "ast_youtube_demo.py:850-950",
        "requirement": "事件类型映射关系保持不变"
    },
    
    "PARALLEL_INITIALIZATION": {
        "description": "FFmpeg、WebSocket、yt-dlp并行初始化",
        "source": "ast_youtube_demo.py:480-600",
        "requirement": "并行策略和错误处理逻辑保持一致"
    }
}
```

## 🏗️ 架构约束 (ARCHITECTURAL CONSTRAINTS)

### 模块设计约束
```python
MODULE_DESIGN_CONSTRAINTS = {
    "FILE_SIZE_LIMIT": "每个模块文件不超过500行代码",
    "CIRCULAR_DEPENDENCIES": "禁止模块间循环依赖",
    "INTERFACE_STABILITY": "模块公共接口必须向后兼容",
    "SEPARATION_OF_CONCERNS": "每个模块单一职责，职责边界清晰",
    "DEPENDENCY_DIRECTION": "依赖关系必须单向，从上层到下层"
}
```

### 模块依赖层次约束
```python
DEPENDENCY_HIERARCHY = {
    "LAYER_1_API": ["api/endpoints.py", "api/models.py"],
    "LAYER_2_CORE": ["core/session_manager.py", "core/audio_pipeline.py", "core/publisher_client.py", "core/event_processor.py"],
    "LAYER_3_INFRASTRUCTURE": ["infrastructure/ffmpeg_manager.py", "infrastructure/ytdlp_manager.py", "infrastructure/volcengine_client.py", "infrastructure/websocket_client.py"],
    "LAYER_4_PROTOCOLS": ["protocols/volcengine_protocol.py", "protocols/message_converter.py"],
    "LAYER_5_ADAPTERS": ["adapters/environment_detector.py", "adapters/logging_adapter.py", "adapters/resource_manager.py"],
    "LAYER_6_CONFIG": ["config/config_loader.py", "config/settings.py", "config/validation.py"],
    "LAYER_7_UTILS": ["utils/async_utils.py", "utils/file_utils.py", "utils/timing_utils.py"]
}
```

**依赖规则**: 上层可以依赖下层，下层不得依赖上层，同层间依赖需要特殊审批

### 接口设计约束
```python
INTERFACE_CONSTRAINTS = {
    "ASYNC_COMPONENTS": {
        "base_class": "必须继承AsyncComponent基类",
        "required_methods": ["initialize", "start", "stop", "cleanup"],
        "status_property": "必须实现status属性",
        "exception_handling": "必须妥善处理和传播异常"
    },
    
    "ERROR_HANDLING": {
        "exception_types": "使用标准异常类型",
        "error_context": "异常必须包含足够的上下文信息",
        "logging": "所有异常必须记录日志",
        "recovery": "可恢复错误必须实现重试机制"
    },
    
    "CONFIGURATION": {
        "type_safety": "所有配置必须有类型注解",
        "validation": "必须实现配置参数验证",
        "environment_specific": "支持环境特定配置覆盖",
        "hot_reload": "支持运行时配置更新(非关键参数)"
    }
}
```

## 📊 数据格式约束

### API数据格式约束
```python
API_DATA_FORMAT_CONSTRAINTS = {
    "REQUEST_FORMAT": {
        "start_session": {
            "sessionId": "string, required, UUID格式推荐",
            "youtube_url": "string, required, 有效YouTube URL",
            "publishUrl": "string, required, 有效WebSocket URL"
        },
        "stop_session": {
            "sessionId": "string, required, 与启动时一致"
        }
    },
    
    "RESPONSE_FORMAT": {
        "success_200": {
            "sessionId": "string, 会话标识",
            "status": "string, 会话状态",
            "message": "string, optional, 状态描述"
        },
        "already_running_202": {
            "sessionId": "string, 已存在的会话标识", 
            "status": "string, 当前状态",
            "message": "string, 幂等性说明"
        },
        "error_4xx_5xx": {
            "error": "string, 错误类型",
            "message": "string, 错误描述",
            "details": "object, optional, 错误详情"
        }
    }
}
```

### WebSocket数据格式约束
```python
WEBSOCKET_DATA_FORMAT_CONSTRAINTS = {
    "VOLCENGINE_INPUT": {
        "StartSession": "TranslateRequest protobuf格式",
        "TaskRequest": "TranslateRequest + 640字节PCM数据",
        "FinishSession": "TranslateRequest无音频数据"
    },
    
    "VOLCENGINE_OUTPUT": {
        "SessionStarted": "Type.SessionStarted(150)",
        "SessionFinished": "Type.SessionFinished(152)", 
        "SessionFailed": "Type.SessionFailed(153)",
        "SourceSubtitleEnd": "Type.SourceSubtitleEnd(652) + 文本",
        "TranslationSubtitleEnd": "Type.TranslationSubtitleEnd(655) + 文本",
        "TTSSentenceEnd": "Type.TTSSentenceEnd(351) + 音频数据"
    },
    
    "PUBLISH_URL_OUTPUT": {
        "subtitle_json": {
            "type": "subtitle",
            "lane": "source|translation", 
            "phase": "end",
            "text": "string, 字幕文本",
            "start_time": "number, optional",
            "end_time": "number, optional",
            "final": "boolean, true"
        },
        "audio_binary": "直接二进制数据，Opus格式"
    }
}
```

## ⏱️ 时序约束 (TIMING CONSTRAINTS)

### 关键时序参数
```python
TIMING_CONSTRAINTS = {
    "AUDIO_PROCESSING": {
        "chunk_interval": 0.02,         # 20ms严格间隔，不得修改
        "silence_timeout_local": 8,     # 本地环境静音超时8秒
        "silence_timeout_cloudflare": 18, # Cloudflare环境静音超时18秒
        "first_chunk_timeout": 30       # 首个音频块超时30秒
    },
    
    "NETWORK_TIMEOUTS": {
        "websocket_connect": 30,        # WebSocket连接超时30秒
        "websocket_send": 5,            # 单次发送超时5秒
        "websocket_recv": 5,            # 单次接收超时5秒
        "volcengine_session_start": 10  # VolcEngine会话启动超时10秒
    },
    
    "PROCESS_TIMEOUTS": {
        "ffmpeg_start": 30,             # FFmpeg启动超时30秒
        "ytdlp_extract": 60,            # yt-dlp提取超时60秒
        "session_cleanup": 30           # 会话清理超时30秒
    }
}
```

### 时序同步约束
```python
SYNCHRONIZATION_CONSTRAINTS = {
    "SILENCE_BRIDGE_COORDINATION": {
        "description": "静音桥接与真实音频的切换时机",
        "requirement": "首个PCM块到达时立即停止静音发送",
        "implementation": "使用asyncio.Event进行协调"
    },
    
    "PARALLEL_INITIALIZATION": {
        "description": "FFmpeg、WebSocket、yt-dlp组件并行启动",
        "requirement": "任一组件失败则全部停止",
        "implementation": "使用asyncio.gather with return_exceptions=True"
    },
    
    "SESSION_STATE_TRANSITIONS": {
        "description": "会话状态变更的原子性",
        "requirement": "状态变更必须原子性，避免竞态条件",
        "implementation": "使用适当的同步原语"
    }
}
```

## 🔒 安全约束 (SECURITY CONSTRAINTS)

### 认证和授权约束
```python
SECURITY_CONSTRAINTS = {
    "API_AUTHENTICATION": {
        "volcengine_credentials": {
            "app_key": "必须从环境变量获取，禁止硬编码",
            "access_key": "必须从环境变量获取，禁止硬编码",
            "resource_id": "必须从环境变量获取，禁止硬编码"
        },
        "credential_validation": "启动时必须验证凭据有效性",
        "credential_rotation": "支持运行时凭据更新"
    },
    
    "DATA_PROTECTION": {
        "audio_data": "音频数据仅在内存中处理，禁止持久化",
        "logs": "日志中禁止记录敏感信息(API密钥、音频内容)",
        "temp_files": "如需临时文件，使用后必须安全删除",
        "network_transmission": "所有网络传输使用TLS加密"
    },
    
    "INPUT_VALIDATION": {
        "youtube_url": "严格验证YouTube URL格式和域名",
        "publish_url": "验证WebSocket URL格式和协议",
        "session_id": "验证会话ID格式，防止注入攻击",
        "audio_data": "验证音频数据大小和格式"
    }
}
```

### 资源保护约束
```python
RESOURCE_PROTECTION = {
    "MEMORY_LIMITS": {
        "single_session": "单会话内存使用<10MB",
        "total_limit_cloudflare": "Cloudflare环境总内存<90MB",
        "memory_leak_prevention": "实现内存使用监控和清理"
    },
    
    "PROCESS_LIMITS": {
        "max_concurrent_sessions": "最大并发会话数可配置",
        "ffmpeg_process_limit": "每会话最多1个FFmpeg进程",
        "subprocess_timeout": "所有子进程必须有超时机制"
    },
    
    "NETWORK_LIMITS": {
        "connection_pool": "WebSocket连接池大小限制",
        "request_rate_limiting": "实现请求频率限制",
        "bandwidth_monitoring": "监控网络带宽使用"
    }
}
```

## 🧪 测试约束 (TESTING CONSTRAINTS)

### 测试覆盖率约束
```python
TESTING_CONSTRAINTS = {
    "COVERAGE_REQUIREMENTS": {
        "unit_tests": "单元测试覆盖率>80%",
        "integration_tests": "主要业务流程100%覆盖",
        "e2e_tests": "端到端场景全覆盖",
        "error_path_tests": "异常路径测试覆盖"
    },
    
    "TEST_TYPES": {
        "unit_tests": "每个函数和类的独立测试",
        "integration_tests": "模块间交互测试", 
        "performance_tests": "性能基准和负载测试",
        "compatibility_tests": "环境兼容性测试",
        "protocol_tests": "协议兼容性测试"
    },
    
    "TEST_DATA": {
        "audio_samples": "使用标准测试音频文件",
        "mock_services": "外部服务Mock实现",
        "test_configurations": "多环境配置测试",
        "edge_cases": "边界条件和异常情况测试"
    }
}
```

### 验证标准约束
```python
VALIDATION_STANDARDS = {
    "FUNCTIONAL_VALIDATION": {
        "api_compatibility": "API响应格式100%匹配",
        "business_logic": "业务流程行为完全一致",
        "error_handling": "错误处理逻辑等价",
        "data_integrity": "数据传输完整性验证"
    },
    
    "PERFORMANCE_VALIDATION": {
        "latency_threshold": "延迟增加<10%",
        "memory_threshold": "内存使用符合限制",
        "throughput_threshold": "吞吐量不降低",
        "stability_test": "24小时稳定性测试"
    },
    
    "QUALITY_VALIDATION": {
        "code_style": "通过flake8, black, isort检查",
        "type_checking": "通过mypy类型检查",
        "security_scan": "通过bandit安全扫描",
        "dependency_check": "通过safety依赖检查"
    }
}
```

## 🚫 禁止事项清单

### 绝对禁止的操作
```python
ABSOLUTELY_FORBIDDEN = [
    "修改ast_demo.py中的协议处理函数",
    "改变音频处理的关键参数(640字节、16kHz等)",
    "破坏会话启动的幂等性逻辑",
    "忽略环境适配的差异处理",
    "在代码中硬编码敏感信息",
    "跳过必要的错误处理",
    "引入循环依赖",
    "修改protobuf消息格式",
    "改变WebSocket认证机制",
    "忽略性能约束要求"
]
```

### 需要特别注意的事项
```python
SPECIAL_ATTENTION_REQUIRED = [
    "静音桥接的时机控制必须精确",
    "并行初始化的错误处理必须完整",
    "WebSocket连接的重连机制必须稳定",
    "Cloudflare环境的资源限制必须严格遵守",
    "配置参数的类型安全必须保证",
    "日志输出的环境适配必须正确",
    "会话状态的并发安全必须考虑",
    "外部服务的超时处理必须完善"
]
```

## 📋 快速检查清单

### 开始重构前检查
- [ ] 已仔细阅读并理解所有约束条件
- [ ] 已确认现有ast_demo.py框架的保护要求  
- [ ] 已理解目标模块结构和依赖关系
- [ ] 已掌握关键配置参数和环境适配需求
- [ ] 已了解测试覆盖和验证标准要求

### 实现过程中检查
- [ ] 每个模块文件大小是否<500行
- [ ] 是否严格复用了ast_demo.py的核心函数
- [ ] 音频处理参数是否保持不变
- [ ] 环境适配逻辑是否正确实现
- [ ] 配置外化是否完整
- [ ] 错误处理是否完善
- [ ] 是否存在循环依赖

### 完成后验证检查  
- [ ] API兼容性测试是否100%通过
- [ ] 端到端业务流程是否正常
- [ ] 性能指标是否达标
- [ ] 测试覆盖率是否满足要求
- [ ] 代码质量检查是否通过
- [ ] 两种环境是否都能正常部署

---

**使用说明**: 本文档应在整个重构过程中持续参考，任何不确定的地方都应该查阅相关约束条件。所有约束条件都是经过分析得出的必要限制，不应随意忽略或修改。

**文档版本**: v1.0.0  
**关联文档**: [AI重写主要提示词](master-prompt.md) | [实现分析](../01-current-system/implementation-analysis.md)  
**最后更新**: 2025-01-XX