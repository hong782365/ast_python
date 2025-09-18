import asyncio
import logging
import time

from .models import TranslateRequestData, Audio
from .proto_helpers import send_request

async def send_silence_until_ready(conn, session_id, audio_ready_event, timeout_seconds=8):
    """Send silence frames until audio is ready"""
    silence_chunk = b'\x00' * 640  # 640 bytes of silence (20ms at 16kHz mono s16le)
    silence_start_time = time.monotonic()
    frame_count = 0
    
    logging.info(f"🔇 Starting silence bridge (timeout: {timeout_seconds}s)")
    
    try:
        while not audio_ready_event.is_set():
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
            
            # Log every 50 frames (1 second)
            if frame_count % 50 == 0:
                logging.info(f"🔇 Silence bridge: {frame_count} frames sent ({elapsed:.1f}s)")
            
            # Wait 20ms for next frame
            await asyncio.sleep(0.02)
        
        # Audio is ready
        silence_duration = time.monotonic() - silence_start_time
        if audio_ready_event.is_set():
            logging.info(f"🔇 Silence bridge completed: {frame_count} frames sent in {silence_duration:.2f}s")
        return silence_duration, frame_count
        
    except Exception as e:
        silence_duration = time.monotonic() - silence_start_time
        logging.error(f"🔇 Silence bridge error after {silence_duration:.2f}s: {e}")
        import traceback
        logging.error(f"🔇 Silence bridge traceback: {traceback.format_exc()}")
        return silence_duration, frame_count