import asyncio
import uuid
import os
import subprocess
import signal
import sys
import time
import logging
import json
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Union
import websockets
from websockets import Headers
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("APP_KEY")
ACCESS_KEY = os.getenv("ACCESS_KEY")
RESOURCE_ID = os.getenv("RESOURCE_ID")
WS_URL = os.getenv("WS_URL")

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 计算 python_protogen 目录的路径
protogen_dir = os.path.join(current_dir, "python_protogen")

# 只添加一次 python_protogen 目录
sys.path.append(protogen_dir)

# 现在可以直接导入所有模块
from products.understanding.ast.ast_service_pb2 import TranslateRequest, ReqParams, TranslateResponse
from common.events_pb2 import Type

# Configuration
@dataclass
class Config:
    ws_url: str
    app_key: str
    access_key: str
    resource_id: str

@dataclass
class Audio:
    format: str = None
    rate: int = None
    bits: Optional[int] = None
    channel: Optional[int] = None
    binary_data: Optional[bytes] = None

@dataclass
class TranslateRequestData:
    session_id: str
    event: str
    source_audio: Optional[Audio] = None
    target_audio: Optional[Audio] = None
    mode: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None

@dataclass
class TranslateResponseData:
    event: str
    session_id: str
    sequence: int
    text: str
    data: bytes
    message: str = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None

@dataclass
class SubtitleMessage:
    type: str = "subtitle"
    lane: str = None  # "source" or "translation"
    phase: str = None  # "start", "delta", or "end"
    text: str = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    final: bool = False

@dataclass
class StreamData:
    data_type: str  # "audio" or "subtitle"
    content: Union[bytes, str]  # binary audio data or JSON string

class ASTEventLogger:
    """事件日志记录器，用于记录同声传译的事件消息"""
    
    def __init__(self, youtube_url: str):
        self.youtube_url = youtube_url
        self.youtube_id = self._extract_youtube_id(youtube_url)
        
        # 创建日志文件
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"ast_{timestamp}_{self.youtube_id}.txt"
        
        # 确保目录存在
        self.log_dir = Path(current_dir) / "youtube" / "ast_event"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.log_dir / filename
        
        # 事件类型映射
        self.event_descriptions = {
            # 发送端事件
            Type.StartSession: "建联请求-StartSession-100",
            Type.UpdateConfig: "更新参数-UpdateConfig-201", 
            Type.TaskRequest: "发送音频数据-TaskRequest-200",
            Type.FinishSession: "结束session-FinishSession-102",
            
            # 接收端事件
            Type.SessionStarted: "建联成功-SessionStarted-150",
            Type.SourceSubtitleStart: "原文开始-SourceSubtitleStart-650",
            Type.SourceSubtitleEnd: "原文结束-SourceSubtitleEnd-652",
            Type.TranslationSubtitleStart: "译文开始-TranslationSubtitleStart-653", 
            Type.TranslationSubtitleEnd: "译文结束-TranslationSubtitleEnd-655",
            Type.TTSSentenceStart: "TTS开始-TTSSentenceStart-350",
            Type.TTSSentenceEnd: "TTS结束-TTSSentenceEnd-351",
            Type.UsageResponse: "计量计费-UsageResponse-154",
            Type.SessionFinished: "会话正常结束-SessionFinished-152",
            Type.SessionFailed: "会话失败-SessionFailed-153",
            Type.AudioMuted: "静音事件-AudioMuted-250"
        }
        
        logging.info(f"AST事件日志文件创建: {self.log_file}")
    
    def _extract_youtube_id(self, url: str) -> str:
        """从YouTube URL中提取视频ID"""
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
        
        # 如果没有匹配到，使用URL的哈希值作为后备
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:8]
    
    def log_send_event(self, event_type: Type, request_data: TranslateRequestData):
        """记录发送端事件"""
        if event_type not in self.event_descriptions:
            return
            
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S,") + str(int(time.time() * 1000) % 1000).zfill(3)
        description = self.event_descriptions[event_type]
        
        # 构建JSON数据
        event_name = f"Type_{event_type.name}" if hasattr(event_type, 'name') else f"event.Type_{event_type}"
        json_data = {
            "event": event_name,
            "session_id": request_data.session_id
        }
        
        # 根据事件类型添加特定字段
        if event_type == Type.StartSession:
            if request_data.source_audio:
                json_data["source_audio"] = {
                    "format": request_data.source_audio.format,
                    "rate": request_data.source_audio.rate,
                    "bits": request_data.source_audio.bits,
                    "channel": request_data.source_audio.channel
                }
            if request_data.target_audio:
                json_data["target_audio"] = {
                    "format": request_data.target_audio.format,
                    "rate": request_data.target_audio.rate
                }
            if request_data.mode:
                json_data["mode"] = request_data.mode
            if request_data.source_language:
                json_data["source_language"] = request_data.source_language
            if request_data.target_language:
                json_data["target_language"] = request_data.target_language
                
        elif event_type == Type.TaskRequest:
            if request_data.source_audio and request_data.source_audio.binary_data:
                json_data["source_audio"] = {
                    "data": "二进制数据"
                }
        
        # 写入日志文件
        log_entry = f"{timestamp} ==>> {description}: {json.dumps(json_data, ensure_ascii=False)}\n"
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def log_receive_event(self, response_data: TranslateResponseData):
        """记录接收端事件"""
        event_type = response_data.event
        if event_type not in self.event_descriptions:
            return
            
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S,") + str(int(time.time() * 1000) % 1000).zfill(3)
        description = self.event_descriptions[event_type]
        
        # 构建JSON数据
        event_name = f"Type_{event_type.name}" if hasattr(event_type, 'name') else f"event.Type_{event_type}"
        json_data = {
            "event": event_name,
            "session_id": response_data.session_id
        }
        
        # 根据事件类型添加特定字段
        if event_type in [Type.SourceSubtitleStart, Type.TranslationSubtitleStart, Type.TTSSentenceStart]:
            if response_data.start_time is not None:
                json_data["start_time"] = response_data.start_time
                
        elif event_type in [Type.SourceSubtitleEnd, Type.TranslationSubtitleEnd]:
            if response_data.start_time is not None:
                json_data["start_time"] = response_data.start_time
            if response_data.end_time is not None:
                json_data["end_time"] = response_data.end_time
            if response_data.text:
                json_data["text"] = response_data.text
                
        elif event_type == Type.TTSSentenceEnd:
            if response_data.data:
                json_data["data"] = "二进制数据"
            if response_data.start_time is not None:
                json_data["start_time"] = response_data.start_time
            if response_data.end_time is not None:
                json_data["end_time"] = response_data.end_time
                
        elif event_type == Type.AudioMuted:
            # 从message中提取静音时长（如果有的话）
            if response_data.message:
                json_data["message"] = response_data.message
        
        # 写入日志文件
        log_entry = f"{timestamp} ==>> {description}: {json.dumps(json_data, ensure_ascii=False)}\n"
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

