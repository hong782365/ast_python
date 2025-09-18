from dataclasses import dataclass, field
from typing import Optional, List, Union

@dataclass
class Config:
    ws_url: str
    app_key: str
    access_key: str
    resource_id: str

@dataclass
class Audio:
    format: str = None
    rate: int = None
    bits: Optional[int] = None
    channel: Optional[int] = None
    binary_data: Optional[bytes] = None

@dataclass
class TranslateRequestData:
    session_id: str
    event: str
    source_audio: Optional[Audio] = None
    target_audio: Optional[Audio] = None
    mode: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None

@dataclass
class TranslateResponseData:
    event: str
    session_id: str
    sequence: int
    text: str
    data: bytes
    message: str = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    status_code: Optional[int] = None
    billing: Optional["BillingData"] = None

@dataclass
class BillingItemData:
    unit: Optional[str] = None
    quantity: Optional[float] = None

@dataclass
class BillingData:
    items: List[BillingItemData] = field(default_factory=list)
    duration_msec: Optional[int] = None
    word_count: Optional[int] = None

@dataclass
class SubtitleMessage:
    type: str = "subtitle"
    lane: str = None  # "source" or "translation"
    phase: str = None  # "start", "delta", or "end"
    text: str = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    final: bool = False

@dataclass
class StreamData:
    data_type: str  # "audio", "subtitle", or "error"
    content: Union[bytes, str]  # binary audio data or JSON string