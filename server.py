import copy
import calendar
import json
import os
import platform
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "state.json"
PUBLIC_DIR = ROOT / "public"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "4317"))
HEARTBEAT_TIMEOUT_SECONDS = 45
LOCK = threading.RLock()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value, default=0):
    return int(number(value, default))


def initial_state():
    created = now()
    return {
        "users": [
            # {"id": "user_alice", "name": "Alice", "role": "member", "createdAt": created},
            # {"id": "user_bob", "name": "Bob", "role": "member", "createdAt": created},
            # {"id": "user_carol", "name": "Carol", "role": "member", "createdAt": created},
        ],
        "nodes": [
            # {
            #     "id": "node_alice_4090",
            #     "ownerId": "user_alice",
            #     "name": "Alice 的工作站",
            #     "platform": "win32",
            #     "status": "online",
            #     "lastSeenAt": created,
            #     "cpuModel": "AMD Ryzen 9 7950X",
            #     "cpuSlots": 8,
            #     "gpuName": "NVIDIA RTX 4090",
            #     "gpuSlots": 1,
            #     "memoryGb": 24,
            #     "labels": ["windows", "cuda", "training"],
            #     "allocations": [],
            # },
            # {
            #     "id": "node_bob_a6000",
            #     "ownerId": "user_bob",
            #     "name": "Bob 的 Linux GPU",
            #     "platform": "linux",
            #     "status": "online",
            #     "lastSeenAt": created,
            #     "cpuModel": "AMD EPYC 7543",
            #     "cpuSlots": 16,
            #     "gpuName": "NVIDIA RTX A6000",
            #     "gpuSlots": 2,
            #     "memoryGb": 48,
            #     "labels": ["linux", "cuda", "secure"],
            #     "allocations": [],
            # },
            # {
            #     "id": "node_carol_cpu",
            #     "ownerId": "user_carol",
            #     "name": "Carol 的 CPU 节点",
            #     "platform": "linux",
            #     "status": "online",
            #     "lastSeenAt": created,
            #     "cpuModel": "Intel Xeon Gold 6338",
            #     "cpuSlots": 24,
            #     "gpuName": "",
            #     "gpuSlots": 0,
            #     "memoryGb": 64,
            #     "labels": ["linux", "cpu", "batch"],
            #     "allocations": [],
            # },
        ],
        "tasks": [],
        "events": [
            {
                "id": new_id("evt"),
                "type": "system",
                "message": "共享资源池已初始化",
                "at": created,
            }
        ],
    }


def save_state():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


def load_state():
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = initial_state()
    state.setdefault("users", [])
    state.setdefault("nodes", [])
    state.setdefault("tasks", [])
    state.setdefault("events", [])
    for node in state["nodes"]:
        node.setdefault("allocations", [])
        node.setdefault("labels", [])
    return state


STATE = load_state()


def user_name(user_id):
    for user in STATE["users"]:
        if user["id"] == user_id:
            return user["name"]
    return "未知用户"


def add_event(event_type, message, **metadata):
    event = {"id": new_id("evt"), "type": event_type, "message": message, "at": now()}
    event.update(metadata)
    STATE["events"].insert(0, event)
    del STATE["events"][80:]


