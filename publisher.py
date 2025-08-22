import asyncio
import logging
import time
import json
import uuid
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
import uvicorn

# Add the current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import modified youtube demo functions
from ast_youtube_demo import Config, YouTubeLiveStreamer, translate_youtube_live_stream, StreamData, ytdlp_manager
from dotenv import load_dotenv

load_dotenv()

# Configuration
APP_KEY = os.getenv("APP_KEY")
ACCESS_KEY = os.getenv("ACCESS_KEY")
RESOURCE_ID = os.getenv("RESOURCE_ID")
WS_URL = os.getenv("WS_URL")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI应用生命周期管理"""
    # 启动时执行
    logging.info("🚀 Publisher starting up - initializing yt-dlp manager...")
    try:
        init_start_time = time.time()
        await ytdlp_manager.warmup()
        init_elapsed_time = time.time() - init_start_time
        logging.info(f"🚀 yt-dlp manager initialization completed in {init_elapsed_time:.2f}s")
    except Exception as e:
        logging.warning(f"🚀 yt-dlp manager initialization failed (continuing anyway): {e}")
    
    yield
    
    # 关闭时执行
    logging.info("🔥 Publisher shutting down - cleaning up yt-dlp manager...")
    try:
        ytdlp_manager.cleanup()
        logging.info("🔥 yt-dlp manager cleanup completed")
    except Exception as e:
        logging.error(f"🔥 yt-dlp manager cleanup failed: {e}")

app = FastAPI(title="Audio Stream Publisher", version="1.0.0", lifespan=lifespan)

class IngestStartRequest(BaseModel):
    sessionId: str
    youtube_url: str
    publishUrl: str

class IngestStartResponse(BaseModel):
    success: bool
    message: str
    session_id: str

class IngestStopRequest(BaseModel):
    sessionId: str

class IngestStopResponse(BaseModel):
    success: bool
    message: str
    session_id: str

@dataclass
class PublisherSession:
    session_id: str
    youtube_url: str
    publish_url: str
    status: str
    created_at: float
    websocket: Optional[Any] = None
    streamer: Optional[YouTubeLiveStreamer] = None
    task: Optional[asyncio.Task] = None
    stop_event: Optional[asyncio.Event] = None

class AudioStreamPublisher:
    def __init__(self):
        self.sessions: Dict[str, PublisherSession] = {}
        self.logger = logging.getLogger(__name__)
        
    async def start_publishing_session(self, session_id: str, youtube_url: str, publish_url: str) -> tuple[str, bool]:
        """Start a new publishing session or return existing one (idempotent)"""
        # Check if session already exists and is active
        if session_id in self.sessions:
            existing_session = self.sessions[session_id]
            if existing_session.status in ["initializing", "starting", "connected_to_publisher", "processing_audio"]:
                self.logger.info(f"Session {session_id} already running with status: {existing_session.status}")
                return session_id, False  # False indicates session was already running
            else:
                # Session exists but is not active, remove it
                self.logger.info(f"Removing inactive session {session_id} with status: {existing_session.status}")
                await self._cleanup_session(session_id)
        
        # Create new session
        stop_event = asyncio.Event()
        session = PublisherSession(
            session_id=session_id,
            youtube_url=youtube_url,
            publish_url=publish_url,
            status="initializing",
            created_at=time.time(),
            stop_event=stop_event
        )
        
        self.sessions[session_id] = session
        
        # Start the publishing task in background
        task = asyncio.create_task(self._publish_audio_stream(session))
        session.task = task
        
        return session_id, True  # True indicates new session was created
    
    async def stop_publishing_session(self, session_id: str) -> bool:
        """Stop a publishing session (idempotent)"""
        if session_id not in self.sessions:
            self.logger.info(f"Session {session_id} not found, nothing to stop")
            return False  # Session doesn't exist
        
        session = self.sessions[session_id]
        
        # If already stopped/completed, return success
        if session.status in ["completed", "failed", "stopped"]:
            self.logger.info(f"Session {session_id} already stopped with status: {session.status}")
            return True
        
        self.logger.info(f"Stopping session {session_id} with status: {session.status}")
        
        # Set stop event to signal the session to stop
        if session.stop_event:
            session.stop_event.set()
        
        # Cancel the task if it exists
        if session.task and not session.task.done():
            session.task.cancel()
            try:
                await session.task
            except asyncio.CancelledError:
                pass
        
        # Update status and cleanup
        session.status = "stopped"
        await self._cleanup_session(session_id)
        
        return True
    
    async def _cleanup_session(self, session_id: str):
        """Cleanup session resources"""
        if session_id not in self.sessions:
            return
        
        session = self.sessions[session_id]
        
        # Cancel task if still running
        if session.task and not session.task.done():
            session.task.cancel()
            try:
                await session.task
            except asyncio.CancelledError:
                pass
        
        # Cleanup WebSocket connection
        if session.websocket:
            try:
                await session.websocket.close()
            except Exception as e:
                self.logger.warning(f"Error closing WebSocket for session {session_id}: {e}")
        
        # Cleanup streamer
        if session.streamer:
            try:
                await session.streamer.cleanup()
            except Exception as e:
                self.logger.warning(f"Error cleaning up streamer for session {session_id}: {e}")
        
        self.logger.info(f"Session {session_id} cleaned up")
    
    async def _publish_audio_stream(self, session: PublisherSession):
        """Main publishing logic"""
        try:
            session.status = "starting"
            self.logger.info(f"Session {session.session_id}: Starting audio stream publishing")
            self.logger.info(f"YouTube URL: {session.youtube_url}")
            self.logger.info(f"Publish URL: {session.publish_url}")
            
            # Create translation config
            if not all([APP_KEY, ACCESS_KEY, RESOURCE_ID, WS_URL]):
                raise Exception("Missing required environment variables")
            
            config = Config(
                ws_url=WS_URL,
                app_key=APP_KEY,
                access_key=ACCESS_KEY,
                resource_id=RESOURCE_ID
            )
            
            # Start WebSocket connection to publish URL first
            ws_client = WebSocketPublishClient(session.publish_url, session.session_id)
            await ws_client.connect()
            session.status = "connected_to_publisher"
            
            # Start YouTube live translation stream
            session.status = "processing_audio"
            await self._stream_translated_audio(config, session, ws_client)
            
        except Exception as e:
            self.logger.error(f"Session {session.session_id}: Publishing failed: {e}")
            session.status = "failed"
        finally:
            if session.session_id in self.sessions:
                self.sessions[session.session_id].status = "completed"
    
    async def _stream_translated_audio(self, config: Config, session: PublisherSession, ws_client):
        """Stream translated PCM audio and subtitles to WebSocket publisher"""
        try:
            async for stream_data in translate_youtube_live_stream(config, session.youtube_url):
                # Check if stop was requested
                if session.stop_event and session.stop_event.is_set():
                    self.logger.info(f"Session {session.session_id}: Stop requested, terminating stream")
                    break
                
                if not stream_data:
                    break
                
                # Handle different types of stream data
                if stream_data.data_type == "audio":
                    # Directly forward PCM audio chunks without any processing
                    # The audio is already in PCM format from the translation service
                    await ws_client.send_audio_frame(stream_data.content)
                elif stream_data.data_type == "subtitle":
                    # Send subtitle JSON as text message
                    await ws_client.send_text_message(stream_data.content)
                    self.logger.debug(f"Session {session.session_id}: Sent subtitle: {stream_data.content}")
                
        except asyncio.CancelledError:
            self.logger.info(f"Session {session.session_id}: Streaming cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Session {session.session_id}: Streaming error: {e}")
            raise
        finally:
            await ws_client.disconnect()

class WebSocketPublishClient:
    def __init__(self, publish_url: str, session_id: str):
        self.publish_url = publish_url
        self.session_id = session_id
        self.websocket = None
        self.logger = logging.getLogger(__name__)
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.base_retry_delay = 1.0
        self.max_retry_delay = 60.0
        self.heartbeat_interval = 30.0
        self.heartbeat_task = None
        self.frame_count = 0
        self.start_time = None
        
    async def connect(self):
        """Connect to WebSocket with exponential backoff retry"""
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Session {self.session_id}: Attempting to connect to {self.publish_url}")
                
                self.websocket = await websockets.connect(
                    self.publish_url,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=1000000000
                )
                
                self.logger.info(f"Session {self.session_id}: Successfully connected to publisher")
                self.reconnect_attempts = 0
                self.start_time = time.time()
                
                # Start heartbeat
                self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                return
                
            except Exception as e:
                self.reconnect_attempts += 1
                retry_delay = min(
                    self.base_retry_delay * (2 ** (self.reconnect_attempts - 1)),
                    self.max_retry_delay
                )
                
                self.logger.warning(
                    f"Session {self.session_id}: Connection failed (attempt {self.reconnect_attempts}): {e}"
                )
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    self.logger.info(f"Session {self.session_id}: Retrying in {retry_delay:.1f} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    self.logger.error(f"Session {self.session_id}: Max reconnection attempts reached")
                    raise
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat messages"""
        try:
            while self.websocket:
                await asyncio.sleep(self.heartbeat_interval)
                if self.websocket:
                    try:
                        await self.websocket.ping()
                        self.logger.debug(f"Session {self.session_id}: Heartbeat sent")
                    except Exception:
                        # Connection is likely closed, exit heartbeat loop
                        break
        except Exception as e:
            self.logger.warning(f"Session {self.session_id}: Heartbeat error: {e}")
    
    async def send_audio_frame(self, audio_chunk: bytes):
        """Send audio chunk with automatic reconnection"""
        if not self.websocket:
            self.logger.warning(f"Session {self.session_id}: Connection lost, attempting to reconnect...")
            await self.connect()
        
        try:
            await self.websocket.send(audio_chunk)
            self.frame_count += 1
            
            # Log every 100 chunks sent
            if self.frame_count % 100 == 0:
                elapsed_time = time.time() - self.start_time
                chunk_rate = self.frame_count / elapsed_time
                self.logger.info(
                    f"Session {self.session_id}: Sent {self.frame_count} audio chunks, "
                    f"rate: {chunk_rate:.1f} chunks/sec, total bytes: {self.frame_count * len(audio_chunk)}"
                )
                
        except (ConnectionClosed, WebSocketException) as e:
            self.logger.warning(f"Session {self.session_id}: Send failed, reconnecting: {e}")
            await self.connect()
            # Retry sending the chunk
            await self.websocket.send(audio_chunk)
            self.frame_count += 1
    
    async def send_text_message(self, text_message: str):
        """Send text message (JSON subtitle) with automatic reconnection"""
        if not self.websocket:
            self.logger.warning(f"Session {self.session_id}: Connection lost, attempting to reconnect...")
            await self.connect()
        
        try:
            await self.websocket.send(text_message)
            self.logger.debug(f"Session {self.session_id}: Sent text message: {text_message}")
                
        except (ConnectionClosed, WebSocketException) as e:
            self.logger.warning(f"Session {self.session_id}: Send text failed, reconnecting: {e}")
            await self.connect()
            # Retry sending the message
            await self.websocket.send(text_message)
    
    async def disconnect(self):
        """Gracefully disconnect"""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self.websocket:
            await self.websocket.close()
            self.logger.info(f"Session {self.session_id}: Disconnected from publisher")
            
            if self.start_time:
                elapsed_time = time.time() - self.start_time
                chunk_rate = self.frame_count / elapsed_time if elapsed_time > 0 else 0
                self.logger.info(
                    f"Session {self.session_id}: Final stats - "
                    f"Total chunks: {self.frame_count}, "
                    f"Duration: {elapsed_time:.1f}s, "
                    f"Average chunk rate: {chunk_rate:.1f} chunks/sec"
                )

