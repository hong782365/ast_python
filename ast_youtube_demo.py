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
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union
import websockets
from websockets import Headers
from dotenv import load_dotenv
import yt_dlp
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

APP_KEY = os.getenv("APP_KEY")
ACCESS_KEY = os.getenv("ACCESS_KEY")
RESOURCE_ID = os.getenv("RESOURCE_ID")
WS_URL = os.getenv("WS_URL")

SOURCE_LANGUAGE="en"
TARGET_LANGUAGE="zh"

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
    status_code: Optional[int] = None
    billing: Optional["BillingData"] = None

@dataclass
class BillingItemData:
    unit: Optional[str] = None
    quantity: Optional[float] = None

@dataclass
class BillingData:
    items: List[BillingItemData] = field(default_factory=list)
    duration_msec: Optional[int] = None
    word_count: Optional[int] = None

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
                
        elif event_type == Type.UsageResponse:
            # 计量计费
            if response_data.status_code is not None:
                json_data["status_code"] = response_data.status_code
            if response_data.message:
                json_data["message"] = response_data.message
            if response_data.billing is not None:
                billing_data = {}
                if response_data.billing.items:
                    billing_data["items"] = [
                        {"unit": item.unit, "quantity": item.quantity}
                        for item in response_data.billing.items
                        if item.unit is not None or item.quantity is not None
                    ]
                if response_data.billing.duration_msec is not None:
                    billing_data["duration_msec"] = response_data.billing.duration_msec
                if response_data.billing.word_count is not None:
                    billing_data["word_count"] = response_data.billing.word_count
                if billing_data:
                    json_data["billing"] = billing_data
        
        # 写入日志文件
        log_entry = f"{timestamp} ==>> {description}: {json.dumps(json_data, ensure_ascii=False)}\n"
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

# 1) 自定义 logger：把 yt-dlp 的 debug/info/warning/error 写进你的日志系统
class YtdlpLogger:
    def __init__(self, name="ytdlp", logfile="youtube/logs/yt-dlp-debug.log"):
        import logging, os
        self._log = logging.getLogger(name)
        if not self._log.handlers:
            # 确保日志目录存在
            log_dir = os.path.dirname(logfile)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
                
            fh = logging.FileHandler(logfile, encoding="utf-8")
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            fh.setFormatter(fmt)
            self._log.addHandler(fh)
            self._log.setLevel(logging.DEBUG)
        self._ts = time.time()

    def _stamp(self, level, msg):
        now = time.time()
        self._log.log(level, f"[+{now - self._ts:.3f}s] {msg}")

    def debug(self, msg):   self._stamp(10, str(msg))  # DEBUG
    def info(self, msg):    self._stamp(20, str(msg))  # INFO
    def warning(self, msg): self._stamp(30, str(msg))  # WARNING
    def error(self, msg):   self._stamp(40, str(msg))  # ERROR

