import torch
from coordinator.remote_ops import remote_linear, set_auth_token

set_auth_token("")  # 对应worker端没设GPU_SHARE_SECRET时的"无认证"模式

x = torch.randn(2, 4)
w = torch.randn(3, 4)
b = torch.randn(3)

result = remote_linear("127.0.0.1:50051", x, w, b)
print("remote result:", result)
print("local  result:", torch.nn.functional.linear(x, w, b))
print("match:", torch.allclose(result, torch.nn.functional.linear(x, w, b)))
