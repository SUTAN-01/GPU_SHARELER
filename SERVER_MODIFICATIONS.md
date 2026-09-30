# Server.py 修改指南

## 需要修改的内容

### 1. 添加全局变量（第22行附近，在 `LOCK = threading.RLock()` 之后）

在 `LOCK = threading.RLock()` 这一行后面添加：

```python
# SSE 客户端连接管理
SSE_CLIENTS = []
SSE_CLIENTS_LOCK = threading.Lock()
```

---

### 2. 添加广播函数（第70行附近，在 `save_state()` 函数之后）

在 `save_state()` 函数的后面，添加这个新函数：

```python
def broadcast_state_update():
    """向所有SSE客户端广播状态更新"""
    with SSE_CLIENTS_LOCK:
        if not SSE_CLIENTS:
            return
        
        state = public_state()
        # 计算汇总统计
        total_gpu = sum(node.get("gpuSlots", 0) for node in state["nodes"])
        total_cpu = sum(node.get("cpuSlots", 0) for node in state["nodes"])
        used_gpu = sum(node.get("gpuUsed", 0) for node in state["nodes"])
        used_cpu = sum(node.get("cpuUsed", 0) for node in state["nodes"])
        online_nodes = sum(1 for node in state["nodes"] if node.get("status") == "online")
        running_tasks = sum(1 for task in state["tasks"] if task.get("status") in ("running", "partial"))
        
        message = json.dumps({
            "type": "state_update",
            "timestamp": now(),
            "summary": {
                "totalGpu": total_gpu,
                "totalCpu": total_cpu,
                "usedGpu": used_gpu,
                "usedCpu": used_cpu,
                "availableGpu": total_gpu - used_gpu,
                "availableCpu": total_cpu - used_cpu,
                "onlineNodes": online_nodes,
                "totalNodes": len(state["nodes"]),
                "runningTasks": running_tasks,
                "totalTasks": len(state["tasks"]),
            },
            "nodes": state["nodes"],
            "tasks": state["tasks"][:5],  # 只发送最近5个任务
        }, ensure_ascii=False)
        
        data = f"data: {message}\n\n".encode("utf-8")
        
        # 移除已断开的客户端
        disconnected = []
        for client in SSE_CLIENTS:
            try:
                client.wfile.write(data)
                client.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                disconnected.append(client)
        
        for client in disconnected:
            SSE_CLIENTS.remove(client)
```

---

### 3. 修改 `save_state()` 函数（第65-69行）

在 `save_state()` 函数的**最后一行**添加广播调用：

**原来的代码：**
```python
def save_state():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)
```

**修改为：**
```python
def save_state():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)
    broadcast_state_update()  # ← 添加这一行
```

---

### 4. 修改 `do_GET` 方法（第313-318行）

在 `Handler` 类的 `do_GET` 方法中，在 `if parsed.path == "/api/state":` 这段后面添加 SSE 端点：

**原来的代码：**
```python
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            with LOCK:
                return self.send_json(HTTPStatus.OK, public_state())
        return self.serve_static(parsed.path)
```

**修改为：**
```python
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            with LOCK:
                return self.send_json(HTTPStatus.OK, public_state())
        
        # 添加 SSE 端点
        if parsed.path == "/api/events":
            return self.handle_sse()
        
        return self.serve_static(parsed.path)
```

---

### 5. 添加 `handle_sse` 方法（在 `serve_static` 方法之前，约第452行）

在 `Handler` 类中，在 `serve_static` 方法的**前面**添加这个新方法：

```python
    def handle_sse(self):
        """处理Server-Sent Events连接"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        
        # 立即发送初始状态
        with LOCK:
            state = public_state()
            total_gpu = sum(node.get("gpuSlots", 0) for node in state["nodes"])
            total_cpu = sum(node.get("cpuSlots", 0) for node in state["nodes"])
            used_gpu = sum(node.get("gpuUsed", 0) for node in state["nodes"])
            used_cpu = sum(node.get("cpuUsed", 0) for node in state["nodes"])
            online_nodes = sum(1 for node in state["nodes"] if node.get("status") == "online")
            running_tasks = sum(1 for task in state["tasks"] if task.get("status") in ("running", "partial"))
            
            initial = json.dumps({
                "type": "connected",
                "timestamp": now(),
                "summary": {
                    "totalGpu": total_gpu,
                    "totalCpu": total_cpu,
                    "usedGpu": used_gpu,
                    "usedCpu": used_cpu,
                    "availableGpu": total_gpu - used_gpu,
                    "availableCpu": total_cpu - used_cpu,
                    "onlineNodes": online_nodes,
                    "totalNodes": len(state["nodes"]),
                    "runningTasks": running_tasks,
                    "totalTasks": len(state["tasks"]),
                },
                "nodes": state["nodes"],
                "tasks": state["tasks"][:5],
            }, ensure_ascii=False)
            
            try:
                self.wfile.write(f"data: {initial}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        
        # 将此连接添加到客户端列表
        with SSE_CLIENTS_LOCK:
            SSE_CLIENTS.append(self)
        
        # 保持连接活跃（每30秒发送心跳）
        try:
            while True:
                time.sleep(30)
                self.wfile.write(": heartbeat\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with SSE_CLIENTS_LOCK:
                if self in SSE_CLIENTS:
                    SSE_CLIENTS.remove(self)
```

---

## 修改摘要

总共需要在 server.py 中做 **5处修改**：

1. ✅ 添加 2 个全局变量
2. ✅ 添加 `broadcast_state_update()` 函数
3. ✅ 在 `save_state()` 末尾添加 1 行代码
4. ✅ 在 `do_GET()` 中添加 3 行代码
5. ✅ 添加完整的 `handle_sse()` 方法

## 测试步骤

修改完成后：

1. 停止服务（如果正在运行）：
   ```powershell
   .\stop.ps1
   ```

2. 启动服务：
   ```powershell
   .\start.ps1
   ```

3. 打开浏览器访问监控页面：
   - 本地：http://localhost:4317/monitor.html
   - 远程：http://10.168.41.72:4317/monitor.html

4. 在主界面创建节点和任务，监控页面会实时更新

## 注意事项

- 所有修改都使用 Python 标准库，不需要安装任何第三方依赖
- SSE 连接会自动重连，网络断开后会自动恢复
- 支持多个浏览器同时监控
- 每次状态改变时会自动推送更新
