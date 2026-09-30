import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()
def request(server, path, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_object = urllib.request.Request(
        f"{server.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request_object, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8"))
        except Exception:
            detail = {}
        raise RuntimeError(detail.get("error", f"HTTP {error.code}")) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"无法连接服务 {server}。请确认服务已启动、IP/端口正确，并允许防火墙端口 4317。原始错误: {error.reason}"
        ) from error
    except ValueError as error:
        raise RuntimeError(
            f"服务地址格式错误: {server}。请使用 http://10.168.41.72:4317，"
            "不要使用 [地址](地址) 这种 Markdown 格式。"
        ) from error

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


def platform_name():
    current = platform.system().lower()
    if current == "windows":
        return "win32"
    if current == "darwin":
        return "darwin"
    return "linux"


def main():
    parser = argparse.ArgumentParser(description="GPU Share Pool cross-platform node agent")
    parser.add_argument("--server", default="http://localhost:4317")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--name", default=f"{socket.gethostname()} · {platform.system()}")
    parser.add_argument("--cpu-slots", type=int, default=max(1, (os_cpu_count() or 1) // 2))
    parser.add_argument("--gpu-count", type=int)
    parser.add_argument("--worker-port", type=int, default=50051)
    parser.add_argument("--gpu-name", default="")
    parser.add_argument("--memory-gb", type=int, default=0)
    args = parser.parse_args()

    try:
        existing = request(args.server, "/api/state")
        user = next(
            (item for item in existing["users"] if item["name"].lower() == args.owner.lower()),
            None,
        )
        if user is None:
            user = request(args.server, "/api/users", "POST", {"name": args.owner})
        gpu = gpu_info(args)
        node = request(
            args.server,
            "/api/nodes",
            "POST",
            {
                "ownerId": user["id"],
                "name": args.name,
                "platform": platform_name(),
                "cpuModel": platform.processor() or "Generic CPU",
                "cpuSlots": args.cpu_slots,
                "gpuSlots": gpu["count"],
                "gpuName": gpu["name"],
                "memoryGb": gpu["memoryGb"],
                "labels": [platform_name(), "cuda" if gpu["count"] else "cpu"],
                "agentManaged": True,
                "rpcAddress": f"{get_local_ip()}:{args.worker_port}",
            },
        )
        print(f"Registered {node['name']} as {node['id']}")
        print(f"Platform: {platform.system()}; CPU slots: {args.cpu_slots}; GPU slots: {gpu['count']}")
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
                    "rpcAddress": f"{get_local_ip()}:{args.worker_port}",
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
    except KeyboardInterrupt:
        print("\n节点代理已停止")
    except RuntimeError as error:
        print(f"启动失败: {error}", file=sys.stderr)
        return 1
    return 0


def os_cpu_count():
    import os
    return os.cpu_count()


if __name__ == "__main__":
    raise SystemExit(main())
