# 实时资源监控完整指南

## 🎯 功能说明

添加后将显示：
- ✅ **GPU**: 槽位使用、显存使用量、GPU利用率百分比
- ✅ **CPU**: 槽位使用、CPU利用率百分比
- ✅ **内存**: 已用/总量、使用百分比
- ✅ **实时更新**: 每15秒自动刷新，通过SSE推送

---

## 📝 需要修改的 Python 文件

### 1. agent/node_agent.py

#### 修改 1: 添加 os 导入（第1行）
在文件开头添加：
```python
import os
```

#### 修改 2: 添加 CPU 和内存监控函数（在 gpu_info 函数之前添加）
```python
def get_cpu_memory_usage():
    """获取CPU和内存使用率"""
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        return {
            "cpuPercent": cpu_percent,
            "memoryTotalGb": round(memory.total / (1024**3), 1),
            "memoryUsedGb": round(memory.used / (1024**3), 1),
            "memoryPercent": memory.percent,
        }
    except ImportError:
        # 如果没有psutil，使用基本方法
        return {
            "cpuPercent": 0,
            "memoryTotalGb": 0,
            "memoryUsedGb": 0,
            "memoryPercent": 0,
        }
```

#### 修改 3: 修改 gpu_info 函数
**找到原来的 gpu_info 函数（第41-71行），完整替换为：**

```python
def gpu_info(args):
    """获取GPU信息和使用率"""
    if args.gpu_count is not None:
        return {
            "count": args.gpu_count,
            "name": args.gpu_name or "Configured GPU",
            "memoryGb": args.memory_gb or 0,
            "memoryUsedGb": 0,
            "utilizationPercent": 0,
        }
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"count": 0, "name": "", "memoryGb": 0, "memoryUsedGb": 0, "utilizationPercent": 0}
    try:
        # 查询 GPU 名称、总内存、已用内存、利用率
        output = subprocess.check_output(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return {"count": 0, "name": "", "memoryGb": 0, "memoryUsedGb": 0, "utilizationPercent": 0}
    if not output:
        return {"count": 0, "name": "", "memoryGb": 0, "memoryUsedGb": 0, "utilizationPercent": 0}
    rows = [line.split(",") for line in output.splitlines()]
    first_gpu = rows[0]
    return {
        "count": len(rows),
        "name": first_gpu[0].strip(),
        "memoryGb": int(float(first_gpu[1].strip() or 0)),
        "memoryUsedGb": int(float(first_gpu[2].strip() or 0)),
        "utilizationPercent": int(float(first_gpu[3].strip() or 0)),
    }
```

#### 修改 4: 在心跳循环中上报使用率（第122-135行）
**找到 while True 循环中的心跳代码：**

```python
        while True:
            current_gpu = gpu_info(args)
            request(
                args.server,
                f"/api/nodes/{node['id']}/heartbeat",
                "POST",
                {
                    "cpuSlots": args.cpu_slots,
                    "gpuSlots": current_gpu["count"],
                    "memoryGb": current_gpu["memoryGb"],
                },
            )
            print(f"heartbeat {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
            time.sleep(15)
```

**替换为：**

```python
        while True:
            current_gpu = gpu_info(args)
            cpu_mem = get_cpu_memory_usage()
            request(
                args.server,
                f"/api/nodes/{node['id']}/heartbeat",
                "POST",
                {
                    "cpuSlots": args.cpu_slots,
                    "gpuSlots": current_gpu["count"],
                    "memoryGb": current_gpu["memoryGb"],
                    # 新增：实时使用率
                    "cpuPercent": cpu_mem["cpuPercent"],
                    "memoryTotalGb": cpu_mem["memoryTotalGb"],
                    "memoryUsedGb": cpu_mem["memoryUsedGb"],
                    "memoryPercent": cpu_mem["memoryPercent"],
                    "gpuMemoryUsedGb": current_gpu.get("memoryUsedGb", 0),
                    "gpuUtilizationPercent": current_gpu.get("utilizationPercent", 0),
                },
            )
            print(f"heartbeat {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
            time.sleep(15)
```

---

### 2. server.py

#### 修改: 接收实时资源数据

**找到 `/api/nodes/.../heartbeat` 端点（第380-396行左右）：**

