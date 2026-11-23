"""Durable, immutable working results kept separately from campaign/cache data."""

import hashlib
import io
import json
import math
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image

from .campaign_media import _byte_range
from .models.grid import empty_grid_cell
from .models.video_timing import normalize_video_timing

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 512 * 1024 * 1024
MAX_SCRIPT_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 128 * 1024


class ResultError(ValueError):
    """A working result is invalid, missing, or fails its integrity check."""


def _identifier(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as error:
        raise ResultError("Invalid working-result ID") from error
    return value


def _read_file(path, limit):
    path = Path(path).expanduser()
    if not path.is_file():
        raise ResultError("Result artifacts must be existing regular files")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ResultError(f"Artifact exceeds the {limit} byte limit")
    return data


def _probe_video(data):
    """Validate copied MP4 bytes without opening external media references."""
    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "pipe",
                "-i",
                "pipe:0",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=format_name,duration:stream=codec_name,pix_fmt,width,height,avg_frame_rate,duration,nb_frames",
                "-of",
                "json",
            ],
            input=data,
            capture_output=True,
            timeout=30,
            check=True,
        )
        info = json.loads(process.stdout)
        stream = info["streams"][0]
        numerator, denominator = stream["avg_frame_rate"].split("/")
        fps = float(numerator) / float(denominator)
        duration = float(stream.get("duration") or info["format"]["duration"])
        width, height = int(stream["width"]), int(stream["height"])
        count = stream.get("nb_frames", "N/A")
        count = int(count) if count != "N/A" else round(duration * fps)
        if (
            "mp4" not in info["format"]["format_name"].split(",")
            or stream["codec_name"] != "h264"
            or stream.get("pix_fmt") not in {"yuv420p", "yuvj420p"}
            or not math.isfinite(fps)
            or not 0 < fps <= 240
            or not math.isfinite(duration)
            or duration <= 0
            or width <= 0
            or height <= 0
            or count <= 0
        ):
            raise ValueError("Unsupported movie format")
        return {
            "mime_type": "video/mp4",
            "codec": "h264",
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
            "frame_count": count,
        }
    except FileNotFoundError as error:
        raise ResultError(
            "Movie registration requires ffprobe from the existing FFmpeg installation"
        ) from error
    except (
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        ZeroDivisionError,
    ) as error:
        raise ResultError(
            "The movie must be a valid browser-compatible H.264 MP4 with 4:2:0 color"
        ) from error


