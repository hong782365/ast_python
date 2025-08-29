# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based real-time speech-to-speech (S2S) translation system that integrates with VolcEngine's simultaneous interpretation API. The system can process live YouTube streams, extract audio, perform real-time translation, and play back translated audio.

## Core Dependencies & Requirements

**Python Version**: 3.x

**Key Dependencies**:
```bash
pip install websockets protobuf python-dotenv yt-dlp pyaudio pydub sounddevice numpy fastapi uvicorn pydantic
```

**System Dependencies**:
- **FFmpeg**: Required for audio conversion and decoding
- **PortAudio**: Required for audio device access
- **protoc**: Protocol buffer compiler (for regenerating proto files if needed)

## Development Commands

### Environment Setup
```bash
# Install Python dependencies
pip install -r requirements.txt

# Install system dependencies (macOS)
brew install ffmpeg portaudio

# Install system dependencies (Ubuntu)
sudo apt install ffmpeg portaudio19-dev
```

### Protobuf Code Generation
The project includes pre-generated protobuf code in `python_protogen/`. To regenerate:
```bash
# Make script executable and run
chmod +x protos/build_python.sh
./protos/build_python.sh
```

### Running the Application
```bash
# Basic audio file processing demo
python3 ast_demo.py

# YouTube live stream with real-time playback (recommended)
python3 ast_youtube_realtime_demo.py

# Test demo
python3 test/test_demo.py
```

## Environment Configuration

Create a `.env` file with the following variables:
```bash
APP_KEY=your_volcengine_app_key
ACCESS_KEY=your_volcengine_access_key
RESOURCE_ID=your_volcengine_resource_id
WS_URL=wss://openspeech.bytedance.com/api/v2/ast

# Optional: YouTube API (if needed)
YOUTUBE_API_KEY=your_youtube_api_key

# Optional: Redis configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB_BROKER=0
REDIS_DB_BACKEND=1
REDIS_DB_CACHE=2
```

## High-Level Architecture

### System Data Flow
```
YouTube Live Stream → yt-dlp (audio extraction) → FFmpeg (format conversion) 
→ WebSocket Client (chunked transmission) → VolcEngine S2S API → Real-time Audio Playback
```

### Key Components

1. **Audio Extraction** (`youtube/live_audio_download.py`):
   - Uses `yt-dlp` to extract live audio from YouTube streams
   - Outputs raw audio stream (Opus/WebM or AAC/MP4)

2. **Audio Processing Pipeline**:
   - **Input**: Raw audio stream from yt-dlp
   - **FFmpeg Conversion**: Converts to 16kHz mono PCM for API transmission
   - **Chunking**: Splits PCM stream into 640-byte frames (20ms each)
   - **WebSocket Transmission**: Sends frames to VolcEngine API

3. **Real-time Translation & Playback**:
   - **API Response**: Receives Opus-encoded translated audio
   - **FFmpeg Decoding**: Decodes Opus to 32-bit float PCM at 24kHz
   - **Audio Playback**: Uses `sounddevice` for real-time audio output

4. **Protocol Buffers** (`python_protogen/`):
   - Generated from `.proto` files in `protos/`
   - Handles WebSocket message serialization/deserialization
   - Key message types: `TranslateRequest`, `TranslateResponse`

### Core Modules

- **`ast_demo.py`**: Basic file-based S2S translation demo
- **`ast_youtube_realtime_demo.py`**: Complete live streaming solution with real-time playback
- **`config.py`**: Environment configuration and Redis setup
- **`publisher.py`**: FastAPI-based publishing service
- **`python_protogen/`**: Auto-generated protobuf Python bindings

## Key Implementation Details

### WebSocket Connection
- Uses custom headers for authentication: `X-Api-App-Key`, `X-Api-Access-Key`, `X-Api-Resource-Id`, `X-Api-Connect-Id`
- Session management with `StartSession`, `TaskRequest`, `FinishSession` events
- Real-time bidirectional communication for audio streaming

### Audio Processing Parameters
- **Input Audio**: 16kHz, 16-bit, mono PCM
- **Output Audio**: 24kHz, 32-bit float, mono
- **Chunk Size**: 640 bytes (20ms frames)
- **Supported Languages**: Chinese ↔ English (configurable)

### Performance Optimizations
- Asynchronous processing throughout the pipeline
- Low-latency FFmpeg parameters (`-fflags +nobuffer -flags low_delay`)
- Minimal buffering for real-time performance
- Parallel audio processing and playback

## Directory Structure

- `protos/`: Protocol buffer definitions and build scripts
- `python_protogen/`: Generated protobuf Python code
- `youtube/`: YouTube-specific processing and logs
- `test/`: Test files and troubleshooting scripts
- `output/`: Generated audio files
- `doc/`: Documentation and API references

## Troubleshooting

### Common Issues
1. **Import Errors**: Run `./protos/build_python.sh` to regenerate protobuf code
2. **Authentication Failures**: Verify `.env` file contains valid VolcEngine credentials
3. **Audio Quality Issues**: Check FFmpeg installation and audio device permissions
4. **YouTube Extraction Failures**: Update `yt-dlp` version or verify URL validity

### Debug Logs
- FFmpeg logs: `youtube/ffmpeg/log/`
- yt-dlp logs: `youtube/logs/`
- AST transcription events: `youtube/ast_event/`

## Testing

No formal test framework is configured. Testing is done through:
- Running demo scripts with test audio files
- Live stream testing with real YouTube URLs
- Manual verification of audio output quality

## Development Notes

- The system is designed for real-time processing with ~3-5 second end-to-end latency
- All generated protobuf files should not be manually edited
- Audio format compatibility is handled automatically by FFmpeg
- The project supports both file-based and live streaming workflows
- Error handling includes automatic retry logic and graceful degradation