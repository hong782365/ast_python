import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Any
from pydantic import BaseModel

# Pydantic request/response models for FastAPI
class IngestStartRequest(BaseModel):
    sessionId: str
    youtube_url: str
    publishUrl: str

class IngestStartResponse(BaseModel):
    success: bool
    message: str
    session_id: str

class IngestStopRequest(BaseModel):
    sessionId: str

class IngestStopResponse(BaseModel):
    success: bool
    message: str
    session_id: str

# Session management dataclass
@dataclass
class PublisherSession:
    session_id: str
    youtube_url: str
    publish_url: str
    status: str
    created_at: float
    task: Optional[asyncio.Task] = None
    stop_event: Optional[asyncio.Event] = None
    publisher_ws: Optional[Any] = None  # WebSocket发布客户端引用，防止泄漏