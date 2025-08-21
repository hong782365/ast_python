import asyncio
import uuid
import os
import subprocess
import signal
import sys
import time
import logging
import json
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

class YouTubeLiveStreamer:
    def __init__(self, youtube_url: str, duration_seconds: int = 10):
        self.youtube_url = youtube_url
        self.duration_seconds = duration_seconds
        self.yt_dlp_process = None
        self.ffmpeg_process = None
        self.log_dir = Path(current_dir) / "youtube" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
    async def start_streaming_pipeline(self):
        """Start yt-dlp (extract URL) + ffmpeg (direct network pull) pipeline for PCM streaming"""
        timestamp = time.strftime("%Y%m%dT%H%M%SZ")
        yt_dlp_log = self.log_dir / f"yt-dlp_{timestamp}.log"
        
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
                "-loglevel", "error",  # 恢复详细日志以诊断问题
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
            
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            # No need for yt-dlp process anymore
            self.yt_dlp_process = None
            
            # Wait longer for ffmpeg to initialize and start processing HLS stream
            await asyncio.sleep(5.0)  # Give ffmpeg more time to initialize HLS stream
            if self.ffmpeg_process.poll() is not None:
                # ffmpeg process has already exited
                stderr_output = self.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore')
                logging.error(f"FFmpeg process exited early with code: {self.ffmpeg_process.returncode}")
                logging.error(f"FFmpeg stderr: {stderr_output}")
                raise Exception(f"FFmpeg failed to start: {stderr_output}")
            
            logging.info(f"FFmpeg process started successfully (PID: {self.ffmpeg_process.pid})")
            
            # Start a background task to monitor ffmpeg stderr
            asyncio.create_task(self._monitor_ffmpeg_stderr())
            
            logging.info(f"Started direct network streaming pipeline, yt-dlp logs: {yt_dlp_log}")
            return self.ffmpeg_process.stdout
            
        except Exception as e:
            logging.error(f"Failed to start streaming pipeline: {e}")
            await self.cleanup()
            raise
    
    async def _monitor_ffmpeg_stderr(self):
        """Monitor ffmpeg stderr output in the background"""
        if not self.ffmpeg_process or not self.ffmpeg_process.stderr:
            return
            
        try:
            while self.ffmpeg_process.poll() is None:
                # Read stderr with timeout
                try:
                    loop = asyncio.get_event_loop()
                    line = await asyncio.wait_for(
                        loop.run_in_executor(None, self.ffmpeg_process.stderr.readline),
                        timeout=1.0
                    )
                    if line:
                        line_str = line.decode('utf-8', errors='ignore').strip()
                        if line_str:
                            logging.info(f"FFmpeg: {line_str}")
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logging.error(f"Error reading ffmpeg stderr: {e}")
                    break
        except Exception as e:
            logging.error(f"FFmpeg stderr monitor error: {e}")
            
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

async def read_pcm_chunks(pcm_stream, chunk_size: int = 640):
    """Read PCM data in chunks (640 bytes = 20ms at 16kHz mono s16le)"""
    import asyncio
    loop = asyncio.get_event_loop()
    chunk_count = 0
    
    logging.info(f"Starting PCM chunk reading, chunk_size: {chunk_size}")
    
    while True:
        try:
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
                if chunk_count == 0:
                    logging.error("Timeout waiting for first PCM chunk - ffmpeg may be stuck or stream unavailable")
                else:
                    logging.error(f"Timeout reading PCM chunk {chunk_count + 1} - stream may have ended")
                break
            
            if not chunk:
                logging.info(f"PCM stream ended after {chunk_count} chunks")
                break
                
            chunk_count += 1
            if chunk_count == 1:
                logging.info(f"SUCCESS: First PCM chunk received! {len(chunk)} bytes")
            elif chunk_count % 50 == 0:
                logging.info(f"Successfully read PCM chunk {chunk_count}: {len(chunk)} bytes")
            else:
                logging.debug(f"Successfully read PCM chunk {chunk_count}: {len(chunk)} bytes")
            
            yield chunk
            
        except Exception as e:
            logging.error(f"Error reading PCM chunk {chunk_count}: {e}")
            import traceback
            logging.error(f"PCM read traceback: {traceback.format_exc()}")
            break
    
    logging.info(f"PCM chunk reading completed, total chunks: {chunk_count}")

async def translate_youtube_live_stream(conf: Config, youtube_url: str, duration_seconds: int = None):
    """Generator function that yields translated audio chunks from YouTube live stream"""
    streamer = YouTubeLiveStreamer(youtube_url, duration_seconds or 3600)  # Default 1 hour
    
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
        
        await send_request(conn, start_request)
        resp = await receive_message(conn)
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
                    stderr_output = streamer.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore')
                    logging.error(f"FFmpeg process has exited with code: {streamer.ffmpeg_process.returncode}")
                    logging.error(f"FFmpeg stderr: {stderr_output}")
                    finished.set()
                    return
                
                async for chunk in read_pcm_chunks(pcm_stream):
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
                    await send_request(conn, chunk_request)
                    await asyncio.sleep(0.02)  # 20ms delay to match chunk rate
                
                logging.info(f"Finished sending {chunk_count} PCM chunks, total {total_bytes} bytes")
                
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
                logging.error(f"Send chunks traceback: {traceback.format_exc()}")
                finished.set()
        
        async def receive_responses():
            try:
                while not finished.is_set():
                    resp = await receive_message(conn)
                    
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
                async for chunk in read_pcm_chunks(pcm_stream):
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
