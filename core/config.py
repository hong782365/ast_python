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
LOG_DIR = BASE_DIR / "youtube" / "logs"
FFMPEG_REPORT_DIR = BASE_DIR / "youtube" / "ffmpeg" / "report"
FFMPEG_LOG_DIR = BASE_DIR / "youtube" / "ffmpeg" / "log"
AST_EVENT_DIR = BASE_DIR / "youtube" / "ast_event"

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
    """Ensure all required directories exist."""
    directories = [LOG_DIR, FFMPEG_REPORT_DIR, FFMPEG_LOG_DIR, AST_EVENT_DIR]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)