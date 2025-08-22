#!/usr/bin/env python3
"""
Test script for optimized YouTube live streaming
测试优化后的YouTube直播流功能
"""

import asyncio
import logging
import time
from ast_youtube_demo import translate_youtube_live_stream, Config
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

async def test_optimized_streaming():
    """Test the optimized streaming with parallel startup and silence bridge"""
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Check environment variables
    APP_KEY = os.getenv("APP_KEY")
    ACCESS_KEY = os.getenv("ACCESS_KEY")
    RESOURCE_ID = os.getenv("RESOURCE_ID")
    WS_URL = os.getenv("WS_URL")
    
    if not all([APP_KEY, ACCESS_KEY, RESOURCE_ID, WS_URL]):
        logging.error("Missing required environment variables. Please check your .env file.")
        return
    
    conf = Config(
        ws_url=WS_URL,
        app_key=APP_KEY,
        access_key=ACCESS_KEY,
        resource_id=RESOURCE_ID
    )
    
    # Test URL (replace with a live stream URL)
    youtube_url = "https://www.youtube.com/watch?v=HHGEDLPBIxA"
    duration_seconds = 30  # Test with 30 seconds
    
    logging.info(f"🧪 Testing optimized YouTube live translation for {duration_seconds} seconds")
    logging.info(f"📺 YouTube URL: {youtube_url}")
    
    total_start_time = time.monotonic()
    
    try:
        # Test the generator function
        stream_count = 0
        audio_chunks = 0
        subtitle_messages = 0
        
        async for stream_data in translate_youtube_live_stream(conf, youtube_url, duration_seconds):
            stream_count += 1
            
            if stream_data.data_type == "audio":
                audio_chunks += 1
                if audio_chunks == 1:
                    logging.info(f"🎵 First audio chunk received: {len(stream_data.content)} bytes")
                elif audio_chunks % 10 == 0:
                    logging.info(f"🎵 Audio chunk #{audio_chunks}: {len(stream_data.content)} bytes")
            
            elif stream_data.data_type == "subtitle":
                subtitle_messages += 1
                logging.info(f"📝 Subtitle #{subtitle_messages}: {stream_data.content}")
            
            # Stop after reasonable amount of data for testing
            if stream_count >= 100:
                logging.info(f"🧪 Test limit reached: {stream_count} stream items processed")
                break
        
        total_duration = time.monotonic() - total_start_time
        
        logging.info(f"🧪 Test completed in {total_duration:.2f}s")
        logging.info(f"📊 Statistics:")
        logging.info(f"   - Total stream items: {stream_count}")
        logging.info(f"   - Audio chunks: {audio_chunks}")
        logging.info(f"   - Subtitle messages: {subtitle_messages}")
        
    except Exception as e:
        logging.error(f"🧪 Test failed: {e}")
        import traceback
        logging.error(f"🧪 Traceback: {traceback.format_exc()}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(test_optimized_streaming())
    except KeyboardInterrupt:
        logging.info("🧪 Test interrupted by user")
    except Exception as e:
        logging.error(f"🧪 Unexpected test error: {e}")