class YouTubeLiveStreamer:
    def __init__(self, youtube_url: str, duration_seconds: int = 10):
        self.youtube_url = youtube_url
        self.duration_seconds = duration_seconds
        self.yt_dlp_process = None
        self.ffmpeg_process = None
        self.ffmpeg_console_file = None
        self.log_dir = Path(current_dir) / "youtube" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create ffmpeg log directories
        self.ffmpeg_report_dir = Path(current_dir) / "youtube" / "ffmpeg" / "report"
        self.ffmpeg_log_dir = Path(current_dir) / "youtube" / "ffmpeg" / "log"
        self.ffmpeg_report_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_log_dir.mkdir(parents=True, exist_ok=True)
        
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
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:8]
        
    async def start_streaming_pipeline(self):
        """Start yt-dlp (extract URL) + ffmpeg (direct network pull) pipeline for PCM streaming"""
        timestamp = time.strftime("%Y%m%dT%H%M%SZ")
        yt_dlp_log = self.log_dir / f"yt-dlp_{timestamp}.log"
        
        # Create ffmpeg log file paths
        ffmpeg_report_log = self.ffmpeg_report_dir / f"ffmpeg-report-{timestamp}-{self.youtube_url_id}.log"
        ffmpeg_console_log = self.ffmpeg_log_dir / f"ffmpeg-console-{timestamp}-{self.youtube_url_id}.log"
        
        # Step 1: Use yt-dlp to extract direct stream URL only
        yt_dlp_cmd = [
            "yt-dlp",  # yt-dlp 主程序
            "-f", "234/233/140/bestaudio[ext=m4a]/bestaudio",  # 优先选择纯音频流：234(高质量)>233(低质量)>140>m4a>最佳音频
            "--get-url",  # 只获取直链URL，不下载
            "--no-warnings",  # 不显示警告信息
            "--ffmpeg-location", "/opt/homebrew/Caskroom/miniforge/base/bin/ffmpeg",  # 指定 ffmpeg 可执行文件路径
            self.youtube_url  # YouTube 直播 URL
        ]
        
        try:
            # Extract direct stream URL using yt-dlp
            logging.info("Extracting direct stream URL with yt-dlp...")
            with open(yt_dlp_log, 'w') as log_file:
                yt_dlp_result = subprocess.run(
                    yt_dlp_cmd,
                    stdout=subprocess.PIPE,
                    stderr=log_file,
                    text=True,
                    timeout=30  # 30秒超时
                )
            
            if yt_dlp_result.returncode != 0:
                raise Exception(f"yt-dlp failed with return code: {yt_dlp_result.returncode}")
            
            # Get the direct stream URL
            direct_url = yt_dlp_result.stdout.strip()
            if not direct_url:
                raise Exception("Failed to extract direct stream URL")
            
            logging.info(f"Extracted direct stream URL: {direct_url[:100]}...")
            
            # Step 2: Use ffmpeg to directly pull from network with reconnect parameters
            ffmpeg_cmd = [
                "/opt/homebrew/Caskroom/miniforge/base/bin/ffmpeg",  # ffmpeg 主程序
                "-hide_banner",  # 隐藏 ffmpeg 启动横幅信息
                "-report",  # 它会生成一个详细的报告文件，完整记录 FFmpeg 的所有命令行输出（无论你在 -loglevel 设置了什么级别）、运行环境、库版本等信息。当你的 Python 脚本无法完全捕获实时输出时，这个报告文件就是你最终的真相来源。
                "-loglevel", "verbose",  # 恢复详细日志以诊断问题

                # --- ↓↓↓ 超低延迟优化参数 ↓↓↓ ---
                "-fflags", "nobuffer",       # 告诉 demuxer 不要缓冲数据包
                "-probesize", "32",           # 极大地减小探测数据大小，快速启动
                "-analyzeduration", "0",      # 不花时间分析流的初始部分
                "-avioflags", "direct",       # 减少 I/O 层的缓冲
                "-flush_packets", "1",        # 每处理一个包就立刻刷新，而不是等待
                # "-hls_live_edge", "99999",   # 设置 HLS 直播边缘时间，确保快速响应
                # --- ↑↑↑ 超低延迟优化参数 ↑↑↑ ---

                "-http_proxy", "http://127.0.0.1:7897",
                "-i", direct_url,  # 输入源：直接从网络URL读取
                "-ac", "1",  # 音频通道数：1（单声道）
                "-ar", "16000",  # 音频采样率：16000Hz
                "-acodec", "pcm_s16le",  # 音频编码器：16位小端序 PCM
                "-f", "s16le",  # 输出格式：16位小端序原始音频
                "-t", str(self.duration_seconds),  # 限制处理时长（秒）
                "-y",  # 覆盖输出文件（如果存在）
                "pipe:1"  # 输出到标准输出（管道）
            ]
            
            # Start ffmpeg process directly with network stream
            logging.info("Starting ffmpeg with direct network stream...")
            logging.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
            logging.info(f"FFmpeg report log: {ffmpeg_report_log}")
            logging.info(f"FFmpeg console log: {ffmpeg_console_log}")
            
            # Set up environment for ffmpeg report output
            ffmpeg_env = os.environ.copy()
            ffmpeg_env['FFREPORT'] = f"file={ffmpeg_report_log}:level=48"
            
            # Open console log file for stderr redirection
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
            self.yt_dlp_process = None
            
            # Wait longer for ffmpeg to initialize and start processing HLS stream
            await asyncio.sleep(5.0)  # Give ffmpeg more time to initialize HLS stream
            if self.ffmpeg_process.poll() is not None:
                # ffmpeg process has already exited
                logging.error(f"FFmpeg process exited early with code: {self.ffmpeg_process.returncode}")
                logging.error(f"FFmpeg console log: {ffmpeg_console_log}")
                # Try to read the console log file for error details
                try:
                    with open(ffmpeg_console_log, 'r') as f:
                        stderr_content = f.read()
                        if stderr_content.strip():
                            logging.error(f"FFmpeg stderr from log file: {stderr_content}")
                except Exception as e:
                    logging.error(f"Could not read ffmpeg console log: {e}")
                raise Exception(f"FFmpeg failed to start, check log file: {ffmpeg_console_log}")
            
            logging.info(f"FFmpeg process started successfully (PID: {self.ffmpeg_process.pid})")
            
            # Start a background task to monitor ffmpeg console log
            stderr_monitor_task = asyncio.create_task(self._monitor_ffmpeg_stderr(ffmpeg_console_log))
            
            # Start a background task to monitor ffmpeg health
            health_monitor_task = asyncio.create_task(self._monitor_ffmpeg_health())
            
            logging.info(f"Started direct network streaming pipeline, yt-dlp logs: {yt_dlp_log}")
            return self.ffmpeg_process.stdout
            
        except Exception as e:
            logging.error(f"Failed to start streaming pipeline: {e}")
            await self.cleanup()
            raise
    
    async def _monitor_ffmpeg_stderr(self, console_log_path):
        """Monitor ffmpeg console log file in the background"""
        if not self.ffmpeg_process:
            logging.warning("🔧 FFmpeg stderr monitor: No process available")
            return
            
        logging.info(f"🔧 Starting FFmpeg console log monitor for PID {self.ffmpeg_process.pid}")
        logging.info(f"🔧 Monitoring log file: {console_log_path}")
        
        try:
            line_count = 0
            last_position = 0
            
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
                                        logging.error(f"🔴 FFmpeg ERROR: {line_str}")
                                    elif "warning" in line_str.lower():
                                        logging.warning(f"🟡 FFmpeg WARNING: {line_str}")
                                    elif "connection" in line_str.lower() or "http" in line_str.lower():
                                        logging.info(f"🌐 FFmpeg NETWORK: {line_str}")
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
            
            # Read any final content from the log file
            try:
                if os.path.exists(console_log_path):
                    with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(last_position)
                        remaining_content = f.read()
                        if remaining_content.strip():
                            logging.info(f"🔧 Final FFmpeg log content: {remaining_content}")
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
                except ImportError:
                    logging.info(f"💓 FFmpeg health check #{check_count}: Process alive (psutil not available for detailed stats)")
                except Exception as e:
                    logging.warning(f"💓 FFmpeg health check #{check_count}: Error getting process stats: {e}")
            
            # Process has exited
            exit_code = self.ffmpeg_process.returncode
            elapsed_time = time.time() - start_time
            logging.info(f"💓 FFmpeg health monitor: Process exited with code {exit_code} after {check_count} health checks")
            logging.info(f"💓 Total runtime: {elapsed_time:.1f}s (limit was {self.duration_seconds}s)")
            
            # Check if FFmpeg reached its duration limit
            if abs(elapsed_time - self.duration_seconds) < 5.0:  # Within 5 seconds of limit
                logging.info(f"💓 FFmpeg likely exited due to reaching duration limit ({self.duration_seconds}s)")
            
            # Provide interpretation of common exit codes
            if exit_code == 0:
                logging.info("💓 Exit code 0: Normal termination")
            elif exit_code == 1:
                logging.warning("💓 Exit code 1: Generic error (check FFmpeg stderr for details)")
            elif exit_code == -9:
                logging.error("💓 Exit code -9: Process was killed (SIGKILL)")
            elif exit_code == -15:
                logging.warning("💓 Exit code -15: Process was terminated (SIGTERM)")
            else:
                logging.warning(f"💓 Exit code {exit_code}: Check FFmpeg documentation for details")
                
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
        
        if self.yt_dlp_process:
            try:
                self.yt_dlp_process.terminate()
                self.yt_dlp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.yt_dlp_process.kill()
            except Exception as e:
                logging.error(f"Error terminating yt-dlp: {e}")

