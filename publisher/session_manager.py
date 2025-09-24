import asyncio
import logging
import os
import time
from typing import Dict, Optional

from core.config import APP_KEY, ACCESS_KEY, RESOURCE_ID, WS_URL
from streaming import Config, translate_youtube_live_stream
from .models import PublisherSession
from .websocket_client import WebSocketPublishClient

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
            
            # 创建翻译控制事件
            translation_allowed_event = asyncio.Event()
            # 默认不允许翻译，等待控制消息
            
            # 定义控制消息处理回调
            async def control_message_handler(message):
                code = message.get("code")
                msg_text = message.get("message", "")

                if code == "TRANSLATION_START_ALLOWED":
                    self.logger.info(f"Session {session.session_id}: Translation start allowed: {msg_text}")
                    translation_allowed_event.set()
                    session.status = "translation_allowed"

                elif code == "TRANSLATION_STOP_REQUIRED":
                    self.logger.info(f"Session {session.session_id}: Translation stop required: {msg_text}")
                    translation_allowed_event.clear()
                    session.status = "stopping_due_to_control"  # 区分停止原因
                    
                    # 触发会话停止（复用现有逻辑）
                    self.logger.info(f"Session {session.session_id}: Initiating session stop due to TRANSLATION_STOP_REQUIRED")
                    if session.stop_event:
                        session.stop_event.set()
                else:
                    self.logger.warning(f"Session {session.session_id}: Unknown control code: {code}")
            
            # Start WebSocket connection to publish URL with control callback
            ws_client = WebSocketPublishClient(
                session.publish_url, 
                session.session_id,
                control_message_callback=control_message_handler
            )
            await ws_client.connect()
            session.status = "connected_to_publisher"
            
            # 保存WebSocket客户端引用，防止取消时泄漏
            session.publisher_ws = ws_client
            
            # Start YouTube live translation stream with translation control
            session.status = "processing_audio"
            await self._stream_translated_audio(config, session, ws_client, translation_allowed_event)
            
        except asyncio.CancelledError:
            # 任务被取消（stop操作或其他取消场景）
            self.logger.info(f"Session {session.session_id}: Publishing cancelled")
            session.status = "stopped"
            raise  # 重新抛出，保持取消语义
        except Exception as e:
            self.logger.error(f"Session {session.session_id}: Publishing failed: {e}")
            session.status = "failed"
            
            # 防御性确保 stop_event 已触发
            if session.stop_event and not session.stop_event.is_set():
                session.stop_event.set()
                self.logger.warning(f"Session {session.session_id}: stop_event set as fallback in _publish_audio_stream")
        finally:
            # 只在正常完成时才设置completed，保留failed/stopped状态
            if session.session_id in self.sessions:
                current_status = self.sessions[session.session_id].status
                if current_status not in ["failed", "stopped"]:
                    self.sessions[session.session_id].status = "completed"
                    self.logger.info(f"Session {session.session_id}: Set status to completed")
                else:
                    self.logger.info(f"Session {session.session_id}: Keeping status as {current_status}")
    
    async def _stream_translated_audio(self, config: Config, session: PublisherSession, ws_client, translation_allowed_event):
        """Stream translated PCM audio and subtitles to WebSocket publisher"""
        try:
            # 获取环境变量配置的宽限期时长
            finish_grace_timeout = float(os.getenv("FINISH_GRACE_TIMEOUT", "30.0"))  # 默认30秒
            
            # Start YouTube live translation stream with stop control and translation allowed event
            async for stream_data in translate_youtube_live_stream(
                config, 
                session.youtube_url, 
                stop_event=session.stop_event,
                finish_grace_timeout=finish_grace_timeout,
                translation_allowed_event=translation_allowed_event
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
                    # 尽力发送错误通知（如果 WebSocket 已断开会失败）
                    try:
                        error_notification = {
                            "type": "system_control",
                            "code": "TRANSLATION_FAILED_SESSION",
                            "message": stream_data.content
                        }
                        await ws_client.send_text_message(json.dumps(error_notification))
                        self.logger.info(f"Session {session.session_id}: Error notification sent: {error_notification}")
                    except Exception as e:
                        self.logger.warning(f"Session {session.session_id}: Failed to send error notification (WebSocket may be closed): {e}")
                    
                    # 确保触发 stop_event（防止翻译服务继续运行）
                    if session.stop_event:
                        session.stop_event.set()
                        self.logger.info(f"Session {session.session_id}: stop_event triggered due to error from translation service")
                    
                    session.status = "failed"
                    self.logger.info(f"Session {session.session_id}: Status set to 'failed' due to live check failure")
                    break
                
        except asyncio.CancelledError:
            self.logger.info(f"Session {session.session_id}: Streaming cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Session {session.session_id}: Streaming error: {e}")
            
            # 确保触发 stop_event（Publisher WebSocket 异常等）
            if session.stop_event:
                session.stop_event.set()
                self.logger.info(f"Session {session.session_id}: stop_event triggered due to streaming exception")
            
            raise
        finally:
            await ws_client.disconnect()

# Global publisher instance
_publisher_instance: Optional[AudioStreamPublisher] = None

def get_publisher() -> AudioStreamPublisher:
    """获取全局AudioStreamPublisher实例"""
    global _publisher_instance
    if _publisher_instance is None:
        _publisher_instance = AudioStreamPublisher()
    return _publisher_instance