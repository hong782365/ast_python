import pathlib
import time
from youtube.live_audio_download import stream_youtube_live_audio


def test_stream_for_five_minutes():
    url = "https://www.youtube.com/watch?v=wIfmqFa7rcg"
    # 5 minutes = 300 seconds
    output_path = stream_youtube_live_audio(url=url, duration_seconds=300)

    assert output_path.exists(), "Output file was not created"
    # Ensure some data was written (at least 1 KiB)
    assert output_path.stat().st_size > 1024, "Output file is too small; stream may not have started"