async def send_request(ws, request: TranslateRequestData):
    """Send request to WebSocket server"""
    request_data = TranslateRequest()
    request_data.request_meta.SessionID = request.session_id
    if request.event == "Type_StartSession":
        request_data.event = Type.StartSession
    elif request.event == "Type_TaskRequest":
        request_data.event = Type.TaskRequest
    elif request.event == "Type_FinishSession":
        request_data.event = Type.FinishSession
    request_data.user.uid = "ast_py_youtube_client"
    request_data.user.did = "ast_py_youtube_client"
    request_data.source_audio.format = "wav"
    request_data.source_audio.rate = 16000
    request_data.source_audio.bits = 16
    request_data.source_audio.channel = 1
    if request.source_audio and request.source_audio.binary_data:
        request_data.source_audio.binary_data = request.source_audio.binary_data
    request_data.target_audio.format = "pcm"
    request_data.target_audio.rate = 16000
    request_data.target_audio.bits = 16
    request_data.target_audio.channel = 1
    request_data.request.mode = "s2s"
    request_data.request.source_language = "zh"
    request_data.request.target_language = "en"
    await ws.send(request_data.SerializeToString())

async def receive_message(ws) -> TranslateResponseData:
    """Receive and parse response from server"""
    response = await ws.recv()
    Response_data = TranslateResponse()
    Response_data.ParseFromString(response)
    return TranslateResponseData(
        event=Response_data.event,
        session_id=Response_data.response_meta.SessionID,
        sequence=Response_data.response_meta.Sequence,
        text=Response_data.text,
        data=Response_data.data,
        message=Response_data.response_meta.Message,
        start_time=Response_data.start_time if hasattr(Response_data, 'start_time') else None,
        end_time=Response_data.end_time if hasattr(Response_data, 'end_time') else None
    )

