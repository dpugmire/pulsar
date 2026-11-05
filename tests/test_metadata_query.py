"""Metadata semantics, SQL boundaries, and durable query snapshots."""

import base64
import csv
import io
import json
import sqlite3
from threading import Event
from unittest.mock import patch

import pytest

from pulsar.metadata_query import MetadataQueryEngine, MetadataQueryError, source_reference
from pulsar.query_results import QueryResultStore
from sqlite_store import SQLiteCampaignCollection


@pytest.fixture
def metadata(tmp_path):
    campaign = tmp_path / "test.aca"
    with sqlite3.connect(campaign) as con:
        con.executescript("""
            create table campaign_identity(singleton integer,uuid text);
            insert into campaign_identity values(1,'campaign-identity');
            create table dataset(name text,uuid text,deltime integer);
            insert into dataset values('run-a/output.bp','dataset-a',0);
            insert into dataset values('run-b/output.bp','dataset-b',0);
        """)
    collection = SQLiteCampaignCollection(tmp_path / "cache.sqlite", str(campaign))
    for source, offset in (("run-a/output.bp", 0), ("run-b/output.bp", 10)):
        collection.insert_one(
            {
                "variable_id": "pressure",
                "variable_name": "Pressure",
                "variable_type": "variable",
                "source_dataset": source,
                "producer": "simulation",
                "file": "output.bp",
                "min": 0,
                "max": 100 + offset,
                "metadata": {"Shape": "2,2"},
            }
        )
        for index, physical_time in enumerate((0.0, 0.6, 1.0)):
            collection.insert_one(
                {
                    "variable_id": "pressure",
                    "variable_name": "Pressure",
                    "variable_type": "scalarField",
                    "source_dataset": source,
                    "producer": "",
                    "file": "",
                    "frame_index": index,
                    "time_index": index,
                    "physical_time": physical_time,
                    "variable_path": f"{source}/fields/{index}",
                    "visualization_name": "heatmap",
                    "visualization_sequence_name": source + "/heatmap",
                    "visualization_item_uuid": f"{source}-{index}",
                    "time_unit": "s",
                    "min": index,
                    "max": 3 - index + offset,
                    "metadata": {"dtype": "float32", "shape": [2, 2]},
                    "image_bytes": b"PAYLOAD MUST NOT BE READ",
                }
            )
            collection.insert_one(
                {
                    "variable_id": "pressure",
                    "variable_name": "Pressure",
                    "variable_type": "image",
                    "source_dataset": source,
                    "frame_index": index,
                    "physical_time": physical_time,
                    "variable_path": f"{source}/images/{index}",
                    "visualization_name": "image",
                }
            )
    collection.insert_one(
        {
            "source_dataset": "run-a/output.bp",
            "variable_id": "pressure",
            "variable_type": "statistic",
            "statistic_type": "mean",
            "data": [4, 5, 6],
        }
    )
    engine = MetadataQueryEngine(collection.path, campaign)
    store = QueryResultStore(tmp_path / "durable", campaign)
    yield engine, store, collection, campaign
    collection.close()


def test_grain_identity_and_statistics_scope(metadata):
    engine, _store, _collection, _campaign = metadata
    schema = engine.schema()
    assert schema["campaign"]["campaign_uuid"] == "campaign-identity"
    assert len(schema["views"]) == 4
    assert engine.execute(
        "select producer,file from q_sources order by source_dataset"
    )["rows"] == [["simulation", "output.bp"], ["simulation", "output.bp"]]
    result = engine.execute("""
        select s.source_dataset,s.dataset_uuid,v.maximum,v.statistics_scope,
               v.representation_type_count
        from q_sources s join q_variables v using(source_ref)
        order by s.source_dataset
    """)
    assert result["rows"] == [
        ["run-a/output.bp", "dataset-a", 100.0, "whole_source", 4],
        ["run-b/output.bp", "dataset-b", 110.0, "whole_source", 3],
    ]
    assert engine.execute("select count(*) from q_samples")["rows"] == [[12]]
    assert engine.execute("select count(*) from q_samples where maximum is null")[
        "rows"
    ] == [[6]]


@pytest.mark.parametrize("fields", [
    {"source_dataset": "résolution/温度.bp"},
    {"source_collection_id": "collection", "schema_name": "schema",
     "source_dataset": "member.bp"},
    {"schema_file_group": "frames", "schema_mode": "file_per_timestep",
     "schema_name": "schema", "source_dataset": "frame-1.bp"},
    {"schema_file_group": "frames", "schema_mode": "single_file",
     "source_dataset": "single.bp"},
    {"producer": "simulation", "casename": "case", "file": "legacy.bp"},
])
def test_source_descriptor_reference_matches_sql_projection(metadata, fields):
    engine, _store, collection, _campaign = metadata
    collection.insert_one({
        "variable_id": "identity-test", "variable_type": "variable", **fields,
    })
    result = engine.execute(
        "select source_ref from q_variables where variable_id='identity-test'"
    )
    assert result["rows"] == [[source_reference(fields)]]


