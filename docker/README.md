# Docker 容器部署指南

本文档说明如何使用 Docker 容器部署和测试分布式 GPU/CPU 共享训练系统。

## 架构说明

本项目采用 Worker-Coordinator 分离架构：

- **Worker 容器**：运行 gRPC 服务端（`worker/op_executor.py`），接收远程算子执行请求，只包含算子执行逻辑，**不包含任何 coordinator 代码和训练数据**
- **Coordinator 容器**：运行训练脚本/测试脚本（`test/test_rpc.py`），通过 gRPC 调用远程 Worker 执行算子，数据和完整代码都在这一侧

两个容器通过 Docker 网络通信，物理隔离文件系统，可直接验证"Worker 节点无法访问 Coordinator 代码和数据"这一安全特性。

## 前置要求

- Docker Desktop 或 Docker Engine（已安装并运行中）
- 项目根目录完整（包含 `worker/`、`coordinator/`、`test/`、`requirements.txt`）
- Python 代码已按前序步骤完成修改（见下方"代码准备"）

## 代码准备

### 必须完成的修改

**修改 `test/test_rpc.py`**（让测试脚本支持环境变量配置 Worker 地址）：

在文件顶部添加：
```python
import os
```

在文件中找到：
```python
result = remote_linear("127.0.0.1:50051", x, w, b)
```

改为：
```python
WORKER_ADDR = os.environ.get("WORKER_ADDR", "127.0.0.1:50051")
result = remote_linear(WORKER_ADDR, x, w, b)
```

这样容器内可以通过环境变量 `WORKER_ADDR=worker:50051` 连接到 Worker 容器（服务名），本机直接运行时默认仍用 `127.0.0.1:50051`。

### 验证现有文件

确认以下文件存在且无报错：
- `worker/op_executor.py`
- `worker/op_service_pb2.py`
- `worker/op_service_pb2_grpc.py`
- `worker/__init__.py`
- `coordinator/remote_ops.py`
- `coordinator/__init__.py`
- `test/test_rpc.py`
- `test/__init__.py`

## 快速启动（推荐）

### 1. 构建并启动两个容器

在项目根目录 `D:\ai\FL\my_gpu_share\` 执行：

```powershell
docker compose -f docker/docker-compose.yml up --build
```

**预期输出：**
```
[+] Building ...
[+] Running 2/2
 ✔ Container gpu_share_worker       Created
 ✔ Container gpu_share_coordinator  Created

gpu_share_worker       | INFO:worker.op_executor:worker gRPC service listening on port 50051
gpu_share_coordinator  | remote result: tensor([[ 0.4195, -1.2046,  0.9377], ...])
gpu_share_coordinator  | local  result: tensor([[ 0.4195, -1.2046,  0.9377], ...])
gpu_share_coordinator  | match: True
gpu_share_coordinator exited with code 0
```

- Worker 容器会持续运行（因为 gRPC 服务 `server.wait_for_termination()` 会阻塞）
- Coordinator 容器运行完测试脚本后自动退出（exit code 0 表示成功）

### 2. 验证隔离性（重要）

在另一个终端窗口执行：

```powershell
# 查看 Worker 容器的文件系统
docker exec gpu_share_worker ls -la /app

# 预期只看到：
# worker/
# requirements.txt
# 没有 coordinator/ 和 test/ 目录
```

```powershell
# 查看 Coordinator 容器的文件系统（如果容器已退出，需要先重启）
docker compose -f docker/docker-compose.yml run --rm coordinator ls -la /app

# 预期看到：
# worker/
# coordinator/
# test/
# requirements.txt
```

这证明了 **Worker 容器物理上无法访问 Coordinator 的代码和数据**。

### 3. 停止容器

```powershell
docker compose -f docker/docker-compose.yml down
```

## 带鉴权的启动（可选）

如果要测试 HMAC 共享密钥鉴权：

```powershell
# 设置环境变量
$env:GPU_SHARE_SECRET="your-shared-secret-here"

