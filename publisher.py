#!/usr/bin/env python3

# Import sys first for logging
import sys
import os
import asyncio
import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
import uvicorn
from dotenv import load_dotenv

load_dotenv()

# 配置日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logging.info("🚀 Publisher script starting...")

try:
    from ast_youtube_demo import Config, translate_youtube_live_stream, ytdlp_manager
except Exception as e:
    logging.error(f"❌ YouTube demo imports failed: {e}")
    sys.exit(1)

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
    task: Optional[asyncio.Task] = None
    stop_event: Optional[asyncio.Event] = None
    publisher_ws: Optional[Any] = None  # WebSocket发布客户端引用，防止泄漏

class AudioStreamPublisher:
    def __init__(self):
        self.sessions: Dict[str, PublisherSession] = {}
        self.logger = logging.getLogger(__name__)
        
    async def start_publishing_session(self, session_id: str, youtube_url: str, publish_url: str) -> tuple[str, int]:
        """Start a new publishing session or return existing one (idempotent)"""
        # 一容器一链接：检查活跃会话状态
        active_statuses = ["initializing", "starting", "connected_to_publisher", "processing_audio"]
        
        # 检查是否已存在相同session_id
        if session_id in self.sessions:
            existing_session = self.sessions[session_id]
            if existing_session.status in active_statuses:
                self.logger.info(f"Session {session_id} already running with status: {existing_session.status}")
                return session_id, 202  # HTTP 202 Accepted - 已在跑，幂等
            else:
                # Session exists but is not active, remove it
                self.logger.info(f"Removing inactive session {session_id} with status: {existing_session.status}")
                await self._cleanup_session(session_id)
        
        # 检查是否有其他sessionId的活跃会话（一容器一链接限制）
        active_sessions = [
            s for s in self.sessions.values() 
            if s.status in active_statuses
        ]
        if active_sessions:
            active_session = active_sessions[0]
            self.logger.warning(f"Container busy with active session {active_session.session_id} (status: {active_session.status})")
            return session_id, 409  # HTTP 409 Conflict - 容器忙碌
        
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
        
        # 添加任务完成回调，自动清理会话（避免内存泄漏）
        task.add_done_callback(lambda task_obj: self._schedule_session_cleanup(session_id))
        
        return session_id, 201  # HTTP 201 Created - 新会话创建成功
    
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
        
        # ❗ 关键修复：不要立即取消任务！让宽限期监督协程来处理
        # 只设置停止信号，任务会自然完成 FinishSession 流程后结束
        
        # Update status immediately (立即返回 - 不等待任务完成)
        session.status = "stopping"
        
        # 启动宽限期监督协程，不阻塞返回
        asyncio.create_task(self._grace_period_supervisor(session))
        
        return True
    
    def _schedule_session_cleanup(self, session_id: str):
        """安全地调度会话清理，避免在任务回调中直接调用async方法"""
        # 任务完成回调是同步的，只记录状态，不删除字典（避免与后台清理竞态）
        try:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                # 记录最终状态用于调试
                final_status = getattr(session, 'status', 'unknown')
                self.logger.info(f"Session {session_id} task completed (final status: {final_status}) - cleanup will be handled by background cleanup")
        except Exception as e:
            self.logger.warning(f"Error in session auto-cleanup for {session_id}: {e}")
    
    async def _grace_period_supervisor(self, session: PublisherSession):
        """宽限期监督协程：在FinishSession宽限期内监视会话，超时则强制清理"""
        session_id = session.session_id
        # 从环境变量获取宽限期时长
        grace_timeout = float(os.getenv("FINISH_GRACE_TIMEOUT", "30.0"))
        
        try:
            self.logger.info(f"Grace period supervisor started for session {session_id} (timeout: {grace_timeout}s)")
            
            # 等待宽限期时长或直到任务完成
            if session.task:
                try:
                    await asyncio.wait_for(session.task, timeout=grace_timeout)
                    # 任务在宽限期内正常完成
                    self.logger.info(f"Session {session_id} completed gracefully within {grace_timeout}s")
                    session.status = "completed"
                except asyncio.TimeoutError:
                    # 宽限期超时，强制清理
                    self.logger.warning(f"Session {session_id}: Grace period timeout ({grace_timeout}s), forcing cleanup")
                    session.status = "stopped"
                    if session.task and not session.task.done():
                        session.task.cancel()
                except asyncio.CancelledError:
                    # 任务被取消（正常的强制停止流程）
                    self.logger.info(f"Session {session_id}: Task was cancelled during grace period")
                    session.status = "stopped"
                except Exception as e:
                    # 任务执行异常
                    self.logger.error(f"Session {session_id}: Task ended with exception: {e}")
                    session.status = "failed"
            else:
                # 没有任务对象，直接等待后清理
                await asyncio.sleep(grace_timeout)
                self.logger.warning(f"Session {session_id}: No task found, cleanup after timeout")
                session.status = "stopped"
            
            # 执行后台清理
            await self._background_cleanup(session)
            
        except Exception as e:
            self.logger.error(f"Grace period supervisor error for session {session_id}: {e}")
            session.status = "failed"
            await self._background_cleanup(session)

    async def _background_cleanup(self, session: PublisherSession):
        """后台清理器：先断连再等待，避免阻塞stop接口"""
        session_id = session.session_id
        try:
            self.logger.info(f"Starting background cleanup for session {session_id}")
            
            # Phase 1: 立即断开关键连接（不等待）
            cleanup_tasks = []
            
            # 关闭发布端WebSocket连接
            if session.publisher_ws:
                try:
                    cleanup_tasks.append(asyncio.create_task(session.publisher_ws.disconnect()))
                    self.logger.info(f"Session {session_id}: Initiated publisher WebSocket disconnect")
                except Exception as e:
                    self.logger.warning(f"Error initiating publisher WebSocket disconnect: {e}")
            
            
            # Phase 2: 等待任务取消完成（有超时保护）
            if session.task and not session.task.done():
                try:
                    await asyncio.wait_for(session.task, timeout=3.0)  # 3秒超时
                except asyncio.TimeoutError:
                    self.logger.warning(f"Session {session_id}: Task cancellation timeout, forcing cleanup")
                except Exception as e:
                    self.logger.debug(f"Session {session_id}: Task ended with exception (expected): {e}")
            
            # Phase 3: 等待清理任务完成（有超时保护）
            if cleanup_tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*cleanup_tasks, return_exceptions=True), timeout=5.0)
                except asyncio.TimeoutError:
                    self.logger.warning(f"Session {session_id}: Cleanup tasks timeout")
            
            # Phase 4: 最终清理（兜底）
            await self._cleanup_session(session_id)
            
            # Phase 5: 从字典中移除会话（避免竞态，在最后执行）
            if session_id in self.sessions:
                del self.sessions[session_id]
                self.logger.info(f"Session {session_id} removed from sessions dict via background cleanup")
            
            self.logger.info(f"Background cleanup completed for session {session_id}")
            
        except Exception as e:
            self.logger.error(f"Background cleanup failed for session {session_id}: {e}")
            # 即使后台清理失败，也要尝试基本清理
            try:
                await self._cleanup_session(session_id)
                # 确保即使清理失败也要移除字典条目
                if session_id in self.sessions:
                    del self.sessions[session_id]
                    self.logger.info(f"Session {session_id} removed from sessions dict after cleanup failure")
            except Exception as cleanup_e:
                self.logger.error(f"Final cleanup also failed for session {session_id}: {cleanup_e}")
    
    async def _cleanup_session(self, session_id: str):
        """Cleanup session resources"""
        # 获取会话对象，如果已被自动清理则跳过
        session = self.sessions.get(session_id)
        if not session:
            self.logger.debug(f"Session {session_id} already cleaned up")
            return
        
        # Cancel task if still running
        if session.task and not session.task.done():
            session.task.cancel()
            try:
                # 添加超时保护，避免无限等待（后台清理已等待过，这里快速处理）
                await asyncio.wait_for(session.task, timeout=1.0)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                self.logger.warning(f"Session {session_id}: Task cancellation timeout in cleanup, forcing continue")
        
        # Cleanup publisher WebSocket connection
        if session.publisher_ws:
            try:
                await session.publisher_ws.disconnect()
            except Exception as e:
                self.logger.warning(f"Error disconnecting publisher WebSocket for session {session_id}: {e}")
        
        # 字典清理由后台清理器负责，这里只清理资源
        self.logger.info(f"Session {session_id} resources cleaned up (dict removal handled by background cleanup)")
    
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
            
            # 保存WebSocket客户端引用，防止取消时泄漏
            session.publisher_ws = ws_client
            
            # Start YouTube live translation stream
            session.status = "processing_audio"
            await self._stream_translated_audio(config, session, ws_client)
            
        except asyncio.CancelledError:
            # 任务被取消（stop操作或其他取消场景）
            self.logger.info(f"Session {session.session_id}: Publishing cancelled")
            session.status = "stopped"
            raise  # 重新抛出，保持取消语义
        except Exception as e:
            self.logger.error(f"Session {session.session_id}: Publishing failed: {e}")
            session.status = "failed"
        finally:
            # 只在正常完成时才设置completed，保留failed/stopped状态
            if session.session_id in self.sessions:
                current_status = self.sessions[session.session_id].status
                if current_status not in ["failed", "stopped"]:
                    self.sessions[session.session_id].status = "completed"
                    self.logger.info(f"Session {session.session_id}: Set status to completed")
                else:
                    self.logger.info(f"Session {session.session_id}: Keeping status as {current_status}")
    
    async def _stream_translated_audio(self, config: Config, session: PublisherSession, ws_client):
        """Stream translated PCM audio and subtitles to WebSocket publisher"""
        try:
            # 获取环境变量配置的宽限期时长
            finish_grace_timeout = float(os.getenv("FINISH_GRACE_TIMEOUT", "30.0"))  # 默认30秒
            
            # Start YouTube live translation stream with stop control
            async for stream_data in translate_youtube_live_stream(
                config, 
                session.youtube_url, 
                stop_event=session.stop_event,
                finish_grace_timeout=finish_grace_timeout
            ):
                # 无条件转发所有流数据，包括 FinishSession 的响应
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
                elif stream_data.data_type == "error":
                    # Handle live check errors (Codex方案错误处理)
                    self.logger.warning(f"Session {session.session_id}: Live check failed, sending error to client")
                    await ws_client.send_text_message(stream_data.content)
                    self.logger.info(f"Session {session.session_id}: Error message sent: {stream_data.content}")
                    
                    # 🔥审核者建议：检查失败时标记会话状态为failed
                    session.status = "failed"
                    self.logger.info(f"Session {session.session_id}: Status set to 'failed' due to live check failure")
                    
                    # Error已发送，流程即将结束
                    break
                
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

