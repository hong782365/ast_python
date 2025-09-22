import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Define project paths
BASE_DIR = Path(__file__).resolve().parent.parent
PROTO_DIR = BASE_DIR / "python_protogen"

# Add protobuf path to sys.path if not already present
if str(PROTO_DIR) not in sys.path:
    sys.path.append(str(PROTO_DIR))

# Environment variables
APP_KEY = os.getenv("APP_KEY")
ACCESS_KEY = os.getenv("ACCESS_KEY")
RESOURCE_ID = os.getenv("RESOURCE_ID")
WS_URL = os.getenv("WS_URL")

# Configuration constants
SOURCE_LANGUAGE = "en"
TARGET_LANGUAGE = "zh"

# Audio streaming configuration
AUDIO_CHUNK_DURATION_MS = 80  # 关键参数：改成80解决AudioSendSlow问题
AUDIO_SAMPLE_RATE = 16000
AUDIO_BITS = 16
AUDIO_CHANNELS = 1

# Calculated derived values
AUDIO_CHUNK_SIZE = (AUDIO_CHUNK_DURATION_MS * AUDIO_SAMPLE_RATE * AUDIO_BITS * AUDIO_CHANNELS) // (8 * 1000)
AUDIO_CHUNK_SLEEP_SECONDS = AUDIO_CHUNK_DURATION_MS / 1000.0
AUDIO_LOG_INTERVAL = max(1, 1000 // AUDIO_CHUNK_DURATION_MS)  # 确保至少1秒日志一次

# Required environment variables for validation
REQUIRED_VARS = ["APP_KEY", "ACCESS_KEY", "RESOURCE_ID", "WS_URL"]

def setup_logging():
    """Setup logging configuration if not already configured."""
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

def validate_config():
    """Validate that all required environment variables are present."""
    missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")

def ensure_directories():
    """No-op function - all logging now goes to stdout/stderr."""
    pass