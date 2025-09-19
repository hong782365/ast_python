import asyncio
import logging
import os
import re
import subprocess
import sys
import time
import hashlib
from pathlib import Path

from core.config import BASE_DIR
from .ytdlp_manager import get_manager

# 导入重构后的FFmpeg工具函数
from ffmpeg_utils import get_ffmpeg_path, is_cloudflare_environment

class YouTubeLiveStreamer:
    def __init__(self, youtube_url: str, duration_seconds: int = 10):
        self.youtube_url = youtube_url
        self.duration_seconds = duration_seconds
        self.ffmpeg_process = None
        
        # 使用结构化日志记录器
        self.logger = logging.getLogger("ast.ffmpeg")
        
        # Extract YouTube video ID from URL
        self.youtube_url_id = self._extract_youtube_id(youtube_url)
    
    def _extract_youtube_id(self, url: str) -> str:
        """Extract YouTube video ID from various YouTube URL formats"""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([^&\n?#]+)',
            r'youtube\.com/live/([^&\n?#]+)',
            r'youtube\.com/channel/([^&\n?#/]+)',
            r'youtube\.com/c/([^&\n?#/]+)',
            r'youtube\.com/@([^&\n?#/]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # If no pattern matches, use a hash of the URL as fallback
        return hashlib.md5(url.encode()).hexdigest()[:8]
        
    async def start_streaming_pipeline(self):
        """Start yt-dlp (library mode) + ffmpeg (direct network pull) pipeline for PCM streaming"""
        timestamp = time.strftime("%Y%m%dT%H%M%SZ")
        # 统一使用控制台输出，不再区分环境
        self.logger.info(f"🌐 统一使用控制台日志输出模式")
        
        try:
            # Step 1: Use yt-dlp library to extract direct stream URL
            ytdlp_manager = get_manager()
            direct_url = await ytdlp_manager.extract_stream_url(self.youtube_url)
            
            # Step 2: Build ffmpeg command with optimized logging
            ffmpeg_cmd = [
                get_ffmpeg_path(),  # ffmpeg 主程序
                "-loglevel", "error",  # 只显示错误和更严重的消息
                "-stats",  # 显示编码进度统计
                "-hide_banner",  # 隐藏 ffmpeg 启动横幅信息
                
                # --- ↓↓↓ 超低延迟优化参数 ↓↓↓ ---
                "-fflags", "nobuffer",       # 告诉 demuxer 不要缓冲数据包
                # "-probesize", "32",           # 极大地减小探测数据大小，快速启动
                # "-analyzeduration", "0",      # 不花时间分析流的初始部分
                # "-avioflags", "direct",       # 减少 I/O 层的缓冲
                # "-flush_packets", "1",        # 每处理一个包就立刻刷新，而不是等待
                # "-hls_live_edge", "99999",   # 设置 HLS 直播边缘时间，确保快速响应
                # --- ↑↑↑ 超低延迟优化参数 ↑↑↑ ---
                
                # "-http_proxy", "http://127.0.0.1:7897",
                "-i", direct_url,  # 输入源：直接从网络URL读取
                "-ac", "1",  # 音频通道数：1（单声道）
                "-ar", "16000",  # 音频采样率：16000Hz
                "-acodec", "pcm_s16le",  # 音频编码器：16位小端序 PCM
                "-f", "s16le",  # 输出格式：16位小端序原始音频
                # 移除 "-t" 参数，支持无限时长直播直到显式stop
                "-y",  # 覆盖输出文件（如果存在）
                "pipe:1"  # 输出到 stdout 标准输出（管道）
            ]
            
            # Start ffmpeg process directly with network stream
            self.logger.info("启动 FFmpeg 直接网络流处理...")
            self.logger.info(f"FFmpeg 命令: {' '.join(ffmpeg_cmd)}")
            self.logger.info("🌐 FFmpeg stderr 输出到控制台")
            
            # Set up environment
            ffmpeg_start_time = time.time()
            ffmpeg_env = os.environ.copy()
            
            # 统一使用 stderr 直接输出到控制台
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,  # FFmpeg stderr 直接输出到控制台
                bufsize=0,
                env=ffmpeg_env,
                encoding='utf-8',
                text=True
            )
            
            # No need for yt-dlp process anymore
                
            # Store the spawn timestamp for later timing calculation
            self.ffmpeg_spawn_time = time.monotonic()
            
            # Basic process health check (don't wait for stream readiness)
            await asyncio.sleep(0.1)  # Very short wait just to detect immediate failures
            if self.ffmpeg_process.poll() is not None:
                # ffmpeg process has already exited
                self.logger.error(f"FFmpeg 进程提前退出，退出码: {self.ffmpeg_process.returncode}")
                self.logger.error("🌐 FFmpeg stderr 应在上方可见（直接输出）")
                raise Exception(f"FFmpeg 启动失败，退出码: {self.ffmpeg_process.returncode}")
            
            self.logger.info(f"FFmpeg 进程启动成功 (PID: {self.ffmpeg_process.pid})")
            
            # 启动健康监控任务（不再需要文件监控）
            self.logger.info("🌐 启动 FFmpeg 健康监控")
            health_monitor_task = asyncio.create_task(self._monitor_ffmpeg_health())
            
            self.logger.info(f"直接网络流水线启动完成，使用 yt-dlp 库")
            return self.ffmpeg_process.stdout
            
        except Exception as e:
            self.logger.error(f"启动流水线失败: {e}")
            await self.cleanup()
            raise
    

    async def _monitor_ffmpeg_health(self):
        """Monitor FFmpeg process health and network connectivity"""
        if not self.ffmpeg_process:
            self.logger.warning("💓 FFmpeg 健康监控: 无可用进程")
            return
            
        self.logger.info(f"💓 启动 FFmpeg 健康监控，PID: {self.ffmpeg_process.pid}")
        self.logger.info(f"💓 FFmpeg 持续时间限制: {self.duration_seconds} 秒")
        
        check_count = 0
        start_time = time.time()
        
        try:
            while self.ffmpeg_process.poll() is None:
                await asyncio.sleep(30)  # Check every 30 seconds
                check_count += 1
                
                # Log process health status
                try:
                    import psutil
                    process = psutil.Process(self.ffmpeg_process.pid)
                    cpu_percent = process.cpu_percent()
                    memory_info = process.memory_info()
                    self.logger.info(f"💓 FFmpeg 健康检查 #{check_count}: CPU {cpu_percent:.1f}%, 内存 {memory_info.rss/1024/1024:.1f}MB")
                    
                    # Output health status to stderr for monitoring (every 5 checks = 2.5 minutes)
                    if check_count % 5 == 0:
                        self.logger.info(f"📊 FFmpeg 健康状态: CPU {cpu_percent:.1f}%, 内存 {memory_info.rss/1024/1024:.1f}MB")
                        
                except ImportError:
                    self.logger.info(f"💓 FFmpeg 健康检查 #{check_count}: 进程正常 (无 psutil 详细统计)")
                    if check_count % 5 == 0:
                        self.logger.info(f"📊 FFmpeg 健康状态: 进程正常 (无详细统计)")
                except Exception as e:
                    self.logger.warning(f"💓 FFmpeg 健康检查 #{check_count}: 获取进程统计错误: {e}")
            
            # Process has exited
            exit_code = self.ffmpeg_process.returncode
            elapsed_time = time.time() - start_time
            self.logger.info(f"💓 FFmpeg 健康监控: 进程退出，退出码 {exit_code}，共检查 {check_count} 次")
            self.logger.info(f"💓 总运行时间: {elapsed_time:.1f}s (限制为 {self.duration_seconds}s)")
            
            # Check if FFmpeg reached its duration limit
            duration_reached = abs(elapsed_time - self.duration_seconds) < 5.0  # Within 5 seconds of limit
            if duration_reached:
                self.logger.info(f"💓 FFmpeg 可能因达到时间限制 ({self.duration_seconds}s) 而退出")
            
            # Provide interpretation of common exit codes
            exit_interpretation = ""
            if exit_code == 0:
                self.logger.info("💓 退出码 0: 正常终止")
                exit_interpretation = "正常终止"
            elif exit_code == 1:
                self.logger.warning("💓 退出码 1: 通用错误 (检查 FFmpeg stderr 获取详细信息)")
                exit_interpretation = "通用错误"
            elif exit_code == -9:
                self.logger.error("💓 退出码 -9: 进程被强制终止 (SIGKILL)")
                exit_interpretation = "进程被强制终止 (SIGKILL)"
            elif exit_code == -15:
                self.logger.warning("💓 退出码 -15: 进程被终止 (SIGTERM)")
                exit_interpretation = "进程被终止 (SIGTERM)"
            else:
                self.logger.warning(f"💓 退出码 {exit_code}: 检查 FFmpeg 文档获取详细信息")
                exit_interpretation = f"未知退出码 {exit_code}"
            
            # Output comprehensive exit status to stderr
                
        except Exception as e:
            self.logger.error(f"💓 FFmpeg 健康监控错误: {e}")
            import traceback
            self.logger.error(f"💓 健康监控堆栈跟踪: {traceback.format_exc()}")
        
        self.logger.info("💓 FFmpeg 健康监控结束")
            
    async def cleanup(self):
        """Clean up subprocess resources"""
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=5)
                self.logger.info("FFmpeg 进程已正常终止")
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()
                self.logger.warning("FFmpeg 进程已强制终止")
            except Exception as e:
                self.logger.error(f"终止 FFmpeg 进程时出错: {e}")