import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import yt_dlp

from core.config import BASE_DIR
from .logger import YtdlpLogger

class YtDlpManager:
    """常驻yt-dlp解析器管理器，提供预热和高效的URL提取"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytdlp")
        self.ydl_opts = {
            'quiet': True,  # 减少输出
            'no_warnings': True,
            # 'verbose': True,
            # 'format': '234/233/140/bestaudio[ext=m4a]/bestaudio',  # 音频优先级
            'format': 'bestaudio[protocol^=m3u8]/bestaudio/140/91/92/93/94/95/96/best', # '234/233/140/bestaudio[ext=m4a]/bestaudio',  # 音频优先级
            # "extractor_args": {  # 目前这个参数不报错了, 但还没验证其效果, 暂时先注释了.
            #     "youtube": {
            #         "player_client": ["ios", "web"],
            #         "player_skip": ["webpage"]
            #     }
            # },
            'forcejson': False,
            'extract_flat': False,
            'writethumbnail': False,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': False,
        }
        self._ydl = None
        self._warmed_up = False
        self.warmup_url = "https://www.youtube.com/watch?v=G3_Um0yIsow"  # 公共预热视频: 3 秒倒计时(纯人声)
        
    def _create_ydl_instance(self):
        """创建yt-dlp实例"""
        if self._ydl is None:
            logger = YtdlpLogger()
            # 添加代理配置
            opts = self.ydl_opts.copy()
            # opts['proxy'] = 'http://127.0.0.1:7897'
            # 添加cookie支持 - 从文件读取
            cookie_file = BASE_DIR / "youtube" / "cookie" / "youtube_hongc_cookies.txt"
            if cookie_file.exists():
                opts['cookiefile'] = str(cookie_file)
                logging.info(f"🍪 Loading cookies from: {cookie_file}")
            else:
                logging.warning(f"🍪 Cookie file not found: {cookie_file}")
            # 强制IPv4
            opts['forceipv4'] = True

            opts['logger'] = logger
            
            self._ydl = yt_dlp.YoutubeDL(opts)
        return self._ydl
            
    async def warmup(self):
        """预热yt-dlp实例，预编译JS和缓存设置"""
        if self._warmed_up:
            logging.info("🔥 yt-dlp already warmed up, skipping...")
            return
            
        logging.info("🔥 Starting yt-dlp warmup with public video...")
        warmup_start_time = time.time()
        
        try:
            # 在线程池中运行yt-dlp预热
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor, self._warmup_sync)
            
            warmup_elapsed = time.time() - warmup_start_time
            logging.info(f"🔥 yt-dlp warmup completed in {warmup_elapsed:.2f}s")
            self._warmed_up = True
            
        except Exception as e:
            logging.warning(f"🔥 yt-dlp warmup failed (will continue anyway): {e}")
            # 即使预热失败也继续，不影响主流程
            self._warmed_up = True
    
    def _warmup_sync(self):
        """同步预热方法，在线程池中执行"""
        try:
            ydl = self._create_ydl_instance()
            # 只验证yt-dlp实例创建和基本配置，不实际提取视频
            # 这样可以预热库本身而无需网络访问
            logging.info(f"🔥 yt-dlp instance created successfully")
            logging.info(f"🔥 Warmup options: {ydl.params}")
            
            # 使用轻量级的URL提取进行网络预热
            try:
                # 仅提取基本信息和URL，不下载
                info = ydl.extract_info(self.warmup_url, download=False, process=True)
                
                # 检查是否成功获取到格式信息
                formats = info.get('formats', [])
                if formats:
                    # 查找最佳音频格式的URL（类似于--get-url功能）
                    audio_formats = [f for f in formats if f.get('acodec') != 'none']
                    if audio_formats:
                        best_url = audio_formats[0].get('url', '')
                        logging.info(f"🔥 Network warmup successful - extracted URL (length: {len(best_url)})")
                        logging.info(f"🔥 Video title: {info.get('title', 'Unknown')[:50]}...")
                    else:
                        logging.info(f"🔥 Partial warmup - no audio formats found")
                else:
                    logging.info(f"🔥 Partial warmup - no formats extracted")
                    
            except Exception as net_e:
                logging.info(f"🔥 Network warmup skipped (network issue): {net_e}")
                # 网络预热失败不影响整体预热成功
                
        except Exception as e:
            logging.warning(f"🔥 Warmup failed: {e}")
            raise
    
    async def extract_stream_url(self, youtube_url: str) -> str:
        """异步提取YouTube直播流URL"""
        logging.info("📡 Extracting stream URL with yt-dlp library...")
        extract_start_time = time.time()
        
        try:
            # 在线程池中运行yt-dlp以避免阻塞事件循环
            loop = asyncio.get_event_loop()
            stream_url = await loop.run_in_executor(
                self.executor, 
                self._extract_stream_url_sync, 
                youtube_url
            )
            
            extract_elapsed = time.time() - extract_start_time
            logging.info(f"📡 Stream URL extracted in {extract_elapsed:.2f}s")
            logging.info(f"📡 Stream URL: {stream_url}")
            
            return stream_url
            
        except Exception as e:
            logging.error(f"📡 Failed to extract stream URL: {e}")
            raise
    
    def _extract_stream_url_sync(self, youtube_url: str) -> str:
        """同步提取URL方法，在线程池中执行"""
        try:
            ydl = self._create_ydl_instance()
            info = ydl.extract_info(youtube_url, download=False)
            
            # 查找最佳音频格式的URL
            formats = info.get('formats', [])
            if not formats:
                raise ValueError("No formats found for this video")
            
            # 按照优先级查找音频流
            audio_formats = [f for f in formats if f.get('acodec') != 'none']
            if not audio_formats:
                raise ValueError("No audio formats found for this video")
            
            # 优先选择format_id为234/233/140的格式
            preferred_ids = ['234', '233', '140']
            for format_id in preferred_ids:
                for fmt in audio_formats:
                    if fmt.get('format_id') == format_id:
                        return fmt['url']
            
            # 如果没找到首选格式，使用第一个可用的音频格式
            return audio_formats[0]['url']
            
        except Exception as e:
            logging.error(f"📡 Sync URL extraction failed: {e}")
            raise
    
    def cleanup(self):
        """清理资源"""
        if self.executor:
            self.executor.shutdown(wait=True)
        if self._ydl:
            # yt-dlp实例通常不需要显式清理
            self._ydl = None

# 全局管理器实例
_manager: Optional[YtDlpManager] = None

def get_manager() -> YtDlpManager:
    """获取全局yt-dlp管理器实例"""
    global _manager
    if _manager is None:
        _manager = YtDlpManager()
    return _manager