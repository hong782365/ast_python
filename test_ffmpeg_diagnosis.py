#!/usr/bin/env python3

"""
FFmpeg 诊断测试脚本
用于测试线上 FFmpeg 命令是否正常工作
"""

import asyncio
import ast_youtube_demo as demo

async def test_real_ffmpeg_command():
    """测试实际的 FFmpeg 命令（简化版）"""
    
    # 获取正确的 FFmpeg 路径
    ffmpeg_path = demo.get_ffmpeg_path()
    
    # 你的原始命令（简化后用于测试）
    original_cmd = [
        "ffmpeg", "-hide_banner", "-report", "-loglevel", "verbose", 
        "-fflags", "nobuffer", 
        "-i", "https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1756663786/ei/iju0aIySAvWKvdIPrOS4sAM/ip/104.28.158.11/id/1D1etqfl54Q.1/itag/91/source/yt_live_broadcast/requiressl/yes/ratebypass/yes/live/1/sgoap/gir%3Dyes%3Bitag%3D139/sgovp/gir%3Dyes%3Bitag%3D160/rqh/1/hls_chunk_host/rr13---sn-2on4v5-5j.googlevideo.com/xpc/EgVo2aDSNQ%3D%3D/playlist_duration/30/manifest_duration/30/ss/1/siu/1/bui/AY1jyLNm9f7Sxk56a-SUBFjdt3JkRLSNJAvzLeG2yx_pAnc0ZI61wMHdHvUKlcs5HbZYBlDc2A/spc/l3OVKd3h1Ai2mwAslqUEcH4kwHR4WDy9d6STaDS4g40yXyhxjbZBJPBAFOTRBZ-Tkg7dvZBE19EXsFlIVqq6DurxOnt_zC3tcui-DeopmOPx_4g/vprv/1/playlist_type/DVR/initcwndbps/975000/met/1756642186,/mh/tI/mm/44/mn/sn-2on4v5-5j/ms/lva/mv/m/mvi/13/pl/24/rms/lva,lva/dover/11/pacing/0/keepalive/yes/fexp/51355912,51552689,51565116,51565681,51580968/mt/1756641645/sparams/expire,ei,ip,id,itag,source,requiressl,ratebypass,live,sgoap,sgovp,rqh,xpc,playlist_duration,manifest_duration,ss,siu,bui,spc,vprv,playlist_type/sig/AJfQdSswRQIgQOcnM1c09bfa68lru0ESp2Rc9VctJHYk3wykAmnCg48CIQC_1N8ietG4pOs1ODwZ2A4kyDjtpLkjLCNUbCS7tjl9Uw%3D%3D/lsparams/hls_chunk_host,initcwndbps,met,mh,mm,mn,ms,mv,mvi,pl,rms/lsig/APaTxxMwRgIhANqkrku1_R9LOv5iJnRShopJCaHvTT2FrHLjLWs3MctoAiEA7XYleLDv_0jxooHmxTzJBrsUXzZYYgMBsHRXUnoFzio%3D/playlist/index.m3u8", 
        "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "s16le", "-t", "3600", "-y", "pipe:1"
    ]
    
    # 替换第一个参数为正确的路径
    test_cmd = [ffmpeg_path] + original_cmd[1:]
    
    print("🔧 Testing your original FFmpeg command...")
    print(f"🔧 FFmpeg path: {ffmpeg_path}")
    print(f"🔧 Command length: {len(test_cmd)} args")
    print(f"🔧 Input URL: ...{test_cmd[6][-50:]}...")  # 显示URL末尾50个字符
    
    try:
        # 测试较短的时间，避免长时间运行
        limited_cmd = test_cmd[:-4] + ["-t", "10", "-y", "pipe:1"]  # 限制到10秒
        
        result = await demo.diagnose_ffmpeg_command(limited_cmd, timeout=15)
        
        print("\n📊 诊断结果:")
        print(f"  ✅ 成功: {result['success']}")
        print(f"  🌐 环境: {result['environment']}")
        print(f"  ⏱️  执行时间: {result['execution_time']:.2f}s")
        print(f"  🎵 音频chunk数量: {result['chunks_generated']}")
        print(f"  📝 错误信息: {result['error']}")
        print(f"  📋 stderr日志行数: {len(result['stderr_log'])}")
        
        if result.get('key_issues'):
            print(f"  ⚠️  关键问题: {len(result['key_issues'])}个")
            for issue in result['key_issues'][:3]:
                print(f"    - {issue}")
        
        if result['stderr_log']:
            print("\n📄 前几行stderr日志:")
            for i, line in enumerate(result['stderr_log'][:5]):
                print(f"  {i+1}: {line}")
        
        # 分析结果
        if result['success'] and result['chunks_generated'] > 0:
            print("\n✅ 结论: FFmpeg 命令在本地运行正常，能够生成音频数据")
        elif result['success'] and result['chunks_generated'] == 0:
            print("\n⚠️  结论: FFmpeg 启动成功但没有生成音频数据，可能是网络或流问题")
        else:
            print("\n❌ 结论: FFmpeg 命令执行失败")
            
        return result
        
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_simple_ffmpeg():
    """测试简单的 FFmpeg 功能"""
    ffmpeg_path = demo.get_ffmpeg_path()
    
    print("\n🔧 测试 FFmpeg 基础功能...")
    
    # 测试版本信息
    version_cmd = [ffmpeg_path, "-version"]
    result = await demo.diagnose_ffmpeg_command(version_cmd, timeout=3)
    
    if result['success']:
        print("✅ FFmpeg 版本检测成功")
        print(f"  版本信息: {result.get('ffmpeg_version', 'Unknown')}")
    else:
        print("❌ FFmpeg 版本检测失败")
        return False
    
    # 测试协议支持
    protocols_cmd = [ffmpeg_path, "-protocols"]
    result = await demo.diagnose_ffmpeg_command(protocols_cmd, timeout=3)
    
    if result['success']:
        protocols = [line for line in result['stderr_log'] if 'http' in line.lower()]
        if protocols:
            print("✅ HTTP 协议支持正常")
        else:
            print("⚠️  未检测到 HTTP 协议支持")
    else:
        print("❌ 协议检测失败")
    
    return True

async def main():
    """主测试函数"""
    print("🚀 开始 FFmpeg 诊断测试")
    print("=" * 50)
    
    # 检测环境
    is_cf = demo.is_cloudflare_environment()
    print(f"🌐 运行环境: {'Cloudflare' if is_cf else 'Local'}")
    
    # 测试基础功能
    basic_ok = await test_simple_ffmpeg()
    if not basic_ok:
        print("❌ 基础测试失败，终止测试")
        return
    
    print("\n" + "=" * 50)
    
    # 测试实际命令
    result = await test_real_ffmpeg_command()
    
    print("\n" + "=" * 50)
    print("🎯 诊断完成!")
    
    if result:
        if result['success'] and result['chunks_generated'] > 0:
            print("✅ 你的 FFmpeg 命令在当前环境下运行正常")
        else:
            print("❌ 你的 FFmpeg 命令存在问题，需要进一步调试")
            print("💡 建议: 检查网络连接、URL有效性、FFmpeg版本兼容性")

if __name__ == "__main__":
    asyncio.run(main())