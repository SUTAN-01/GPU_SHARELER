"""
纯算子执行服务。这个进程只做一件事：接收白名单算子调用，执行，返回结果。
绝不 import 任何本机训练代码或数据集相关模块。
"""

import hmac
import os,io
import secrets
import torch
import torch.distributed.rpc as rpc
import logging
import grpc
from concurrent import futures

from worker import op_service_pb2_grpc, op_service_pb2

logger = logging.getLogger(__name__)

# 白名单算子：只允许调用这些，防止调用方远程执行任意代码
ALLOWED_OPS = {
    "linear": torch.nn.functional.linear,
    "conv2d": torch.nn.functional.conv2d,
    "relu": torch.nn.functional.relu,
    "matmul": torch.matmul,
    "add": torch.add,
    "batch_norm": torch.nn.functional.batch_norm,
    "cross_entropy": torch.nn.functional.cross_entropy,
    # 需要哪个算子就在这里加，不要图省事直接开放 eval/exec
}

SHARED_SECRET = os.environ.get("GPU_SHARE_SECRET", "")
MAX_TENSOR_ELEMENTS = 50_000_000
def verify_token(token: str) -> bool:
    if not SHARED_SECRET:
        logger.warning("SHARED_SECRET NOT SET, RUNNING WITHOUT SECURITY")
        return True
    expected = hmac.new(SHARED_SECRET.encode(), b"gpu-share-node", "sha256").hexdigest()
    return hmac.compare_digest(token or "", expected)

def _tensor_to_bytes(t: torch.Tensor) -> bytes:
    buf = io.BytesIO()
    torch.save(t, buf)
    return buf.getvalue()

def _bytes_to_tensor(b: bytes) -> torch.Tensor:
    buf = io.BytesIO(b)
    return torch.load(buf, weights_only=True)


class OpExecutorServicer(op_service_pb2_grpc.OpExecutorServicer):
    def ExecuteOp(self, request, context):
        if not verify_token(request.token):
            context.set_code(grpc.StatusCode.PERMISSION_DENIED)
            context.set_details("invalid or missing auth token")
            return op_service_pb2.ExecuteOpResponse()

        if request.op_name not in ALLOWED_OPS:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"{request.op_name} is not allowed")
            return op_service_pb2.ExecuteOpResponse()

        try:
            tensors = [
                _bytes_to_tensor(t) for t in request.tensors
            ]
        except Exception as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"invalid input tensors: {e}")
            return op_service_pb2.ExecuteOpResponse()

        for t in tensors:
            if t.numel() > MAX_TENSOR_ELEMENTS:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"tensor size {t.numel()} is too large")
                return op_service_pb2.ExecuteOpResponse()

        logger.info("executing op=%s from peer=%s", request.op_name, context.peer())

        fn = ALLOWED_OPS[request.op_name]
        try:
            result = fn(*tensors)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"error executing op: {e}")
            return op_service_pb2.ExecuteOpResponse()

        return op_service_pb2.ExecuteOpResponse(result=_tensor_to_bytes(result))

def serve(port: int = 50051, max_workers: int = 4):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    op_service_pb2_grpc.add_OpExecutorServicer_to_server(OpExecutorServicer(), server)
    server.add_insecure_port(f"[::]:{port}")  # 阶段4会换成 add_secure_port + TLS
    server.start()
    logger.info("worker gRPC service listening on port %d", port)
    server.wait_for_termination()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve(port=int(os.environ.get("GPU_SHARE_PORT", "50051")))
