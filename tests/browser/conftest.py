"""Fixtures for browser-level Trame tests."""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_APP = Path(__file__).with_name("fixture_app.py")


def _unused_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(process, url, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output, _ = process.communicate(timeout=1)
            raise RuntimeError(
                f"Trame fixture server exited with {process.returncode}:\n{output}"
            )
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for Trame fixture server at {url}")


@pytest.fixture
def pulsar_server():
    processes = []

    def start(mode="step"):
        port = _unused_port()
        base_url = f"http://127.0.0.1:{port}/"
        url = f"{base_url}?sessionURL=ws://127.0.0.1:{port}/ws"
        env = dict(os.environ)
        env.update({"TRAME_SERVER": "true", "PYTHONUNBUFFERED": "1"})
        process = subprocess.Popen(
            [
                sys.executable,
                str(FIXTURE_APP),
                "--port",
                str(port),
                "--mode",
                mode,
            ],
            cwd=REPOSITORY_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        processes.append(process)
        _wait_for_server(process, base_url)
        return url

    yield start

    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
