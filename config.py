import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Redis 配置
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_DB_BROKER = os.getenv('REDIS_DB_BROKER', '0')
REDIS_DB_BACKEND = os.getenv('REDIS_DB_BACKEND', '1')
REDIS_DB_CACHE = os.getenv('REDIS_DB_CACHE', '2')  # 用于存储API统计等缓存数据

# 构建Redis URL
def get_redis_url(db: str = REDIS_DB_CACHE) -> str:
    """获取Redis URL"""
    if REDIS_PASSWORD:
        return f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{db}"
    return f"redis://{REDIS_HOST}:{REDIS_PORT}/{db}"

# Celery Redis URLs
CELERY_BROKER_URL = get_redis_url(REDIS_DB_BROKER)
CELERY_RESULT_BACKEND = get_redis_url(REDIS_DB_BACKEND)

# Cache Redis URL
REDIS_CACHE_URL = get_redis_url(REDIS_DB_CACHE)

# YouTube API 配置
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# 其他配置...
APP_KEY = os.getenv('APP_KEY')
ACCESS_KEY = os.getenv('ACCESS_KEY')
RESOURCE_ID = os.getenv('RESOURCE_ID')
WS_URL = os.getenv('WS_URL')