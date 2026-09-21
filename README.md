# 算力共享网络 MVP

这是一个面向 Windows 与 Linux 的多用户 CPU/GPU 共享池原型。当前运行时已经改为 Python 标准库版本，不需要安装 Flask/FastAPI 等第三方依赖。它把设备资源拆成可调度的 CPU/GPU 槽位：

- 一个用户可以登记多台设备；
- 多个用户的设备统一进入共享池；
- 多个任务可以同时使用所有用户共享的资源；
- 一个任务可以跨多个用户的节点分配多个 worker；
- 资源不足时任务排队，任务完成或停止后自动释放；
- Windows 与 Linux 使用同一份 Python 节点代理；
- `data/state.json` 保存本地演示数据，重启服务后仍然保留。

当前版本完成的是产品闭环和调度接口。真实生产环境还需要在节点代理执行容器、加入 GPU 隔离（MIG/vGPU/HAMi 等）、任务检查点/迁移、身份认证、计费和真正的 SecretFlow/Kuscia 适配。

## 启动服务

需要 Python 3.9 或更高版本，不需要安装第三方依赖。

Windows PowerShell:

```powershell
.\start.ps1
```

如果 `4317` 已经有服务运行，脚本会直接提示访问地址。使用其他端口：

```powershell
.\start.ps1 -Port 4318
```

停止服务：

```powershell
.\stop.ps1
```

Windows CMD:

```bat
start.cmd
```

使用其他端口：

```bat
start.cmd 4318
```

停止服务：

```bat
stop.cmd
```

Linux:

```bash
chmod +x start.sh
./start.sh
```

使用其他端口：

```bash
./start.sh 4318
```

停止服务：

```bash
./stop.sh
```

打开 http://localhost:4317。

## 模拟多用户与任务

控制台右上角可以切换或创建用户；“分享我的设备”可以快速登记不同用户的 CPU/GPU；“创建计算任务”可以设置 worker 数量。任务会自动从所有在线节点按槽位分配，因此能直观看到跨用户和并发效果。

## 接入真实 Windows/Linux 设备

在设备上安装 Python 3.9+，进入本项目目录，运行：

```bash
python agent/node_agent.py --server http://你的服务地址:4317 --owner Alice --name "Alice 家用工作站"
```

Windows PowerShell 也可以使用：

```powershell
python .\agent\node_agent.py --server http://10.168.41.72:4317 --owner tan --name "tans dev"
```

命令中的 URL 要写成纯文本，不能把 Markdown 链接标记一起复制。正确示例：

```powershell
python .\agent\node_agent.py --server http://10.168.41.72:4317 --owner tan --name "tans dev"
```

节点代理会持续发送心跳；按 `Ctrl+C` 可停止代理。停止后服务端会在约 45 秒内将节点标记为离线。

可选参数：

```text
--cpu-slots 8
--gpu-count 1
--gpu-name "NVIDIA RTX 4090"
--memory-gb 24
```

不传 `--gpu-count` 时，代理会尝试调用 `nvidia-smi` 自动发现 NVIDIA GPU。当前代理负责注册和心跳；真正执行任务需要在 `agent` 中继续接入 Docker/Podman 或 Kubernetes/Kuscia。

## 远程连接

服务端默认监听所有网卡。先在服务端本机确认服务正常：

```powershell
Invoke-WebRequest http://localhost:4317/api/state
```

再从共享设备上测试：

```powershell
Invoke-WebRequest http://10.168.41.72:4317/api/state
```

如果本机可访问、其他设备不行，请确认双方已连接同一 ZeroTier 网络，并在服务端 Windows 防火墙放行 TCP 4317：

```powershell
New-NetFirewallRule -DisplayName "GPU Share Pool 4317" -Direction Inbound -Protocol TCP -LocalPort 4317 -Action Allow
```

本机访问 `10.168.41.72:4317` 已验证返回 HTTP 200；远端仍需按上述方式测试网络和防火墙。
