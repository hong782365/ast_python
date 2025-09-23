import asyncio
import json
import logging
import time
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

class WebSocketPublishClient:
    def __init__(self, publish_url: str, session_id: str, control_message_callback=None):
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
        self.control_message_callback = control_message_callback
        self.message_listener_task = None
        self.is_listening = False
        
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
                
                # Start message listener if callback is provided
                if self.control_message_callback:
                    await self.start_message_listener()
                
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
    
    async def start_message_listener(self):
        """启动消息监听循环"""
        if self.is_listening:
            return
        
        self.is_listening = True
        self.message_listener_task = asyncio.create_task(self._message_listener_loop())
        self.logger.info(f"Session {self.session_id}: Started message listener")
    
    async def _message_listener_loop(self):
        """监听WebSocket消息的循环"""
        try:
            while self.is_listening and self.websocket:
                try:
                    # 设置合理的接收超时，避免无限阻塞
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
                    await self._handle_received_message(message)
                except asyncio.TimeoutError:
                    # 超时是正常的，继续循环
                    continue
                except ConnectionClosed:
                    self.logger.info(f"Session {self.session_id}: WebSocket connection closed during message listening")
                    break
                except Exception as e:
                    self.logger.error(f"Session {self.session_id}: Message listener error: {e}")
                    if self.websocket and self.websocket.closed:
                        break
                    # 其他错误继续监听
                    await asyncio.sleep(1.0)
        except Exception as e:
            self.logger.error(f"Session {self.session_id}: Message listener loop error: {e}")
        finally:
            self.is_listening = False
            self.logger.info(f"Session {self.session_id}: Message listener stopped")
    
    async def _handle_received_message(self, message):
        """处理接收到的消息"""
        try:
            # 尝试解析JSON控制消息
            data = json.loads(message)
            if data.get("type") == "system_control":
                self.logger.info(f"Session {self.session_id}: Received control message: {data}")
                if self.control_message_callback:
                    await self.control_message_callback(data)
            else:
                self.logger.debug(f"Session {self.session_id}: Received non-control message: {data}")
        except json.JSONDecodeError:
            # 非JSON消息，可能是其他类型数据，记录但忽略
            self.logger.debug(f"Session {self.session_id}: Received non-JSON message: {len(message)} bytes")
        except Exception as e:
            self.logger.error(f"Session {self.session_id}: Error handling received message: {e}")
    
    async def disconnect(self):
        """Gracefully disconnect"""
        # Stop message listening
        self.is_listening = False
        if self.message_listener_task:
            self.message_listener_task.cancel()
            try:
                await self.message_listener_task
            except asyncio.CancelledError:
                pass
        
        # Stop heartbeat
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Close WebSocket
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