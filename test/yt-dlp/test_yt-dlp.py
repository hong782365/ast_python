import subprocess
import os
import shutil
import sys

# --- 配置 ---
YOUTUBE_URL = "https://www.youtube.com/watch?v=m_dhMSvUCIc"
# PROXY_URL = "socks5://127.0.0.1:7897"
FFMPEG_PATH = "/opt/homebrew/Caskroom/miniforge/base/bin/ffmpeg"

# --- 打印诊断信息 ---
print("--- 诊断信息 ---")
print(f"Python 版本: {sys.version}")
print(f"当前工作目录: {os.getcwd()}")

# 检查环境变量
print("\n--- 检查环境变量 ---")
http_proxy_env = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
https_proxy_env = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
print(f"HTTP_PROXY: {http_proxy_env}")
print(f"HTTPS_PROXY: {https_proxy_env}")

# 查找可执行文件路径
yt_dlp_path = shutil.which("yt-dlp")
ffmpeg_path = shutil.which("ffmpeg")
print("\n--- 查找可执行文件 ---")
print(f"yt-dlp 路径: {yt_dlp_path}")
print(f"ffmpeg 路径: {ffmpeg_path}")
if not all([yt_dlp_path, ffmpeg_path]):
    print("错误: 找不到 yt-dlp 或 ffmpeg, 请确保它们在系统的 PATH 中。")
    exit(1)

# --- 构造命令 ---
yt_dlp_cmd = [
    yt_dlp_path,
    "--ffmpeg-location", FFMPEG_PATH,  # <--- 核心改动：为 yt-dlp 指定 ffmpeg 路径
    # "--hls-prefer-native",  # <--- 黄金解决方案：使用 yt-dlp 的原生 HLS 下载器
    # "-4",                   # <--- 继续保留，强制 IPv4 作为双重保险
    # "--proxy", PROXY_URL,    # <--- 使用 SOCKS5 代理，原生下载器支持它
    "-f", "bestaudio",      # <--- 可以简化为 bestaudio，让 yt-dlp 自己选
    "--no-part",
    "--no-keep-fragments",
    "--no-live-from-start",
    "-o", "-",
    YOUTUBE_URL
]

ffmpeg_cmd = [
    ffmpeg_path,
    "-hide_banner",
    "-loglevel", "error",
    "-fflags", "+nobuffer",
    "-flags", "low_delay",
    "-i", "pipe:0",
    "-ac", "1",
    "-ar", "16000",
    "-acodec", "pcm_s16le",
    "-f", "s16le",
    "-y",
    "pipe:1"
]

print("\n--- 执行命令 ---")
print(f"yt-dlp command: {' '.join(yt_dlp_cmd)}")
print(f"ffmpeg command: {' '.join(ffmpeg_cmd)}")
print("\n--- 实时日志输出 ---")


# --- 执行子进程 ---
try:
    # 启动 yt-dlp 进程，捕获其 stdout 和 stderr
    yt_dlp_process = subprocess.Popen(
        yt_dlp_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True # 使用 text=True 让输出为字符串
    )

    # 启动 ffmpeg 进程，将其 stdin 连接到 yt-dlp 的 stdout
    ffmpeg_process = subprocess.Popen(
        ffmpeg_cmd,
        stdin=yt_dlp_process.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, # 也捕获 ffmpeg 的 stderr
        text=True
    )

    # 创建一个线程来实时打印 yt-dlp 的 stderr
    import threading
    def log_stream(stream, prefix):
        for line in iter(stream.readline, ''):
            print(f"[{prefix}] {line.strip()}", flush=True)
        stream.close()

    yt_dlp_stderr_thread = threading.Thread(target=log_stream, args=(yt_dlp_process.stderr, "yt-dlp-stderr"))
    ffmpeg_stderr_thread = threading.Thread(target=log_stream, args=(ffmpeg_process.stderr, "ffmpeg-stderr"))

    yt_dlp_stderr_thread.start()
    ffmpeg_stderr_thread.start()

    # 尝试从 ffmpeg 读取数据
    print("\n--- 开始从 FFMPEG 读取数据 ---")
    chunk_count = 0
    while True:
        # 读取 3200 字节 (等于 16kHz * 16-bit * 1 channel * 0.1 seconds)
        audio_chunk = ffmpeg_process.stdout.read(3200)
        if not audio_chunk:
            print("FFMPEG 输出管道已关闭，停止读取。")
            break
        chunk_count += 1
        if chunk_count % 10 == 0: # 每秒打印一次
             print(f"已成功读取 {chunk_count} 个音频块...")

    print(f"\n--- 读取完成 ---")
    print(f"总共读取了 {chunk_count} 个音频块。")


finally:
    # 等待进程结束
    yt_dlp_process.wait()
    ffmpeg_process.wait()
    yt_dlp_stderr_thread.join()
    ffmpeg_stderr_thread.join()
    print(f"\n--- 进程已退出 ---")
    print(f"yt-dlp 返回码: {yt_dlp_process.returncode}")
    print(f"ffmpeg 返回码: {ffmpeg_process.returncode}")