class YtDlpManager:
    """常驻yt-dlp解析器管理器，提供预热和高效的URL提取"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytdlp")
        self.ydl_opts = {
            'quiet': True,  # 减少输出
            'no_warnings': True,
            # 'verbose': True,
            # 'format': '234/233/140/bestaudio[ext=m4a]/bestaudio',  # 音频优先级
            'format': 'bestaudio[protocol^=m3u8]/bestaudio/140/91/92/93/94/95/96/best', # '234/233/140/bestaudio[ext=m4a]/bestaudio',  # 音频优先级
            # "extractor_args": {  # 目前这个参数不报错了, 但还没验证其效果, 暂时先注释了.
            #     "youtube": {
            #         "player_client": ["ios", "web"],
            #         "player_skip": ["webpage"]
            #     }
            # },
            'forcejson': False,
            'extract_flat': False,
            'writethumbnail': False,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': False,
        }
        self._ydl = None
        self._warmed_up = False
        self.warmup_url = "https://www.youtube.com/watch?v=G3_Um0yIsow"  # 公共预热视频: 3 秒倒计时(纯人声)
        
    def _create_ydl_instance(self):
        """创建yt-dlp实例"""
        if self._ydl is None:
            logger = YtdlpLogger()
            # 添加代理配置
            opts = self.ydl_opts.copy()
            # opts['proxy'] = 'http://127.0.0.1:7897'
            # 添加cookie支持 - 从文件读取
            cookie_file = os.path.join(current_dir, "youtube", "cookie", "youtube_hongc_cookies.txt")
            if os.path.exists(cookie_file):
                opts['cookiefile'] = cookie_file
                logging.info(f"🍪 Loading cookies from: {cookie_file}")
            else:
                logging.warning(f"🍪 Cookie file not found: {cookie_file}")
            # 强制IPv4
            opts['forceipv4'] = True

            opts['logger'] = logger
            
            self._ydl = yt_dlp.YoutubeDL(opts)
        return self._ydl
            
    async def warmup(self):
        """预热yt-dlp实例，预编译JS和缓存设置"""
        if self._warmed_up:
            logging.info("🔥 yt-dlp already warmed up, skipping...")
            return
            
        logging.info("🔥 Starting yt-dlp warmup with public video...")
        warmup_start_time = time.time()
        
        try:
            # 在线程池中运行yt-dlp预热
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor, self._warmup_sync)
            
            warmup_elapsed = time.time() - warmup_start_time
            logging.info(f"🔥 yt-dlp warmup completed in {warmup_elapsed:.2f}s")
            self._warmed_up = True
            
        except Exception as e:
            logging.warning(f"🔥 yt-dlp warmup failed (will continue anyway): {e}")
            # 即使预热失败也继续，不影响主流程
            self._warmed_up = True
    
    def _warmup_sync(self):
        """同步预热方法，在线程池中执行"""
        try:
            ydl = self._create_ydl_instance()
            # 只验证yt-dlp实例创建和基本配置，不实际提取视频
            # 这样可以预热库本身而无需网络访问
            logging.info(f"🔥 yt-dlp instance created successfully")
            logging.info(f"🔥 Warmup options: {ydl.params}")
            
            # 使用轻量级的URL提取进行网络预热
            try:
                # 仅提取基本信息和URL，不下载
                info = ydl.extract_info(self.warmup_url, download=False, process=True)
                
                # 检查是否成功获取到格式信息
                formats = info.get('formats', [])
                if formats:
                    # 查找最佳音频格式的URL（类似于--get-url功能）
                    audio_formats = [f for f in formats if f.get('acodec') != 'none']
                    if audio_formats:
                        best_url = audio_formats[0].get('url', '')
                        logging.info(f"🔥 Network warmup successful - extracted URL (length: {len(best_url)})")
                        logging.info(f"🔥 Video title: {info.get('title', 'Unknown')[:50]}...")
                    else:
                        logging.info(f"🔥 Partial warmup - no audio formats found")
                else:
                    logging.info(f"🔥 Partial warmup - no formats extracted")
                    
            except Exception as net_e:
                logging.info(f"🔥 Network warmup skipped (network issue): {net_e}")
                # 网络预热失败不影响整体预热成功
                
        except Exception as e:
            logging.warning(f"🔥 Warmup failed: {e}")
            raise
    
    async def extract_stream_url(self, youtube_url: str) -> str:
        """异步提取YouTube直播流URL"""
        logging.info("📡 Extracting stream URL with yt-dlp library...")
        extract_start_time = time.time()
        
        try:
            # 在线程池中运行yt-dlp以避免阻塞事件循环
            loop = asyncio.get_event_loop()
            stream_url = await loop.run_in_executor(
                self.executor, 
                self._extract_stream_url_sync, 
                youtube_url
            )
            
            extract_elapsed = time.time() - extract_start_time
            logging.info(f"📡 Stream URL extracted in {extract_elapsed:.2f}s")
            logging.info(f"📡 Stream URL: {stream_url}")
            
            return stream_url
            
        except Exception as e:
            logging.error(f"📡 Failed to extract stream URL: {e}")
            raise
    
    def _extract_stream_url_sync(self, youtube_url: str) -> str:
        """同步提取URL方法，在线程池中执行"""
        try:
            ydl = self._create_ydl_instance()
            info = ydl.extract_info(youtube_url, download=False)
            
            # 查找最佳音频格式的URL
            formats = info.get('formats', [])
            if not formats:
                raise ValueError("No formats found for this video")
            
            # 按照优先级查找音频流
            audio_formats = [f for f in formats if f.get('acodec') != 'none']
            if not audio_formats:
                raise ValueError("No audio formats found for this video")
            
            # 优先选择format_id为234/233/140的格式
            preferred_ids = ['234', '233', '140']
            for format_id in preferred_ids:
                for fmt in audio_formats:
                    if fmt.get('format_id') == format_id:
                        return fmt['url']
            
            # 如果没找到首选格式，使用第一个可用的音频格式
            return audio_formats[0]['url']
            
        except Exception as e:
            logging.error(f"📡 Sync URL extraction failed: {e}")
            raise
    
    def cleanup(self):
        """清理资源"""
        if self.executor:
            self.executor.shutdown(wait=True)
        if self._ydl:
            # yt-dlp实例通常不需要显式清理
            self._ydl = None

def get_ffmpeg_path():
    """Detect FFmpeg path based on environment"""
    # Production paths (Cloudflare/Docker)
    production_paths = [
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
        "/app/ffmpeg",
        "/opt/ffmpeg/bin/ffmpeg"
    ]
    
    # Local development path (macOS with Homebrew)
    local_path = "/opt/homebrew/Caskroom/miniforge/base/bin/ffmpeg"
    
    # First try local development path
    if os.path.exists(local_path):
        return local_path
    
    # Then try production paths
    for path in production_paths:
        if os.path.exists(path):
            return path
    
    # Finally, try to find ffmpeg in PATH
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path
    
    # If nothing found, raise an error
    raise FileNotFoundError("FFmpeg not found. Please install FFmpeg or set the correct path.")

# 全局yt-dlp管理器实例
ytdlp_manager = YtDlpManager()

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
        """Start yt-dlp (library mode) + ffmpeg (direct network pull) pipeline for PCM streaming"""
        timestamp = time.strftime("%Y%m%dT%H%M%SZ")
        
        # Create ffmpeg log file paths
        ffmpeg_report_log = self.ffmpeg_report_dir / f"ffmpeg-report-{timestamp}-{self.youtube_url_id}.log"
        ffmpeg_console_log = self.ffmpeg_log_dir / f"ffmpeg-console-{timestamp}-{self.youtube_url_id}.log"
        
        try:
            # Step 1: Use yt-dlp library to extract direct stream URL
            direct_url = await ytdlp_manager.extract_stream_url(self.youtube_url)
            
            # Step 2: Use ffmpeg to directly pull from network with reconnect parameters
            ffmpeg_cmd = [
                get_ffmpeg_path(),  # ffmpeg 主程序
                "-hide_banner",  # 隐藏 ffmpeg 启动横幅信息
                "-report",  # 它会生成一个详细的报告文件，完整记录 FFmpeg 的所有命令行输出（无论你在 -loglevel 设置了什么级别）、运行环境、库版本等信息。当你的 Python 脚本无法完全捕获实时输出时，这个报告文件就是你最终的真相来源。
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
                "-t", str(self.duration_seconds),  # 限制处理时长（秒）
                "-y",  # 覆盖输出文件（如果存在）
                "pipe:1"  # 输出到 stdout 标准输出（管道）
            ]
            
            # Start ffmpeg process directly with network stream
            logging.info("Starting ffmpeg with direct network stream...")
            logging.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
            logging.info(f"FFmpeg report log: {ffmpeg_report_log}")
            logging.info(f"FFmpeg console log: {ffmpeg_console_log}")
            
            # Set up environment for ffmpeg report output
            ffmpeg_start_time = time.time()
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
            
            # Store the spawn timestamp for later timing calculation
            self.ffmpeg_spawn_time = time.monotonic()
            
            # Basic process health check (don't wait for stream readiness)
            await asyncio.sleep(0.1)  # Very short wait just to detect immediate failures
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
            
            logging.info(f"FFmpeg process spawned successfully (PID: {self.ffmpeg_process.pid})")
            
            # Start a background task to monitor ffmpeg console log
            stderr_monitor_task = asyncio.create_task(self._monitor_ffmpeg_stderr(ffmpeg_console_log))
            
            # Start a background task to monitor ffmpeg health
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
        
        # No need to clean up yt_dlp_process since we're using library mode now

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
    request_data.request.source_language = SOURCE_LANGUAGE
    request_data.request.target_language = TARGET_LANGUAGE
    await ws.send(request_data.SerializeToString())

async def receive_message(ws) -> TranslateResponseData:
    """Receive and parse response from server"""
    response = await ws.recv()
    Response_data = TranslateResponse()
    Response_data.ParseFromString(response)
    # Parse billing information if present
    status_code_value: Optional[int] = None
    billing_value: Optional[BillingData] = None
    try:
        status_code_value = Response_data.response_meta.StatusCode
    except Exception:
        status_code_value = None
    try:
        meta_billing = Response_data.response_meta.Billing
        # Build BillingData regardless; it will be empty if not set
        items_list: List[BillingItemData] = []
        try:
            for item in getattr(meta_billing, 'Items', []):
                items_list.append(BillingItemData(
                    unit=getattr(item, 'Unit', None),
                    quantity=getattr(item, 'Quantity', None)
                ))
        except Exception:
            items_list = []
        billing_value = BillingData(
            items=items_list,
            duration_msec=getattr(meta_billing, 'DurationMsec', None),
            word_count=getattr(meta_billing, 'WordCount', None)
        )
        # If nothing meaningful was set, keep it as None
        if not billing_value.items and billing_value.duration_msec in (None, 0) and billing_value.word_count in (None, 0):
            billing_value = None
    except Exception:
        billing_value = None

    return TranslateResponseData(
        event=Response_data.event,
        session_id=Response_data.response_meta.SessionID,
        sequence=Response_data.response_meta.Sequence,
        text=Response_data.text,
        data=Response_data.data,
        message=Response_data.response_meta.Message,
        start_time=Response_data.start_time if hasattr(Response_data, 'start_time') else None,
        end_time=Response_data.end_time if hasattr(Response_data, 'end_time') else None,
        status_code=status_code_value,
        billing=billing_value
    )

async def send_silence_until_ready(conn, session_id, audio_ready_event, timeout_seconds=8):
    """Send silence frames until real audio is ready or timeout"""
    silence_chunk = b'\x00' * 640  # 640 bytes of silence (20ms at 16kHz mono s16le)
    silence_start_time = time.monotonic()
    frame_count = 0
    
    logging.info(f"🔇 Starting silence bridge (timeout: {timeout_seconds}s)")
    
    try:
        while not audio_ready_event.is_set():
            # Check timeout
            elapsed = time.monotonic() - silence_start_time
            if elapsed >= timeout_seconds:
                logging.warning(f"🔇 Silence bridge timeout after {elapsed:.2f}s, {frame_count} frames sent")
                break
            
            # Send silence frame
            chunk_request = TranslateRequestData(
                session_id=session_id,
                event="Type_TaskRequest",
                source_audio=Audio(binary_data=silence_chunk)
            )
            
            await send_request(conn, chunk_request)
            frame_count += 1
            
            # Log every 50 frames (1 second)
            if frame_count % 50 == 0:
                logging.info(f"🔇 Silence bridge: {frame_count} frames sent ({elapsed:.1f}s)")
            
            # Wait 20ms for next frame
            await asyncio.sleep(0.02)
        
        # Audio is ready
        silence_duration = time.monotonic() - silence_start_time
        if audio_ready_event.is_set():
            logging.info(f"🔇 Silence bridge completed: {frame_count} frames sent in {silence_duration:.2f}s")
        return silence_duration, frame_count
        
    except Exception as e:
        silence_duration = time.monotonic() - silence_start_time
        logging.error(f"🔇 Silence bridge error after {silence_duration:.2f}s: {e}")
        import traceback
        logging.error(f"🔇 Silence bridge traceback: {traceback.format_exc()}")
        return silence_duration, frame_count

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

async def connect_websocket_and_start_session(conf: Config, source_language: str, target_language: str, event_logger=None):
    """Connect to WebSocket and start translation session"""
    ws_start_time = time.monotonic()
    
    # Connect to WebSocket server
    conn_id = str(uuid.uuid4())
    headers = await build_http_headers(conf, conn_id)
    
    conn = await websockets.connect(
        conf.ws_url,
        additional_headers=headers,
        max_size=1000000000,
        ping_interval=None
    )
    
    ws_connect_duration = time.monotonic() - ws_start_time
    log_id = conn.response.headers.get('X-Tt-Logid')
    logging.info(f"Connected to translation server (log id={log_id}), 连接同声传译websocket耗时: {ws_connect_duration:.2f}s")
    
    session_id = str(uuid.uuid4())
    
    # Start session
    start_request = TranslateRequestData(
        session_id=session_id,
        event="Type_StartSession",
        source_audio=Audio(format="wav", rate=16000, bits=16, channel=1),
        target_audio=Audio(format="pcm", rate=16000, bits=16, channel=1),
        mode="s2s",
        source_language=source_language,
        target_language=target_language
    )
    
    # Log event if logger is provided
    if event_logger:
        event_logger.log_send_event(Type.StartSession, start_request)
    
    await send_request(conn, start_request)
    resp = await receive_message(conn)
    
    # Log received event if logger is provided
    if event_logger and resp.event == Type.SessionStarted:
        event_logger.log_receive_event(resp)
    
    if resp.event != Type.SessionStarted:
        logging.error(f"Unexpected response logid: {log_id}")
        logging.error(f"Unexpected response: {resp.event}")
        logging.error(f"Unexpected response message: {resp.message}")
        await conn.close()
        raise Exception(f"Failed to start session: {resp.message}")
    
    logging.info(f"Translation session (ID={session_id}) started.")
    
    return conn, session_id, log_id, ws_connect_duration

async def build_http_headers(conf: Config, conn_id: str) -> Headers:
    """Build WebSocket connection headers from config"""
    headers = Headers({
        "X-Api-App-Key": conf.app_key,
        "X-Api-Access-Key": conf.access_key,
        "X-Api-Resource-Id": conf.resource_id,
        "X-Api-Connect-Id": conn_id
    })
    return headers

async def read_pcm_chunks(pcm_stream, chunk_size: int = 640, ffmpeg_process=None, audio_ready_event=None, ffmpeg_spawn_time=None):
    """Read PCM data in chunks (640 bytes = 20ms at 16kHz mono s16le)"""
    import asyncio
    loop = asyncio.get_event_loop()
    chunk_count = 0
    first_chunk_received = False
    
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
                timeout_duration = 30.0 if chunk_count == 0 else 10.0
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
            
            # Handle first PCM chunk arrival
            if chunk_count == 1 and not first_chunk_received:
                first_chunk_received = True
                first_pcm_time = time.monotonic()
                
                # Calculate ffmpeg startup time if spawn time is available
                if ffmpeg_spawn_time is not None:
                    ffmpeg_startup_duration = first_pcm_time - ffmpeg_spawn_time
                    logging.info(f"SUCCESS: First PCM chunk received! {len(chunk)} bytes, ffmpeg启动耗时: {ffmpeg_startup_duration:.2f}s")
                else:
                    logging.info(f"SUCCESS: First PCM chunk received! {len(chunk)} bytes")
                
                # Signal that audio is ready
                if audio_ready_event:
                    audio_ready_event.set()
                    logging.info(f"🎵 Audio ready event signaled")
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
    
    # Create audio ready event for coordination
    audio_ready_event = asyncio.Event()
    
    try:
        # Start both tasks in parallel
        logging.info("🚀 Starting parallel initialization: ffmpeg + WebSocket...")
        parallel_start_time = time.monotonic()
        
        # Task 1: Start ffmpeg streaming pipeline
        ffmpeg_task = asyncio.create_task(streamer.start_streaming_pipeline())
        
        # Task 2: Connect WebSocket and start session
        websocket_task = asyncio.create_task(
            connect_websocket_and_start_session(conf, SOURCE_LANGUAGE, TARGET_LANGUAGE, event_logger)
        )
        
        # Wait for both to complete
        pcm_stream, (conn, session_id, log_id, ws_connect_duration) = await asyncio.gather(
            ffmpeg_task, websocket_task
        )
        
        parallel_duration = time.monotonic() - parallel_start_time
        logging.info(f"🚀 Parallel initialization completed in {parallel_duration:.2f}s")
        logging.info(f"📊 WebSocket connect duration: {ws_connect_duration:.2f}s")
        
        # Create queues for communication between sender and receiver
        stream_queue = asyncio.Queue()  # Queue for both audio and subtitle data
        finished = asyncio.Event()
        
        # Start silence bridge immediately
        silence_task = asyncio.create_task(
            send_silence_until_ready(conn, session_id, audio_ready_event, timeout_seconds=18)
        )
        
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
                
                async for chunk in read_pcm_chunks(
                    pcm_stream, 
                    ffmpeg_process=streamer.ffmpeg_process,
                    audio_ready_event=audio_ready_event,
                    ffmpeg_spawn_time=streamer.ffmpeg_spawn_time
                ):
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
                import traceback
                logging.error(f"Receive message traceback: {traceback.format_exc()}")
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
            
            # Wait for silence bridge to complete and log results
            try:
                silence_duration, silence_frames = await silence_task
                logging.info(f"🔇 Final silence bridge stats: {silence_frames} frames, {silence_duration:.2f}s")
            except Exception as e:
                logging.error(f"🔇 Silence bridge task error: {e}")
                import traceback
                logging.error(f"🔇 Silence bridge task traceback: {traceback.format_exc()}")
            
            await sender_task
            await receiver_task
            await conn.close()
            
    except Exception as e:
        logging.error(f"Translation streaming error: {e}")
        import traceback
        logging.error(f"Translation streaming traceback: {traceback.format_exc()}")
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
            source_language=SOURCE_LANGUAGE,
            target_language=TARGET_LANGUAGE
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
            import traceback
            logging.error(f"Receive message traceback: {traceback.format_exc()}")
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
        import traceback
        logging.error(f"Translation traceback: {traceback.format_exc()}")
    finally:
        await streamer.cleanup()

async def main():
    """Main function"""
    if not all([APP_KEY, ACCESS_KEY, RESOURCE_ID, WS_URL]):
        logging.error("Missing required environment variables. Please check your .env file.")
        return
    
    # 预热yt-dlp管理器
    logging.info("🚀 Initializing application...")
    init_start_time = time.time()
    
    try:
        await ytdlp_manager.warmup()
        init_elapsed_time = time.time() - init_start_time
        logging.info(f"🚀 Application initialization completed in {init_elapsed_time:.2f}s")
    except Exception as e:
        logging.warning(f"🚀 Application initialization failed (continuing anyway): {e}")
    
    conf = Config(
        ws_url=WS_URL,
        app_key=APP_KEY,
        access_key=ACCESS_KEY,
        resource_id=RESOURCE_ID
    )
    
    youtube_url = "https://www.youtube.com/watch?v=HHGEDLPBIxA"
    duration_seconds = 100  # Test with 100 seconds
    
    logging.info(f"Starting YouTube live translation for {duration_seconds} seconds")
    logging.info(f"YouTube URL: {youtube_url}")
    
    start_time = time.time()
    try:
        await translate_youtube_live(conf, youtube_url, duration_seconds)
    finally:
        # 清理资源
        ytdlp_manager.cleanup()
        
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
        import traceback
        logging.error(f"Unexpected error traceback: {traceback.format_exc()}")
