import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from db import CampaignDb
from ingest_campaign import (
    _load_visualization_api_index,
    _video_variables_from_provenance,
)
from pulsar.campaign_media import (
    _byte_range,
    read_embedded_video,
    register_campaign_media_route,
)
from sqlite_store import open_sqlite_collection


class CampaignMediaTests(unittest.TestCase):
    def _archive_with_video(self, path: Path, payload: bytes, *, keyid=0):
        con = sqlite3.connect(path)
        con.executescript(
            """
            create table dataset(name text, uuid text, fileformat text, deltime int);
            create table replica(datasetid int, deltime int, keyid int);
            create table repfiles(replicaid int, fileid int);
            create table file(fileid integer primary key, compression int, lenorig int, data blob);
            """
        )
        con.execute(
            "insert into dataset values (?, ?, 'VIDEO', 0)",
            ("runs/run-a/movie.mp4", "12345678-1234-1234"),
        )
        con.execute("insert into replica values (1, 0, ?)", (keyid,))
        con.execute(
            "insert into file values (1, 1, ?, ?)",
            (len(payload), zlib.compress(payload)),
        )
        con.execute("insert into repfiles values (1, 1)")
        con.commit()
        con.close()

    def test_reads_embedded_video_from_local_archive(self):
        payload = b"\x00\x00\x00\x18ftypmp42-test-video"
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "campaign.aca"
            self._archive_with_video(archive, payload)

            self.assertEqual(
                read_embedded_video(str(archive), "12345678-1234-1234"),
                payload,
            )

    def test_encrypted_or_invalid_video_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "campaign.aca"
            self._archive_with_video(archive, b"video", keyid=4)

            self.assertIsNone(
                read_embedded_video(str(archive), "12345678-1234-1234")
            )
            self.assertIsNone(read_embedded_video(str(archive), "../outside"))

    def test_byte_ranges_include_open_and_suffix_forms(self):
        self.assertEqual(_byte_range("bytes=2-5", 10), (2, 5))
        self.assertEqual(_byte_range("bytes=7-", 10), (7, 9))
        self.assertEqual(_byte_range("bytes=-3", 10), (7, 9))
        self.assertIsNone(_byte_range("bytes=10-", 10))

    def test_media_route_serves_mp4_and_http_byte_ranges(self):
        async def check_route():
            payload = b"\x00\x00\x00\x18ftypmp42-test-video"
            with tempfile.TemporaryDirectory() as temp_dir:
                archive = Path(temp_dir) / "campaign.aca"
                self._archive_with_video(archive, payload)
                callbacks = []
                server = SimpleNamespace(
                    controller=SimpleNamespace(
                        on_server_bind=SimpleNamespace(add=callbacks.append)
                    )
                )
                register_campaign_media_route(server, str(archive))
                app = web.Application()
                callbacks[0](SimpleNamespace(app=app))
                client = TestClient(TestServer(app))
                await client.start_server()
                try:
                    full = await client.get("/pulsar-media/12345678-1234-1234")
                    self.assertEqual(full.status, 200)
                    self.assertEqual(full.headers["Content-Type"], "video/mp4")
                    self.assertEqual(await full.read(), payload)

                    partial = await client.get(
                        "/pulsar-media/12345678-1234-1234",
                        headers={"Range": "bytes=4-11"},
                    )
                    self.assertEqual(partial.status, 206)
                    self.assertEqual(partial.headers["Content-Range"], f"bytes 4-11/{len(payload)}")
                    self.assertEqual(await partial.read(), payload[4:12])
                finally:
                    await client.close()

        import asyncio

        asyncio.run(check_route())

    def test_visualization_index_includes_video_item_and_physical_times(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "campaign.aca"
            con = sqlite3.connect(archive)
            con.executescript(
                """
                create table dataset(name text, uuid text, fileformat text);
                create table visualization_sequence(
                  visid integer, name text, vistype text, metadata text
                );
                create table visualization_item(
                  visid integer, item_order integer, item_type text,
                  item_uuid text, metadata text
                );
                create table visualization_variable(
                  visid integer, datasetid integer, variable_name text, role text
                );
                """
            )
            con.execute(
                "insert into dataset values (?, ?, ?)",
                ("runs/run-a/movie.mp4", "12345678-1234-1234", "VIDEO"),
            )
            con.execute(
                "insert into dataset values (?, ?, ?)",
                ("runs/run-a/output.bp", "source-uuid-12345678", "BP"),
            )
            con.execute(
                "insert into visualization_sequence values (1, ?, ?, ?)",
                (
                    "runs/run-a/visualizations/pressure",
                    "heatmap",
                    "{}",
                ),
            )
            con.execute(
                "insert into visualization_item values (1, 0, 'VIDEO', ?, ?)",
                (
                    "12345678-1234-1234",
                    '{"time_mode":"physical_time","time_values":[0.0,0.25],"frame_count":2}',
                ),
            )
            con.execute(
                "insert into visualization_variable values (1, 2, 'pressure', 'color-by')"
            )
            con.commit()
            con.close()

            item = _load_visualization_api_index(str(archive))["runs/run-a/movie.mp4"]

        self.assertEqual(item["item_type"], "VIDEO")
        self.assertEqual(item["item_dataset_uuid"], "12345678-1234-1234")
        self.assertEqual(item["item_metadata"]["time_values"], [0.0, 0.25])
        self.assertEqual(item["display_variables"][0]["name"], "pressure")

    def test_video_provenance_repairs_semantic_variable_roles(self):
        variables = _video_variables_from_provenance(
            {
                "activity_metadata": {
                    "semantic_variables": {
                        "color_by": "pressure",
                        "streamline_by": ["velocity_x", "velocity_y"],
                    }
                },
                "inputs": [
                    {
                        "name": "pressure",
                        "source_dataset": "runs/run-a/output.bp",
                    },
                    {
                        "name": "velocity_x",
                        "source_dataset": "runs/run-a/output.bp",
                    },
                    {
                        "name": "velocity_y",
                        "source_dataset": "runs/run-a/output.bp",
                    },
                ],
            }
        )

        self.assertEqual(
            [(item["name"], item["roles"]) for item in variables],
            [
                ("pressure", ["color-by"]),
                ("velocity_x", ["streamline-x"]),
                ("velocity_y", ["streamline-y"]),
            ],
        )
        self.assertEqual(
            {item["source_dataset"] for item in variables},
            {"runs/run-a/output.bp"},
        )

    def test_video_tile_uses_media_route_and_time_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "campaign.aca"
            archive.touch()
            collection = open_sqlite_collection(
                str(archive), db_path=str(Path(temp_dir) / "sidecar.sqlite")
            )
            try:
                collection.insert_one(
                    {
                        "campaign_path": str(archive),
                        "variable_id": "pressure",
                        "variable_name": "pressure",
                        "variable_type": "video",
                        "visualization_name": "pressure_movie",
                        "visualization_item_uuid": "12345678-1234-1234",
                        "visualization_item_type": "VIDEO",
                        "visualization_item_metadata": {
                            "frame_count": 2,
                            "time_values": [0.0, 0.25],
                        },
                        "frame_count": 2,
                        "frame_indices": [0, 1],
                        "time_values": [0.0, 0.25],
                        "time_mode": "physical_time",
                    }
                )
                tile = CampaignDb(collection).get_first_movie_tiles_for_variable(
                    "pressure", fps=10
                )[0]
            finally:
                collection.close()

        self.assertEqual(tile["media_type"], "video")
        self.assertEqual(tile["src"], "/pulsar-media/12345678-1234-1234")
        self.assertEqual(tile["frame_count"], 2)
        self.assertEqual(tile["time_values"], [0.0, 0.25])
        self.assertEqual(tile["time_mode"], "physical_time")
        self.assertEqual(tile["fps"], 10)


if __name__ == "__main__":
    unittest.main()
