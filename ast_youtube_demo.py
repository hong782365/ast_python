import asyncio
import uuid
import os
import subprocess
import signal
import sys
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
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

class YouTubeLiveStreamer:
    def __init__(self, youtube_url: str, duration_seconds: int = 10):
        self.youtube_url = youtube_url
        self.duration_seconds = duration_seconds
        self.yt_dlp_process = None
        self.ffmpeg_process = None
        self.log_dir = Path(current_dir) / "youtube" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
    async def start_streaming_pipeline(self):
        """Start yt-dlp + ffmpeg pipeline for PCM streaming"""
        timestamp = time.strftime("%Y%m%dT%H%M%SZ")
        yt_dlp_log = self.log_dir / f"yt-dlp_{timestamp}.log"
        
        # yt-dlp command to extract live audio
        yt_dlp_cmd = [
            "yt-dlp",
            "-f", "91/92/93/94/bestaudio",  # Try formats that work with this stream
            "--no-part", "--no-keep-fragments", "--no-live-from-start",
            "-o", "-",
            self.youtube_url
        ]
        
        # ffmpeg command to convert to 16kHz mono PCM
        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-fflags", "+nobuffer", "-flags", "low_delay",
            "-probesize", "32k", "-analyzeduration", "0",
            "-i", "pipe:0",
            "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "s16le",
            "-af", "aresample=async=1:min_comp=0.001:first_pts=0",
            "-t", str(self.duration_seconds),  # Limit duration for testing
            "-y",  # Overwrite output files
            "pipe:1"
        ]
        
        try:
            # Start yt-dlp process with stderr redirected to log file
            with open(yt_dlp_log, 'w') as log_file:
                self.yt_dlp_process = subprocess.Popen(
                    yt_dlp_cmd,
                    stdout=subprocess.PIPE,
                    stderr=log_file,
                    bufsize=0
                )
            
            # Start ffmpeg process
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=self.yt_dlp_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            # Close yt-dlp stdout in parent process to allow proper pipe communication
            self.yt_dlp_process.stdout.close()
            
            logging.info(f"Started streaming pipeline, yt-dlp logs: {yt_dlp_log}")
            return self.ffmpeg_process.stdout
            
        except Exception as e:
            logging.error(f"Failed to start streaming pipeline: {e}")
            await self.cleanup()
            raise
    
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
    request_data.target_audio.format = "ogg_opus"
    request_data.target_audio.rate = 24000
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
        message=Response_data.response_meta.Message
    )

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
    
    while True:
        try:
            # Use run_in_executor to make blocking read non-blocking
            chunk = await loop.run_in_executor(None, pcm_stream.read, chunk_size)
            if not chunk:
                break
            yield chunk
        except Exception as e:
            logging.error(f"Error reading PCM chunk: {e}")
            break

async def translate_youtube_live(conf: Config, youtube_url: str, duration_seconds: int = 10, out_dir: str = "output"):
    """Main translation function for YouTube live stream"""
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
            target_audio=Audio(format="ogg_opus", rate=24000),
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
