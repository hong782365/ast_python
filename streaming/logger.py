import json
import logging
import re
import time
import hashlib
from pathlib import Path
from typing import Optional

from core.config import AST_EVENT_DIR, SOURCE_LANGUAGE, TARGET_LANGUAGE
from .models import TranslateRequestData, TranslateResponseData, BillingItemData

# Import protobuf types after ensuring path is set
from products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse
from common.events_pb2 import Type

def safe_serialize_protobuf(pb_obj):
    """
    安全序列化protobuf对象为字典，用于JSON输出
    - 递归遍历已设置的字段
    - 二进制字段替换为"二进制数据"字符串
    - 保持原始字段名和结构
    """
    from google.protobuf.descriptor import FieldDescriptor
    
    def serialize_value(field_descriptor, value):
        # 处理二进制字段
        if isinstance(value, bytes) or field_descriptor.type == FieldDescriptor.TYPE_BYTES:
            return "二进制数据"
        
        # 处理重复字段（列表）
        if field_descriptor.label == FieldDescriptor.LABEL_REPEATED:
            return [serialize_value_single(field_descriptor, item) for item in value]
        else:
            return serialize_value_single(field_descriptor, value)
    
    def serialize_value_single(field_descriptor, value):
        # 处理嵌套消息
        if field_descriptor.type == FieldDescriptor.TYPE_MESSAGE:
            return safe_serialize_protobuf(value)  # 递归处理
        
        # 处理枚举（输出原始数值）
        elif field_descriptor.type == FieldDescriptor.TYPE_ENUM:
            return int(value)
        
        # 处理二进制
        elif isinstance(value, bytes) or field_descriptor.type == FieldDescriptor.TYPE_BYTES:
            return "二进制数据"
        
        # 处理标量值（字符串、整数、浮点、布尔）
        else:
            return value
    
    if not hasattr(pb_obj, 'ListFields'):
        # 不是protobuf对象，直接返回
        return pb_obj
    
    result = {}
    try:
        # 遍历所有已设置的字段
        for field_descriptor, value in pb_obj.ListFields():
            try:
                field_name = field_descriptor.name
                result[field_name] = serialize_value(field_descriptor, value)
            except Exception as e:
                # 跳过异常字段，记录警告
                import sys
                print(f"WARN: 序列化字段 {field_descriptor.name} 失败: {e}", file=sys.stderr, flush=True)
                continue
    except Exception as e:
        import sys
        print(f"WARN: protobuf序列化失败: {e}", file=sys.stderr, flush=True)
        return {"error": "序列化失败"}
    
    return result

def log_protobuf_message(pb_obj, prefix=""):
    """
    打印protobuf对象的原始结构到stderr
    - 单行JSON格式
    - 带时间戳前缀
    - 立即flush
    """
    import json
    import time
    import sys
    
    try:
        # 安全序列化
        serialized = safe_serialize_protobuf(pb_obj)
        
        # 生成时间戳
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"
        
        # 单行JSON输出
        json_str = json.dumps(serialized, ensure_ascii=False, separators=(',', ':'))
        
        # 输出到stderr
        log_line = f"{timestamp} {prefix} {json_str}"
        print(log_line, file=sys.stderr, flush=True)
        
    except Exception as e:
        # 序列化失败的异常处理
        print(f"ERROR: protobuf日志输出失败: {e}", file=sys.stderr, flush=True)

