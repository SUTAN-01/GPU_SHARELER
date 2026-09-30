FROM python:3.11-slim

WORKDIR /app

# 只装依赖，不带任何 coordinator 代码
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 只拷贝 worker 运行所需文件，验证隔离性：
# coordinator/ 和 test/ 目录不会出现在这个镜像里
COPY worker/ ./worker/

EXPOSE 50051

ENV GPU_SHARE_PORT=50051
# 运行时用 -e GPU_SHARE_SECRET=xxx 传入共享密钥（可选）

CMD ["python", "-m", "worker.op_executor"]