@app.post("/python/ingest/start", response_model=IngestStartResponse)
async def start_ingest(request: IngestStartRequest):
    """Start audio ingestion from YouTube to WebSocket publisher"""
    try:
        # Validate URLs
        if not request.youtube_url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        if not request.publishUrl.startswith(('ws://', 'wss://')):
            raise HTTPException(status_code=400, detail="Invalid WebSocket publish URL")
        
        # Start publishing session (idempotent)
        session_id, status_code = await publisher.start_publishing_session(
            request.sessionId,
            request.youtube_url, 
            request.publishUrl
        )
        
        if status_code == 201:
            # 新会话创建成功
            return IngestStartResponse(
                success=True,
                message="Ingestion started successfully",
                session_id=session_id
            )
        elif status_code == 202:
            # 同sessionId已在运行，幂等返回
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
        elif status_code == 409:
            # 容器忙碌，不同sessionId冲突
            raise HTTPException(
                status_code=409, 
                detail=f"Container is busy with another session. This container supports only one active session at a time."
            )
        
    except Exception as e:
        logging.error(f"Failed to start ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/python/ingest/stop", response_model=IngestStopResponse)
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

@app.get("/python/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": time.time()}

@app.get("/python/sessions")
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
    
    try:
        # host = os.getenv("HOST", "0.0.0.0")
        host = "0.0.0.0"
        port = 9000
        
        logging.info(f"🚀 Starting FastAPI server on {host}:{port}")
        logging.info(f"🔧 Environment variables: HOST={os.getenv('HOST', 'not set')}")
        logging.info(f"🔧 Current working directory: {os.getcwd()}")
        logging.info(f"🔧 Python path: {sys.path}")
        
        uvicorn.run(
            "publisher:app",
            host=host,
            port=port,
            log_level="info",
            reload=False
        )
        
    except Exception as e:
        logging.error(f"❌ Failed to start server: {e}")
        logging.error(f"❌ Exception type: {type(e).__name__}")
        import traceback
        logging.error(f"❌ Full traceback: {traceback.format_exc()}")
        raise
