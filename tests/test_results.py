"""Working-result storage is durable, immutable, and independent of the cache."""

from pathlib import Path

import pytest
from PIL import Image

from pulsar.results import ResultError, ResultStore


@pytest.fixture
def artifacts(tmp_path):
    image = tmp_path / "comparison.png"
    Image.new("RGB", (16, 12), "red").save(image)
    script = tmp_path / "analysis.py"
    script.write_text("raise RuntimeError('must never execute during registration')\n")
    return image, script


def test_registration_copies_inputs_and_survives_a_fresh_store(tmp_path, artifacts):
    image, script = artifacts
    original = image.read_bytes(), script.read_bytes()
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    provenance = {
        "request": "Compare current_z",
        "intent": "Examine resolution sensitivity",
        "inputs": [
            {
                "source_dataset": "hll_32/output.bp",
                "variable_id": "current_z",
                "step": 4,
            }
        ],
    }
    result = store.register(
        title="Comparison",
        image_path=image,
        script_path=script,
        parameters={"time": 0.1},
        provenance=provenance,
    )
    image.write_bytes(b"overwritten")
    script.write_text("overwritten")
    provenance["intent"] = "changed after registration"
    fresh = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    assert fresh.artifact(result["result_id"], "image") == original[0]
    assert fresh.artifact(result["result_id"], "script") == original[1]
    assert (
        fresh.get(result["result_id"])["provenance"]["intent"]
        == "Examine resolution sensitivity"
    )
    assert fresh.get(result["result_id"])["parameters"] == {"time": 0.1}
    assert fresh.list() == [result]
    assert result["publication_status"] == "unpublished"
    assert fresh.tile(result["result_id"])["src"].endswith("/image.png")
    assert not (tmp_path / "campaign.aca").exists()


def test_valid_array_metadata_survives_manifest_round_trip(tmp_path, artifacts):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    provenance = {"sample_indices": list(range(16000))}
    result = store.register(
        title="Many inputs", image_path=artifacts[0], provenance=provenance
    )
    assert store.get(result["result_id"]) == result
    assert store.list() == [result]
    assert store.tile(result["result_id"])["status"] == "ok"


@pytest.mark.parametrize(
    "metadata",
    [
        {"parameters": []},
        {"provenance": "unstructured"},
        {"parameters": {"invalid": float("nan")}},
        {"provenance": {"oversized": "x" * 131073}},
    ],
)
def test_invalid_metadata_leaves_no_result(tmp_path, artifacts, metadata):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    with pytest.raises(ResultError):
        store.register(title="Bad", image_path=artifacts[0], **metadata)
    assert store.list() == []
    assert not store.directory.exists()


def test_rejects_non_png_and_bad_script_without_partial_registration(
    tmp_path, artifacts
):
    image, _ = artifacts
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    with pytest.raises(ResultError):
        store.register(
            title="Bad", image_path=image, script_path=tmp_path / "missing.py"
        )
    Image.new("RGB", (2, 2)).save(image, format="JPEG")
    with pytest.raises(ResultError, match="PNG"):
        store.register(title="Bad", image_path=image)
    assert store.list() == []


def test_staged_failure_does_not_publish_incomplete_bundle(
    tmp_path, artifacts, monkeypatch
):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(OSError, match="disk full"):
        store.register(title="Failure", image_path=artifacts[0])
    assert store.list() == []
    assert list(store.directory.iterdir()) == []


def test_checksums_and_campaign_scoping(tmp_path, artifacts):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    result = store.register(title="Comparison", image_path=artifacts[0])
    different_campaign = ResultStore(tmp_path / "results", tmp_path / "other.aca")
    with pytest.raises(ResultError):
        different_campaign.get(result["result_id"])
    copied_image = store.directory / result["result_id"] / "image.png"
    copied_image.write_bytes(b"corrupted")
    with pytest.raises(ResultError, match="checksum"):
        store.tile(result["result_id"])


def test_corrupted_copied_script_is_detected_when_restoring_a_result(
    tmp_path, artifacts
):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    result = store.register(
        title="Comparison", image_path=artifacts[0], script_path=artifacts[1]
    )
    (store.directory / result["result_id"] / "analysis.py").write_text(
        "changed copied code"
    )
    with pytest.raises(ResultError, match="checksum"):
        store.tile(result["result_id"])


