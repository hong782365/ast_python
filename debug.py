#!/usr/bin/env python3
import subprocess
import time
import signal
import sys

def run_ast_demo():
    for i in range(1, 101):  # 循环100次
        print(f"\n=== 开始第 {i}/100 次运行 ===")

        # 启动子进程
        proc = subprocess.Popen(["python3", "ast_demo.py"])

        try:
            # 等待5秒
            time.sleep(5)

            # 发送SIGINT (Ctrl+C)
            proc.send_signal(signal.SIGINT)

            # 等待进程结束
            proc.wait(timeout=2)
            print(f"第 {i} 次运行已正常终止")

        except subprocess.TimeoutExpired:
            print("进程未在超时时间内结束，强制终止")
            proc.terminate()
            proc.wait(timeout=1)

        except KeyboardInterrupt:
            print("\n用户中断，退出脚本")
            proc.terminate()
            sys.exit(0)

        except Exception as e:
            print(f"第 {i} 次运行出现异常: {str(e)}")
            proc.terminate()

if __name__ == "__main__":
    run_ast_demo()
    print("\n=== 所有100次运行完成 ===")