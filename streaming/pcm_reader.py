import asyncio
import logging
import time

async def read_pcm_chunks(pcm_stream, chunk_size: int = 640, ffmpeg_process=None, audio_ready_event=None, ffmpeg_spawn_time=None):
    """Read PCM data in chunks (640 bytes = 20ms at 16kHz mono s16le)"""
    import asyncio
    loop = asyncio.get_event_loop()
    chunk_count = 0
    first_chunk_received = False
    consecutive_timeouts = 0  # 连续超时计数
    max_consecutive_timeouts = 3  # 连续超时阈值
    
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
                # 成功读取，重置连续超时计数
                consecutive_timeouts = 0
                
            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                
                # 首包超时：立即结束（兼容广告/播放列表warmup场景）
                if chunk_count == 0:
                    logging.error("🔴 Timeout waiting for first PCM chunk - ffmpeg may be stuck or stream unavailable")
                    break
                
                # 后续包：连续超时阈值检测
                logging.warning(f"⏰ PCM读取超时 #{consecutive_timeouts}/{max_consecutive_timeouts} (chunk {chunk_count + 1})")
                
                if consecutive_timeouts >= max_consecutive_timeouts:
                    # 连续超时达到阈值，判定为真实断流
                    logging.error(f"🔴 连续{max_consecutive_timeouts}次超时，判定为直播流中断")
                    
                    # Check FFmpeg process status on final timeout
                    if ffmpeg_process:
                        if ffmpeg_process.poll() is not None:
                            logging.error(f"⏰ FFmpeg process exited (code: {ffmpeg_process.returncode})")
                        else:
                            logging.error(f"⏰ FFmpeg still running (PID: {ffmpeg_process.pid}) but stream seems ended")
                    break
                else:
                    # 未达阈值，继续重试
                    logging.info(f"🔄 第{consecutive_timeouts}次超时，继续重试 (阈值: {max_consecutive_timeouts})")
                    continue
            
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
                    # Output critical first chunk timing to stderr for performance monitoring
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