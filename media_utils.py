import base64
import os
import subprocess
import tempfile
from typing import List


def png_bytes_to_data_uri(png_bytes: bytes) -> str:
    if not png_bytes:
        return ""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def mp4_bytes_to_data_uri(mp4_bytes: bytes) -> str:
    if not mp4_bytes:
        return ""
    b64 = base64.b64encode(mp4_bytes).decode("ascii")
    return f"data:video/mp4;base64,{b64}"


def frames_to_mp4_bytes(png_frames: List[bytes], fps: int = 24) -> bytes:
    if not png_frames:
        return b""

    if fps <= 0:
        fps = 24

    with tempfile.TemporaryDirectory(prefix="pulsar_movie_") as tmpdir:
        for i, b in enumerate(png_frames):
            fname = os.path.join(tmpdir, f"frame_{i:06d}.png")
            with open(fname, "wb") as f:
                f.write(b)

        out_mp4 = os.path.join(tmpdir, "movie.mp4")

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(int(fps)),
            "-i",
            os.path.join(tmpdir, "frame_%06d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            out_mp4,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"ffmpeg failed (code {result.returncode}): {stderr}")

        with open(out_mp4, "rb") as f:
            return f.read()
