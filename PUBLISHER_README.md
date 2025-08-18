# Audio Stream Publisher

This module provides an API server that ingests YouTube live streams, translates them using the AST service, and publishes the translated audio to WebSocket endpoints.

## Features

- **REST API**: POST `/ingest/start` endpoint to start audio ingestion
- **YouTube Integration**: Uses yt-dlp → ffmpeg → translation WebSocket pipeline
- **Real-time Streaming**: Streams translated audio as 20ms PCM frames (640 bytes each)
- **WebSocket Publisher**: Connects to external WebSocket endpoints as a client
- **Fault Tolerance**: Exponential backoff reconnection and heartbeat maintenance
- **Comprehensive Logging**: Connection status, reconnection attempts, and frame rate metrics

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

Make sure you have the following system dependencies:
- `yt-dlp` (for YouTube stream extraction)
- `ffmpeg` (for audio processing)

## Configuration

Create a `.env` file with your AST service credentials:

```env
APP_KEY=your_app_key
ACCESS_KEY=your_access_key
RESOURCE_ID=your_resource_id
WS_URL=wss://your-ast-service-url
```

## Usage

### Starting the Server

```bash
python publisher.py
```

The server will start on `http://0.0.0.0:8000`

### API Endpoints

#### POST `/ingest/start`

Start audio ingestion from YouTube to WebSocket publisher.

**Request Body:**
```json
{
    "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "publishUrl": "ws://your-websocket-endpoint"
}
```

**Response:**
```json
{
    "success": true,
    "message": "Ingestion started successfully",
    "session_id": "uuid-session-id"
}
```

#### GET `/health`

Health check endpoint.

#### GET `/sessions`

Get all active sessions.

### Example Usage

```bash
curl -X POST "http://localhost:8000/ingest/start" \
     -H "Content-Type: application/json" \
     -d '{
       "youtube_url": "https://www.youtube.com/watch?v=HHGEDLPBIxA",
       "publishUrl": "ws://localhost:9000/audio"
     }'
```

## Architecture

1. **API Layer**: FastAPI server handles HTTP requests
2. **YouTube Processing**: yt-dlp extracts live audio, ffmpeg converts to PCM
3. **Translation**: AST WebSocket service translates audio (Chinese → English)
4. **Publishing**: Translated audio is streamed to external WebSocket as 20ms frames

## Audio Format

- **Input**: YouTube live stream (various formats)
- **Processing**: 16kHz mono PCM s16le
- **Output**: Translated audio streamed as 640-byte frames (20ms each)

## Logging

The system provides detailed logging for:
- Connection success/failure to both AST service and publish URL
- Reconnection attempts with exponential backoff
- Frame rate statistics (logged every 1000 frames / 20 seconds)
- Session lifecycle events

## Error Handling

- **Connection Failures**: Automatic reconnection with exponential backoff
- **Stream Interruptions**: Graceful handling and recovery
- **Invalid URLs**: Validation and error responses
- **Service Unavailability**: Proper error propagation and logging
