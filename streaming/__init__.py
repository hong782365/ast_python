# 导入 core.config 确保配置初始化
import core.config

# 导出主要接口
from .models import Config, StreamData
from .pipeline import translate_youtube_live_stream
from .ytdlp_manager import get_manager

# 可选的其他导出
from .logger import ASTEventLogger
from .streamer import YouTubeLiveStreamer

__all__ = [
    'Config',
    'StreamData', 
    'translate_youtube_live_stream',
    'get_manager',
    'ASTEventLogger',
    'YouTubeLiveStreamer'
]