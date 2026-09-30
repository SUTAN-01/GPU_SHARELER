import os
import threading
import logging

from worker.op_executor import serve as worker_serve
from coordinator.remote_ops import set_auth_token

logger = logging.getLogger(__name__)


def run_dual_role(worker_port: int, my_training_fn):
    """
    在本机同时：
    1. 起一个 worker gRPC 服务线程，响应别人的算子调用
    2. 在主线程跑自己的训练函数（内部会用 coordinator.remote_ops 去调用别的节点）
    """
    auth_token = os.environ.get("GPU_SHARE_AUTH_TOKEN", "")
    set_auth_token(auth_token)

    worker_thread = threading.Thread(
        target=worker_serve, kwargs={"port": worker_port}, daemon=True
    )
    worker_thread.start()
    logger.info("worker service started on port %d, running training now", worker_port)

    my_training_fn()  # 这里调用你自己的训练脚本入口


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    def demo_training():
        import time
        logger.info("training running... (replace with real training loop)")
        time.sleep(5)

    run_dual_role(worker_port=int(os.environ.get("GPU_SHARE_PORT", "50051")), my_training_fn=demo_training)