def map_event_to_subtitle_json(resp: TranslateResponseData) -> Optional[str]:
    """Map WebSocket events (650-655) to unified JSON format"""
    subtitle_msg = None
    
    # Source subtitle events (650-652)
    if resp.event == Type.SourceSubtitleStart:
        subtitle_msg = SubtitleMessage(
            lane="source",
            phase="start",
            start_time=resp.start_time,
            final=False
        )
    elif resp.event == Type.SourceSubtitleResponse:
        subtitle_msg = SubtitleMessage(
            lane="source", 
            phase="delta",
            text=resp.text,
            final=False
        )
    elif resp.event == Type.SourceSubtitleEnd:
        subtitle_msg = SubtitleMessage(
            lane="source",
            phase="end", 
            text=resp.text,
            start_time=resp.start_time,
            end_time=resp.end_time,
            final=True
        )
    # Translation subtitle events (653-655)
    elif resp.event == Type.TranslationSubtitleStart:
        subtitle_msg = SubtitleMessage(
            lane="translation",
            phase="start",
            start_time=resp.start_time,
            final=False
        )
    elif resp.event == Type.TranslationSubtitleResponse:
        subtitle_msg = SubtitleMessage(
            lane="translation",
            phase="delta",
            text=resp.text,
            final=False
        )
    elif resp.event == Type.TranslationSubtitleEnd:
        subtitle_msg = SubtitleMessage(
            lane="translation",
            phase="end",
            text=resp.text,
            start_time=resp.start_time,
            end_time=resp.end_time,
            final=True
        )
    
    if subtitle_msg:
        # Convert to JSON, filtering out None values
        subtitle_dict = {
            "type": subtitle_msg.type,
            "lane": subtitle_msg.lane,
            "phase": subtitle_msg.phase,
            "final": subtitle_msg.final
        }
        
        if subtitle_msg.text is not None:
            subtitle_dict["text"] = subtitle_msg.text
        if subtitle_msg.start_time is not None:
            subtitle_dict["start_time"] = subtitle_msg.start_time
        if subtitle_msg.end_time is not None:
            subtitle_dict["end_time"] = subtitle_msg.end_time
            
        return json.dumps(subtitle_dict, ensure_ascii=False)
    
    return None

