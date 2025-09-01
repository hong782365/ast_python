#!/usr/bin/env python3

"""
FFmpeg 基础工具函数
提供FFmpeg路径检测、环境判断等通用功能
"""

import os
import shutil


def is_cloudflare_environment():
    """Detect if running in Cloudflare Containers environment"""
    # Method 1: Check for Cloudflare-specific environment variables
    if os.getenv("CF_PAGES") == "1":
        return True
    if os.getenv("CLOUDFLARE_ENVIRONMENT") == "production":
        return True
    if os.getenv("DEPLOY_ENV") == "cloudflare":
        return True
    
    # Method 2: Check for Cloudflare container characteristics
    if os.path.exists("/usr/local/bin/ffmpeg"):
        return True
    
    # Method 3: Check if we're in a container-like environment with specific paths
    container_indicators = [
        "/app",  # Common container app directory
        "/.dockerenv"  # Docker environment indicator
    ]
    
    # If multiple container indicators exist, likely in Cloudflare
    indicators_found = sum(1 for path in container_indicators if os.path.exists(path))
    
    # Additional heuristic: check if we're not in typical local dev paths
    local_dev_indicators = [
        "/Users",  # macOS
        "/home",   # Linux home directories
        "/opt/homebrew"  # Homebrew on macOS
    ]
    
    has_local_indicators = any(os.path.exists(path) for path in local_dev_indicators)
    
    # If we have container indicators but no local dev indicators, likely Cloudflare
    if indicators_found > 0 and not has_local_indicators:
        return True
    
    return False


def get_ffmpeg_path():
    """Detect FFmpeg path based on environment"""
    # Production paths (Cloudflare/Docker)
    production_paths = [
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
        "/app/ffmpeg",
        "/opt/ffmpeg/bin/ffmpeg"
    ]
    
    # Local development path (macOS with Homebrew)
    local_path = "/opt/homebrew/Caskroom/miniforge/base/bin/ffmpeg"
    
    # First try local development path
    if os.path.exists(local_path):
        return local_path
    
    # Then try production paths
    for path in production_paths:
        if os.path.exists(path):
            return path
    
    # Finally, try to find ffmpeg in PATH
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path
    
    # If nothing found, raise an error
    raise FileNotFoundError("FFmpeg not found. Please install FFmpeg or set the correct path.")