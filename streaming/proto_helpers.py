import asyncio
import uuid
import logging
import time
from typing import List, Optional

import websockets
from websockets import Headers

from core.config import SOURCE_LANGUAGE, TARGET_LANGUAGE
from .models import TranslateRequestData, TranslateResponseData, BillingItemData, BillingData, Config, Audio
from .logger import log_protobuf_message

# Import protobuf types after ensuring path is set
from products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse
from common.events_pb2 import Type

async def send_request(ws, request: TranslateRequestData, log_raw: bool = True):
    """Send request to WebSocket server
    
    Args:
        ws: WebSocket connection
        request: Request data to send
        log_raw: Whether to log the raw protobuf message (default True)
    """
    request_data = TranslateRequest()
    request_data.request_meta.SessionID = request.session_id
    if request.event == "Type_StartSession":
        request_data.event = Type.StartSession
    elif request.event == "Type_TaskRequest":
        request_data.event = Type.TaskRequest
    elif request.event == "Type_FinishSession":
        request_data.event = Type.FinishSession
    request_data.user.uid = "ast_py_youtube_client"
    request_data.user.did = "ast_py_youtube_client"
    request_data.source_audio.format = "wav"
    request_data.source_audio.rate = 16000
    request_data.source_audio.bits = 16
    request_data.source_audio.channel = 1
    if request.source_audio and request.source_audio.binary_data:
        request_data.source_audio.binary_data = request.source_audio.binary_data
    request_data.target_audio.format = "pcm"
    request_data.target_audio.rate = 16000
    request_data.target_audio.bits = 16
    request_data.target_audio.channel = 1
    request_data.request.mode = "s2s"
    request_data.request.source_language = SOURCE_LANGUAGE
    request_data.request.target_language = TARGET_LANGUAGE
    
    # 打印原始发送请求（根据log_raw参数控制）
    if log_raw:
        log_protobuf_message(request_data, "SEND")
    
    await ws.send(request_data.SerializeToString())

async def receive_message(ws) -> TranslateResponseData:
    """Receive and parse response from server"""
    response = await ws.recv()
    Response_data = TranslateResponse()
    Response_data.ParseFromString(response)
    
    # 打印原始接收响应
    log_protobuf_message(Response_data, "RECV")
    # Parse billing information if present
    status_code_value: Optional[int] = None
    billing_value: Optional[BillingData] = None
    try:
        status_code_value = Response_data.response_meta.StatusCode
    except Exception:
        status_code_value = None
    try:
        meta_billing = Response_data.response_meta.Billing
        # Build BillingData regardless; it will be empty if not set
        items_list: List[BillingItemData] = []
        try:
            for item in getattr(meta_billing, 'Items', []):
                items_list.append(BillingItemData(
                    unit=getattr(item, 'Unit', None),
                    quantity=getattr(item, 'Quantity', None)
                ))
        except Exception:
            items_list = []
        billing_value = BillingData(
            items=items_list,
            duration_msec=getattr(meta_billing, 'DurationMsec', None),
            word_count=getattr(meta_billing, 'WordCount', None)
        )
        # If nothing meaningful was set, keep it as None
        if not billing_value.items and billing_value.duration_msec in (None, 0) and billing_value.word_count in (None, 0):
            billing_value = None
    except Exception:
        billing_value = None

    return TranslateResponseData(
        event=Response_data.event,
        session_id=Response_data.response_meta.SessionID,
        sequence=Response_data.response_meta.Sequence,
        text=Response_data.text,
        data=Response_data.data,
        message=Response_data.response_meta.Message,
        start_time=Response_data.start_time if hasattr(Response_data, 'start_time') else None,
        end_time=Response_data.end_time if hasattr(Response_data, 'end_time') else None,
        status_code=status_code_value,
        billing=billing_value
    )

async def connect_websocket_and_start_session(conf: Config, source_language: str, target_language: str, event_logger=None):
    """Connect to WebSocket and start translation session"""
    ws_start_time = time.monotonic()
    
    # Connect to WebSocket server
    conn_id = str(uuid.uuid4())
    headers = await build_http_headers(conf, conn_id)
    
    conn = await websockets.connect(
        conf.ws_url,
        additional_headers=headers,
        max_size=1000000000,
        ping_interval=None
    )
    
    ws_connect_duration = time.monotonic() - ws_start_time
    log_id = conn.response.headers.get('X-Tt-Logid')
    logging.info(f"Connected to translation server (log id={log_id}), 连接同声传译websocket耗时: {ws_connect_duration:.2f}s")
    
    session_id = str(uuid.uuid4())
    
    # Start session
    start_request = TranslateRequestData(
        session_id=session_id,
        event="Type_StartSession",
        source_audio=Audio(format="wav", rate=16000, bits=16, channel=1),
        target_audio=Audio(format="pcm", rate=16000, bits=16, channel=1),
        mode="s2s",
        source_language=source_language,
        target_language=target_language
    )
    
    # Log event if logger is provided
    if event_logger:
        event_logger.log_send_event(Type.StartSession, start_request)
    
    await send_request(conn, start_request)
    resp = await receive_message(conn)
    
    # Log received event if logger is provided
    if event_logger and resp.event == Type.SessionStarted:
        event_logger.log_receive_event(resp)
    
    if resp.event != Type.SessionStarted:
        logging.error(f"Unexpected response logid: {log_id}")
        logging.error(f"Unexpected response: {resp.event}")
        logging.error(f"Unexpected response message: {resp.message}")
        await conn.close()
        raise Exception(f"Failed to start session: {resp.message}")
    
    logging.info(f"Translation session (ID={session_id}) started.")
    
    return conn, session_id, log_id, ws_connect_duration

async def build_http_headers(conf: Config, conn_id: str) -> Headers:
    """Build WebSocket connection headers from config"""
    headers = Headers({
        "X-Api-App-Key": conf.app_key,
        "X-Api-Access-Key": conf.access_key,
        "X-Api-Resource-Id": conf.resource_id,
        "X-Api-Connect-Id": conn_id
    })
    return headers