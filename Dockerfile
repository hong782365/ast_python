FROM python:3.11-slim

# 安装系统依赖包括 FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制 YouTube cookies（关键文件）
COPY youtube/cookie/youtube_hongc_cookies.txt ./youtube/cookie/
RUN mkdir -p youtube/cookie

# 复制并安装 Python 依赖（仅 Cloudflare Containers 所需）
COPY requirements-container.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 9000

# 启动命令
CMD ["python", "publisher.py"]