```python
        if path.startswith("/api/nodes/") and path.endswith("/heartbeat"):
            node_id = path.split("/")[3]
            node = next((item for item in STATE["nodes"] if item["id"] == node_id), None)
            if not node:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "节点不存在"})
            body = self.read_json()
            node["lastSeenAt"] = now()
            node["status"] = "online"
            node["agentManaged"] = True
            if "cpuSlots" in body:
                node["cpuSlots"] = clamp(integer(body["cpuSlots"]), 0, 256)
            if "gpuSlots" in body:
                node["gpuSlots"] = clamp(integer(body["gpuSlots"]), 0, 16)
            if "memoryGb" in body:
                node["memoryGb"] = clamp(integer(body["memoryGb"]), 0, 2048)
            save_state()
            return self.send_json(HTTPStatus.OK, normalize_node(node))
```

**在 `save_state()` 之前添加以下代码：**

```python
            if "memoryGb" in body:
                node["memoryGb"] = clamp(integer(body["memoryGb"]), 0, 2048)
            # 新增：接收实时使用率数据
            if "cpuPercent" in body:
                node["cpuPercent"] = clamp(number(body["cpuPercent"]), 0, 100)
            if "memoryTotalGb" in body:
                node["memoryTotalGb"] = number(body["memoryTotalGb"])
            if "memoryUsedGb" in body:
                node["memoryUsedGb"] = number(body["memoryUsedGb"])
            if "memoryPercent" in body:
                node["memoryPercent"] = clamp(number(body["memoryPercent"]), 0, 100)
            if "gpuMemoryUsedGb" in body:
                node["gpuMemoryUsedGb"] = number(body["gpuMemoryUsedGb"])
            if "gpuUtilizationPercent" in body:
                node["gpuUtilizationPercent"] = clamp(number(body["gpuUtilizationPercent"]), 0, 100)
            save_state()
```

---

## 🚀 安装依赖（可选但推荐）

如果想要准确的CPU和内存监控，需要安装 psutil：

```powershell
pip install psutil
```

如果不安装，资源使用率会显示为 0，但不会影响程序运行。

---

## ✅ 测试步骤

### 1. 修改完代码后，重启服务

```powershell
# 停止服务
.\stop.ps1

# 启动服务
.\start.ps1
```

### 2. 启动一个 agent 节点

```powershell
python .\agent\node_agent.py --server http://localhost:4317 --owner tan --name "测试节点"
```

### 3. 打开监控页面

- 本地访问：http://localhost:4317/monitor.html
- 远程访问：http://10.168.41.72:4317/monitor.html

### 4. 查看实时数据

你应该能看到：
- GPU槽位使用情况
- 显存使用：X.X / X.X GB
- GPU利用率：X%
- CPU槽位使用情况
- CPU利用率：X.X%
- 内存使用：X.X / X.X GB

每15秒自动更新一次！

---

## 🎨 显示效果

监控页面会显示每个节点的：

```
┌─────────────────────────────┐
│ 节点名称            [在线]  │
│ 👤 所有者                   │
│ 💻 平台                     │
│ 🎮 GPU型号                  │
│                             │
│ GPU槽位   ▓▓▓░░░  2 / 4    │
│ 显存      ▓▓▓▓░░  8.5 / 24 GB │
│ GPU利用率 ▓▓░░░░  45%       │
│ CPU槽位   ▓▓░░░░  4 / 16   │
│ CPU利用率 ▓▓▓░░░  32.5%    │
│ 内存      ▓▓▓▓░░  12.3 / 32.0 GB │
└─────────────────────────────┘
```

---

## 🐛 常见问题

### Q: 显示都是 0 怎么办？
A: 
1. 确认 server.py 已经添加了 SSE 支持（之前的修改）
2. 确认 agent 正在运行并发送心跳
3. 检查浏览器控制台是否有错误
4. 刷新页面，看右上角是否显示"🟢 已连接"

### Q: CPU 和内存使用率显示 0？
A: 安装 psutil：`pip install psutil`

### Q: GPU 利用率显示 0？
A: 
1. 确认机器有 NVIDIA GPU
2. 确认安装了 nvidia-smi
3. 运行一些 GPU 任务测试

### Q: 页面不自动更新？
A: 
1. 检查 server.py 是否添加了 SSE 支持
2. 查看浏览器控制台网络标签，是否有 /api/events 连接
3. 确认没有防火墙阻止

---

## 📊 数据更新流程

```
Agent (每15秒) → 心跳 → Server (保存+广播) → SSE → 监控页面 (实时更新)
    ↓                         ↓
 读取系统资源            推送给所有连接的客户端
 - CPU使用率
 - 内存使用
 - GPU状态
```

完成！🎉
