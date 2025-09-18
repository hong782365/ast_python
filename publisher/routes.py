import logging
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from fastapi import status

from .models import IngestStartRequest, IngestStartResponse, IngestStopRequest, IngestStopResponse
from .session_manager import get_publisher

router = APIRouter()

@router.post("/python/ingest/start", response_model=IngestStartResponse)
async def start_ingest(request: IngestStartRequest):
    """Start audio ingestion from YouTube to WebSocket publisher"""
    try:
        # Validate URLs
        if not request.youtube_url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        if not request.publishUrl.startswith(('ws://', 'wss://')):
            raise HTTPException(status_code=400, detail="Invalid WebSocket publish URL")
        
        # Get publisher instance
        publisher = get_publisher()
        
        # Start publishing session (idempotent)
        session_id, status_code = await publisher.start_publishing_session(
            request.sessionId,
            request.youtube_url, 
            request.publishUrl
        )
        
        if status_code == 201:
            # 新会话创建成功
            return IngestStartResponse(
                success=True,
                message="Ingestion started successfully",
                session_id=session_id
            )
        elif status_code == 202:
            # 同sessionId已在运行，幂等返回
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "success": True,
                    "message": "Session already running",
                    "session_id": session_id
                }
            )
        elif status_code == 409:
            # 容器忙碌，不同sessionId冲突
            raise HTTPException(
                status_code=409, 
                detail=f"Container is busy with another session. This container supports only one active session at a time."
            )
        
    except Exception as e:
        logging.error(f"Failed to start ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/python/ingest/stop", response_model=IngestStopResponse)
async def stop_ingest(request: IngestStopRequest):
    """Stop audio ingestion session (idempotent)"""
    try:
        # Get publisher instance
        publisher = get_publisher()
        
        # Stop publishing session
        success = await publisher.stop_publishing_session(request.sessionId)
        
        if success:
            return IngestStopResponse(
                success=True,
                message="Session stopped successfully",
                session_id=request.sessionId
            )
        else:
            # Session doesn't exist, but we treat this as successful (idempotent)
            return IngestStopResponse(
                success=True,
                message="Session not found (already stopped or never existed)",
                session_id=request.sessionId
            )
        
    except Exception as e:
        logging.error(f"Failed to stop ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/python/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": time.time()}

@router.get("/python/sessions")
async def get_sessions():
    """Get all active sessions"""
    publisher = get_publisher()
    return {
        "sessions": [
            {
                "session_id": session.session_id,
                "youtube_url": session.youtube_url,
                "publish_url": session.publish_url,
                "status": session.status,
                "created_at": session.created_at
            }
            for session in publisher.sessions.values()
        ]
    }