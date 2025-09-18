#!/usr/bin/env python3
"""
简单测试脚本，验证直播状态检查功能
"""
import asyncio
import logging
from ast_youtube_demo import ytdlp_manager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def test_live_check():
    """测试直播状态检查"""
    # 测试URL (需要根据实际情况调整)
    test_urls = [
        # 普通视频 (应该返回 NOT_LIVE)
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        # 直播URL (需要替换为实际的直播链接)
        # "https://www.youtube.com/watch?v=LIVE_VIDEO_ID",
    ]
    
    print("🔍 开始测试直播状态检查功能...")
    
    # 初始化 yt-dlp 管理器
    try:
        print("📡 初始化 yt-dlp 管理器...")
        await ytdlp_manager.warmup()
        print("✅ yt-dlp 管理器初始化完成")
    except Exception as e:
        print(f"❌ yt-dlp 管理器初始化失败: {e}")
        return
    
    for i, url in enumerate(test_urls, 1):
        print(f"\n--- 测试 {i}: {url} ---")
        
        try:
            # 调用检查函数
            live_info = await ytdlp_manager.check_live_status(url)
            
            print(f"✅ 检查完成:")
            print(f"  is_live: {live_info.get('is_live')}")
            print(f"  live_status: {live_info.get('live_status')}")
            print(f"  title: {live_info.get('title', 'N/A')}")
            print(f"  error: {live_info.get('error')}")
            
            # 测试判断逻辑
            def is_live_valid(live_info):
                if live_info.get('error'):
                    return False, "LIVE_STATUS_UNKNOWN"
                
                is_live = live_info.get('is_live')
                live_status = live_info.get('live_status')
                
                if is_live is True or live_status == "is_live":
                    return True, None
                
                if live_status == "is_upcoming":
                    return False, "LIVE_NOT_STARTED"
                elif live_status == "was_live":
                    return False, "LIVE_ENDED" 
                elif is_live is False:
                    return False, "NOT_LIVE"
                else:
                    return False, "LIVE_STATUS_UNKNOWN"
            
            is_valid, error_code = is_live_valid(live_info)
            print(f"  判断结果: valid={is_valid}, error_code={error_code}")
            
        except Exception as e:
            print(f"❌ 检查失败: {e}")
            import traceback
            print(f"详细错误: {traceback.format_exc()}")
    
    # 清理
    ytdlp_manager.cleanup()
    print(f"\n🎉 测试完成！")

if __name__ == "__main__":
    try:
        asyncio.run(test_live_check())
    except KeyboardInterrupt:
        print("\n⚠️ 测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")