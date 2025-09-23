import asyncio
import logging
import time

from core.config import AUDIO_CHUNK_SIZE, AUDIO_CHUNK_SLEEP_SECONDS, AUDIO_LOG_INTERVAL
from .models import TranslateRequestData, Audio
from .proto_helpers import send_request

async def send_silence_until_ready(conn, session_id, audio_ready_event, translation_allowed_event=None, timeout_seconds=8):
    """Send silence frames until audio is ready and translation is allowed"""
    silence_chunk = b'\x00' * AUDIO_CHUNK_SIZE  # Configurable silence chunk size
    silence_start_time = time.monotonic()
    frame_count = 0
    
    logging.info(f"🔇 Starting silence bridge (timeout: {timeout_seconds}s)")
    
    try:
        while True:
            # 检查双重条件
            audio_ready = audio_ready_event.is_set()
            translation_allowed = translation_allowed_event.is_set() if translation_allowed_event else True
            
            if audio_ready and translation_allowed:
                logging.info(f"🎵 Both conditions met, stopping silence bridge after {frame_count} frames")
                break
            
            # Check timeout
            elapsed = time.monotonic() - silence_start_time
            if elapsed >= timeout_seconds:
                logging.warning(f"🔇 Silence bridge timeout after {elapsed:.2f}s, {frame_count} frames sent")
                break
            
            # Send silence frame
            chunk_request = TranslateRequestData(
                session_id=session_id,
                event="Type_TaskRequest",
                source_audio=Audio(binary_data=silence_chunk)
            )
            
            await send_request(conn, chunk_request, log_raw=False)
            frame_count += 1
            
            # Log every AUDIO_LOG_INTERVAL frames (~1 second)
            if frame_count % AUDIO_LOG_INTERVAL == 0:
                logging.info(
                    f"🔇 Silence bridge: {frame_count} frames sent ({elapsed:.1f}s), "
                    f"audio_ready={audio_ready}, translation_allowed={translation_allowed}"
                )
            
            # Wait for next frame interval
            await asyncio.sleep(AUDIO_CHUNK_SLEEP_SECONDS)
        
        # Both conditions are met
        silence_duration = time.monotonic() - silence_start_time
        logging.info(f"🔇 Silence bridge completed: {frame_count} frames sent in {silence_duration:.2f}s")
        return silence_duration, frame_count
        
    except Exception as e:
        silence_duration = time.monotonic() - silence_start_time
        logging.error(f"🔇 Silence bridge error after {silence_duration:.2f}s: {e}")
        import traceback
        logging.error(f"🔇 Silence bridge traceback: {traceback.format_exc()}")
        return silence_duration, frame_count