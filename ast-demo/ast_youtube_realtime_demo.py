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
import tempfile
import sounddevice as sd
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import threading
import queue

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

class RealTimeAudioPlayer:
    def __init__(self):
        self.audio_queue = queue.Queue()
        self.is_playing = False
        self.player_thread = None
        self.ffmpeg_process = None
        self.executor = ThreadPoolExecutor(max_workers=2)
        
    def start(self):
        """Start the real-time audio player"""
        if not self.is_playing:
            self.is_playing = True
            self.player_thread = threading.Thread(target=self._audio_player_loop, daemon=True)
            self.player_thread.start()
            logging.info("🎵 Real-time audio player started")
    
    def stop(self):
        """Stop the audio player"""
        self.is_playing = False
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=2)
            except:
                if self.ffmpeg_process:
                    self.ffmpeg_process.kill()
        
        if self.player_thread and self.player_thread.is_alive():
            self.player_thread.join(timeout=2)
        
        self.executor.shutdown(wait=False)
        logging.info("🔇 Audio player stopped")
    
    def add_audio_data(self, audio_data: bytes):
        """Add audio data to the playback queue"""
        if audio_data and len(audio_data) > 0:
            try:
                self.audio_queue.put(audio_data, timeout=0.1)
                logging.info(f"🎶 Queued {len(audio_data)} bytes for playback")
            except queue.Full:
                logging.warning("Audio queue is full, dropping audio data")
    
    def _audio_player_loop(self):
        """Main audio player loop running in separate thread"""
        logging.info("🎵 Starting audio player loop")
        
        # Start persistent ffmpeg process for Opus decoding
        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-f", "ogg",  # Input format: OGG container with Opus
            "-i", "pipe:0",  # Read from stdin
            "-f", "f32le",  # Output format: 32-bit float little-endian
            "-ar", "24000",  # Sample rate: 24kHz (matching target_audio)
            "-ac", "1",  # Mono
            "-"  # Output to stdout
        ]
        
        try:
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            # Start audio output stream
            def audio_callback(outdata, frames, time, status):
                if status:
                    logging.warning(f"Audio callback status: {status}")
                
                try:
                    # Read decoded audio from ffmpeg
                    audio_bytes = self.ffmpeg_process.stdout.read(frames * 4)  # 4 bytes per float32 sample
                    if audio_bytes:
                        # Convert bytes to numpy array
                        audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
                        # Reshape for mono output
                        if len(audio_array) == frames:
                            outdata[:, 0] = audio_array
                        else:
                            # Pad with zeros if not enough data
                            outdata.fill(0)
                            if len(audio_array) > 0:
                                outdata[:len(audio_array), 0] = audio_array
                    else:
                        outdata.fill(0)
                except Exception as e:
                    logging.error(f"Audio callback error: {e}")
                    outdata.fill(0)
            
            # Start audio stream
            with sd.OutputStream(
                samplerate=24000,
                channels=1,
                dtype=np.float32,
                callback=audio_callback,
                blocksize=1024
            ):
                logging.info("🔊 Audio output stream started")
                
                while self.is_playing:
                    try:
                        # Get audio data from queue
                        audio_data = self.audio_queue.get(timeout=1.0)
                        
                        # Send to ffmpeg for decoding
                        if self.ffmpeg_process and self.ffmpeg_process.stdin:
                            self.ffmpeg_process.stdin.write(audio_data)
                            self.ffmpeg_process.stdin.flush()
                            logging.info(f"✅ Sent {len(audio_data)} bytes to ffmpeg decoder")
                        
                    except queue.Empty:
                        continue
                    except Exception as e:
                        logging.error(f"Error in audio player loop: {e}")
                        break
                        
        except Exception as e:
            logging.error(f"Failed to start audio player: {e}")
        finally:
            logging.info("🔇 Audio player loop ended")

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

async def translate_youtube_live(conf: Config, youtube_url: str, duration_seconds: int = 30, out_dir: str = "output", enable_playback: bool = True):
    """Main translation function for YouTube live stream with real-time playback"""
    streamer = YouTubeLiveStreamer(youtube_url, duration_seconds)
    audio_player = RealTimeAudioPlayer() if enable_playback else None
    
    try:
        # Start real-time audio player
        if audio_player:
            audio_player.start()
            
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
                    if chunk_count % 50 == 0:  # Log every 50 chunks to reduce spam
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
                
                if chunk_count % 50 == 0 or resp.text:  # Log less frequently
                    logging.info(
                        f"Received message (event={resp.event}, session_id={resp.session_id}): "
                        f"seq: {resp.sequence}, text: '{resp.text}', audio data length: {len(resp.data)}"
                    )
                
                if resp.event == Type.SessionFailed or resp.event == Type.SessionCanceled:
                    logging.error(f"Session failed, message: {resp.message} logid: {log_id}")
                    break
                
                if resp.event == Type.SessionFinished:
                    break
                
                # Add audio data to real-time playback
                if audio_player and resp.data and len(resp.data) > 0:
                    audio_player.add_audio_data(resp.data)
                
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
            output_path = Path(out_dir) / f"youtube_realtime_{timestamp}.opus"
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
        logging.error(traceback.format_exc())
    finally:
        # Stop audio player
        if audio_player:
            audio_player.stop()
        # Clean up streamer
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
    duration_seconds = 30  # Test with 30 seconds
    enable_playback = True  # Enable real-time audio playback
    
    logging.info(f"🚀 Starting YouTube live translation for {duration_seconds} seconds")
    logging.info(f"📺 YouTube URL: {youtube_url}")
    logging.info(f"🔊 Real-time playback: {'Enabled' if enable_playback else 'Disabled'}")
    
    start_time = time.time()
    await translate_youtube_live(conf, youtube_url, duration_seconds, enable_playback=enable_playback)
    end_time = time.time()
    
    logging.info(f"⏱️ Total processing time: {end_time - start_time:.2f} seconds")

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
        logging.error(traceback.format_exc())