async def build_http_headers(conf: Config, conn_id: str) -> Headers:
    """Build WebSocket connection headers from config"""
    headers = Headers({
        "X-Api-App-Key": conf.app_key,
        "X-Api-Access-Key": conf.access_key,
        "X-Api-Resource-Id": conf.resource_id,
        "X-Api-Connect-Id": conn_id
    })
    return headers

async def read_pcm_chunks(pcm_stream, chunk_size: int = 640, ffmpeg_process=None):
    """Read PCM data in chunks (640 bytes = 20ms at 16kHz mono s16le)"""
    import asyncio
    loop = asyncio.get_event_loop()
    chunk_count = 0
    
    logging.info(f"Starting PCM chunk reading, chunk_size: {chunk_size}")
    
    while True:
        try:
            # Check FFmpeg process health before reading
            if ffmpeg_process and ffmpeg_process.poll() is not None:
                # FFmpeg process has terminated
                logging.error(f"🚫 FFmpeg process terminated during chunk {chunk_count + 1} read")
                logging.error(f"🚫 FFmpeg exit code: {ffmpeg_process.returncode}")
                logging.error(f"🚫 Check FFmpeg console log file for error details")
                break
            
            # Use run_in_executor to make blocking read non-blocking with timeout
            logging.debug(f"Attempting to read PCM chunk {chunk_count + 1}...")
            
            # Add timeout to detect if ffmpeg is stuck
            try:
                # Use much longer timeout for first chunk to skip through ad segments
                timeout_duration = 12.0 if chunk_count == 0 else 10.0
                chunk = await asyncio.wait_for(
                    loop.run_in_executor(None, pcm_stream.read, chunk_size),
                    timeout=timeout_duration
                )
            except asyncio.TimeoutError:
                # Check FFmpeg process status on timeout
                if ffmpeg_process:
                    if ffmpeg_process.poll() is not None:
                        logging.error(f"⏰ Timeout reading chunk {chunk_count + 1}: FFmpeg process exited (code: {ffmpeg_process.returncode})")
                        logging.error(f"⏰ Check FFmpeg console log file for error details")
                    else:
                        logging.error(f"⏰ Timeout reading chunk {chunk_count + 1}: FFmpeg still running (PID: {ffmpeg_process.pid})")
                        logging.error(f"⏰ This suggests the stream ended or FFmpeg is blocked")
                else:
                    logging.error(f"⏰ Timeout reading chunk {chunk_count + 1}: No FFmpeg process reference")
                
                if chunk_count == 0:
                    logging.error("🔴 Timeout waiting for first PCM chunk - ffmpeg may be stuck or stream unavailable")
                else:
                    logging.error(f"🔴 Timeout reading PCM chunk {chunk_count + 1} - stream may have ended")
                break
            
            if not chunk:
                logging.info(f"📄 PCM stream ended naturally after {chunk_count} chunks")
                # Check if FFmpeg is still running when stream ends
                if ffmpeg_process and ffmpeg_process.poll() is None:
                    logging.info(f"✅ FFmpeg still running (PID: {ffmpeg_process.pid}) when stream ended")
                elif ffmpeg_process:
                    logging.info(f"⚠️ FFmpeg exited (code: {ffmpeg_process.returncode}) when stream ended")
                break
                
            chunk_count += 1
            if chunk_count == 1:
                logging.info(f"SUCCESS: First PCM chunk received! {len(chunk)} bytes")
            elif chunk_count % 50 == 0:
                logging.info(f"Successfully read PCM chunk {chunk_count}: {len(chunk)} bytes")
                # Periodic FFmpeg health check
                if ffmpeg_process and ffmpeg_process.poll() is not None:
                    logging.warning(f"⚠️ FFmpeg process died during streaming at chunk {chunk_count}")
            else:
                logging.debug(f"Successfully read PCM chunk {chunk_count}: {len(chunk)} bytes")
            
            yield chunk
            
        except Exception as e:
            logging.error(f"❌ Error reading PCM chunk {chunk_count}: {e}")
            import traceback
            logging.error(f"❌ PCM read traceback: {traceback.format_exc()}")
            
            # Check FFmpeg status on error
            if ffmpeg_process:
                if ffmpeg_process.poll() is not None:
                    logging.error(f"❌ FFmpeg process status on error: exited with code {ffmpeg_process.returncode}")
                    logging.error(f"❌ Check FFmpeg console log file for error details")
                else:
                    logging.error(f"❌ FFmpeg process status on error: still running (PID: {ffmpeg_process.pid})")
            break
    
    logging.info(f"📊 PCM chunk reading completed, total chunks: {chunk_count}")
    if ffmpeg_process:
        if ffmpeg_process.poll() is not None:
            logging.info(f"📊 Final FFmpeg status: exited with code {ffmpeg_process.returncode}")
        else:
            logging.info(f"📊 Final FFmpeg status: still running (PID: {ffmpeg_process.pid})")

