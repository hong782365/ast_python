#!/usr/bin/env python3

"""
FFmpeg 诊断 API 调用测试
演示如何通过 HTTP API 调用诊断功能
"""

import requests
import json
import time

# 你的实际 FFmpeg 命令（从 Cloudflare 日志复制）
ffmpeg_command = """ffmpeg -hide_banner -report -loglevel verbose -fflags nobuffer -i https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1756663786/ei/iju0aIySAvWKvdIPrOS4sAM/ip/104.28.158.11/id/1D1etqfl54Q.1/itag/91/source/yt_live_broadcast/requiressl/yes/ratebypass/yes/live/1/sgoap/gir%3Dyes%3Bitag%3D139/sgovp/gir%3Dyes%3Bitag%3D160/rqh/1/hls_chunk_host/rr13---sn-2on4v5-5j.googlevideo.com/xpc/EgVo2aDSNQ%3D%3D/playlist_duration/30/manifest_duration/30/ss/1/siu/1/bui/AY1jyLNm9f7Sxk56a-SUBFjdt3JkRLSNJAvzLeG2yx_pAnc0ZI61wMHdHvUKlcs5HbZYBlDc2A/spc/l3OVKd3h1Ai2mwAslqUEcH4kwHR4WDy9d6STaDS4g40yXyhxjbZBJPBAFOTRBZ-Tkg7dvZBE19EXsFlIVqq6DurxOnt_zC3tcui-DeopmOPx_4g/vprv/1/playlist_type/DVR/initcwndbps/975000/met/1756642186,/mh/tI/mm/44/mn/sn-2on4v5-5j/ms/lva/mv/m/mvi/13/pl/24/rms/lva,lva/dover/11/pacing/0/keepalive/yes/fexp/51355912,51552689,51565116,51565681,51580968/mt/1756641645/sparams/expire,ei,ip,id,itag,source,requiressl,ratebypass,live,sgoap,sgovp,rqh,xpc,playlist_duration,manifest_duration,ss,siu,bui,spc,vprv,playlist_type/sig/AJfQdSswRQIgQOcnM1c09bfa68lru0ESp2Rc9VctJHYk3wykAmnCg48CIQC_1N8ietG4pOs1ODwZ2A4kyDjtpLkjLCNUbCS7tjl9Uw%3D%3D/lsparams/hls_chunk_host,initcwndbps,met,mh,mm,mn,ms,mv,mvi,pl,rms/lsig/APaTxxMwRgIhANqkrku1_R9LOv5iJnRShopJCaHvTT2FrHLjLWs3MctoAiEA7XYleLDv_0jxooHmxTzJBrsUXzZYYgMBsHRXUnoFzio%3D/playlist/index.m3u8 -ac 1 -ar 16000 -acodec pcm_s16le -f s16le -t 3600 -y pipe:1"""

def test_local_api():
    """测试本地 API 端点"""
    # 本地测试用的URL
    api_url = "http://localhost:9000/python/debug/ffmpeg"
    
    # 请求数据
    payload = {
        "command": ffmpeg_command,
        "timeout": 30
    }
    
    print("🔧 测试本地 API 调用...")
    print(f"📡 API URL: {api_url}")
    print(f"🎯 命令: {ffmpeg_command[:100]}...")
    
    try:
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=35  # 略长于 FFmpeg timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            print("\n✅ API 调用成功!")
            print(f"  成功: {result['success']}")
            print(f"  环境: {result['environment']}")
            print(f"  执行时间: {result['execution_time']:.2f}s")
            print(f"  音频chunks: {result['chunks_generated']}")
            print(f"  错误: {result.get('error', 'None')}")
            print(f"  日志行数: {len(result['stderr_log'])}")
            
            if result.get('key_issues'):
                print(f"  关键问题: {len(result['key_issues'])}个")
                for issue in result['key_issues'][:3]:
                    print(f"    - {issue}")
            
            return result
        else:
            print(f"❌ API 调用失败: HTTP {response.status_code}")
            print(f"响应: {response.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败 - 请确保本地服务器正在运行")
        print("💡 启动方法: python publisher.py")
        return None
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
        return None
    except Exception as e:
        print(f"❌ 请求异常: {e}")
        return None