# Global publisher instance
publisher = AudioStreamPublisher()

@app.post("/ingest/start", response_model=IngestStartResponse)
async def start_ingest(request: IngestStartRequest):
    """Start audio ingestion from YouTube to WebSocket publisher"""
    try:
        # Validate URLs
        if not request.youtube_url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        if not request.publishUrl.startswith(('ws://', 'wss://')):
            raise HTTPException(status_code=400, detail="Invalid WebSocket publish URL")
        
        # Start publishing session (idempotent)
        session_id, is_new = await publisher.start_publishing_session(
            request.sessionId,
            request.youtube_url, 
            request.publishUrl
        )
        
        if is_new:
            return IngestStartResponse(
                success=True,
                message="Ingestion started successfully",
                session_id=session_id
            )
        else:
            # Session already running, return 202 Accepted
            from fastapi import status
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "success": True,
                    "message": "Session already running",
                    "session_id": session_id
                }
            )
        
    except Exception as e:
        logging.error(f"Failed to start ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ingest/stop", response_model=IngestStopResponse)
async def stop_ingest(request: IngestStopRequest):
    """Stop audio ingestion session (idempotent)"""
    try:
        # Stop publishing session
        success = await publisher.stop_publishing_session(request.sessionId)
        
        if success:
            return IngestStopResponse(
                success=True,
                message="Session stopped successfully",
                session_id=request.sessionId
            )
        else:
            # Session doesn't exist, but we treat this as successful (idempotent)
            return IngestStopResponse(
                success=True,
                message="Session not found (already stopped or never existed)",
                session_id=request.sessionId
            )
        
    except Exception as e:
        logging.error(f"Failed to stop ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": time.time()}

@app.get("/sessions")
async def get_sessions():
    """Get all active sessions"""
    return {
        "sessions": [
            {
                "session_id": session.session_id,
                "youtube_url": session.youtube_url,
                "publish_url": session.publish_url,
                "status": session.status,
                "created_at": session.created_at
            }
            for session in publisher.sessions.values()
        ]
    }

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    uvicorn.run(
        "publisher:app",
        host="0.0.0.0",
        port=9000,
        log_level="info",
        reload=False
    )
