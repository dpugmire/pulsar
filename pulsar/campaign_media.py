"""Serve local media payloads embedded in an ACA campaign."""

import re
import sqlite3
import zlib
from pathlib import Path

_UUID_PATTERN = re.compile(r"^[0-9a-fA-F-]{16,64}$")


def read_embedded_video(campaign_path: str, dataset_uuid: str) -> bytes | None:
    """Read an unencrypted, embedded VIDEO file from a local ACA archive."""
    if not _UUID_PATTERN.fullmatch(str(dataset_uuid or "")):
        return None
    path = Path(campaign_path).expanduser()
    if not path.is_file():
        return None

    try:
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as con:
            row = con.execute(
                """
                select f.data, f.compression, f.lenorig
                from dataset as d
                join replica as r on r.datasetid = d.rowid
                join repfiles as rf on rf.replicaid = r.rowid
                join file as f on f.fileid = rf.fileid
                where d.uuid = ? and upper(d.fileformat) = 'VIDEO'
                  and d.deltime = 0 and r.deltime = 0 and coalesce(r.keyid, 0) = 0
                order by r.rowid desc, f.fileid desc
                limit 1
                """,
                (dataset_uuid,),
            ).fetchone()
    except (sqlite3.Error, OSError):
        return None

    if row is None or row[0] is None:
        return None
    try:
        payload = bytes(row[0])
        if int(row[1] or 0):
            payload = zlib.decompress(payload)
        expected_size = int(row[2] or 0)
        if expected_size and len(payload) != expected_size:
            return None
        return payload
    except (TypeError, ValueError, zlib.error):
        return None


def _byte_range(value: str, size: int) -> tuple[int, int] | None:
    """Parse one HTTP byte range; return inclusive endpoints."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", str(value or "").strip())
    if not match or size <= 0:
        return None
    first, last = match.groups()
    try:
        if not first:
            suffix_size = int(last or 0)
            if suffix_size <= 0:
                return None
            return max(0, size - suffix_size), size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def register_campaign_media_route(server, campaign_path: str) -> None:
    """Add the same-origin HTTP endpoint used by browser video elements."""

    def on_server_bind(http_server):
        from aiohttp import web

        async def video_handler(request):
            payload = read_embedded_video(
                campaign_path, request.match_info.get("dataset_uuid", "")
            )
            if payload is None:
                raise web.HTTPNotFound(text="Embedded local video is unavailable")

            headers = {
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-store",
            }
            byte_range = request.headers.get("Range", "")
            if byte_range:
                selected = _byte_range(byte_range, len(payload))
                if selected is None:
                    raise web.HTTPRequestRangeNotSatisfiable(
                        headers={"Content-Range": f"bytes */{len(payload)}"}
                    )
                start, end = selected
                headers["Content-Range"] = f"bytes {start}-{end}/{len(payload)}"
                headers["Content-Length"] = str(end - start + 1)
                return web.Response(
                    status=206,
                    body=payload[start : end + 1],
                    content_type="video/mp4",
                    headers=headers,
                )

            headers["Content-Length"] = str(len(payload))
            return web.Response(
                body=payload,
                content_type="video/mp4",
                headers=headers,
            )

        http_server.app.router.add_get(
            "/pulsar-media/{dataset_uuid}", video_handler
        )

    server.controller.on_server_bind.add(on_server_bind)
