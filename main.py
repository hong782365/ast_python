#!/usr/bin/env python3

import sys
import os
import logging

# 导入并初始化配置
import core.config
core.config.setup_logging()

# 导入 FastAPI 应用
from publisher import app

if __name__ == "__main__":
    import uvicorn
    
    try:
        # 保留原有的启动日志信息
        host = "0.0.0.0"
        port = 9000
        
        logging.info("🚀 Publisher script starting...")
        logging.info(f"🚀 Starting FastAPI server on {host}:{port}")
        logging.info(f"🔧 Environment variables: HOST={os.getenv('HOST', 'not set')}")
        logging.info(f"🔧 Current working directory: {os.getcwd()}")
        logging.info(f"🔧 Python path: {sys.path}")
        
        uvicorn.run(
            app,
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