import asyncio
import json
import logging
import os
import time
from typing import Optional

from core.config import SOURCE_LANGUAGE, TARGET_LANGUAGE, AUDIO_CHUNK_SLEEP_SECONDS, AUDIO_LOG_INTERVAL
from .models import Config, StreamData, SubtitleMessage, TranslateRequestData, TranslateResponseData, Audio
from .logger import ASTEventLogger
from .streamer import YouTubeLiveStreamer
from .proto_helpers import connect_websocket_and_start_session, send_request, receive_message
from .pcm_reader import read_pcm_chunks
from .silence_bridge import send_silence_until_ready

# Import protobuf types after ensuring path is set
from common.events_pb2 import Type

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

async def translate_youtube_live_stream(conf: Config, youtube_url: str, duration_seconds: int = None, stop_event: Optional[asyncio.Event] = None, finish_grace_timeout: float = 30.0, translation_allowed_event: Optional[asyncio.Event] = None):
    """Generator function that yields translated audio chunks from YouTube live stream"""
    streamer = YouTubeLiveStreamer(youtube_url, duration_seconds or 3600)  # Default 1 hour
    
    # 初始化事件日志记录器
    event_logger = ASTEventLogger(youtube_url)
    
    # Create events for coordination
    audio_ready_event = asyncio.Event()  # 首帧PCM就绪
    
    try:
        # 按审核者建议：分阶段启动，确保延迟最优
        logging.info("🚀 Starting optimized parallel initialization...")
        parallel_start_time = time.monotonic()
        
        # Phase 1: 启动WebSocket建联任务（优先级最高，需要立即获得conn）
        websocket_task = asyncio.create_task(
            connect_websocket_and_start_session(conf, SOURCE_LANGUAGE, TARGET_LANGUAGE, event_logger)
        )
        
        # Phase 2: 并行启动FFmpeg任务
        ffmpeg_task = asyncio.create_task(streamer.start_streaming_pipeline())
        
        # Phase 3: 优先等待WebSocket建联完成（获得conn以便立即启动静音桥）
        logging.info("🔗 Waiting for WebSocket connection...")
        conn, session_id, log_id, ws_connect_duration = await websocket_task
        websocket_ready_time = time.monotonic()
        
        logging.info(f"🔗 WebSocket ready in {websocket_ready_time - parallel_start_time:.2f}s (log_id={log_id})")
        
        # Create queues for communication (需要提前创建，用于错误处理)
        stream_queue = asyncio.Queue()  # Queue for both audio and subtitle data
        finished = asyncio.Event()
        
        # Phase 4: 🔥关键修复 - 立即启动静音桥（避免等包超时）
        logging.info("🔇 Starting silence bridge immediately to prevent timeout...")
        silence_task = asyncio.create_task(
            send_silence_until_ready(
                conn, session_id, audio_ready_event, translation_allowed_event, timeout_seconds=30
            )
        )
        
        # 🔥关键修复：在使用前定义函数避免NameError
        async def send_pcm_chunks():
            chunk_count = 0
            total_bytes = 0
            finish_sent = False  # 防止重复发送FinishSession
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
                    # 检查是否需要停止（外部stop请求）
                    if stop_event and stop_event.is_set():
                        logging.info(f"Stop event detected at chunk {chunk_count}, sending FinishSession and continuing to receive...")
                        break
                    
                    if not chunk:
                        logging.info("No more PCM chunks available")
                        break
                    
                    chunk_count += 1
                    total_bytes += len(chunk)
                    
                    # 🔥关键修改：双重条件检查
                    audio_ready = audio_ready_event.is_set()
                    translation_allowed = translation_allowed_event.is_set() if translation_allowed_event else True
                    
                    if not (audio_ready and translation_allowed):
                        # 条件未满足，丢弃这个PCM帧但保持管道畅通
                        if chunk_count % AUDIO_LOG_INTERVAL == 0:
                            logging.info(
                                f"🚫 Discarding PCM chunk {chunk_count} "
                                f"(audio_ready={audio_ready}, translation_allowed={translation_allowed})"
                            )
                        continue  # 继续读取下一个chunk但不发送
                    
                    # 双重条件都满足，发送真实PCM
                    if chunk_count == 1:
                        logging.info(f"🎵 First PCM chunk transmission started (both conditions met, chunk #{chunk_count})")
                    
                    # Log every AUDIO_LOG_INTERVAL chunks (about 1 second of audio)
                    if chunk_count % AUDIO_LOG_INTERVAL == 0:
                        logging.info(f"Sent {chunk_count} PCM chunks, {total_bytes} total bytes (conditions: audio_ready={audio_ready}, translation_allowed={translation_allowed})")
                    else:
                        logging.debug(f"Sending PCM chunk {chunk_count}: {len(chunk)} bytes")
                    
                    chunk_request = TranslateRequestData(
                        session_id=session_id,
                        event="Type_TaskRequest",
                        source_audio=Audio(binary_data=chunk)
                    )
                    
                    # 记录TaskRequest事件（只记录第一个和每AUDIO_LOG_INTERVAL个chunk以避免日志过多）
                    if chunk_count == 1 or chunk_count % AUDIO_LOG_INTERVAL == 0:
                        event_logger.log_send_event(Type.TaskRequest, chunk_request)
                    
                    await send_request(conn, chunk_request, log_raw=False)
                    await asyncio.sleep(AUDIO_CHUNK_SLEEP_SECONDS)  # Configurable delay to match chunk rate
                
                logging.info(f"Finished sending {chunk_count} PCM chunks, total {total_bytes} bytes")
                
            except Exception as e:
                logging.error(f"Error sending PCM chunks: {e}")
                import traceback
                logging.error(f"Send chunks traceback: {traceback.format_exc()}")
            finally:
                # 无论如何都要发送 FinishSession（自然结束或外部停止）
                if not finish_sent:
                    try:
                        finish_request = TranslateRequestData(
                            session_id=session_id,
                            event="Type_FinishSession",
                            source_audio=Audio()
                        )
                        
                        # 记录发送FinishSession事件
                        event_logger.log_send_event(Type.FinishSession, finish_request)
                        
                        await send_request(conn, finish_request)
                        finish_sent = True
                        logging.info("FinishSession request sent.")
                    except Exception as e:
                        logging.error(f"Error sending FinishSession: {e}")
                        # 即使FinishSession发送失败，也要设置finished避免无限等待
                        finished.set()
        
        async def receive_responses():
            grace_period_start = None
            try:
                while not finished.is_set():
                    try:
                        # ❗ 关键修复：从检测到 stop 开始就启用宽限期计时
                        if stop_event and stop_event.is_set() and grace_period_start is None:
                            grace_period_start = time.time()
                            logging.info(f"Started FinishSession grace period ({finish_grace_timeout}s) due to stop event")
                        
                        # 如果处于宽限期或检测到stop，使用较短的超时避免无限等待
                        timeout = 2.0 if (grace_period_start or (stop_event and stop_event.is_set())) else None
                        if timeout:
                            resp = await asyncio.wait_for(receive_message(conn), timeout=timeout)
                        else:
                            resp = await receive_message(conn)
                    except asyncio.TimeoutError:
                        # 宽限期超时检查
                        if grace_period_start:
                            elapsed = time.time() - grace_period_start
                            if elapsed >= finish_grace_timeout:
                                logging.warning(f"Grace period timeout ({finish_grace_timeout}s), ending receive loop")
                                finished.set()
                                break
                            else:
                                logging.debug(f"Grace period active: {elapsed:.1f}s/{finish_grace_timeout}s")
                                continue
                        elif stop_event and stop_event.is_set():
                            # stop 了但还没有宽限期，继续重试
                            logging.debug("Stop detected, continuing to wait for responses...")
                            continue
                        else:
                            # 不应该发生（没有超时设置却超时了）
                            logging.warning("Unexpected receive timeout")
                            continue
                    
                    # 记录接收到的事件
                    event_logger.log_receive_event(resp)
                    
                    logging.debug(
                        f"Received message (event={resp.event}, session_id={resp.session_id}): "
                        f"seq: {resp.sequence}, text: '{resp.text}', audio data length: {len(resp.data)}"
                    )
                    
                    if resp.event == Type.SessionFailed or resp.event == Type.SessionCanceled:
                        logging.error(f"Session failed, message: {resp.message} logid: {log_id}")
                        # 将错误信息作为特殊的 StreamData 传递给上层
                        await stream_queue.put(StreamData(data_type="error", content=resp.message))
                        finished.set()
                        break
                    
                    if resp.event == Type.SessionFinished:
                        logging.info("Translation session finished")
                        finished.set()
                        break
                    
                    # 宽限期计时已在上面统一处理，不再依赖 UsageResponse
                    
                    # Handle subtitle events (650-655)
                    subtitle_json = map_event_to_subtitle_json(resp)
                    if subtitle_json:
                        await stream_queue.put(StreamData(data_type="subtitle", content=subtitle_json))
                        logging.debug(f"Queued subtitle: {subtitle_json}")
                    
                    # Handle TTS audio data and text responses
                    if resp.data:
                        await stream_queue.put(StreamData(data_type="audio", content=resp.data))
                    
                    # 将重要的响应事件（如 UsageResponse）作为字幕转发
                    if resp.event in [Type.UsageResponse, Type.SessionFinished]:
                        response_info = {
                            "type": "system_event", 
                            "event": resp.event.name if hasattr(resp.event, 'name') else str(resp.event),
                            "message": resp.message if resp.message else None
                        }
                        if resp.event == Type.UsageResponse and resp.billing:
                            response_info["billing"] = {
                                "duration_msec": resp.billing.duration_msec,
                                "items": [{"unit": item.unit, "quantity": item.quantity} for item in resp.billing.items] if resp.billing.items else []
                            }
                        await stream_queue.put(StreamData(data_type="subtitle", content=json.dumps(response_info, ensure_ascii=False)))
                        
            except Exception as e:
                logging.error(f"Receive message error: {e}")
                import traceback
                logging.error(f"Receive message traceback: {traceback.format_exc()}")
                finished.set()
        
        # Phase 5: 等待FFmpeg就绪并立即启动PCM读取（丢弃模式直到检查通过）
        logging.info("🎵 Waiting for FFmpeg to be ready...")
        pcm_stream = await ffmpeg_task
        ffmpeg_ready_time = time.monotonic()
        logging.info(f"🎵 FFmpeg ready in {ffmpeg_ready_time - parallel_start_time:.2f}s")
        
        # Phase 6: 🔥关键修复 - 立即启动PCM读取任务（避免管道阻塞）
        logging.info("🎵 Starting PCM reading immediately (discard mode until audio ready)...")
        sender_task = asyncio.create_task(send_pcm_chunks())
        receiver_task = asyncio.create_task(receive_responses())
        
        # Phase 7: 初始化完成
        check_ready_time = time.monotonic()
        
        parallel_duration = time.monotonic() - parallel_start_time
        
        logging.info(f"🚀 All initialization completed in {parallel_duration:.2f}s")
        
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
            
            # ❗ 关键修复：使用 asyncio.shield 保护清理代码不被取消传播打断
            try:
                # 等待静音桥任务完成
                try:
                    silence_duration, silence_frames = await asyncio.shield(silence_task)
                    logging.info(f"🔇 Final silence bridge stats: {silence_frames} frames, {silence_duration:.2f}s")
                except Exception as e:
                    logging.error(f"🔇 Silence bridge task error: {e}")
                    import traceback
                    logging.error(f"🔇 Silence bridge task traceback: {traceback.format_exc()}")
                
                # 保护关键任务等待，确保 FinishSession 能完成
                await asyncio.shield(sender_task)
                await asyncio.shield(receiver_task)
                
                # 保护连接关闭
                await asyncio.shield(conn.close())
                
            except asyncio.CancelledError:
                # 即使被取消也要尝试基本清理
                logging.warning("Cleanup was cancelled, attempting basic cleanup")
                try:
                    if conn:
                        await conn.close()
                except:
                    pass
            
    except Exception as e:
        logging.error(f"Translation streaming error: {e}")
        import traceback
        logging.error(f"Translation streaming traceback: {traceback.format_exc()}")
    finally:
        await streamer.cleanup()