@pytest.mark.parametrize("identifier", ["../outside", "", "not-a-uuid"])
def test_invalid_ids_cannot_escape_store(tmp_path, identifier):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    with pytest.raises(ResultError):
        store.get(identifier)


def test_registered_versions_have_distinct_identities(tmp_path, artifacts):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    one = store.register(title="Comparison", image_path=artifacts[0])
    two = store.register(title="Comparison", image_path=artifacts[0])
    assert one["result_id"] != two["result_id"]
    assert one["artifacts"]["image"]["sha256"] == two["artifacts"]["image"]["sha256"]
    assert len(store.list()) == 2


def test_movie_registration_copies_bytes_and_restores_without_original(
    tmp_path, artifacts, working_movie
):
    image, script = artifacts
    original = working_movie.read_bytes()
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    result = store.register(
        title="Comparison movie",
        image_path=image,
        video_path=working_movie,
        script_path=script,
        provenance={"intent": "Compare contours"},
    )
    assert result["media_type"] == "video"
    assert result["video"]["frame_count"] == 2
    assert result["video"]["fps"] == 2
    assert result["video"]["duration"] == 1
    working_movie.write_bytes(b"changed outside store")
    fresh = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    tile = fresh.tile(result["result_id"])
    assert tile["media_type"] == "video"
    assert tile["frame_count"] == 2
    assert tile["src"].endswith("/movie.mp4")
    assert tile["poster"].endswith("/image.png")
    assert tile["publication_status"] == "unpublished"
    assert fresh.artifact(result["result_id"], "video") == original
    assert fresh.get(result["result_id"])["provenance"]["intent"] == "Compare contours"
    assert not (tmp_path / "campaign.aca").exists()
    (fresh.directory / result["result_id"] / "movie.mp4").write_bytes(b"corrupt")
    with pytest.raises(ResultError, match="checksum"):
        fresh.tile(result["result_id"])


def test_invalid_movie_does_not_register_partial_bundle(tmp_path, artifacts):
    movie = tmp_path / "bad.mp4"
    movie.write_bytes(b"not a movie")
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    with pytest.raises(ResultError, match="valid browser-compatible"):
        store.register(title="Bad movie", image_path=artifacts[0], video_path=movie)
    assert store.list() == []
    assert not store.directory.exists()


def test_movie_physical_times_survive_copy_and_restore(
    tmp_path, artifacts, working_movie
):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    times = [1.0, 1.0]
    source = {"kind": "explicit"}
    result = store.register(
        title="Timed movie",
        image_path=artifacts[0],
        video_path=working_movie,
        frame_times=times,
        time_unit="s",
        time_source=source,
    )
    times[0] = 99
    source["kind"] = "changed"
    fresh = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    tile = fresh.tile(result["result_id"])
    assert tile["time_mode"] == "physical_time"
    assert tile["time_values"] == [1.0, 1.0]
    assert tile["time_unit"] == "s"
    assert tile["time_source"] == {"kind": "explicit"}


@pytest.mark.parametrize(
    "timing",
    [
        {"frame_times": [0]},
        {"frame_times": [1, 0]},
        {"frame_times": [0, float("nan")]},
        {"frame_times": [0, 1], "time_unit": ""},
        {"frame_times": [0, 1], "time_source": []},
        {"time_unit": "s"},
    ],
)
def test_invalid_movie_times_leave_no_working_result(
    tmp_path, artifacts, working_movie, timing
):
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    with pytest.raises(ResultError):
        store.register(
            title="Invalid timing",
            image_path=artifacts[0],
            video_path=working_movie,
            **timing,
        )
    assert not store.directory.exists()


def test_movie_size_limit_is_checked_before_registration(
    tmp_path, artifacts, working_movie, monkeypatch
):
    from pulsar import results

    monkeypatch.setattr(results, "MAX_VIDEO_BYTES", 16)
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    with pytest.raises(ResultError, match="byte limit"):
        store.register(
            title="Too big", image_path=artifacts[0], video_path=working_movie
        )
    assert not store.directory.exists()


def test_movie_registration_reports_missing_ffprobe(
    tmp_path, artifacts, working_movie, monkeypatch
):
    from pulsar import results

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(results.subprocess, "run", missing)
    store = ResultStore(tmp_path / "results", tmp_path / "campaign.aca")
    with pytest.raises(ResultError, match="requires ffprobe"):
        store.register(
            title="No probe", image_path=artifacts[0], video_path=working_movie
        )
    assert not store.directory.exists()
