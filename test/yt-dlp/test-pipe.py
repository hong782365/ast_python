import subprocess
import os
import shutil
import sys
import threading

# --- 配置 ---
YOUTUBE_URL = "https://www.youtube.com/watch?v=m_dhMSvUCIc"
# 我们用回 HTTP 代理，因为是我们要直接传给 ffmpeg，而 ffmpeg 明确支持它
PROXY_URL = "http://127.0.0.1:7897"

# --- 查找可执行文件 ---
yt_dlp_path = shutil.which("yt-dlp")
ffmpeg_path = shutil.which("ffmpeg")

# --- 步骤 1: 单独调用 yt-dlp 获取 M3U8 URL ---
def get_m3u8_url(youtube_url):
    print("--- 步骤 1: 正在使用 yt-dlp 获取 M3U8 URL... ---")
    yt_dlp_cmd_get_url = [
        yt_dlp_path,
        "-4",
        "--proxy", PROXY_URL,
        "-f", "bestaudio",
        "-g",  # -g = --get-url
        youtube_url,
    ]
    print(f"执行命令: {' '.join(yt_dlp_cmd_get_url)}")
    
    # 使用 subprocess.run, 因为这是一个需要等待结果的、一次性的任务
    result = subprocess.run(yt_dlp_cmd_get_url, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        print("!!!!!! 获取 URL 失败 !!!!!!")
        print(f"yt-dlp Stderr:\n{result.stderr}")
        raise RuntimeError("yt-dlp a échoué à obtenir l'URL M3U8.")
    
    m3u8_url = result.stdout.strip()
    print(f"--- 成功获取 URL: {m3u8_url[:80]}... ---") # 只打印前80个字符
    return m3u8_url


# --- 步骤 2: 单独调用 ffmpeg 进行下载和转码 ---
def stream_audio_from_url(m3u8_url):
    print("\n--- 步骤 2: 正在使用我们自己的 ffmpeg 进程进行推流... ---")
    ffmpeg_cmd_stream = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel", "error",
        "-http_proxy", PROXY_URL,  # <--- 关键！直接为 ffmpeg 指定代理
        "-i", m3u8_url,
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        "-f", "s16le",
        "-y",
        "pipe:1",
    ]
    print(f"执行命令: {' '.join(ffmpeg_cmd_stream)}")

    try:
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd_stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # 注意：这里我们不再需要 text=True，因为我们要读取原始的二进制音频数据
        )
        
        # 实时打印 ffmpeg 的 stderr
        def log_stream(stream, prefix):
            # 将二进制流解码为文本
            for line in iter(lambda: stream.readline().decode('utf-8', errors='ignore'), ''):
                if line:
                    print(f"[{prefix}] {line.strip()}", flush=True)
            stream.close()
        
        ffmpeg_stderr_thread = threading.Thread(target=log_stream, args=(ffmpeg_process.stderr, "ffmpeg-stderr"))
        ffmpeg_stderr_thread.start()

        print("\n--- 开始从 FFMPEG 读取数据 ---")
        chunk_count = 0
        while True:
            # 读取二进制数据
            audio_chunk = ffmpeg_process.stdout.read(3200)
            if not audio_chunk:
                print("FFMPEG 输出管道已关闭，停止读取。")
                break
            chunk_count += 1
            if chunk_count % 10 == 0:
                print(f"已成功读取 {chunk_count} 个音频块...")

        print(f"\n--- 读取完成 ---")
        print(f"总共读取了 {chunk_count} 个音频块。")

    finally:
        print("\n--- 清理 ffmpeg 进程 ---")
        ffmpeg_process.kill()
        ffmpeg_process.wait()
        ffmpeg_stderr_thread.join()
        print("清理完毕。")
        print(f"ffmpeg 返回码: {ffmpeg_process.returncode}")


# --- 主程序 ---
if __name__ == "__main__":
    try:
        # 第一步
        final_m3u8_url = get_m3u8_url(YOUTUBE_URL)
        # 第二步
        stream_audio_from_url(final_m3u8_url)
        print("\n🎉🎉🎉 任务成功完成！🎉🎉🎉")
    except Exception as e:
        print(f"\n❌❌❌ 任务失败: {e} ❌❌❌")