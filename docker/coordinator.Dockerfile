FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# coordinator 需要 worker/op_service_pb2*.py 来做 gRPC 序列化，
# 但不需要也不会拷贝 worker/op_executor.py 之外的任何服务端执行逻辑变化
COPY worker/ ./worker/
COPY coordinator/ ./coordinator/
COPY test/ ./test/

# 默认跑测试脚本；也可以在 docker run 时覆盖 command 换成别的入口
CMD ["python", "-m", "test.test_rpc"]
