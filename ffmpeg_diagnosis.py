#!/usr/bin/env python3

"""
FFmpeg 诊断工具
提供单命令诊断和综合诊断功能，用于调试线上FFmpeg问题
"""

import asyncio
import os
import subprocess
import sys
import time
import logging
from ffmpeg_utils import get_ffmpeg_path, is_cloudflare_environment


async def diagnose_ffmpeg_command(ffmpeg_args, timeout=30):
    """
    独立的 FFmpeg 诊断函数，用于调试线上问题
    使用 FFREPORT + stderr=PIPE 捕获完整的 FFmpeg 日志
    """
    start_time = time.time()
    result = {
        "success": False,
        "ffmpeg_version": None,
        "execution_time": 0,
        "chunks_generated": 0,
        "stderr_log": [],
        "report_log": [],
        "error": None,
        "environment": "cloudflare" if is_cloudflare_environment() else "local"
    }
    
    try:
        # 设置环境变量，让 FFmpeg report 输出到 stderr
        env = os.environ.copy()
        env["FFREPORT"] = "file=/dev/stderr:level=48"
        
        logging.info(f"🔧 DIAGNOSE: Starting FFmpeg diagnosis with command: {' '.join(ffmpeg_args)}")
        print(f"🔧 CLOUDFLARE_DIAGNOSE: Starting FFmpeg diagnosis", file=sys.stderr, flush=True)
        print(f"🔧 CLOUDFLARE_DIAGNOSE: Command: {' '.join(ffmpeg_args)}", file=sys.stderr, flush=True)
        
        # 创建进程，stdout 和 stderr 都用 PIPE 捕获
        proc = subprocess.Popen(
            ffmpeg_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env
        )
        
        # 异步读取 stderr 和 stdout
        async def read_stderr():
            stderr_lines = []
            try:
                # 使用线程池读取 stderr（因为 stderr 是阻塞的）
                import concurrent.futures
                loop = asyncio.get_event_loop()
                
                def read_stderr_blocking():
                    lines = []
                    try:
                        for line in iter(proc.stderr.readline, b''):
                            if not line:
                                break
                            line_str = line.decode('utf-8', errors='ignore').rstrip()
                            lines.append(line_str)
                            # 实时输出到 stderr 和日志
                            logging.info(f"🔧 FFMPEG_STDERR: {line_str}")
                            print(f"🔧 CLOUDFLARE_FFMPEG: {line_str}", file=sys.stderr, flush=True)
                    except Exception as e:
                        logging.error(f"🔧 DIAGNOSE: Error reading stderr: {e}")
                    return lines
                
                stderr_lines = await loop.run_in_executor(None, read_stderr_blocking)
            except Exception as e:
                logging.error(f"🔧 DIAGNOSE: Error in stderr reader: {e}")
                stderr_lines.append(f"Error reading stderr: {e}")
            
            return stderr_lines
        
        async def read_stdout():
            stdout_chunks = 0
            try:
                loop = asyncio.get_event_loop()
                
                def read_stdout_blocking():
                    chunks = 0
                    try:
                        while True:
                            chunk = proc.stdout.read(640)  # 读取 640 字节 PCM 数据
                            if not chunk:
                                break
                            chunks += 1
                            if chunks <= 5:  # 只记录前5个chunk
                                logging.info(f"🔧 DIAGNOSE: Received stdout chunk {chunks}: {len(chunk)} bytes")
                                print(f"🔧 CLOUDFLARE_DIAGNOSE: Received stdout chunk {chunks}: {len(chunk)} bytes", file=sys.stderr, flush=True)
                                
                            # For diagnostic commands like -version, don't read too much
                            if chunks >= 100:  # Limit to prevent hanging
                                break
                    except Exception as e:
                        logging.error(f"🔧 DIAGNOSE: Error reading stdout: {e}")
                    return chunks
                
                stdout_chunks = await loop.run_in_executor(None, read_stdout_blocking)
            except Exception as e:
                logging.error(f"🔧 DIAGNOSE: Error in stdout reader: {e}")
            
            return stdout_chunks
        
        # 等待进程完成或超时
        try:
            stderr_task = asyncio.create_task(read_stderr())
            stdout_task = asyncio.create_task(read_stdout())
            
            # 等待超时或进程完成
            done, pending = await asyncio.wait(
                [stderr_task, stdout_task],
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Check if we timed out
            if pending:
                # We timed out, cancel pending tasks
                for task in pending:
                    task.cancel()
                raise asyncio.TimeoutError()
            
            stderr_lines = await stderr_task
            chunks_count = await stdout_task
            
            # 等待进程结束
            proc.wait()
            
        except asyncio.TimeoutError:
            logging.warning(f"🔧 DIAGNOSE: FFmpeg diagnosis timed out after {timeout}s")
            print(f"🔧 CLOUDFLARE_DIAGNOSE: FFmpeg diagnosis timed out after {timeout}s", file=sys.stderr, flush=True)
            proc.kill()
            proc.wait()
            
            stderr_lines = []
            chunks_count = 0
            result["error"] = f"Timeout after {timeout} seconds"
        
        # 处理结果
        execution_time = time.time() - start_time
        result["execution_time"] = execution_time
        result["chunks_generated"] = chunks_count
        result["stderr_log"] = stderr_lines
        
        # 解析 FFmpeg 版本信息
        for line in stderr_lines:
            if "ffmpeg version" in line.lower():
                result["ffmpeg_version"] = line
                break
        
        # 判断成功/失败
        return_code = proc.returncode
        if return_code == 0:
            result["success"] = True
            logging.info(f"🔧 DIAGNOSE: FFmpeg diagnosis completed successfully")
            print(f"🔧 CLOUDFLARE_DIAGNOSE: FFmpeg diagnosis completed successfully - Chunks: {chunks_count}, Time: {execution_time:.2f}s", file=sys.stderr, flush=True)
        else:
            result["error"] = f"FFmpeg exited with code {return_code}"
            logging.error(f"🔧 DIAGNOSE: FFmpeg diagnosis failed with exit code: {return_code}")
            print(f"🔧 CLOUDFLARE_DIAGNOSE: FFmpeg diagnosis failed - Exit code: {return_code}, Chunks: {chunks_count}, Time: {execution_time:.2f}s", file=sys.stderr, flush=True)
        
        # 分析关键问题
        analysis = []
        for line in stderr_lines:
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ["error", "failed", "timeout", "connection", "refused", "unavailable"]):
                analysis.append(line)
        
        if analysis:
            result["key_issues"] = analysis
            print(f"🔧 CLOUDFLARE_DIAGNOSE: Key issues found: {len(analysis)}", file=sys.stderr, flush=True)
            for issue in analysis[:3]:  # 只输出前3个关键问题
                print(f"🔧 CLOUDFLARE_ISSUE: {issue}", file=sys.stderr, flush=True)
        
    except Exception as e:
        result["error"] = f"Diagnosis failed: {str(e)}"
        result["execution_time"] = time.time() - start_time
        logging.error(f"🔧 DIAGNOSE: Diagnosis exception: {e}")
        print(f"🔧 CLOUDFLARE_ERROR: Diagnosis exception - {e}", file=sys.stderr, flush=True)
        import traceback
        logging.error(f"🔧 DIAGNOSE: Traceback: {traceback.format_exc()}")
    
    return result


