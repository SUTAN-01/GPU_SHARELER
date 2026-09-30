

import io
import torch
import grpc

from worker import op_service_pb2_grpc, op_service_pb2

AUTH_TOKEN = ""

def set_auth_token(token: str):
    global AUTH_TOKEN
    AUTH_TOKEN = token

def _tensor_to_bytes(t: torch.Tensor) -> bytes:
    buf = io.BytesIO()
    torch.save(t, buf)
    return buf.getvalue()

def _bytes_to_tensor(b: bytes) -> torch.Tensor:
    buf = io.BytesIO(b)
    return torch.load(buf, weights_only=True)

def call_remote_op(worker_address: str, op_name: str, tensors: list, timeout: float = 30.0):
    """
    worker_address 形如 "192.168.1.23:50051"，从 server.py 的节点列表里查到。
    这是每次调用独立建连，不维护常驻的RPC world，掉线只影响这一次调用。
    """
    with grpc.insecure_channel(worker_address) as channel:  # 阶段4换成 secure_channel
        stub = op_service_pb2_grpc.OpExecutorStub(channel)
        request = op_service_pb2.ExecuteOpRequest(
            op_name=op_name,
            tensors=[_tensor_to_bytes(t) for t in tensors],
            token=AUTH_TOKEN,
        )
        response = stub.ExecuteOp(request, timeout=timeout)
        return _bytes_to_tensor(response.result)


def remote_linear(worker_address: str, input_tensor, weight, bias=None):
    args = [input_tensor, weight] + ([bias] if bias is not None else [])
    return call_remote_op(worker_address, "linear", args)


def remote_conv2d(worker_address: str, input_tensor, weight, bias=None):
    args = [input_tensor, weight] + ([bias] if bias is not None else [])
    return call_remote_op(worker_address, "conv2d", args)


def remote_matmul(worker_address: str, a, b):
    return call_remote_op(worker_address, "matmul", [a, b])