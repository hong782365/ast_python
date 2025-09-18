import asyncio
import logging
import os
import re
import subprocess
import sys
import time
import hashlib
from pathlib import Path

from core.config import BASE_DIR, FFMPEG_REPORT_DIR, FFMPEG_LOG_DIR
from .ytdlp_manager import get_manager

# 导入重构后的FFmpeg工具函数
from ffmpeg_utils import get_ffmpeg_path, is_cloudflare_environment

class YouTubeLiveStreamer:
    def __init__(self, youtube_url: str, duration_seconds: int = 10):
        self.youtube_url = youtube_url
        self.duration_seconds = duration_seconds
        self.ffmpeg_process = None
        self.ffmpeg_console_file = None
        
        # Create ffmpeg log directories
        FFMPEG_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        FFMPEG_LOG_DIR.mkdir(parents=True, exist_ok=True)
        
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
        is_cloudflare = is_cloudflare_environment()
        
        # Environment-specific logging setup
        if is_cloudflare:
            # Cloudflare: No file logs, direct stderr output
            ffmpeg_report_log = None
            ffmpeg_console_log = None
            logging.info(f"🌐 Running in Cloudflare environment - using direct stderr logging")
        else:
            # Local: File-based logging (existing behavior)
            ffmpeg_report_log = FFMPEG_REPORT_DIR / f"ffmpeg-report-{timestamp}-{self.youtube_url_id}.log"
            ffmpeg_console_log = FFMPEG_LOG_DIR / f"ffmpeg-console-{timestamp}-{self.youtube_url_id}.log"
            logging.info(f"🏠 Running in local environment - using file-based logging")
        
        try:
            # Step 1: Use yt-dlp library to extract direct stream URL
            ytdlp_manager = get_manager()
            direct_url = await ytdlp_manager.extract_stream_url(self.youtube_url)
            
            # Step 2: Build ffmpeg command based on environment
            ffmpeg_cmd = [
                get_ffmpeg_path(),  # ffmpeg 主程序
                "-hide_banner",  # 隐藏 ffmpeg 启动横幅信息
            ]
            
            # Add report parameter only for local environment
            if not is_cloudflare:
                ffmpeg_cmd.append("-report")  # 它会生成一个详细的报告文件，完整记录 FFmpeg 的所有命令行输出（无论你在 -loglevel 设置了什么级别）、运行环境、库版本等信息。当你的 Python 脚本无法完全捕获实时输出时，这个报告文件就是你最终的真相来源。
            
            # Add remaining ffmpeg parameters
            ffmpeg_cmd.extend([
                "-loglevel", "verbose",  # verbose 恢复详细日志以诊断问题

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
            ])
            
            # Start ffmpeg process directly with network stream
            logging.info("Starting ffmpeg with direct network stream...")
            logging.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
            
            if is_cloudflare:
                logging.info("🌐 Cloudflare mode: FFmpeg stderr will output directly to console")
            else:
                logging.info(f"🏠 Local mode: FFmpeg logs to files")
                logging.info(f"FFmpeg report log: {ffmpeg_report_log}")
                logging.info(f"FFmpeg console log: {ffmpeg_console_log}")
            
            # Set up environment and file handles based on environment
            ffmpeg_start_time = time.time()
            ffmpeg_env = os.environ.copy()
            ffmpeg_console_file = None
            
            if is_cloudflare:
                # Cloudflare: Direct stderr output, no file redirection
                self.ffmpeg_process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=sys.stderr,  # FFmpeg stderr goes directly to Python's stderr
                    bufsize=0,
                    env=ffmpeg_env
                )
            else:
                # Local: File-based logging (existing behavior)
                ffmpeg_env['FFREPORT'] = f"file={ffmpeg_report_log}:level=48"
                ffmpeg_console_file = open(ffmpeg_console_log, 'w')
                
                self.ffmpeg_process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=ffmpeg_console_file,
                    bufsize=0,
                    env=ffmpeg_env
                )
            
            # Store the file handle for cleanup
            self.ffmpeg_console_file = ffmpeg_console_file
            
            # No need for yt-dlp process anymore
                
            # Store the spawn timestamp for later timing calculation
            self.ffmpeg_spawn_time = time.monotonic()
            
            # Basic process health check (don't wait for stream readiness)
            await asyncio.sleep(0.1)  # Very short wait just to detect immediate failures
            if self.ffmpeg_process.poll() is not None:
                # ffmpeg process has already exited
                logging.error(f"FFmpeg process exited early with code: {self.ffmpeg_process.returncode}")
                
                # Output critical startup failure to stderr
                
                if is_cloudflare:
                    # Cloudflare: stderr already went directly to console
                    logging.error("🌐 FFmpeg stderr should be visible above (direct output)")
                    raise Exception(f"FFmpeg failed to start in Cloudflare environment, exit code: {self.ffmpeg_process.returncode}")
                else:
                    # Local: Try to read console log file
                    logging.error(f"FFmpeg console log: {ffmpeg_console_log}")
                    
                    try:
                        with open(ffmpeg_console_log, 'r') as f:
                            stderr_content = f.read()
                            if stderr_content.strip():
                                logging.error(f"FFmpeg stderr from log file: {stderr_content}")
                                # Output first 200 chars of error to stderr for immediate visibility
                    except Exception as e:
                        logging.error(f"Could not read ffmpeg console log: {e}")
                    
                    raise Exception(f"FFmpeg failed to start, check log file: {ffmpeg_console_log}")
            
            logging.info(f"FFmpeg process spawned successfully (PID: {self.ffmpeg_process.pid})")
            
            # Start background monitoring tasks based on environment
            if is_cloudflare:
                # Cloudflare: Only health monitoring (no file monitoring needed)
                logging.info("🌐 Cloudflare mode: Starting health monitor only")
                health_monitor_task = asyncio.create_task(self._monitor_ffmpeg_health())
            else:
                # Local: Both file monitoring and health monitoring
                logging.info("🏠 Local mode: Starting file and health monitors")
                stderr_monitor_task = asyncio.create_task(self._monitor_ffmpeg_stderr(ffmpeg_console_log))
                health_monitor_task = asyncio.create_task(self._monitor_ffmpeg_health())
            
            logging.info(f"Started direct network streaming pipeline using yt-dlp library")
            return self.ffmpeg_process.stdout
            
        except Exception as e:
            logging.error(f"Failed to start streaming pipeline: {e}")
            await self.cleanup()
            raise
    
    async def _monitor_ffmpeg_stderr(self, console_log_path):
        """Monitor ffmpeg console log file in the background"""
        if not self.ffmpeg_process:
            logging.warning("🔧 FFmpeg stderr monitor: No process available")
            print("🔧 FFmpeg stderr monitor: No process available", file=sys.stderr, flush=True)
            return
            
        logging.info(f"🔧 Starting FFmpeg console log monitor for PID {self.ffmpeg_process.pid}")
        logging.info(f"🔧 Monitoring log file: {console_log_path}")
        
        try:
            line_count = 0
            last_position = 0
            error_count = 0
            warning_count = 0
            
            while self.ffmpeg_process.poll() is None:
                try:
                    # Check if log file exists and read new lines
                    if os.path.exists(console_log_path):
                        with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                            f.seek(last_position)
                            new_lines = f.readlines()
                            last_position = f.tell()
                            
                            for line in new_lines:
                                line_str = line.strip()
                                if line_str:
                                    line_count += 1
                                    # Categorize different types of FFmpeg messages
                                    if "error" in line_str.lower() or "failed" in line_str.lower():
                                        error_count += 1
                                        logging.error(f"🔴 FFmpeg ERROR: {line_str}")
                                        # Output critical errors to stderr for Cloudflare Workers Logs
                                    elif "warning" in line_str.lower():
                                        warning_count += 1
                                        logging.warning(f"🟡 FFmpeg WARNING: {line_str}")
                                        # Output warnings to stderr for visibility
                                    elif "connection" in line_str.lower() or "http" in line_str.lower():
                                        logging.info(f"🌐 FFmpeg NETWORK: {line_str}")
                                        # Output network issues to stderr as they're critical for debugging
                                        if any(keyword in line_str.lower() for keyword in ["timeout", "refused", "unreachable", "failed"]):
                                            logging.error(f"🔴 FFmpeg NETWORK ERROR: {line_str}")
                                    elif any(keyword in line_str.lower() for keyword in ["duration", "time=", "bitrate", "fps"]):
                                        logging.debug(f"📊 FFmpeg PROGRESS: {line_str}")
                                    else:
                                        logging.info(f"🔧 FFmpeg: {line_str}")
                    
                    # Wait a bit before checking again
                    await asyncio.sleep(1.0)
                    
                except Exception as e:
                    logging.error(f"🔧 Error reading ffmpeg console log: {e}")
                    await asyncio.sleep(2.0)  # Wait longer on error
            
            # Process has exited, read any remaining log content
            final_exit_code = self.ffmpeg_process.returncode
            logging.info(f"🔧 FFmpeg process exited with code: {final_exit_code}, total log lines processed: {line_count}")
            
            # Output exit status to stderr for Cloudflare Workers Logs
                
            # Read any final content from the log file
            try:
                if os.path.exists(console_log_path):
                    with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(last_position)
                        remaining_content = f.read()
                        if remaining_content.strip():
                            logging.info(f"🔧 Final FFmpeg log content: {remaining_content}")
                            # Output final content if it contains errors
                            if any(keyword in remaining_content.lower() for keyword in ["error", "failed", "timeout"]):
                                logging.error(f"🔴 FFmpeg final error content: {remaining_content[:200]}...")
            except Exception as e:
                logging.error(f"🔧 Error reading final log content: {e}")
                
        except Exception as e:
            logging.error(f"🔧 FFmpeg console log monitor error: {e}")
            import traceback
            logging.error(f"🔧 Monitor traceback: {traceback.format_exc()}")
        
        logging.info("🔧 FFmpeg console log monitor ended")

    async def _monitor_ffmpeg_health(self):
        """Monitor FFmpeg process health and network connectivity"""
        if not self.ffmpeg_process:
            logging.warning("💓 FFmpeg health monitor: No process available")
            return
            
        logging.info(f"💓 Starting FFmpeg health monitor for PID {self.ffmpeg_process.pid}")
        logging.info(f"💓 FFmpeg duration limit: {self.duration_seconds} seconds")
        
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
                    logging.info(f"💓 FFmpeg health check #{check_count}: CPU {cpu_percent:.1f}%, Memory {memory_info.rss/1024/1024:.1f}MB")
                    
                    # Output health status to stderr for monitoring (every 5 checks = 2.5 minutes)
                    if check_count % 5 == 0:
                        logging.info(f"📊 FFmpeg health status: CPU {cpu_percent:.1f}%, Memory {memory_info.rss/1024/1024:.1f}MB")
                        
                except ImportError:
                    logging.info(f"💓 FFmpeg health check #{check_count}: Process alive (psutil not available for detailed stats)")
                    if check_count % 5 == 0:
                        logging.info(f"📊 FFmpeg health status: Process alive (no detailed stats)")
                except Exception as e:
                    logging.warning(f"💓 FFmpeg health check #{check_count}: Error getting process stats: {e}")
            
            # Process has exited
            exit_code = self.ffmpeg_process.returncode
            elapsed_time = time.time() - start_time
            logging.info(f"💓 FFmpeg health monitor: Process exited with code {exit_code} after {check_count} health checks")
            logging.info(f"💓 Total runtime: {elapsed_time:.1f}s (limit was {self.duration_seconds}s)")
            
            # Check if FFmpeg reached its duration limit
            duration_reached = abs(elapsed_time - self.duration_seconds) < 5.0  # Within 5 seconds of limit
            if duration_reached:
                logging.info(f"💓 FFmpeg likely exited due to reaching duration limit ({self.duration_seconds}s)")
            
            # Provide interpretation of common exit codes
            exit_interpretation = ""
            if exit_code == 0:
                logging.info("💓 Exit code 0: Normal termination")
                exit_interpretation = "Normal termination"
            elif exit_code == 1:
                logging.warning("💓 Exit code 1: Generic error (check FFmpeg stderr for details)")
                exit_interpretation = "Generic error"
            elif exit_code == -9:
                logging.error("💓 Exit code -9: Process was killed (SIGKILL)")
                exit_interpretation = "Process killed (SIGKILL)"
            elif exit_code == -15:
                logging.warning("💓 Exit code -15: Process was terminated (SIGTERM)")
                exit_interpretation = "Process terminated (SIGTERM)"
            else:
                logging.warning(f"💓 Exit code {exit_code}: Check FFmpeg documentation for details")
                exit_interpretation = f"Unknown exit code {exit_code}"
            
            # Output comprehensive exit status to stderr
                
        except Exception as e:
            logging.error(f"💓 FFmpeg health monitor error: {e}")
            import traceback
            logging.error(f"💓 Health monitor traceback: {traceback.format_exc()}")
        
        logging.info("💓 FFmpeg health monitor ended")
            
    async def cleanup(self):
        """Clean up subprocess resources"""
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()
            except Exception as e:
                logging.error(f"Error terminating ffmpeg: {e}")
        
        # Close ffmpeg console log file if it exists
        if hasattr(self, 'ffmpeg_console_file') and self.ffmpeg_console_file:
            try:
                self.ffmpeg_console_file.close()
            except Exception as e:
                logging.error(f"Error closing ffmpeg console log file: {e}")