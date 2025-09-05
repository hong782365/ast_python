#!/usr/bin/env python3
"""
测试脚本：验证 FinishSession 事件发送修复

测试场景：
1. 启动 ingest session
2. 等待几秒让流开始
3. 调用 stop 接口
4. 验证是否收到 FinishSession 的响应（UsageResponse 和 SessionFinished）
"""

import asyncio
import time
import logging
import os
import json
import websockets
from pathlib import Path

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class FinishSessionTestClient:
    def __init__(self, publish_url: str):
        self.publish_url = publish_url
        self.websocket = None
        self.received_messages = []
        self.usage_response_received = False
        self.session_finished_received = False
        
    async def connect(self):
        """连接到发布端 WebSocket"""
        try:
            self.websocket = await websockets.connect(self.publish_url)
            logging.info(f"Connected to publisher at {self.publish_url}")
            return True
        except Exception as e:
            logging.error(f"Failed to connect to publisher: {e}")
            return False
    
    async def listen_for_messages(self, timeout_seconds=60):
        """监听来自发布端的消息"""
        if not self.websocket:
            logging.error("Not connected to publisher")
            return
            
        start_time = time.time()
        try:
            while True:
                # 检查超时
                if time.time() - start_time > timeout_seconds:
                    logging.warning(f"Listen timeout after {timeout_seconds}s")
                    break
                
                try:
                    # 设置较短的接收超时避免永久阻塞
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=2.0)
                    
                    # 尝试解析消息
                    try:
                        # 如果是文本消息，尝试解析JSON
                        if isinstance(message, str):
                            parsed = json.loads(message)
                            self.received_messages.append(parsed)
                            logging.info(f"Received text message: {parsed}")
                            
                            # 检查是否是系统事件
                            if parsed.get("type") == "system_event":
                                if parsed.get("event") == "UsageResponse":
                                    self.usage_response_received = True
                                    logging.info("✅ UsageResponse received!")
                                elif parsed.get("event") == "SessionFinished":
                                    self.session_finished_received = True
                                    logging.info("✅ SessionFinished received!")
                        else:
                            # 二进制消息（音频数据）
                            self.received_messages.append({"type": "audio_data", "length": len(message)})
                            if len(self.received_messages) % 10 == 1:  # 每10个音频包记录一次
                                logging.info(f"Received audio data: {len(message)} bytes")
                    except json.JSONDecodeError:
                        # 如果不是JSON，可能是音频数据
                        self.received_messages.append({"type": "binary_data", "length": len(message)})
                        
                except asyncio.TimeoutError:
                    # 接收超时，继续循环检查总体超时
                    continue
                except Exception as e:
                    logging.error(f"Error receiving message: {e}")
                    break
                    
        except Exception as e:
            logging.error(f"Listen error: {e}")
        finally:
            if self.websocket:
                await self.websocket.close()
    
    def get_test_results(self):
        """获取测试结果"""
        return {
            "total_messages": len(self.received_messages),
            "usage_response_received": self.usage_response_received,
            "session_finished_received": self.session_finished_received,
            "messages": self.received_messages[-5:] if self.received_messages else []  # 最后5条消息
        }

async def test_finish_session_fix():
    """主测试函数"""
    # 测试配置
    PUBLISHER_BASE_URL = "http://localhost:9000"
    WS_PUBLISH_URL = "ws://localhost:8080/ws"  # 替换为实际的发布端地址
    YOUTUBE_URL = "https://www.youtube.com/watch?v=HHGEDLPBIxA"  # 测试视频
    SESSION_ID = f"test_session_{int(time.time())}"
    
    logging.info("🚀 开始 FinishSession 修复测试")
    
    # 步骤1：连接到发布端监听消息
    test_client = FinishSessionTestClient(WS_PUBLISH_URL)
    connected = await test_client.connect()
    
    if not connected:
        logging.error("❌ 无法连接到发布端，跳过测试")
        return False
    
    # 启动消息监听任务
    listen_task = asyncio.create_task(test_client.listen_for_messages(timeout_seconds=90))
    
    # 等待一秒让连接稳定
    await asyncio.sleep(1)
    
    # 步骤2：启动 ingest session
    logging.info("📡 启动 ingest session...")
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            start_payload = {
                "sessionId": SESSION_ID,
                "youtube_url": YOUTUBE_URL,
                "publishUrl": WS_PUBLISH_URL
            }
            
            async with session.post(f"{PUBLISHER_BASE_URL}/python/ingest/start", json=start_payload) as resp:
                if resp.status in [200, 201, 202]:
                    start_result = await resp.json()
                    logging.info(f"✅ Ingest started: {start_result}")
                else:
                    error_text = await resp.text()
                    logging.error(f"❌ Failed to start ingest: {resp.status} - {error_text}")
                    await listen_task
                    return False
            
            # 步骤3：等待一段时间让流开始传输
            logging.info("⏱️ 等待10秒让流开始传输...")
            await asyncio.sleep(10)
            
            # 步骤4：调用 stop 接口
            logging.info("🛑 停止 ingest session...")
            stop_payload = {"sessionId": SESSION_ID}
            
            async with session.post(f"{PUBLISHER_BASE_URL}/python/ingest/stop", json=stop_payload) as resp:
                if resp.status == 200:
                    stop_result = await resp.json()
                    logging.info(f"✅ Ingest stopped: {stop_result}")
                else:
                    error_text = await resp.text()
                    logging.error(f"❌ Failed to stop ingest: {resp.status} - {error_text}")
            
            # 步骤5：等待宽限期，观察是否收到 FinishSession 响应
            logging.info("⏱️ 等待40秒观察 FinishSession 响应...")
            await asyncio.sleep(40)
            
    except Exception as e:
        logging.error(f"❌ HTTP 请求失败: {e}")
        await listen_task
        return False
    
    # 完成监听
    await listen_task
    
    # 步骤6：分析结果
    results = test_client.get_test_results()
    logging.info("📊 测试结果分析:")
    logging.info(f"  - 总共收到消息: {results['total_messages']}")
    logging.info(f"  - 收到 UsageResponse: {'✅' if results['usage_response_received'] else '❌'}")
    logging.info(f"  - 收到 SessionFinished: {'✅' if results['session_finished_received'] else '❌'}")
    
    # 输出最后几条消息用于调试
    if results['messages']:
        logging.info("  - 最后几条消息:")
        for i, msg in enumerate(results['messages'][-3:], 1):
            logging.info(f"    {i}. {msg}")
    
    # 判断测试是否通过
    test_passed = results['usage_response_received'] and results['session_finished_received']
    
    if test_passed:
        logging.info("🎉 测试通过！FinishSession 事件修复成功")
    else:
        logging.error("❌ 测试失败！可能需要进一步调试")
        
        # 提供调试建议
        if not results['usage_response_received']:
            logging.error("   - 未收到 UsageResponse，检查翻译服务是否正常响应")
        if not results['session_finished_received']:
            logging.error("   - 未收到 SessionFinished，检查会话是否正常结束")
    
    return test_passed

if __name__ == "__main__":
    try:
        # 检查依赖
        try:
            import aiohttp
        except ImportError:
            logging.error("❌ 需要安装 aiohttp: pip install aiohttp")
            exit(1)
            
        # 运行测试
        result = asyncio.run(test_finish_session_fix())
        exit(0 if result else 1)
        
    except KeyboardInterrupt:
        logging.info("⚠️ 测试被用户中断")
        exit(1)
    except Exception as e:
        logging.error(f"❌ 测试执行失败: {e}")
        exit(1)