async def translate_youtube_live_stream(conf: Config, youtube_url: str, duration_seconds: int = None):
    """Generator function that yields translated audio chunks from YouTube live stream"""
    streamer = YouTubeLiveStreamer(youtube_url, duration_seconds or 3600)  # Default 1 hour
    
    # 初始化事件日志记录器
    event_logger = ASTEventLogger(youtube_url)
    
    try:
        # Start streaming pipeline
        pcm_stream = await streamer.start_streaming_pipeline()
        
        # Connect to WebSocket server
        conn_id = str(uuid.uuid4())
        headers = await build_http_headers(conf, conn_id)
        
        conn = await websockets.connect(
            conf.ws_url,
            additional_headers=headers,
            max_size=1000000000,
            ping_interval=None
        )
        
        logging.info(f"Connected to translation server (log id={conn.response.headers.get('X-Tt-Logid')})")
        log_id = conn.response.headers.get('X-Tt-Logid')
        
        session_id = str(uuid.uuid4())
        
        # Start session
        start_request = TranslateRequestData(
            session_id=session_id,
            event="Type_StartSession",
            source_audio=Audio(format="wav", rate=16000, bits=16, channel=1),
            target_audio=Audio(format="pcm", rate=16000, bits=16, channel=1),
            mode="s2s",
            source_language="zh",
            target_language="en"
        )
        
        # 记录发送StartSession事件
        event_logger.log_send_event(Type.StartSession, start_request)
        
        await send_request(conn, start_request)
        resp = await receive_message(conn)
        
        # 记录接收到的SessionStarted事件
        if resp.event == Type.SessionStarted:
            event_logger.log_receive_event(resp)
        
        if resp.event != Type.SessionStarted:
            logging.error(f"Unexpected response logid: {log_id}")
            logging.error(f"Unexpected response: {resp.event}")
            logging.error(f"Unexpected response message: {resp.message}")
            await conn.close()
            return
        
        logging.info(f"Translation session (ID={session_id}) started.")
        
        # Create queues for communication between sender and receiver
        stream_queue = asyncio.Queue()  # Queue for both audio and subtitle data
        finished = asyncio.Event()
        
        async def send_pcm_chunks():
            chunk_count = 0
            total_bytes = 0
            try:
                logging.info("Starting to read PCM chunks from ffmpeg...")
                
                # Check if ffmpeg process is still running
                if streamer.ffmpeg_process.poll() is not None:
                    logging.error(f"FFmpeg process has exited with code: {streamer.ffmpeg_process.returncode}")
                    logging.error(f"Check FFmpeg console log file for error details")
                    finished.set()
                    return
                
                async for chunk in read_pcm_chunks(pcm_stream, ffmpeg_process=streamer.ffmpeg_process):
                    if not chunk:
                        logging.info("No more PCM chunks available")
                        break
                    
                    chunk_count += 1
                    total_bytes += len(chunk)
                    
                    # Log every 50 chunks (about 1 second of audio)
                    if chunk_count % 50 == 0:
                        logging.info(f"Sent {chunk_count} PCM chunks, {total_bytes} total bytes")
                    else:
                        logging.debug(f"Sending PCM chunk {chunk_count}: {len(chunk)} bytes")
                    
                    chunk_request = TranslateRequestData(
                        session_id=session_id,
                        event="Type_TaskRequest",
                        source_audio=Audio(binary_data=chunk)
                    )
                    
                    # 记录TaskRequest事件（只记录第一个和每50个chunk以避免日志过多）
                    if chunk_count == 1 or chunk_count % 50 == 0:
                        event_logger.log_send_event(Type.TaskRequest, chunk_request)
                    
                    await send_request(conn, chunk_request)
                    await asyncio.sleep(0.02)  # 20ms delay to match chunk rate
                
                logging.info(f"Finished sending {chunk_count} PCM chunks, total {total_bytes} bytes")
                
                # Send finish session
                finish_request = TranslateRequestData(
                    session_id=session_id,
                    event="Type_FinishSession",
                    source_audio=Audio()
                )
                
                # 记录发送FinishSession事件
                event_logger.log_send_event(Type.FinishSession, finish_request)
                
                await send_request(conn, finish_request)
                logging.info("FinishSession request sent.")
                
            except Exception as e:
                logging.error(f"Error sending PCM chunks: {e}")
                import traceback
                logging.error(f"Send chunks traceback: {traceback.format_exc()}")
                finished.set()
        
        async def receive_responses():
            try:
                while not finished.is_set():
                    resp = await receive_message(conn)
                    
                    # 记录接收到的事件
                    event_logger.log_receive_event(resp)
                    
                    logging.debug(
                        f"Received message (event={resp.event}, session_id={resp.session_id}): "
                        f"seq: {resp.sequence}, text: '{resp.text}', audio data length: {len(resp.data)}"
                    )
                    
                    if resp.event == Type.SessionFailed or resp.event == Type.SessionCanceled:
                        logging.error(f"Session failed, message: {resp.message} logid: {log_id}")
                        finished.set()
                        break
                    
                    if resp.event == Type.SessionFinished:
                        logging.info("Translation session finished")
                        finished.set()
                        break
                    
                    # Handle subtitle events (650-655)
                    subtitle_json = map_event_to_subtitle_json(resp)
                    if subtitle_json:
                        await stream_queue.put(StreamData(data_type="subtitle", content=subtitle_json))
                        logging.debug(f"Queued subtitle: {subtitle_json}")
                    
                    # Handle TTS audio data
                    if resp.data:
                        await stream_queue.put(StreamData(data_type="audio", content=resp.data))
                        
            except Exception as e:
                logging.error(f"Receive message error: {e}")
                finished.set()
        
        # Start sender and receiver tasks
        sender_task = asyncio.create_task(send_pcm_chunks())
        receiver_task = asyncio.create_task(receive_responses())
        
        # Yield stream data (audio and subtitles) as they arrive
        try:
            while not finished.is_set():
                try:
                    # Wait for stream data with timeout
                    stream_data = await asyncio.wait_for(stream_queue.get(), timeout=1.0)
                    yield stream_data
                except asyncio.TimeoutError:
                    continue
        finally:
            finished.set()
            await sender_task
            await receiver_task
            await conn.close()
            
    except Exception as e:
        logging.error(f"Translation streaming error: {e}")
    finally:
        await streamer.cleanup()

