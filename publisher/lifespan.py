import logging
import time
from contextlib import asynccontextmanager

from core.config import validate_config, ensure_directories
from streaming import get_manager

@asynccontextmanager
async def lifespan(app):
    """FastAPI应用生命周期管理"""
    # 启动时执行
    logging.info("🚀 Publisher starting up - validating configuration...")
    
    try:
        # 验证配置
        validate_config()
        logging.info("✅ Configuration validation passed")
        
        # 确保目录存在
        ensure_directories()
        logging.info("✅ Required directories created")
        
        # 初始化yt-dlp管理器
        init_start_time = time.time()
        ytdlp_manager = get_manager()
        await ytdlp_manager.warmup()
        init_elapsed_time = time.time() - init_start_time
        logging.info(f"🚀 yt-dlp manager initialization completed in {init_elapsed_time:.2f}s")
    except Exception as e:
        logging.error(f"❌ Publisher startup failed: {e}")
        raise
    
    yield
    
    # 关闭时执行
    logging.info("🔥 Publisher shutting down - cleaning up yt-dlp manager...")
    try:
        ytdlp_manager = get_manager()
        ytdlp_manager.cleanup()
        logging.info("🔥 yt-dlp manager cleanup completed")
    except Exception as e:
        logging.error(f"🔥 yt-dlp manager cleanup failed: {e}")