"""Immutable metadata-query snapshots stored independently of the viewer cache."""

import base64
import csv
import hashlib
import io
import json
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from .metadata_query import (
    QUERY_SCHEMA_VERSION,
    MetadataQueryError,
    campaign_fingerprint,
)
from .models.grid import empty_grid_cell

MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024


def _encode(document):
    return json.dumps(
        document, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode()


class QueryResultStore:
    def __init__(self, directory, campaign_path):
        self.directory = Path(directory)
        self.campaign_path = str(Path(campaign_path).expanduser().resolve())

    def save(self, result):
        document = {**result, "query_id": str(uuid4())}
        encoded = _encode(document)
        envelope = _encode(
            {"document": document, "sha256": hashlib.sha256(encoded).hexdigest()}
        )
        if len(envelope) > MAX_SNAPSHOT_BYTES:
            raise MetadataQueryError("Query snapshot exceeds its storage limit")
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / document["query_id"]
        with tempfile.TemporaryDirectory(
            prefix=".query-", dir=self.directory
        ) as staging:
            (Path(staging) / "query.json").write_bytes(envelope)
            Path(staging).rename(destination)
        return self.get(document["query_id"])

    def get(self, query_id):
        try:
            if not isinstance(query_id, str) or str(UUID(query_id)) != query_id:
                raise ValueError("Invalid query ID")
            with (self.directory / query_id / "query.json").open("rb") as stream:
                data = stream.read(MAX_SNAPSHOT_BYTES + 1)
            if len(data) > MAX_SNAPSHOT_BYTES:
                raise ValueError("Query snapshot exceeds its storage limit")
            envelope = json.loads(data)
            document = envelope["document"]
            if hashlib.sha256(_encode(document)).hexdigest() != envelope["sha256"]:
                raise ValueError("Query snapshot checksum mismatch")
            if (
                document["query_id"] != query_id
                or document["campaign"]["fingerprint"]["path"] != self.campaign_path
            ):
                raise ValueError("Query snapshot identity mismatch")
            if document.get("schema_version") != QUERY_SCHEMA_VERSION:
                raise ValueError("Unsupported query snapshot schema version")
            return {
                **document,
                "stale": document["campaign"]["fingerprint"]
                != campaign_fingerprint(self.campaign_path),
            }
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise MetadataQueryError(f"Query result unavailable: {error}") from error

    def list(self):
        if not self.directory.is_dir():
            return []
        results = []
        for entry in sorted(self.directory.iterdir()):
            if entry.name.startswith("."):
                continue
            try:
                document = self.get(entry.name)
            except MetadataQueryError:
                continue
            results.append(
                {
                    key: document[key]
                    for key in (
                        "query_id",
                        "request",
                        "row_count",
                        "truncated",
                        "execution",
                        "stale",
                    )
                }
            )
        return results

    def tile(self, query_id):
        result = self.get(query_id)
        headers = [
            {"title": col["name"], "key": col["key"], "sortable": True}
            for col in result["columns"]
        ]
        items = [
            {col["key"]: value for col, value in zip(result["columns"], row)}
            for row in result["rows"]
        ]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([col["name"] for col in result["columns"]])
        writer.writerows(result["rows"])
        tile = empty_grid_cell()
        tile.update(
            {
                "query_result_id": query_id,
                "variable_name": "Metadata query",
                "display_title": result["request"] or "Metadata query result",
                "media_type": "query_table",
                "tile_type": "stats",
                "status": "ok",
                "query_headers": headers,
                "query_rows": items,
                "query_row_count": result["row_count"],
                "query_truncated": result["truncated"],
                "query_truncation_reason": result["truncation_reason"],
                "query_stale": result["stale"],
                "query_csv_uri": "data:text/csv;charset=utf-8;base64,"
                + base64.b64encode(output.getvalue().encode()).decode(),
            }
        )
        return tile
