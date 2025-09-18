import asyncio
import logging
import time
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

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