def test_comprehensive_diagnosis():
    """测试综合诊断 API"""
    api_url = "http://localhost:9000/python/debug/ffmpeg/comprehensive"
    
    print("\n🔍 测试综合诊断 API...")
    print(f"📡 API URL: {api_url}")
    print("⏱️  预计需要 30-60 秒完成所有测试...")
    
    try:
        start_time = time.time()
        response = requests.post(
            api_url,
            json={},
            headers={"Content-Type": "application/json"},
            timeout=120  # 综合测试需要更长时间
        )
        
        if response.status_code == 200:
            result = response.json()
            end_time = time.time()
            
            print(f"\n✅ 综合诊断完成! (耗时: {end_time - start_time:.1f}s)")
            print(f"  环境: {result['environment']}")
            
            # 支持新旧格式
            total_tests = result.get('total_tests', result.get('summary', {}).get('total_tests', 0))
            passed_tests = result.get('passed_tests', result.get('summary', {}).get('passed', 0))
            failed_tests = result.get('failed_tests', result.get('summary', {}).get('failed', 0) + result.get('summary', {}).get('crashed', 0))
            success_rate = result.get('success_rate', passed_tests / max(total_tests, 1) if total_tests > 0 else 0)
            test_results = result.get('test_results', result.get('tests', []))
            
            print(f"  总测试数: {total_tests}")
            print(f"  通过: {passed_tests}")
            print(f"  失败: {failed_tests}")
            print(f"  成功率: {success_rate:.1%}")
            
            print(f"\n📋 测试结果详情:")
            for i, test in enumerate(test_results, 1):
                status = "✅" if test.get('success', test.get('status') == 'passed') else "❌"
                test_name = test.get('test_name', test.get('name', test.get('description', f'Test {i}')))
                execution_time = test.get('execution_time', 0)
                print(f"  {i}. {status} {test_name} ({execution_time:.2f}s)")
                if not test.get('success', test.get('status') == 'passed'):
                    error = test.get('error') or f"Status: {test.get('status', 'unknown')}"
                    print(f"     错误: {error}")
            
            if result.get('analysis'):
                print(f"\n💡 分析结果:")
                for analysis in result['analysis']:
                    print(f"  - {analysis}")
            
            return result
        else:
            print(f"❌ 综合诊断失败: HTTP {response.status_code}")
            print(f"响应: {response.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败 - 请确保本地服务器正在运行")
        print("💡 启动方法: python publisher.py")
        return None
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
        return None
    except Exception as e:
        print(f"❌ 请求异常: {e}")
        return None

def test_cloudflare_api():
    """测试 Cloudflare Workers API"""
    # 替换为你的实际 Cloudflare Workers URL
    api_url = "https://your-worker.your-subdomain.workers.dev/python/debug/ffmpeg"
    
    payload = {
        "command": ffmpeg_command,
        "timeout": 30
    }
    
    print("\n🌐 测试 Cloudflare Workers API 调用...")
    print(f"📡 API URL: {api_url}")
    print("⚠️  注意: 请将上面的URL替换为你的实际 Cloudflare Workers 地址")
    
    # 这里只是示例，不会真正调用
    print("\n📋 单个命令测试示例:")
    print("curl -X POST 'https://your-worker.your-subdomain.workers.dev/python/debug/ffmpeg' \\")
    print("  -H 'Content-Type: application/json' \\")
    print("  -d '{")
    print(f'    "command": "{ffmpeg_command[:80]}...",')
    print('    "timeout": 30')
    print("  }'")
    
    print("\n📋 综合诊断测试示例:")
    print("curl -X POST 'https://your-worker.your-subdomain.workers.dev/python/debug/ffmpeg/comprehensive' \\")
    print("  -H 'Content-Type: application/json' \\")
    print("  -d '{}'")

def show_usage_guide():
    """显示使用指南"""
    print("\n📖 使用指南:")
    print("=" * 40)
    print("1. 启动本地服务器:")
    print("   python publisher.py")
    print("")
    print("2. 测试单个命令:")
    print("   python test_api_call.py")
    print("")
    print("3. 或者直接调用API:")
    print("   # 单个命令诊断")
    print("   curl -X POST http://localhost:9000/python/debug/ffmpeg -H 'Content-Type: application/json' -d '{\"command\":\"ffmpeg -version\", \"timeout\":10}'")
    print("")
    print("   # 综合诊断")
    print("   curl -X POST http://localhost:9000/python/debug/ffmpeg/comprehensive -H 'Content-Type: application/json' -d '{}'")
    print("")
    print("4. Cloudflare 环境:")
    print("   将本地 URL 替换为你的 Cloudflare Workers URL")
    print("   注意: 保持 /python/debug/ffmpeg 路径不变")

def main():
    print("🚀 FFmpeg 诊断 API 测试套件")
    print("=" * 60)
    
    # 显示使用指南
    show_usage_guide()
    
    print("\n" + "=" * 60)
    print("🔧 开始本地测试...")
    
    # 测试单个命令
    print("\n1️⃣  测试单个 FFmpeg 命令诊断:")
    single_result = test_local_api()
    
    # 测试综合诊断
    print("\n2️⃣  测试综合诊断:")
    comprehensive_result = test_comprehensive_diagnosis()
    
    # 显示 Cloudflare 示例
    test_cloudflare_api()
    
    print("\n" + "=" * 60)
    print("🎯 测试完成!")
    
    # 总结结果
    if single_result or comprehensive_result:
        print("\n📊 测试总结:")
        
        if single_result:
            if single_result['success'] and single_result.get('chunks_generated', 0) > 0:
                print("✅ 单个命令测试: FFmpeg 运行正常，生成了音频数据")
            elif single_result['success']:
                print("⚠️  单个命令测试: FFmpeg 启动成功但没有生成音频数据")
                print("   💡 可能原因: URL过期、网络问题、流不可用")
            else:
                print("❌ 单个命令测试: FFmpeg 执行失败")
        
        if comprehensive_result:
            success_rate = comprehensive_result.get('success_rate', 0)
            if success_rate >= 0.8:
                print("✅ 综合诊断: FFmpeg 环境基本正常")
            elif success_rate >= 0.5:
                print("⚠️  综合诊断: FFmpeg 环境部分功能正常")
            else:
                print("❌ 综合诊断: FFmpeg 环境存在严重问题")
            
            print(f"   测试通过率: {success_rate:.1%}")
    else:
        print("❌ 所有测试都失败了")
        print("💡 请确保:")
        print("  1. 本地服务器正在运行 (python publisher.py)")
        print("  2. 端口 9000 没有被占用")
        print("  3. FFmpeg 已正确安装")

if __name__ == "__main__":
    main()