async def translate_youtube_live(conf: Config, youtube_url: str, duration_seconds: int = 10, out_dir: str = "output"):
    """Main translation function for YouTube live stream (backward compatibility)"""
    streamer = YouTubeLiveStreamer(youtube_url, duration_seconds)
    
    try:
        # Start streaming pipeline
        pcm_stream = await streamer.start_streaming_pipeline()
        
        # Connect to WebSocket server
        conn_id = str(uuid.uuid4())
        headers = await build_http_headers(conf, conn_id)
        
        conn = await websockets.connect(
            conf.ws_url,
            additional_headers=headers,
            max_size=1000000000,
            ping_interval=None
        )
        
        logging.info(f"Connected to server (log id={conn.response.headers.get('X-Tt-Logid')})")
        log_id = conn.response.headers.get('X-Tt-Logid')
        
        session_id = str(uuid.uuid4())
        
        # Start session
        start_request = TranslateRequestData(
            session_id=session_id,
            event="Type_StartSession",
            source_audio=Audio(format="wav", rate=16000, bits=16, channel=1),
            target_audio=Audio(format="pcm", rate=16000, bits=16, channel=1),
            mode="s2s",
            source_language="zh",
            target_language="en"
        )
        
        await send_request(conn, start_request)
        resp = await receive_message(conn)
        if resp.event != Type.SessionStarted:
            logging.error(f"Unexpected response logid: {log_id}")
            logging.error(f"Unexpected response: {resp.event}")
            logging.error(f"Unexpected response message: {resp.message}")
            await conn.close()
            return
        
        logging.info(f"Session (ID={session_id}) started.")
        
        # Send PCM chunks and receive responses
        recv_audio = bytearray()
        recv_text = []
        chunk_count = 0
        
        async def send_pcm_chunks():
            nonlocal chunk_count
            try:
                logging.info("Starting to read PCM chunks from ffmpeg...")
                async for chunk in read_pcm_chunks(pcm_stream, ffmpeg_process=streamer.ffmpeg_process):
                    if not chunk:
                        logging.info("No more PCM chunks available")
                        break
                    
                    chunk_count += 1
                    logging.info(f"Sending PCM chunk {chunk_count}: {len(chunk)} bytes")
                    
                    chunk_request = TranslateRequestData(
                        session_id=session_id,
                        event="Type_TaskRequest",
                        source_audio=Audio(binary_data=chunk)
                    )
                    await send_request(conn, chunk_request)
                    await asyncio.sleep(0.02)  # 20ms delay to match chunk rate
                
                logging.info(f"Finished sending {chunk_count} PCM chunks")
                
                # Send finish session
                finish_request = TranslateRequestData(
                    session_id=session_id,
                    event="Type_FinishSession",
                    source_audio=Audio()
                )
                await send_request(conn, finish_request)
                logging.info("FinishSession request sent.")
                
            except Exception as e:
                logging.error(f"Error sending PCM chunks: {e}")
                import traceback
                logging.error(traceback.format_exc())
        
        # Start sender task
        sender_task = asyncio.create_task(send_pcm_chunks())
        
        # Receive responses
        try:
            while True:
                resp = await receive_message(conn)
                
                logging.info(
                    f"Received message (event={resp.event}, session_id={resp.session_id}): "
                    f"seq: {resp.sequence}, text: '{resp.text}', audio data length: {len(resp.data)}"
                )
                
                if resp.event == Type.SessionFailed or resp.event == Type.SessionCanceled:
                    logging.error(f"Session failed, message: {resp.message} logid: {log_id}")
                    break
                
                if resp.event == Type.SessionFinished:
                    break
                
                recv_audio.extend(resp.data)
                if resp.text:
                    recv_text.append(resp.text)
                    
        except Exception as e:
            logging.error(f"Receive message error: {e}")
        finally:
            await sender_task
            await conn.close()
        
        # Save results
        if recv_audio:
            os.makedirs(out_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%dT%H%M%SZ")
            output_path = Path(out_dir) / f"youtube_translate_{timestamp}.opus"
            try:
                with open(output_path, 'wb') as f:
                    f.write(recv_audio)
                logging.info(f"Session finished, audio saved as: {output_path}")
                logging.info(f"Session finished, text: {' '.join(recv_text)}")
                logging.info(f"Total PCM chunks sent: {chunk_count}")
            except Exception as e:
                logging.error(f"Save audio file: {e}")
        else:
            logging.error("Session finished, no audio data received.")
            
    except Exception as e:
        logging.error(f"Translation error: {e}")
    finally:
        await streamer.cleanup()

async def main():
    """Main function"""
    if not all([APP_KEY, ACCESS_KEY, RESOURCE_ID, WS_URL]):
        logging.error("Missing required environment variables. Please check your .env file.")
        return
    
    conf = Config(
        ws_url=WS_URL,
        app_key=APP_KEY,
        access_key=ACCESS_KEY,
        resource_id=RESOURCE_ID
    )
    
    youtube_url = "https://www.youtube.com/watch?v=HHGEDLPBIxA"
    duration_seconds = 100  # Test with 10 seconds
    
    logging.info(f"Starting YouTube live translation for {duration_seconds} seconds")
    logging.info(f"YouTube URL: {youtube_url}")
    
    start_time = time.time()
    await translate_youtube_live(conf, youtube_url, duration_seconds)
    end_time = time.time()
    
    logging.info(f"Total processing time: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