class ASTEventLogger:
    """事件日志记录器，用于记录同声传译的事件消息"""
    
    def __init__(self, youtube_url: str):
        self.youtube_url = youtube_url
        self.youtube_id = self._extract_youtube_id(youtube_url)
        
        # 创建日志文件
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"ast_{timestamp}_{self.youtube_id}.txt"
        
        # 确保目录存在
        self.log_dir = AST_EVENT_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.log_dir / filename
        
        # 事件类型映射
        self.event_descriptions = {
            # 发送端事件
            Type.StartSession: "建联请求-StartSession-100",
            Type.UpdateConfig: "更新参数-UpdateConfig-201", 
            Type.TaskRequest: "发送音频数据-TaskRequest-200",
            Type.FinishSession: "结束session-FinishSession-102",
            
            # 接收端事件
            Type.SessionStarted: "建联成功-SessionStarted-150",
            Type.SourceSubtitleStart: "原文开始-SourceSubtitleStart-650",
            Type.SourceSubtitleEnd: "原文结束-SourceSubtitleEnd-652",
            Type.TranslationSubtitleStart: "译文开始-TranslationSubtitleStart-653", 
            Type.TranslationSubtitleEnd: "译文结束-TranslationSubtitleEnd-655",
            Type.TTSSentenceStart: "TTS开始-TTSSentenceStart-350",
            Type.TTSSentenceEnd: "TTS结束-TTSSentenceEnd-351",
            Type.UsageResponse: "计量计费-UsageResponse-154",
            Type.SessionFinished: "会话正常结束-SessionFinished-152",
            Type.SessionFailed: "会话失败-SessionFailed-153",
            Type.AudioMuted: "静音事件-AudioMuted-250"
        }
        
        logging.info(f"AST事件日志文件创建: {self.log_file}")
    
    def _extract_youtube_id(self, url: str) -> str:
        """从YouTube URL中提取视频ID"""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([^&\n?#]+)',
            r'youtube\.com/live/([^&\n?#]+)',
            r'youtube\.com/channel/([^&\n?#/]+)',
            r'youtube\.com/c/([^&\n?#/]+)',
            r'youtube\.com/@([^&\n?#/]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # 如果没有匹配到，使用URL的哈希值作为后备
        return hashlib.md5(url.encode()).hexdigest()[:8]
    
    def log_send_event(self, event_type: Type, request_data: TranslateRequestData):
        """记录发送端事件"""
        if event_type not in self.event_descriptions:
            return
            
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S,") + str(int(time.time() * 1000) % 1000).zfill(3)
        description = self.event_descriptions[event_type]
        
        # 构建JSON数据
        event_name = f"Type_{event_type.name}" if hasattr(event_type, 'name') else f"event.Type_{event_type}"
        json_data = {
            "event": event_name,
            "session_id": request_data.session_id
        }
        
        # 根据事件类型添加特定字段
        if event_type == Type.StartSession:
            if request_data.source_audio:
                json_data["source_audio"] = {
                    "format": request_data.source_audio.format,
                    "rate": request_data.source_audio.rate,
                    "bits": request_data.source_audio.bits,
                    "channel": request_data.source_audio.channel
                }
            if request_data.target_audio:
                json_data["target_audio"] = {
                    "format": request_data.target_audio.format,
                    "rate": request_data.target_audio.rate
                }
            if request_data.mode:
                json_data["mode"] = request_data.mode
            if request_data.source_language:
                json_data["source_language"] = request_data.source_language
            if request_data.target_language:
                json_data["target_language"] = request_data.target_language
                
        elif event_type == Type.TaskRequest:
            if request_data.source_audio and request_data.source_audio.binary_data:
                json_data["source_audio"] = {
                    "data": "二进制数据"
                }
        
        # 写入日志文件
        log_entry = f"{timestamp} ==>> {description}: {json.dumps(json_data, ensure_ascii=False)}\n"
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def log_receive_event(self, response_data: TranslateResponseData):
        """记录接收端事件"""
        event_type = response_data.event
        if event_type not in self.event_descriptions:
            return
            
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S,") + str(int(time.time() * 1000) % 1000).zfill(3)
        description = self.event_descriptions[event_type]
        
        # 构建JSON数据
        event_name = f"Type_{event_type.name}" if hasattr(event_type, 'name') else f"event.Type_{event_type}"
        json_data = {
            "event": event_name,
            "session_id": response_data.session_id
        }
        
        # 根据事件类型添加特定字段
        if event_type in [Type.SourceSubtitleStart, Type.TranslationSubtitleStart, Type.TTSSentenceStart]:
            if response_data.start_time is not None:
                json_data["start_time"] = response_data.start_time
                
        elif event_type in [Type.SourceSubtitleEnd, Type.TranslationSubtitleEnd]:
            if response_data.start_time is not None:
                json_data["start_time"] = response_data.start_time
            if response_data.end_time is not None:
                json_data["end_time"] = response_data.end_time
            if response_data.text:
                json_data["text"] = response_data.text
                
        elif event_type == Type.TTSSentenceEnd:
            if response_data.data:
                json_data["data"] = "二进制数据"
            if response_data.start_time is not None:
                json_data["start_time"] = response_data.start_time
            if response_data.end_time is not None:
                json_data["end_time"] = response_data.end_time
                
        elif event_type == Type.AudioMuted:
            # 从message中提取静音时长（如果有的话）
            if response_data.message:
                json_data["message"] = response_data.message
                
        elif event_type == Type.UsageResponse:
            # 计量计费
            if response_data.status_code is not None:
                json_data["status_code"] = response_data.status_code
            if response_data.message:
                json_data["message"] = response_data.message
            if response_data.billing is not None:
                billing_data = {}
                if response_data.billing.items:
                    billing_data["items"] = [
                        {"unit": item.unit, "quantity": item.quantity}
                        for item in response_data.billing.items
                        if item.unit is not None or item.quantity is not None
                    ]
                if response_data.billing.duration_msec is not None:
                    billing_data["duration_msec"] = response_data.billing.duration_msec
                if response_data.billing.word_count is not None:
                    billing_data["word_count"] = response_data.billing.word_count
                if billing_data:
                    json_data["billing"] = billing_data
        
        # 写入日志文件
        log_entry = f"{timestamp} ==>> {description}: {json.dumps(json_data, ensure_ascii=False)}\n"
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

class YtdlpLogger:
    def __init__(self, name="ytdlp", logfile="youtube/logs/yt-dlp-debug.log"):
        import logging, os
        from core.config import BASE_DIR
        
        self._log = logging.getLogger(name)
        if not self._log.handlers:
            # 确保日志目录存在
            log_path = BASE_DIR / logfile
            log_dir = log_path.parent
            log_dir.mkdir(parents=True, exist_ok=True)
                
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            fh.setFormatter(fmt)
            self._log.addHandler(fh)
            self._log.setLevel(logging.DEBUG)
        self._ts = time.time()

    def _stamp(self, level, msg):
        now = time.time()
        self._log.log(level, f"[+{now - self._ts:.3f}s] {msg}")

    def debug(self, msg):   self._stamp(10, str(msg))  # DEBUG
    def info(self, msg):    self._stamp(20, str(msg))  # INFO
    def warning(self, msg): self._stamp(30, str(msg))  # WARNING
    def error(self, msg):   self._stamp(40, str(msg))  # ERROR