# 启动容器（Worker 和 Coordinator 会使用相同的密钥）
docker compose -f docker/docker-compose.yml up --build
```

**预期行为：**
- 鉴权通过：输出 `match: True`
- 鉴权失败（故意只给一边设密钥）：Worker 返回 `PERMISSION_DENIED`，Coordinator 报错退出

## 手动启动（逐步控制）

如果需要更细粒度的控制，可以手动构建和运行：

### 构建镜像

```powershell
# 构建 Worker 镜像
docker build -t gpu-share-worker:latest -f docker/worker.Dockerfile .

# 构建 Coordinator 镜像
docker build -t gpu-share-coordinator:latest -f docker/coordinator.Dockerfile .
```

### 创建网络

```powershell
docker network create gpu_share_net
```

### 启动 Worker 容器

```powershell
docker run -d `
  --name gpu_share_worker `
  --network gpu_share_net `
  -p 50051:50051 `
  -e GPU_SHARE_SECRET="" `
  gpu-share-worker:latest
```

### 启动 Coordinator 容器（运行测试）

```powershell
docker run --rm `
  --name gpu_share_coordinator `
  --network gpu_share_net `
  -e WORKER_ADDR=gpu_share_worker:50051 `
  -e GPU_SHARE_AUTH_TOKEN="" `
  gpu-share-coordinator:latest
```

### 清理

```powershell
docker stop gpu_share_worker
docker rm gpu_share_worker
docker network rm gpu_share_net
```

## 运行自定义训练脚本

如果要在 Coordinator 容器中运行自己的训练脚本而不是测试脚本：

```powershell
# 使用 docker-compose 覆盖默认 command
docker compose -f docker/docker-compose.yml run --rm coordinator python -m coordinator.dual_role_launcher

# 或手动 run 时指定入口
docker run --rm `
  --network gpu_share_net `
  -e WORKER_ADDR=gpu_share_worker:50051 `
  gpu-share-coordinator:latest `
  python your_training_script.py
```

## 常见问题

### Q1: Coordinator 报 `failed to connect to all addresses`

**原因**：Worker 容器未启动或网络不通。

**解决**：
```powershell
# 检查 Worker 是否运行
docker ps | grep gpu_share_worker

# 检查网络连通性（在 Coordinator 容器内）
docker compose -f docker/docker-compose.yml run --rm coordinator ping -c 3 worker
```

### Q2: Worker 报 `ModuleNotFoundError: No module named 'worker'`

**原因**：Dockerfile 的 `COPY worker/` 路径不对，或 build context 不是项目根目录。

**解决**：确保在 `D:\ai\FL\my_gpu_share\` 目录下执行构建命令，且 `-f docker/docker-compose.yml` 中的 `context: ..` 指向根目录。

### Q3: 容器内缺少依赖包

**原因**：`requirements.txt` 未包含所需依赖。

**解决**：更新 `requirements.txt` 后重新构建：
```powershell
docker compose -f docker/docker-compose.yml build --no-cache
```

### Q4: 想在宿主机访问 Worker 服务

已在 `docker-compose.yml` 中将 Worker 的 50051 端口映射到宿主机，可以直接测试：

```powershell
# 在宿主机本地运行（不在容器内）
python -m test.test_rpc
```

这会连接到 `127.0.0.1:50051`（宿主机映射的端口），请求被转发到 Worker 容器内。

## 文件清单

本 `docker/` 目录包含：

- **worker.Dockerfile**：Worker 镜像定义，仅包含 `worker/` 目录和依赖
- **coordinator.Dockerfile**：Coordinator 镜像定义，包含 `worker/`、`coordinator/`、`test/` 和依赖
- **docker-compose.yml**：双容器编排配置，定义网络、环境变量、依赖关系
- **README.md**：本文档

## 下一步

容器测试通过后，可以继续：

1. **动态节点发现**：让 `coordinator/remote_ops.py` 从 `server.py` 的 `/api/state` 拉取在线 Worker 列表，替换硬编码地址
2. **TLS 加密**：替换 `grpc.insecure_channel` 为 `grpc.secure_channel`，添加证书
3. **结果验证**：实现冗余计算/重采样机制，检测恶意 Worker 篡改结果
4. **真实训练循环**：构建完整的模型分层训练流程，参数和梯度聚合逻辑

---

**当前状态**：已完成 Worker/Coordinator 基础架构 + 容器化隔离验证，可以开始真实的分布式训练实验。