def test_ranking_joins_parameters_and_verified_references(metadata):
    engine, _store, collection, _campaign = metadata
    sql = """
        with ranked as (
          select *,row_number() over(partition by source_ref order by maximum desc) as r
          from q_samples where variable_type='scalarField' and physical_time>:after
        )
        select s.source_dataset,f.maximum,f.physical_time,f.sample_ref
        from ranked f join q_sources s using(source_ref)
        where r=1 order by maximum desc
    """
    result = engine.execute(sql, {"after": 0.5}, "Rank pressure")
    assert [row[:3] for row in result["rows"]] == [
        ["run-b/output.bp", 12.0, 0.6],
        ["run-a/output.bp", 2.0, 0.6],
    ]
    assert len(result["references"]) == 2
    assert result["columns"][1]["type"] == "number"
    old_refs = [row[-1] for row in result["rows"]]
    # Reinsert records to change cache row IDs without changing semantic keys.
    docs = list(collection.find({}, {"image_bytes": 0}))
    collection.drop()
    for doc in reversed(docs):
        collection.insert_one(doc)
    assert [row[-1] for row in engine.execute(sql, {"after": 0.5})["rows"]] == old_refs
    assert engine.execute("select 'forged' as sample_ref")["references"] == []


@pytest.mark.parametrize(
    "sql",
    [
        "delete from campaign_entries",
        "drop table campaign_entries",
        "create temp table bad(x)",
        "attach database ':memory:' as other",
        "pragma query_only=off",
        "vacuum",
        "begin",
        "select * from campaign_entries",
        "select * from _q_entries",
        "select * from sqlite_master",
        "select load_extension('missing')",
        "select readfile('/etc/passwd')",
        "select 1; select 2",
        "select image_bytes from campaign_entries",
        "select doc_json from campaign_entries",
        "with _q_entries as (select doc_json from campaign_entries) select * from _q_entries",
        "select * from campaign_index.campaign_entries",
        "select data from q_representations",
    ],
)
def test_disallowed_sql_preserves_database(metadata, sql):
    engine, _store, collection, _campaign = metadata
    count = collection.count_documents({})
    with pytest.raises(MetadataQueryError):
        engine.execute(sql)
    assert collection.count_documents({}) == count


def test_json_metadata_empty_results_duplicate_columns_and_invalid_parameters(metadata):
    engine, _store, _collection, _campaign = metadata
    result = engine.execute(
        "select json_extract(metadata_json,'$.shape[0]') as n,maximum as n from q_samples where variable_type=? limit 1",
        ["scalarField"],
    )
    assert [col["key"] for col in result["columns"]] == ["c0", "c1"]
    assert result["rows"][0][0] == 2
    empty = engine.execute("select maximum from q_samples where 0")
    assert empty["rows"] == [] and empty["columns"][0]["type"] == "unknown"
    with pytest.raises(MetadataQueryError):
        engine.execute("select ?", [float("nan")])
    with pytest.raises(MetadataQueryError, match="64-bit"):
        engine.execute("select ?", [2**64])
    with pytest.raises(MetadataQueryError):
        engine.execute("select 1.0/0.0,1e999")


def test_limits_cancellation_and_deadline(metadata):
    engine, _store, _collection, _campaign = metadata
    with patch("pulsar.metadata_query.MAX_QUERY_ROWS", 2):
        result = engine.execute(
            "select physical_time from q_samples order by physical_time"
        )
        assert len(result["rows"]) == 2
        assert result["truncation_reason"] == "row_limit"
        assert not engine.execute("select 1 union all select 2")["truncated"]
    with patch("pulsar.metadata_query.MAX_QUERY_BYTES", 32):
        result = engine.execute("select 'a long enough row to exceed the byte limit'")
        assert result["truncation_reason"] == "byte_limit"
    cancel = Event()
    cancel.set()
    with pytest.raises(MetadataQueryError, match="cancelled"):
        engine.execute("select 1", cancel=cancel)
    with (
        patch("pulsar.metadata_query.QUERY_TIMEOUT_SECONDS", 0.02),
        pytest.raises(MetadataQueryError, match="time limit"),
    ):
        engine.execute(
            "with recursive n(x) as (values(1) union all select x+1 from n) select sum(x) from n"
        )


def test_snapshots_restore_after_rebuild_and_detect_tampering_or_changed_campaign(
    metadata,
):
    engine, store, collection, campaign = metadata
    result = store.save(
        engine.execute(
            "select 10 as n, 'a,b' as label, null as missing", request="Example"
        )
    )
    query_id = result["query_id"]
    collection.drop()
    reconnected = QueryResultStore(store.directory, campaign)
    assert reconnected.get(query_id)["rows"] == [[10, "a,b", None]]
    assert reconnected.list()[0]["query_id"] == query_id
    tile = reconnected.tile(query_id)
    csv_text = base64.b64decode(tile["query_csv_uri"].split(",", 1)[1]).decode()
    assert list(csv.reader(io.StringIO(csv_text))) == [
        ["n", "label", "missing"],
        ["10", "a,b", ""],
    ]
    with campaign.open("ab") as stream:
        stream.write(b"change")
    assert reconnected.get(query_id)["stale"]
    with pytest.raises(MetadataQueryError, match="changed since indexing"):
        engine.execute("select 1")
    snapshot = store.directory / query_id / "query.json"
    envelope = json.loads(snapshot.read_text())
    envelope["document"]["rows"][0][0] = 999
    snapshot.write_text(json.dumps(envelope))
    with pytest.raises(MetadataQueryError, match="checksum"):
        reconnected.get(query_id)
    with pytest.raises(MetadataQueryError):
        reconnected.get("../escape")
