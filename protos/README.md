### Protobuf/gRPC 协议与生成代码总览

本目录存放跨语言的 Protobuf/gRPC 接口定义（IDL）与构建脚本，是服务间通信的“契约源头”。生成的 Python 代码位于仓库根目录下的 `python_protogen/`。

### 目录结构

```
protos/
├── HOWTO.md                 # 安装、生成步骤示例
├── README.md                # 本文档（概览与用法）
├── build_python.sh          # 一键生成 Python 端 *_pb2.py / *_pb2_grpc.py
├── common/
│   ├── events.proto         # 通用事件消息
│   └── rpcmeta.proto        # RPC 请求/响应元数据（trace、auth 等）
└── products/
    └── understanding/
        ├── base/
        │   └── au_base.proto   # 领域基础模型/枚举
        └── ast/
            └── ast_service.proto  # AST 相关 gRPC 服务与消息
```

### 文件与用途

- **`common/events.proto`**: 定义通用“事件”结构（如事件 ID、类型、时间戳、payload 等），供不同服务产出/消费事件时复用。
- **`common/rpcmeta.proto`**: 定义 RPC 层面的公共元数据（如 `request_id`、`trace_id`、认证信息、多租户、分页等），在各请求/响应中复用。
- **`products/understanding/base/au_base.proto`**: “understanding” 产品域的基础数据模型/枚举（语言、片段、通用实体等），由上层服务引用。
- **`products/understanding/ast/ast_service.proto`**: AST 相关 gRPC 服务接口与请求/响应消息，通常会 `import` 上述 `base` 与 `common` 协议以复用通用结构。
- **`HOWTO.md`**: 详细的安装依赖、目录结构示例与生成步骤说明。
- **`build_python.sh`**: 使用 `grpc_tools.protoc` 生成 Python 代码到 `python_protogen/`，并自动修正导入前缀为 `python_protogen.*`、补齐 `__init__.py`。

### 生成 Python 代码

确保已安装依赖：

```bash
pip3 install grpcio grpcio-tools protobuf
```

执行构建脚本（使用绝对路径）：

```bash
chmod +x /Users/weihongwang/Documents/workspace/s2s/ast_python/protos/build_python.sh
/Users/weihongwang/Documents/workspace/s2s/ast_python/protos/build_python.sh
```

成功后会在项目根目录生成：

```
python_protogen/
├── common/
│   ├── events_pb2.py
│   ├── events_pb2_grpc.py
│   ├── rpcmeta_pb2.py
│   └── rpcmeta_pb2_grpc.py
└── products/
    └── understanding/
        ├── base/
        │   ├── au_base_pb2.py
        │   └── au_base_pb2_grpc.py
        └── ast/
            ├── ast_service_pb2.py
            └── ast_service_pb2_grpc.py
```

### 生成产物说明

- `*_pb2.py`: 由 `.proto` 生成的 Protobuf 消息类，提供序列化/反序列化与字段访问。
- `*_pb2_grpc.py`: 由 `.proto` 中的 `service` 生成的 gRPC 代码：
  - 客户端使用的 `...Stub`
  - 服务端实现的 `...Servicer` 抽象类
  - 将服务注册到 gRPC Server 的 `add_...Servicer_to_server` 函数

### 在 Python 中使用

导入模块：

```python
from python_protogen.common import events_pb2, rpcmeta_pb2
from python_protogen.products.understanding.base import au_base_pb2
from python_protogen.products.understanding.ast import ast_service_pb2, ast_service_pb2_grpc
```

客户端调用示例（实际类名/方法名以 `.proto` 为准）：

```python
import grpc
from python_protogen.products.understanding.ast import ast_service_pb2, ast_service_pb2_grpc

def call_service():
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = ast_service_pb2_grpc.AstServiceStub(channel)
        req = ast_service_pb2.YourRequest(
            # 按 .proto 字段填写
        )
        resp = stub.YourMethod(req)
        return resp
```

服务端实现示例：

```python
import grpc
from concurrent import futures
from python_protogen.products.understanding.ast import ast_service_pb2, ast_service_pb2_grpc

class AstService(ast_service_pb2_grpc.AstServiceServicer):
    def YourMethod(self, request, context):
        return ast_service_pb2.YourResponse(
            # 按 .proto 字段填写
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    ast_service_pb2_grpc.add_AstServiceServicer_to_server(AstService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    server.wait_for_termination()
```

### 维护与扩展建议

- 新增/修改 `.proto` 后，重新运行 `build_python.sh` 以更新 `python_protogen/`。
- 将新增的 `.proto` 文件路径加入 `build_python.sh` 的编译列表。
- 尽量复用 `common/` 与 `base/` 的通用结构，避免重复定义。
- 确保 Python 依赖（`grpcio`、`grpcio-tools`、`protobuf`）版本一致且可用。

### 常见问题

- 生成的导入前缀统一为 `python_protogen.*`，无需手动修改；脚本已自动重写并补齐 `__init__.py`。
- 若 `*_pb2_grpc.py` 内容较少，可能是对应 `.proto` 未定义 `service`（仅消息定义）。


