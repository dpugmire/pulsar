"""Read published image and movie products without requiring the campaign writer package."""

import json
import math
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path
from uuid import UUID

from .models.grid import empty_grid_cell
from .models.video_timing import normalize_video_timing


class PublicationError(ValueError):
    pass


def publication_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise PublicationError("result_id must be a UUID") from error


def load_publications(campaign_path):
    path = Path(campaign_path).expanduser()
    if not path.is_file():
        return {}
    records = {}
    try:
        with closing(
            sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        ) as con:
            rows = con.execute(
                """select d.name, f.data, f.compression from dataset d
                   join replica r on r.datasetid=d.rowid
                   join repfiles rf on rf.replicaid=r.rowid
                   join file f on f.fileid=rf.fileid
                   where (d.name glob '__published_images/*.json' or d.name glob '__published_videos/*.json')
                     and d.fileformat='TEXT' and d.deltime=0 and r.deltime=0
                     and coalesce(r.keyid,0)=0
                   order by f.fileid"""
            )
            for name, payload, compression in rows:
                if payload is None or len(payload) > 128 * 1024:
                    raise PublicationError("Invalid publication catalogue record")
                if compression:
                    decoder = zlib.decompressobj()
                    payload = decoder.decompress(payload, 128 * 1024 + 1)
                    if not decoder.eof or len(payload) > 128 * 1024:
                        raise PublicationError(
                            "Publication catalogue record is too large"
                        )
                record = json.loads(payload)
                if not isinstance(record, dict):
                    raise PublicationError("Invalid publication catalogue record")
                is_video = record.get("format") == "hpc-campaign-published-video"
                kind = "video" if is_video else "image"
                identifier = publication_id(record.get("publication_id"))
                if (
                    record.get("format") != f"hpc-campaign-published-{kind}"
                    or record.get("version") != 1
                    or name != f"__published_{kind}s/{identifier}.json"
                    or not isinstance(record.get("title"), str)
                    or not record["title"].strip()
                    or not isinstance(record.get("associations"), list)
                ):
                    raise PublicationError("Invalid publication catalogue record")
                UUID(record["image_uuid"])
                image = con.execute(
                    "select 1 from dataset where uuid=? and name=? and fileformat='IMAGE' and deltime=0",
                    (record["image_uuid"], record["image_name"]),
                ).fetchone()
                if image is None:
                    raise PublicationError(
                        "Published image is missing from the campaign"
                    )
                if is_video:
                    UUID(record["video_uuid"])
                    video = record.get("video")
                    if not isinstance(video, dict) or any(
                        not isinstance(video.get(key), (int, float))
                        or not math.isfinite(video[key])
                        or video[key] <= 0
                        for key in ("width", "height", "frame_count", "fps", "duration")
                    ):
                        raise PublicationError(
                            "Invalid published movie playback metadata"
                        )
                    if (
                        con.execute(
                            "select 1 from dataset where uuid=? and name=? and fileformat='VIDEO' and deltime=0",
                            (record["video_uuid"], record["video_name"]),
                        ).fetchone()
                        is None
                    ):
                        raise PublicationError(
                            "Published movie is missing from the campaign"
                        )
                    normalize_video_timing(video, video["frame_count"])
                if identifier in records:
                    raise PublicationError(
                        "Duplicate publication identity in the campaign"
                    )
                records[identifier] = record
    except (
        sqlite3.Error,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zlib.error,
    ) as error:
        raise PublicationError(f"Cannot read campaign publications: {error}") from error
    return records


def published_tile(record):
    cell = empty_grid_cell()
    cell.update(
        working_result_id=record["publication_id"],
        publication_status="published",
        publication_image_uuid=record["image_uuid"],
        variable_name=record["title"],
        display_title=record["title"],
        media_type="image",
        status="ok",
        src=f"/pulsar-image/{record['image_uuid']}",
        note="Published in campaign",
    )
    if record.get("format") == "hpc-campaign-published-video":
        video = record["video"]
        cell.update(
            media_type="video",
            publication_video_uuid=record["video_uuid"],
            poster=cell["src"],
            src=f"/pulsar-media/{record['video_uuid']}",
            fps=video["fps"],
            frame_count=video["frame_count"],
            **{
                "time_mode": video.get("time_mode", "timestep"),
                **normalize_video_timing(video, video["frame_count"]),
            },
            note="Published movie in campaign",
        )
    return cell


def publication_documents(campaign_path, records):
    """Catalogue publications and their source-variable visualizations."""
    for record in records.values():
        is_video = record.get("format") == "hpc-campaign-published-video"
        kind = "video" if is_video else "image"
        prefix = "published-videos" if is_video else "published-images"
        product_id = f"published-{kind}:{record['publication_id']}"
        dataset_name = record["video_name"] if is_video else record["image_name"]
        item_uuid = record["video_uuid"] if is_video else record["image_uuid"]
        base = {
            "campaign_path": campaign_path,
            "variable_type": kind,
            "visualization_name": f"{prefix}/{record['publication_id']}",
            "visualization_kind": "plot",
            "visualization_item_uuid": item_uuid,
            "visualization_item_type": kind.upper(),
            "variable_path": dataset_name,
            "payload_type": kind.upper(),
            "image_storage": "embedded",
            "variable_location": "local",
            "frame_index": 0,
            "movie_cache": 1,
            "association_source": "publication",
            "file": "",
        }
        if is_video:
            base.update(
                visualization_item_metadata={
                    **record["video"],
                    "poster_uuid": record["image_uuid"],
                },
                frame_count=record["video"]["frame_count"],
                **{
                    "time_mode": record["video"].get("time_mode", "timestep"),
                    **normalize_video_timing(
                        record["video"], record["video"]["frame_count"]
                    ),
                },
            )
        # Associated movies are already discoverable under their source variables.
        if not is_video or not record["associations"]:
            yield {
                **base,
                "variable_id": product_id,
                "variable_name": record["title"],
                "display_name": record["title"],
                "source_dataset": dataset_name,
                "variable_group": "Published movies" if is_video else "Published plots",
                "variable_group_order": -1,
            }
        for association in record["associations"]:
            yield {
                **base,
                "variable_id": association["name"],
                "variable_name": association["name"],
                "source_dataset": association["source_dataset"],
                "visualization_source_dataset": association["source_dataset"],
                "visualization_roles": [association["role"]],
            }