class ResultStore:
    """One campaign's copied PNG previews, optional MP4s/scripts, and provenance.

    Nothing is written until registration. Published campaign records and the
    viewer's rebuildable sidecar are never modified by this store.
    """

    def __init__(self, root, campaign_path):
        self.campaign_path = str(Path(campaign_path).expanduser().resolve())
        self.campaign_key = hashlib.sha256(self.campaign_path.encode()).hexdigest()
        self.directory = Path(root).expanduser().resolve() / self.campaign_key

    def register(
        self,
        *,
        title,
        image_path,
        video_path=None,
        frame_times=None,
        time_unit=None,
        time_source=None,
        script_path=None,
        parameters=None,
        provenance=None,
    ):
        if not isinstance(title, str) or not title.strip() or len(title) > 1024:
            raise ResultError("title must be nonempty text of at most 1024 characters")
        metadata = {}
        for name, value in (("parameters", parameters), ("provenance", provenance)):
            if value is None:
                value = {}
            if not isinstance(value, dict):
                raise ResultError(f"{name} must be a JSON object")
            metadata[name] = value
        try:
            encoded = json.dumps(metadata, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError) as error:
            raise ResultError(
                "Parameters and provenance must be finite JSON values"
            ) from error
        if len(encoded) > MAX_METADATA_BYTES:
            raise ResultError(
                "Result parameters and provenance exceed the 128 KiB limit"
            )
        image_data = _read_file(image_path, MAX_IMAGE_BYTES)
        try:
            with Image.open(io.BytesIO(image_data)) as image:
                if image.format != "PNG":
                    raise ResultError("The preview must be a PNG image")
                width, height = image.size
                image.verify()
        except (OSError, SyntaxError, Image.DecompressionBombError) as error:
            raise ResultError("The preview is not a valid PNG image") from error
        payloads = {"image": ("image.png", image_data)}
        video = None
        if video_path is not None:
            video_data = _read_file(video_path, MAX_VIDEO_BYTES)
            video = _probe_video(video_data)
            payloads["video"] = ("movie.mp4", video_data)
        if any(value is not None for value in (frame_times, time_unit, time_source)):
            if video is None:
                raise ResultError("Physical-time metadata requires a movie")
            try:
                video.update(
                    normalize_video_timing(
                        {
                            "time_mode": "physical_time",
                            "time_values": frame_times,
                            "time_unit": "s" if time_unit is None else time_unit,
                            "time_source": {"kind": "explicit"}
                            if time_source is None
                            else time_source,
                        },
                        video["frame_count"],
                    )
                )
            except ValueError as error:
                raise ResultError(str(error)) from error
        if (
            video is not None
            and len(
                json.dumps({**metadata, "video": video}, allow_nan=False).encode(
                    "utf-8"
                )
            )
            > MAX_METADATA_BYTES
        ):
            raise ResultError(
                "Result metadata and movie timing exceed the 128 KiB limit"
            )
        if script_path is not None:
            suffix = Path(script_path).suffix
            if not re.fullmatch(r"\.[a-zA-Z0-9]{1,12}", suffix):
                suffix = ".txt"
            payloads["script"] = (
                "analysis" + suffix,
                _read_file(script_path, MAX_SCRIPT_BYTES),
            )
        result_id = str(uuid4())
        manifest = {
            "format": "pulsar-working-result",
            "version": 1,
            "result_id": result_id,
            "campaign_path": self.campaign_path,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "title": title.strip(),
            "publication_status": "unpublished",
            "width": width,
            "height": height,
            **json.loads(encoded),
            "artifacts": {
                role: {
                    "filename": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
                for role, (name, data) in payloads.items()
            },
        }
        if video is not None:
            manifest.update(media_type="video", video=video)
        self.directory.mkdir(parents=True, exist_ok=True)
        # Make the complete bundle visible in one rename; failed registrations
        # leave no listed result and never rewrite a previous version.
        with tempfile.TemporaryDirectory(
            prefix=".register-", dir=self.directory
        ) as staging:
            staging_path = Path(staging)
            for name, data in payloads.values():
                (staging_path / name).write_bytes(data)
            (staging_path / "manifest.json").write_text(
                json.dumps(manifest, allow_nan=False), encoding="utf-8"
            )
            staging_path.rename(self.directory / result_id)
        return manifest

    def get(self, result_id):
        result_id = _identifier(result_id)
        try:
            manifest = json.loads(
                _read_file(
                    self.directory / result_id / "manifest.json",
                    MAX_METADATA_BYTES + 16384,
                )
            )
        except (OSError, ValueError) as error:
            raise ResultError(
                f"Working result {result_id} is unavailable in the configured result store"
            ) from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != "pulsar-working-result"
            or manifest.get("version") != 1
            or manifest.get("result_id") != result_id
            or manifest.get("campaign_path") != self.campaign_path
            or manifest.get("publication_status") != "unpublished"
            or not isinstance(manifest.get("artifacts"), dict)
            or "image" not in manifest["artifacts"]
            or (
                "video" in manifest["artifacts"]
                and (
                    manifest.get("media_type") != "video"
                    or not isinstance(manifest.get("video"), dict)
                    or any(
                        not isinstance(manifest["video"].get(key), (int, float))
                        or not math.isfinite(manifest["video"][key])
                        or manifest["video"][key] <= 0
                        for key in ("width", "height", "fps", "duration", "frame_count")
                    )
                )
            )
        ):
            raise ResultError("Invalid working-result manifest")
        if "video" in manifest["artifacts"]:
            try:
                normalize_video_timing(
                    manifest["video"], manifest["video"]["frame_count"]
                )
            except ValueError as error:
                raise ResultError(str(error)) from error
        return manifest

    def list(self):
        if not self.directory.exists():
            return []
        results = [
            self.get(path.name)
            for path in self.directory.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]
        return sorted(
            results, key=lambda item: (item["created_at_utc"], item["result_id"])
        )

    def artifact(self, result_id, role):
        manifest = self.get(result_id)
        artifact = manifest["artifacts"].get(role)
        if role not in {"image", "script", "video"} or not isinstance(artifact, dict):
            raise ResultError("Working-result artifact is unavailable")
        name = artifact.get("filename", "")
        if role in {"image", "video"}:
            valid_name = name == ("image.png" if role == "image" else "movie.mp4")
        else:
            valid_name = isinstance(name, str) and re.fullmatch(
                r"analysis\.[a-zA-Z0-9]{1,12}", name
            )
        if not valid_name:
            raise ResultError("Invalid working-result artifact filename")
        try:
            data = _read_file(
                self.directory / result_id / name,
                {
                    "image": MAX_IMAGE_BYTES,
                    "video": MAX_VIDEO_BYTES,
                    "script": MAX_SCRIPT_BYTES,
                }[role],
            )
        except OSError as error:
            raise ResultError("Working-result artifact is missing") from error
        if len(data) != artifact.get("bytes") or hashlib.sha256(
            data
        ).hexdigest() != artifact.get("sha256"):
            raise ResultError("Working-result artifact failed its checksum")
        return data

    def tile(self, result_id):
        manifest = self.get(result_id)
        for role in manifest["artifacts"]:
            self.artifact(result_id, role)
        cell = empty_grid_cell()
        cell.update(
            {
                "working_result_id": result_id,
                "publication_status": "unpublished",
                "variable_name": manifest["title"],
                "display_title": manifest["title"],
                "media_type": "image",
                "status": "ok",
                "src": f"/pulsar-results/{self.campaign_key}/{result_id}/image.png",
                "note": "Unpublished working result",
            }
        )
        if "video" in manifest["artifacts"]:
            video = manifest["video"]
            cell.update(
                media_type="video",
                src=f"/pulsar-results/{self.campaign_key}/{result_id}/movie.mp4",
                poster=cell["src"],
                fps=video["fps"],
                frame_count=video["frame_count"],
                **normalize_video_timing(video, video["frame_count"]),
                note="Unpublished working movie",
            )
        return cell


