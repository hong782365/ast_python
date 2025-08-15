import os
import sys
import time
import signal
import pathlib
import subprocess
from datetime import datetime


WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOWNLOAD_DIR = WORKSPACE_ROOT / "youtube" / "download"


def ensure_download_dir() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def build_output_filepath(prefix: str = "ytlive", extension: str = "ts") -> pathlib.Path:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"{prefix}_{timestamp}.{extension}"
    return DOWNLOAD_DIR / filename


def stream_youtube_live_audio(
    url: str,
    output_file: pathlib.Path | None = None,
    duration_seconds: int | None = None,
    chunk_size_bytes: int = 64 * 1024,
) -> pathlib.Path:
    """
    Stream YouTube live audio via yt-dlp stdout piping and save to a file.

    Args:
        url: YouTube live URL.
        output_file: Target file path. If None, a timestamped filename is chosen.
        duration_seconds: If provided, stop after this many seconds.
        chunk_size_bytes: Read buffer size for stdout.

    Returns:
        pathlib.Path to the written file.
    """
    ensure_download_dir()

    # Default to MPEG-TS container to align with HLS-style segmenting for low latency.
    if output_file is None:
        output_file = build_output_filepath(extension="ts")

    # Build yt-dlp process to write raw media to stdout. Prefer AAC/M4A if available.
    ytdlp_cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[acodec^=mp4a]/bestaudio[ext=m4a]/bestaudio",
        "--no-part",
        "--no-progress",
        "--quiet",
        "--ignore-config",
        "-o", "-",
        url,
    ]

    # Pipe into ffmpeg which muxes/transcodes to MPEG-TS for robust .ts output.
    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-fflags", "nobuffer",
        "-i", "pipe:0",
        "-vn",
        "-acodec", "aac",
        "-b:a", "160k",
        "-f", "mpegts",
        str(output_file),
    ]

    start_time = time.monotonic()
    last_log_time = start_time
    bytes_read_total = 0
    bytes_read_last = 0

    ytdlp_proc = subprocess.Popen(
        ytdlp_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert ytdlp_proc.stdout is not None

    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert ffmpeg_proc.stdin is not None

    try:
        while True:
            if duration_seconds is not None and (time.monotonic() - start_time) >= duration_seconds:
                break

            chunk = ytdlp_proc.stdout.read(chunk_size_bytes)
            if not chunk:
                if ytdlp_proc.poll() is not None:
                    break
                time.sleep(0.05)
                # Heartbeat even if no incoming data
                now = time.monotonic()
                if now - last_log_time >= 1.0:
                    elapsed = now - start_time
                    kib_total = bytes_read_total / 1024.0
                    kibps_avg = (bytes_read_total / max(elapsed, 1e-6)) / 1024.0
                    out_size = output_file.stat().st_size if output_file.exists() else 0
                    print(
                        f"{datetime.utcnow().isoformat()}Z heartbeat elapsed={elapsed:.1f}s ytdlp_total_kib={kib_total:.1f} avg_kib_s={kibps_avg:.1f} out_size_kib={out_size/1024.0:.1f}",
                        flush=True,
                    )
                    last_log_time = now
                continue

            try:
                ffmpeg_proc.stdin.write(chunk)
            except BrokenPipeError:
                break
            bytes_read_total += len(chunk)

            now = time.monotonic()
            if now - last_log_time >= 1.0:
                interval_bytes = bytes_read_total - bytes_read_last
                interval = now - last_log_time
                kib_total = bytes_read_total / 1024.0
                kibps_inst = (interval_bytes / max(interval, 1e-6)) / 1024.0
                elapsed = now - start_time
                out_size = output_file.stat().st_size if output_file.exists() else 0
                print(
                    f"{datetime.utcnow().isoformat()}Z writing elapsed={elapsed:.1f}s ytdlp_total_kib={kib_total:.1f} inst_kib_s={kibps_inst:.1f} out_size_kib={out_size/1024.0:.1f}",
                    flush=True,
                )
                last_log_time = now
                bytes_read_last = bytes_read_total
    finally:
        # Signal EOF to ffmpeg
        try:
            if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                ffmpeg_proc.stdin.close()
        except Exception:
            pass

        # Gracefully terminate both processes
        for proc in (ytdlp_proc, ffmpeg_proc):
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        for proc in (ytdlp_proc, ffmpeg_proc):
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    return output_file


def main() -> None:
    url = os.environ.get("YTLIVE_URL", "https://www.youtube.com/watch?v=wIfmqFa7rcg")
    # Default 5 minutes if RUN_MINUTES env var set, otherwise run indefinitely when invoked directly
    run_minutes_env = os.environ.get("RUN_MINUTES")
    duration = int(float(run_minutes_env) * 60) if run_minutes_env else None
    target = stream_youtube_live_audio(url=url, duration_seconds=duration)
    print(str(target))


if __name__ == "__main__":
    main()


