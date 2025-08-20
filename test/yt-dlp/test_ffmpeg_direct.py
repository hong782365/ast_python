import subprocess

# 请务必将下面的 URL 替换成你从第 1 步得到的那个
M3U8_URL = "https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1755704140/ei/7JalaMXBHPCYvcAPvr-88Ag/ip/2a11:3:200::3004/id/m_dhMSvUCIc.5/itag/234/source/yt_live_broadcast/requiressl/yes/ratebypass/yes/live/1/goi/133/sgoap/gir%3Dyes%3Bitag%3D140/rqh/1/hls_chunk_host/rr4---sn-ntqe6nel.googlevideo.com/xpc/EgVo2aDSNQ%3D%3D/playlist_duration/30/manifest_duration/30/bui/AY1jyLPY6qmZWCbOSUP9X0K8vLb2YotwMy0zfpBUY3PmU6y4g_dRy87qVxYJ3xmxX49pPDPqAHuJBTFj/spc/l3OVKZnjomUpL52aoaV1mNDSXnvjmMCrEwdhCK4PDJ5lPmOgy16qohAofUDlww/vprv/1/playlist_type/DVR/initcwndbps/8978750/met/1755682542,/mh/V0/mm/44/mn/sn-ntqe6nel/ms/lva/mv/m/mvi/4/pl/48/rms/lva,lva/dover/13/pacing/0/short_key/1/keepalive/yes/fexp/51548755,51565116,51565682,51580968/mt/1755681633/sparams/expire,ei,ip,id,itag,source,requiressl,ratebypass,live,goi,sgoap,rqh,xpc,playlist_duration,manifest_duration,bui,spc,vprv,playlist_type/sig/AJfQdSswRQIhANZklKKEAXTFeDbd5kkDgerRYkJChbMR3BFbqMYZNaySAiAZX3S8QkJ4-9VWbpixfMbdt70qK3fK2HVpFlBs35H0DQ%3D%3D/lsparams/hls_chunk_host,initcwndbps,met,mh,mm,mn,ms,mv,mvi,pl,rms/lsig/APaTxxMwRAIgWGsO8MH7o5kKk03h2lP_bQGME6M00ZIDHvkbzmEfFB0CIAz6Kjsp-ROLRZoUvbPRFLki0CTTzXYkBfukbKvdsi_E/playlist/index.m3u8"

FFMPEG_CMD = [
    "/opt/homebrew/bin/ffmpeg",  # 使用绝对路径确保一致
    "-http_proxy", "http://127.0.0.1:7897",
    "-i", M3U8_URL,
    "-t", "10",
    "-c", "copy",
    "test_python.ts"
]

print("--- 在 Python 中执行 FFMPEG 命令 ---")
print(" ".join(FFMPEG_CMD))

# 执行命令并等待完成，捕获所有输出
result = subprocess.run(FFMPEG_CMD, capture_output=True, text=True)

print("\n--- 执行完毕 ---")
print(f"返回码: {result.returncode}")
print("\n--- STDOUT ---")
print(result.stdout)
print("\n--- STDERR ---")
print(result.stderr)