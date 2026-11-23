"""Small media fixtures shared by working-result and browser tests."""

import io
import shutil

import pytest
from PIL import Image

from media_utils import frames_to_mp4_bytes


@pytest.fixture
def working_movie(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("MP4 registration tests require the FFmpeg tools")
    frames = []
    for color in ("red", "green"):
        buffer = io.BytesIO()
        Image.new("RGB", (16, 12), color).save(buffer, format="PNG")
        frames.append(buffer.getvalue())
    path = tmp_path / "working-movie.mp4"
    path.write_bytes(frames_to_mp4_bytes(frames, fps=2))
    return path
