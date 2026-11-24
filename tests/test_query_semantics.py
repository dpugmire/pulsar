"""Behavioral parity across text, in-memory filtering, and SQLite selection."""

import json

import pytest

from query_parser import QueryValidationError, parse_query, parse_query_filters
from pulsar.models.query import query_document, query_from_filter, query_matches
from sqlite_store import SQLiteCampaignCollection


DOCUMENTS = [
    {"variable_name": "missing"},
    {"variable_name": "null", "min": None, "producer": None},
    {"variable_name": "negative", "min": -2, "producer": "run[1]"},
    {"variable_name": "zero", "min": 0, "producer": "other"},
    {"variable_name": "positive", "min": 3, "producer": "run[1]"},
]


@pytest.fixture
def collection(tmp_path):
    store = SQLiteCampaignCollection(tmp_path / "query.sqlite")
    for doc in DOCUMENTS:
        store.insert_one(doc)
    yield store
    store.close()


@pytest.mark.parametrize("expression, expected", [
    ("", {"missing", "null", "negative", "zero", "positive"}),
    ("min == None", {"missing", "null"}),
    ("min != None", {"negative", "zero", "positive"}),
    ("min", {"negative", "zero", "positive"}),
    ("min > 0", {"positive"}),
    ("not (min > 0)", {"missing", "null", "negative", "zero"}),
    ("not (min == 0)", {"missing", "null", "negative", "positive"}),
    ("min in [None, 0]", {"missing", "null", "zero"}),
    ("min not in [None, 0]", {"negative", "positive"}),
    ("min in []", set()),
    ("min not in []", {"missing", "null", "negative", "zero", "positive"}),
    ("contains(producer, 'run[1]')", {"negative", "positive"}),
    ("not contains(producer, 'run[1]')", {"missing", "null", "zero"}),
    ("(min < 0 or min > 0) and producer == 'run[1]'", {"negative", "positive"}),
])
def test_query_semantics(collection, expression, expected):
    predicate = parse_query(expression).predicate
    document = json.loads(json.dumps(query_document(predicate)))
    restored = query_from_filter(document)
    assert {doc["variable_name"] for doc in DOCUMENTS if query_matches(restored, doc)} == expected
    assert {doc["variable_name"] for doc in collection.find(document)} == expected


def test_legacy_groups_do_not_ignore_sibling_fields(collection):
    # Previously the Python evaluator returned from $or without checking producer.
    query = {"$or": [{"min": -2}, {"min": 3}], "producer": "other"}
    assert not any(query_matches(query_from_filter(query), doc) for doc in DOCUMENTS)
    assert list(collection.find(query)) == []


@pytest.mark.parametrize("expression", ["min > None", "min >= [1]", "min in [[1]]"])
def test_invalid_numeric_predicates(expression):
    with pytest.raises(QueryValidationError):
        parse_query(expression)


def test_source_clauses_and_json_round_trip():
    plan = parse_query("var == 'temperature' and source(var == 'valid' and min == 1) and source(max > 3)")
    assert len(plan.sources) == 2
    query, sources = parse_query_filters("var == 'temperature' and source(min == 1)")
    assert query_from_filter(json.loads(json.dumps(query))) == plan.predicate
    assert len(sources) == 1


@pytest.mark.parametrize("query", [
    {"query_version": 2, "op": "and", "terms": []},
    {"query_version": 1, "op": "or", "terms": "ignored"},
    {"$and": [{"producer": "run"}, "ignored"]},
    {"$unknown": []},
])
def test_malformed_queries_fail_closed(collection, query):
    with pytest.raises(ValueError):
        query_from_filter(query)
    with pytest.raises(ValueError):
        list(collection.find(query))


@pytest.mark.parametrize("seed", [0, 17, 2026])
def test_generated_nested_predicates_match_sqlite(tmp_path, seed):
    import random
    from itertools import product

    # Fixed seeds and bounded depth keep failures reproducible without a new dependency.
    randomizer = random.Random(seed)
    numbers = [None, -1.0, -5e-324, 0.0, 5e-324, 1.0, 1.7976931348623157e308]
    strings = [None, "", "Δ/run", "run[1]", "O'Reilly", "東京"]
    records = [
        {"variable_id": str(index), "min": number, "producer": text,
         "frame_index": [-2**63, 0, 2**63 - 1][index % 3]}
        for index, (number, text) in enumerate(product(numbers, strings))
    ]
    # A truly missing value is distinct input from an explicitly supplied null.
    records.append({"variable_id": "missing"})
    atoms = [
        "min == None", "min != 0", "min <= 0", "min >= 5e-324",
        "min < 1.7976931348623157e308", "min in [None, -1, 0]", "min not in []",
        "producer == ''", "producer == None", "producer in ['Δ/run', '東京', None]",
        'contains(producer, "O\'Reilly")', "contains(producer, 'run[1]')",
        "frame_index == 9223372036854775807", "frame_index >= -9223372036854775808",
    ]

    def expression(depth):
        if depth == 0 or randomizer.random() < 0.3:
            return randomizer.choice(atoms)
        if randomizer.random() < 0.25:
            return f"not ({expression(depth - 1)})"
        return f"({expression(depth - 1)}) {randomizer.choice(['and', 'or'])} ({expression(depth - 1)})"

    store = SQLiteCampaignCollection(tmp_path / "generated.sqlite")
    try:
        for record in records:
            store.insert_one(record)
        for _ in range(120):
            text = expression(3)
            predicate = parse_query(text).predicate
            encoded = json.loads(json.dumps(query_document(predicate)))
            expected = {record["variable_id"] for record in records if query_matches(predicate, record)}
            actual = {record["variable_id"] for record in store.find(encoded)}
            assert actual == expected, f"seed={seed}, query={text}"
    finally:
        store.close()



def test_null_safe_equality_preserves_indexed_variable_lookup(collection):
    predicate, _ = parse_query_filters("id == 'pressure'")
    where, parameters = collection._where_sql(predicate)
    plan = collection._con.execute(
        "explain query plan select id from campaign_entries where " + where,
        parameters,
    ).fetchall()
    assert any("SEARCH" in row[3] and "variable_id=?" in row[3] for row in plan)