def iso_age_seconds(value):
    try:
        parsed = time.strptime(value.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.000")
        return max(0, time.time() - calendar.timegm(parsed))
    except (AttributeError, ValueError, OverflowError):
        return 10**9


def normalize_node(node):
    if node.get("agentManaged") and iso_age_seconds(node.get("lastSeenAt", "")) > HEARTBEAT_TIMEOUT_SECONDS:
        node["status"] = "offline"
    owner = user_name(node.get("ownerId"))
    gpu_used = sum(1 for item in node.get("allocations", []) if item["resourceType"] == "gpu")
    cpu_used = sum(1 for item in node.get("allocations", []) if item["resourceType"] == "cpu")
    result = copy.deepcopy(node)
    result.update(
        {
            "ownerName": owner,
            "gpuUsed": gpu_used,
            "cpuUsed": cpu_used,
            "gpuAvailable": max(0, integer(node.get("gpuSlots")) - gpu_used),
            "cpuAvailable": max(0, integer(node.get("cpuSlots")) - cpu_used),
        }
    )
    return result


def public_state():
    nodes = [normalize_node(node) for node in STATE["nodes"]]
    tasks = []
    for task in STATE["tasks"]:
        public_task = copy.deepcopy(task)
        public_task["requesterName"] = user_name(task.get("requesterId"))
        for assignment in public_task.get("assignments", []):
            assignment["ownerName"] = user_name(assignment.get("ownerId"))
            assignment["nodeName"] = next(
                (node["name"] for node in STATE["nodes"] if node["id"] == assignment["nodeId"]),
                "未知节点",
            )
        tasks.append(public_task)
    return {
        "users": copy.deepcopy(STATE["users"]),
        "nodes": nodes,
        "tasks": tasks,
        "events": copy.deepcopy(STATE["events"]),
    }


def available(node, resource_type):
    capacity = integer(node.get("gpuSlots")) if resource_type == "gpu" else integer(node.get("cpuSlots"))
    used = sum(1 for item in node.get("allocations", []) if item["resourceType"] == resource_type)
    return max(0, capacity - used)


def allocate_task(task):
    resource_type = task["resourceType"]
    candidates = [
        node
        for node in STATE["nodes"]
        if node.get("status") == "online" and available(node, resource_type) > 0
    ]
    candidates.sort(
        key=lambda node: (
            1 if node["ownerId"] == task["requesterId"] else 0,
            -available(node, resource_type),
        )
    )
    existing = task.get("assignments", [])
    remaining = max(0, integer(task["workers"]) - len(existing))
    assignments = list(existing)
    added = 0
    for node in candidates:
        count = min(remaining, available(node, resource_type))
        for _ in range(count):
            assignment = {
                "id": new_id("assign"),
                "taskId": task["id"],
                "nodeId": node["id"],
                "ownerId": node["ownerId"],
                "resourceType": resource_type,
                "unitIndex": len(assignments) + 1,
                "status": "running",
                "startedAt": now(),
            }
            assignments.append(assignment)
            node.setdefault("allocations", []).append(assignment)
            added += 1
        remaining -= count
        if remaining <= 0:
            break
    task["assignments"] = assignments
    task["allocatedWorkers"] = len(assignments)
    task["status"] = (
        "running"
        if len(assignments) == integer(task["workers"])
        else "partial"
        if assignments
        else "queued"
    )
    if assignments and not task.get("startedAt"):
        task["startedAt"] = now()
    task["updatedAt"] = now()
    if added:
        add_event(
            "task",
            f'{user_name(task["requesterId"])} 的任务新增分配 {added} 个 worker（共 {len(assignments)}/{task["workers"]}）',
            taskId=task["id"],
        )


def release_task(task):
    for node in STATE["nodes"]:
        node["allocations"] = [
            allocation for allocation in node.get("allocations", []) if allocation["taskId"] != task["id"]
        ]


def recover_offline_assignments():
    offline_ids = {node["id"] for node in STATE["nodes"] if node.get("status") == "offline"}
    changed = False
    if not offline_ids:
        return False
    for task in STATE["tasks"]:
        if task.get("status") not in ("running", "partial"):
            continue
        lost = [item for item in task.get("assignments", []) if item["nodeId"] in offline_ids]
        if not lost:
            continue
        task["assignments"] = [item for item in task["assignments"] if item["nodeId"] not in offline_ids]
        for node in STATE["nodes"]:
            if node["id"] in offline_ids:
                node["allocations"] = [
                    item for item in node.get("allocations", []) if item["taskId"] != task["id"]
                ]
        task["allocatedWorkers"] = len(task["assignments"])
        task["status"] = "partial" if task["assignments"] else "queued"
        task["updatedAt"] = now()
        add_event("node", f'{len(lost)} 个 worker 因节点离线而释放，任务将重新调度', taskId=task["id"])
        changed = True
    return changed


def schedule_queued_tasks():
    for task in STATE["tasks"]:
        if task.get("status") in ("queued", "partial"):
            allocate_task(task)


def update_tasks():
    while True:
        changed = False
        with LOCK:
            for task in STATE["tasks"]:
                if task.get("status") not in ("running", "partial"):
                    continue
                elapsed = max(0, time.time() - calendar.timegm(time.strptime(
                    task["startedAt"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S.000"
                )))
                duration = max(1, integer(task.get("durationSeconds"), 45))
                task["progress"] = min(100, round(elapsed / duration * 100))
                task["updatedAt"] = now()
                changed = True
                if task["progress"] >= 100:
                    task["status"] = "completed"
                    task["completedAt"] = now()
                    for assignment in task.get("assignments", []):
                        assignment["status"] = "completed"
                    release_task(task)
                    add_event("task", f'{user_name(task["requesterId"])} 的任务已完成', taskId=task["id"])
            for node in STATE["nodes"]:
                if node.get("agentManaged") and iso_age_seconds(node.get("lastSeenAt", "")) > HEARTBEAT_TIMEOUT_SECONDS:
                    node["status"] = "offline"
            changed = recover_offline_assignments() or changed
            if changed:
                schedule_queued_tasks()
                save_state()
        time.sleep(1)


class Handler(BaseHTTPRequestHandler):
    server_version = "GPUSharePython/1.0"

    def log_message(self, format_string, *args):
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = integer(self.headers.get("Content-Length"), 0)
        if length > 1_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            with LOCK:
                return self.send_json(HTTPStatus.OK, public_state())
        return self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            with LOCK:
                self.handle_api(parsed.path)
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            print(f"API error: {error}")
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def handle_api(self, path):
        global STATE
        if path == "/api/users":
            body = self.read_json()
            name = str(body.get("name", "")).strip()
            if not name:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "用户名不能为空"})
            existing = next((user for user in STATE["users"] if user["name"].lower() == name.lower()), None)
            if existing:
                return self.send_json(HTTPStatus.OK, existing)
            user = {"id": new_id("user"), "name": name, "role": "member", "createdAt": now()}
            STATE["users"].append(user)
            add_event("user", f"{name} 加入了共享网络")
            save_state()
            return self.send_json(HTTPStatus.CREATED, user)

        if path == "/api/nodes":
            body = self.read_json()
            owner_id = str(body.get("ownerId", ""))
            if not any(user["id"] == owner_id for user in STATE["users"]):
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "节点拥有者不存在"})
            name = str(body.get("name") or f"{user_name(owner_id)} 的节点").strip()
            # agentManaged = bool(body.get("agentManaged", False))
            existing = next((item for item in STATE["nodes"] if item["ownerId"] == owner_id and item["name"] == name), None)
           
            node = {
                "id": new_id("node") if not existing else existing["id"],
                "ownerId": owner_id,
                "name": str(body.get("name") or f"{user_name(owner_id)} 的节点").strip(),
                "platform": str(body.get("platform") or platform.system().lower()),
                "status": "online",
                "lastSeenAt": now(),
                "cpuModel": str(body.get("cpuModel") or "Generic CPU"),
                "cpuSlots": clamp(integer(body.get("cpuSlots"), 1), 0, 256),
                "gpuName": str(body.get("gpuName") or ""),
                "gpuSlots": clamp(integer(body.get("gpuSlots"), 0), 0, 16),
                "memoryGb": clamp(integer(body.get("memoryGb"), 0), 0, 2048),
                "labels": [str(item) for item in body.get("labels", [])][:10],
                "agentManaged": bool(body.get("agentManaged", False)),
                "allocations": [],
            }
            if not existing:
                STATE["nodes"].append(node)
                add_event("node", f'{user_name(owner_id)} 创建了 {node["name"]}')
            else:
                add_event("node", f'{user_name(owner_id)} {node["name"]} 上线')
            save_state()
            return self.send_json(HTTPStatus.CREATED, normalize_node(node))

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

        if path == "/api/tasks":
            body = self.read_json()
            requester_id = str(body.get("requesterId", ""))
            if not any(user["id"] == requester_id for user in STATE["users"]):
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "任务用户不存在"})
            resource_type = "cpu" if body.get("resourceType") == "cpu" else "gpu"
            task = {
                "id": new_id("task"),
                "requesterId": requester_id,
                "name": str(body.get("name") or "未命名训练任务").strip(),
                "framework": str(body.get("framework") or "PyTorch"),
                "resourceType": resource_type,
                "workers": clamp(integer(body.get("workers"), 1), 1, 256),
                "durationSeconds": clamp(integer(body.get("durationSeconds"), 45), 10, 3600),
                "privacyMode": str(body.get("privacyMode") or "secure-aggregate"),
                "command": str(body.get("command") or "python train.py"),
                "createdAt": now(),
                "startedAt": None,
                "completedAt": None,
                "updatedAt": now(),
                "status": "queued",
                "progress": 0,
                "allocatedWorkers": 0,
                "assignments": [],
            }
            STATE["tasks"].insert(0, task)
            allocate_task(task)
            add_event("task", f'{user_name(requester_id)} 创建了任务：{task["name"]}', taskId=task["id"])
            save_state()
            return self.send_json(HTTPStatus.CREATED, task)

        if path.startswith("/api/tasks/") and path.endswith("/stop"):
            task_id = path.split("/")[3]
            task = next((item for item in STATE["tasks"] if item["id"] == task_id), None)
            if not task:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "任务不存在"})
            release_task(task)
            task["status"] = "stopped"
            task["completedAt"] = now()
            task["updatedAt"] = now()
            for assignment in task.get("assignments", []):
                assignment["status"] = "stopped"
            add_event("task", f'{user_name(task["requesterId"])} 停止了任务：{task["name"]}', taskId=task["id"])
            schedule_queued_tasks()
            save_state()
            return self.send_json(HTTPStatus.OK, task)

        if path == "/api/reset-demo":
            STATE = initial_state()
            save_state()
            return self.send_json(HTTPStatus.OK, public_state())

        return self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

    def serve_static(self, request_path):
        requested = "index.html" if request_path == "/" else request_path.lstrip("/")
        target = (PUBLIC_DIR / requested).resolve()
        if PUBLIC_DIR.resolve() not in target.parents and target != PUBLIC_DIR.resolve():
            return self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
        if not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_types.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    threading.Thread(target=update_tasks, daemon=True).start()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as error:
        if getattr(error, "errno", None) in (98, 10048):
            print(f"端口 {PORT} 已被占用，请使用 PORT=4318 python server.py")
            return 1
        raise
    print(f"GPU Share Pool Python running at http://localhost:{PORT}")
    print(f"Data file: {STATE_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
