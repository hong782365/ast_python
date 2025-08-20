import subprocess
import os
import sys
import threading

# --- 配置 ---
YOUTUBE_URL = "https://www.youtube.com/watch?v=m_dhMSvUCIc"
PROXY_URL = "http://127.0.0.1:7897"

# --- 关键改动：精确指定 FFMPEG 路径 ---
YT_DLP_PATH = "/Users/weihongwang/Documents/workspace/s2s/ast_python/.venv/bin/yt-dlp"
FFMPEG_PATH = "/opt/homebrew/Caskroom/miniforge/base/bin/ffmpeg"

# --- 步骤 1: 获取 URL ---
def get_m3u8_url(youtube_url):
    print("--- 步骤 1: 正在使用 yt-dlp 获取 M3U8 URL... ---")
    yt_dlp_cmd_get_url = [
        YT_DLP_PATH, "-4", "--proxy", PROXY_URL,
        "-f", "bestaudio", "-g", youtube_url,
    ]
    result = subprocess.run(yt_dlp_cmd_get_url, capture_output=True, text=True, check=True)
    m3u8_url = result.stdout.strip()
    print(f"--- 成功获取 URL ---")
    return m3u8_url

# --- 步骤 2: 使用正确的 FFMPEG 推流 ---
def stream_audio_from_url(m3u8_url):
    print("\n--- 步骤 2: 正在使用我们指定的 ffmpeg 进程进行推流... ---")
    ffmpeg_cmd_stream = [
        FFMPEG_PATH, # <--- 使用我们指定的正确路径
        "-hide_banner", "-loglevel", "error",
        "-http_proxy", PROXY_URL,
        "-i", m3u8_url,
        "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        "-f", "s16le", "-y", "pipe:1",
    ]
    print(f"执行命令: {' '.join(ffmpeg_cmd_stream)}")

    ffmpeg_process = subprocess.Popen(
        ffmpeg_cmd_stream,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # ... (后面的日志读取和清理代码保持不变) ...
    # 为了简洁，这里省略，请参考上一版代码的后半部分
    
    print("\n--- 开始从 FFMPEG 读取数据 ---")
    chunk_count = 0
    while chunk_count < 100:
        audio_chunk = ffmpeg_process.stdout.read(3200)
        if not audio_chunk:
            print("FFMPEG 输出管道已关闭，停止读取。")
            break
        chunk_count += 1
        print(f"已成功读取 {chunk_count} 个音频块...", end='\r')

    ffmpeg_process.stdout.close()
    ffmpeg_process.wait()
    print(f"\n--- 读取完成，总共读取了 {chunk_count} 个音频块。---")


# --- 主程序 ---
if __name__ == "__main__":
    try:
        final_m3u8_url = get_m3u8_url(YOUTUBE_URL)
        stream_audio_from_url(final_m3u8_url)
        print("\n\n🎉🎉🎉 史诗级调试成功结束！问题已解决！ 🎉🎉🎉")
    except Exception as e:
        print(f"\n❌❌❌ 任务失败: {e} ❌❌❌")