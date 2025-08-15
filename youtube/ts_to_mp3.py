import pathlib
import subprocess
import sys
from datetime import datetime


def convert_ts_to_mp3(input_ts: str, output_mp3: str | None = None) -> str:
    src = pathlib.Path(input_ts)
    if not src.exists():
        raise FileNotFoundError(f"Input not found: {src}")

    if output_mp3 is None:
        output_mp3 = str(src.with_suffix("") ) + ".mp3"

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel", "warning",
        "-i", str(src),
        "-vn",
        "-acodec", "libmp3lame",
        "-b:a", "192k",
        output_mp3,
    ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr}")

    return output_mp3


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m youtube.ts_to_mp3 <input.ts> [output.mp3]")
        sys.exit(2)

    input_ts = sys.argv[1]
    output_mp3 = sys.argv[2] if len(sys.argv) > 2 else None
    out = convert_ts_to_mp3(input_ts, output_mp3)
    print(out)


if __name__ == "__main__":
    main()