def register_result_media_route(server, store):
    """Serve registered previews and movies; scripts remain unavailable over HTTP."""
    from aiohttp import web

    def on_bind(http_server):
        async def media_handler(request):
            if request.match_info["campaign_key"] != store.campaign_key:
                raise web.HTTPNotFound()
            role = {"image.png": "image", "movie.mp4": "video"}.get(
                request.match_info["filename"]
            )
            if role is None:
                raise web.HTTPNotFound()
            try:
                payload = store.artifact(request.match_info["result_id"], role)
            except ResultError as error:
                raise web.HTTPNotFound(text=str(error)) from error
            headers = {"Cache-Control": "private, no-cache"}
            status = 200
            if role == "video":
                headers["Accept-Ranges"] = "bytes"
                byte_range = request.headers.get("Range", "")
                if byte_range:
                    selected = _byte_range(byte_range, len(payload))
                    if selected is None:
                        raise web.HTTPRequestRangeNotSatisfiable(
                            headers={"Content-Range": f"bytes */{len(payload)}"}
                        )
                    start, end = selected
                    headers["Content-Range"] = f"bytes {start}-{end}/{len(payload)}"
                    payload = payload[start : end + 1]
                    status = 206
            return web.Response(
                body=payload,
                status=status,
                content_type="video/mp4" if role == "video" else "image/png",
                headers=headers,
            )

        http_server.app.router.add_get(
            "/pulsar-results/{campaign_key}/{result_id}/{filename}", media_handler
        )

    server.controller.on_server_bind.add(on_bind)