async def comprehensive_ffmpeg_diagnosis(timeout_per_test=10):
    """
    综合 FFmpeg 诊断，运行所有预设的测试用例
    """
    ffmpeg_path = get_ffmpeg_path()
    is_cloudflare = is_cloudflare_environment()
    
    diagnosis_result = {
        "environment": "cloudflare" if is_cloudflare else "local",
        "ffmpeg_path": ffmpeg_path,
        "total_execution_time": 0,
        "tests": [],
        "summary": {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "crashed": 0
        }
    }
    
    start_time = time.time()
    
    # 定义测试用例
    test_cases = [
        {
            "name": "version_check",
            "description": "FFmpeg 版本信息",
            "command": [ffmpeg_path, "-version"],
            "expected_chunks": 0,
            "timeout": 5
        },
        {
            "name": "protocols_check", 
            "description": "支持的协议列表",
            "command": [ffmpeg_path, "-protocols"],
            "expected_chunks": 0,
            "timeout": 5
        },
        {
            "name": "demuxers_check",
            "description": "支持的解封装器",
            "command": [ffmpeg_path, "-demuxers"],
            "expected_chunks": 0,
            "timeout": 5
        },
        {
            "name": "sine_wave_test",
            "description": "合成正弦波音频（无网络）",
            "command": [ffmpeg_path, "-f", "lavfi", "-i", "sine=frequency=1000:duration=3", 
                       "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "s16le", "-y", "pipe:1"],
            "expected_chunks": 240,  # 3秒 * 16000/640 ≈ 75 chunks
            "timeout": 8
        },
        {
            "name": "simple_http_test",
            "description": "简单 HTTP 音频文件",
            "command": [ffmpeg_path, "-i", "https://www.wavsource.com/snds_2020-10-01_3728627494378403/sfx/come_get_it.wav",
                       "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "s16le", "-t", "3", "-y", "pipe:1"],
            "expected_chunks": 75,
            "timeout": 15
        },
        {
            "name": "youtube_hls_test",
            "description": "你的问题 YouTube HLS 流",
            "command": [ffmpeg_path, "-hide_banner", "-report", "-loglevel", "verbose", "-fflags", "nobuffer",
                       "-i", "https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1756714624/ei/IAK1aP7wOOjmxN8Ph9vfwQM/ip/104.28.155.125/id/t6_BU_GrG7w.1/itag/91/source/yt_live_broadcast/requiressl/yes/ratebypass/yes/live/1/sgoap/gir%3Dyes%3Bitag%3D139/sgovp/gir%3Dyes%3Bitag%3D160/rqh/1/hls_chunk_host/rr5---sn-apn7en7l.googlevideo.com/xpc/EgVo2aDSNQ%3D%3D/playlist_duration/30/manifest_duration/30/ss/1/siu/1/bui/AY1jyLO1pebu2ik37KZ_xQXU5AwGiM0qHPqOJhH1SIwv882RMg1CcYvxldNIGdIZS1LloG1M5Q/spc/l3OVKf8khKw0XTSDuHBDiWZGDlBvzq_mMyeKSokic8dBzZwkcyg-qhn1LuDMtOLWkbL1XycVO5TFX852GJwP__VJCy_qsC9JFjRu9KcZOINIL8I/vprv/1/playlist_type/DVR/initcwndbps/2377500/met/1756693025,/mh/f_/mm/44/mn/sn-apn7en7l/ms/lva/mv/m/mvi/5/pl/24/rms/lva,lva/dover/11/pacing/0/keepalive/yes/fexp/51355912,51552689,51565116,51565681,51580968/mt/1756692509/sparams/expire,ei,ip,id,itag,source,requiressl,ratebypass,live,sgoap,sgovp,rqh,xpc,playlist_duration,manifest_duration,ss,siu,bui,spc,vprv,playlist_type/sig/AJfQdSswRAIgYuUoNhYESqPvI0hz94nk7MMVfvHZh7dbO-SdSOaCYFACICP2H73dbuwjalCKmwIRuztmGUgUaTub-8zxNXg-DlJA/lsparams/hls_chunk_host,initcwndbps,met,mh,mm,mn,ms,mv,mvi,pl,rms/lsig/APaTxxMwRgIhAKY_C5sPwioUWII4Lx6mzr1X_Vcc0VqKAGFJdwEEb8uaAiEAhbj6Pu3tEn0sizUWxzz1foW-x0fD_7-aB5qA0rn-W_s%3D/playlist/index.m3u8",
                       "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "s16le", "-t", "5", "-y", "pipe:1"],
            "expected_chunks": 125,  # 5秒
            "timeout": 20
        }
    ]
    
    print(f"🔧 CLOUDFLARE_COMPREHENSIVE: Starting comprehensive FFmpeg diagnosis - {len(test_cases)} tests", file=sys.stderr, flush=True)
    
    # 逐个运行测试
    for i, test_case in enumerate(test_cases):
        test_start_time = time.time()
        test_result = {
            "name": test_case["name"],
            "description": test_case["description"],
            "success": False,
            "execution_time": 0,
            "chunks_generated": 0,
            "error": None,
            "status": "unknown",
            "stderr_summary": []
        }
        
        diagnosis_result["tests"].append(test_result)
        diagnosis_result["summary"]["total_tests"] += 1
        
        try:
            print(f"🔧 CLOUDFLARE_TEST[{i+1}/{len(test_cases)}]: {test_case['name']} - {test_case['description']}", file=sys.stderr, flush=True)
            
            # 运行单个测试
            result = await diagnose_ffmpeg_command(test_case["command"], timeout=test_case["timeout"])
            
            test_result["success"] = result["success"]
            test_result["execution_time"] = result["execution_time"]
            test_result["chunks_generated"] = result["chunks_generated"]
            test_result["error"] = result["error"]
            
            # 提取关键 stderr 信息
            if result["stderr_log"]:
                test_result["stderr_summary"] = result["stderr_log"][:5]  # 前5行
            
            # 分析测试状态
            if result["success"]:
                if test_case["name"] in ["version_check", "protocols_check", "demuxers_check"]:
                    # 信息查询类测试，成功即通过
                    test_result["status"] = "passed"
                    diagnosis_result["summary"]["passed"] += 1
                elif result["chunks_generated"] > 0:
                    # 音频生成类测试，需要有音频输出
                    test_result["status"] = "passed"
                    diagnosis_result["summary"]["passed"] += 1
                else:
                    # 成功但没有音频输出
                    test_result["status"] = "no_audio"
                    diagnosis_result["summary"]["failed"] += 1
            else:
                # 检查是否是崩溃
                if result["error"] and "code -11" in result["error"]:
                    test_result["status"] = "crashed"
                    diagnosis_result["summary"]["crashed"] += 1
                else:
                    test_result["status"] = "failed"
                    diagnosis_result["summary"]["failed"] += 1
            
            print(f"🔧 CLOUDFLARE_TEST_RESULT[{i+1}]: {test_case['name']} - {test_result['status']} - Chunks: {result['chunks_generated']}, Time: {result['execution_time']:.2f}s", file=sys.stderr, flush=True)
            
            # 如果是崩溃测试，后续测试可能也会崩溃，但我们继续测试以获得完整信息
            if test_result["status"] == "crashed":
                print(f"🔧 CLOUDFLARE_WARNING: Test {test_case['name']} crashed with SIGSEGV, continuing with other tests", file=sys.stderr, flush=True)
                
        except Exception as e:
            test_result["error"] = f"Test execution failed: {str(e)}"
            test_result["status"] = "exception" 
            diagnosis_result["summary"]["failed"] += 1
            print(f"🔧 CLOUDFLARE_TEST_ERROR[{i+1}]: {test_case['name']} - Exception: {e}", file=sys.stderr, flush=True)
    
    diagnosis_result["total_execution_time"] = time.time() - start_time
    
    # 生成综合分析
    analysis = []
    
    # FFmpeg 基础功能分析
    version_test = next((t for t in diagnosis_result["tests"] if t["name"] == "version_check"), None)
    if version_test and version_test["status"] == "passed":
        analysis.append("✅ FFmpeg 基础功能正常")
    else:
        analysis.append("❌ FFmpeg 基础功能异常")
    
    # 网络功能分析
    http_test = next((t for t in diagnosis_result["tests"] if t["name"] == "simple_http_test"), None)
    if http_test and http_test["status"] == "passed":
        analysis.append("✅ HTTP 网络功能正常")
    elif http_test and http_test["status"] == "crashed":
        analysis.append("❌ HTTP 网络访问导致崩溃")
    else:
        analysis.append("⚠️  HTTP 网络功能异常")
    
    # HLS 功能分析
    hls_test = next((t for t in diagnosis_result["tests"] if t["name"] == "youtube_hls_test"), None)
    if hls_test and hls_test["status"] == "passed":
        analysis.append("✅ YouTube HLS 流处理正常")
    elif hls_test and hls_test["status"] == "crashed":
        analysis.append("🔴 YouTube HLS 流导致 FFmpeg 崩溃 (SIGSEGV)")
    else:
        analysis.append("❌ YouTube HLS 流处理失败")
    
    # 音频处理分析
    sine_test = next((t for t in diagnosis_result["tests"] if t["name"] == "sine_wave_test"), None)
    if sine_test and sine_test["status"] == "passed":
        analysis.append("✅ 音频编码处理正常")
    else:
        analysis.append("❌ 音频编码处理异常")
    
    diagnosis_result["analysis"] = analysis
    
    # 添加与测试脚本兼容的字段
    diagnosis_result["total_tests"] = diagnosis_result["summary"]["total_tests"]
    diagnosis_result["passed_tests"] = diagnosis_result["summary"]["passed"] 
    diagnosis_result["failed_tests"] = diagnosis_result["summary"]["failed"] + diagnosis_result["summary"]["crashed"]
    diagnosis_result["success_rate"] = diagnosis_result["summary"]["passed"] / max(diagnosis_result["summary"]["total_tests"], 1)
    diagnosis_result["test_results"] = diagnosis_result["tests"]
    
    print(f"🔧 CLOUDFLARE_COMPREHENSIVE: Diagnosis completed - {diagnosis_result['summary']['passed']} passed, {diagnosis_result['summary']['failed']} failed, {diagnosis_result['summary']['crashed']} crashed", file=sys.stderr, flush=True)
    
    return diagnosis_result