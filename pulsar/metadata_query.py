"""Bounded SQL over viewer metadata; never opens ADIOS payloads."""

import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

QUERY_SCHEMA_VERSION = 1
MAX_QUERY_ROWS = 1000
MAX_QUERY_BYTES = 1024 * 1024
MAX_SQL_LENGTH = 32768
QUERY_TIMEOUT_SECONDS = 5.0


class MetadataQueryError(ValueError):
    """A query is invalid, unavailable, interrupted, or exceeds its budget."""


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def source_reference(source):
    """Return the metadata source_ref for a backend source descriptor.

    Keep the identity precedence and fields in sync with _BASE_VIEW below.
    SQLite's json_array stores Unicode directly in these opaque references.
    """
    if source.get("source_collection_id"):
        parts = [
            "collection", source.get("schema_name", "") or "",
            source["source_collection_id"],
        ]
    elif (
        source.get("schema_file_group")
        and source.get("schema_mode") == "file_per_timestep"
    ):
        parts = [
            "file_group", source.get("schema_name", "") or "",
            source["schema_file_group"],
        ]
    elif source.get("source_dataset"):
        parts = ["dataset", source["source_dataset"]]
    else:
        parts = [
            "legacy", source.get("producer", "") or "",
            source.get("casename", "") or "", source.get("file", "") or "",
        ]
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def campaign_fingerprint(path):
    path = Path(path).expanduser().resolve()
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
        }
    except FileNotFoundError:
        return {"path": str(path), "mtime_ns": None, "size_bytes": None}


# The isolated metadata projection excludes doc_json, image_bytes, and arrays.
# A source ref is an opaque, stable JSON key, never a sidecar row ID.
_BASE_VIEW = """
create temp table _q_entries as
select
  case
    when coalesce(source_collection_id,'')<>''
      then json_array('collection',coalesce(schema_name,''),source_collection_id)
    when coalesce(schema_file_group,'')<>'' and schema_mode='file_per_timestep'
      then json_array('file_group',coalesce(schema_name,''),schema_file_group)
    when coalesce(source_dataset,'')<>'' then json_array('dataset',source_dataset)
    else json_array('legacy',coalesce(producer,''),coalesce(casename,''),coalesce(file,''))
  end as source_ref,
  variable_id, variable_name, variable_type, source_dataset, source_collection_id,
  producer, casename, file, variable_path, visualization_name, visualization_kind,
  frame_index, time_index, physical_time, time_source, min_value, max_value,
  json_extract(doc_json, '$.metadata') as metadata_json,
  json_extract(doc_json, '$.time_unit') as time_unit,
  json_extract(doc_json, '$.visualization_sequence_name') as sequence_name,
  json_extract(doc_json, '$.visualization_item_uuid') as payload_uuid
from campaign_index.campaign_entries
"""

_VIEWS = {
    "q_sources": (
        "One row per distinct source descriptor. dataset_uuid is null if unavailable.",
        """
        select e.source_ref,
          case when count(distinct e.source_dataset)=1 then min(e.source_dataset) end as source_dataset,
          min(e.source_collection_id) as source_collection_id,
          case when count(distinct nullif(e.producer,''))=1
            then min(nullif(e.producer,'')) end as producer,
          case when count(distinct nullif(e.casename,''))=1
            then min(nullif(e.casename,'')) end as casename,
          case when count(distinct nullif(e.file,''))=1
            then min(nullif(e.file,'')) end as file,
          case when count(distinct e.source_dataset)=1 and count(distinct d.uuid)=1
            then min(d.uuid) end as dataset_uuid
        from _q_entries e left join _q_datasets d on d.name=e.source_dataset
        group by e.source_ref
        """,
    ),
    "q_variables": (
        (
            "One row per source/variable. Extrema summarize stored raw-variable metadata "
            "across the source, not individual frames; null if no such record exists. "
            "metadata_json is null if source members have differing metadata."
        ),
        """
        select source_ref, variable_id, min(variable_name) as variable_name,
          min(case when variable_type='variable' then min_value end) as minimum,
          max(case when variable_type='variable' then max_value end) as maximum,
          case when count(distinct case when variable_type='variable' then metadata_json end)=1
            then min(case when variable_type='variable' then metadata_json end) end as metadata_json,
          count(distinct variable_type) as representation_type_count,
          'whole_source' as statistics_scope
        from _q_entries group by source_ref, variable_id
        """,
    ),
    "q_representations": (
        (
            "One row per source/variable/type/visualization sequence. record_count counts "
            "index records for this representation, not raw simulation steps. A statistic "
            "representation is discoverable here but its value array is not exposed."
        ),
        """
        select json_array(source_ref,variable_id,variable_type,visualization_name,visualization_kind,sequence_name)
            as representation_ref,
          source_ref,variable_id,variable_type,visualization_name,visualization_kind,
          sequence_name,count(*) as record_count,
          min(physical_time) as first_physical_time,max(physical_time) as last_physical_time
        from _q_entries group by source_ref,variable_id,variable_type,
          visualization_name,visualization_kind,sequence_name
        """,
    ),
    "q_samples": (
        (
            "One row per indexed image or scalar-field sample association. Different "
            "representations may describe the same source step: choose a representation "
            "before aggregating. Extrema describe the stored representation, including its "
            "precision. Images without numeric statistics retain null extrema. Physical "
            "time/unit may be unknown; frame_index and time_index are not physical time."
        ),
        """
        select json_array(source_ref,variable_id,variable_type,sequence_name,
            variable_path,payload_uuid,frame_index) as sample_ref,
          json_array(source_ref,variable_id,variable_type,visualization_name,visualization_kind,sequence_name)
            as representation_ref,
          source_ref,source_dataset,variable_id,variable_type,visualization_name,
          variable_path,payload_uuid,frame_index,time_index,physical_time,time_unit,
          time_source,min_value as minimum,max_value as maximum,metadata_json,
          'stored_sample' as statistics_scope
        from _q_entries where variable_type in ('image','scalarField')
        """,
    ),
}

_FUNCTIONS = frozenset(
    [
        "abs",
        "avg",
        "coalesce",
        "count",
        "dense_rank",
        "first_value",
        "format",
        "glob",
        "group_concat",
        "hex",
        "ifnull",
        "iif",
        "instr",
        "json_array",
        "json_array_length",
        "json_each",
        "json_extract",
        "json_group_array",
        "json_group_object",
        "json_object",
        "json_tree",
        "json_type",
        "json_valid",
        "lag",
        "last_value",
        "lead",
        "length",
        "like",
        "lower",
        "ltrim",
        "max",
        "min",
        "nth_value",
        "ntile",
        "nullif",
        "percent_rank",
        "printf",
        "quote",
        "rank",
        "replace",
        "round",
        "row_number",
        "rtrim",
        "sign",
        "substr",
        "substring",
        "sum",
        "total",
        "trim",
        "typeof",
        "unicode",
        "upper",
    ]
)


def _authorize(action, first, second, database, origin):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and str(second).lower() in _FUNCTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        if database == "temp" and first in _VIEWS:
            return sqlite3.SQLITE_OK
        if (
            database == "temp"
            and first in {"_q_entries", "_q_datasets"}
            and origin in _VIEWS
        ):
            return sqlite3.SQLITE_OK
        # Table-valued JSON functions only operate on already-permitted values.
        if first in {"json_each", "json_tree"}:
            return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class MetadataQueryEngine:
    def __init__(self, index_path, campaign_path):
        self.index_path = Path(index_path).expanduser().resolve()
        self.campaign_path = Path(campaign_path).expanduser().resolve()

    def _campaign_metadata(self):
        identity, datasets = None, []
        if not self.campaign_path.is_file():
            return identity, datasets
        with closing(
            sqlite3.connect(
                self.campaign_path.as_uri() + "?mode=ro", uri=True, timeout=1
            )
        ) as con:
            tables = {
                row[0]
                for row in con.execute(
                    "select name from sqlite_master where type='table'"
                )
            }
            if "campaign_identity" in tables:
                row = con.execute(
                    "select uuid from campaign_identity where singleton=1"
                ).fetchone()
                identity = row[0] if row else None
            if "dataset" in tables:
                datasets = con.execute(
                    "select name,uuid from dataset where deltime is null or deltime=0"
                ).fetchall()
        return identity, datasets

    @contextmanager
    def _connection(self, cancel):
        started = time.monotonic()
        fingerprint = campaign_fingerprint(self.campaign_path)
        identity, datasets = self._campaign_metadata()
        with closing(sqlite3.connect(":memory:", uri=True, timeout=1)) as con:
            con.set_progress_handler(
                lambda: int(
                    cancel.is_set()
                    or time.monotonic() - started > QUERY_TIMEOUT_SECONDS
                ),
                1000,
            )
            con.execute(
                "attach database ? as campaign_index",
                (self.index_path.as_uri() + "?mode=ro",),
            )
            con.execute("begin")
            source = con.execute(
                "select path,mtime_ns,size_bytes from campaign_index.campaign_source where id=1"
            ).fetchone()
            if (
                source is None
                or Path(source[0]).expanduser().resolve() != self.campaign_path
            ):
                raise MetadataQueryError("Index belongs to a different campaign")
            if (source[1], source[2]) != (
                fingerprint["mtime_ns"],
                fingerprint["size_bytes"],
            ):
                raise MetadataQueryError(
                    "Campaign changed since indexing; refresh the viewer before querying"
                )
            con.execute(
                "create temp table _q_datasets(name text primary key,uuid text)"
            )
            con.executemany("insert or ignore into _q_datasets values (?,?)", datasets)
            con.execute(_BASE_VIEW)
            # Detach the original DB before preparing any caller SQL. Even a
            # caller-defined CTE that impersonates a view cannot reach payloads.
            con.commit()
            con.execute("detach database campaign_index")
            # Identify the metadata actually queried, including overrides or
            # reindexing, rather than relying on WAL timestamps/sidecar row IDs.
            digest = hashlib.sha256(
                _json([QUERY_SCHEMA_VERSION, fingerprint, identity]).encode()
            )
            width = len(con.execute("select * from _q_entries limit 0").description)
            order = ",".join(str(index + 1) for index in range(width))
            for row in con.execute(f"select * from _q_entries order by {order}"):
                digest.update(
                    json.dumps(row, ensure_ascii=True, separators=(",", ":")).encode()
                )
                digest.update(b"\n")
            digest.update(_json(sorted(datasets)).encode())
            generation = digest.hexdigest()
            for name, (_description, sql) in _VIEWS.items():
                con.execute(f"create temp view {name} as {sql}")
            columns = {
                name: [
                    {"name": row[1], "declared_type": row[2] or "dynamic"}
                    for row in con.execute(f"pragma temp.table_info({name})")
                ]
                for name in _VIEWS
            }
            con.execute("pragma query_only=on")
            con.set_authorizer(_authorize)
            # setlimit is available on Python 3.11+, while Pulsar supports 3.10.
            if hasattr(con, "setlimit"):
                for name, limit in (
                    ("SQLITE_LIMIT_LENGTH", MAX_QUERY_BYTES * 2),
                    ("SQLITE_LIMIT_SQL_LENGTH", MAX_SQL_LENGTH),
                    ("SQLITE_LIMIT_COLUMN", 100),
                    ("SQLITE_LIMIT_EXPR_DEPTH", 50),
                    ("SQLITE_LIMIT_ATTACHED", 0),
                ):
                    con.setlimit(getattr(sqlite3, name), limit)
            yield (
                con,
                {
                    "fingerprint": fingerprint,
                    "campaign_uuid": identity,
                    "index_generation": generation,
                },
                columns,
            )
            if campaign_fingerprint(self.campaign_path) != fingerprint:
                raise MetadataQueryError(
                    "Campaign changed while querying; refresh and retry"
                )

    def schema(self):
        try:
            with self._connection(Event()) as (_con, campaign, columns):
                return {
                    "version": QUERY_SCHEMA_VERSION,
                    "scope": "campaign",
                    "functions": sorted(_FUNCTIONS),
                    "campaign": campaign,
                    "limits": {
                        "rows": MAX_QUERY_ROWS,
                        "bytes": MAX_QUERY_BYTES,
                        "seconds": QUERY_TIMEOUT_SECONDS,
                    },
                    "views": [
                        {
                            "name": name,
                            "description": _VIEWS[name][0],
                            "columns": columns[name],
                        }
                        for name in _VIEWS
                    ],
                    "joins": [
                        "q_variables.source_ref = q_sources.source_ref",
                        (
                            "q_representations.source_ref = q_variables.source_ref AND "
                            "q_representations.variable_id = q_variables.variable_id"
                        ),
                        "q_samples.representation_ref = q_representations.representation_ref",
                    ],
                    "notes": [
                        "Only stored metadata is queried; no raw arrays or media are read.",
                        "Scope is the whole campaign, independent of viewer filters.",
                        "References are opaque keys scoped to the recorded campaign.",
                        "Null means unknown. Do not infer units or align sources by step number.",
                    ],
                }
        except sqlite3.Error as error:
            raise MetadataQueryError(str(error)) from error

    def execute(self, sql, parameters=None, request="", *, cancel=None):
        if not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL_LENGTH:
            raise MetadataQueryError(
                f"SQL must be nonempty text of at most {MAX_SQL_LENGTH} characters"
            )
        if not isinstance(request, str) or len(request) > 8192:
            raise MetadataQueryError("request must be text of at most 8192 characters")
        parameters = {} if parameters is None else parameters
        if not isinstance(parameters, (dict, list)):
            raise MetadataQueryError("parameters must be an object or array")
        values = parameters.values() if isinstance(parameters, dict) else parameters
        if any(
            not isinstance(value, (str, int, float, type(None)))
            or isinstance(value, float)
            and not math.isfinite(value)
            for value in values
        ):
            raise MetadataQueryError("SQL parameters must be finite scalar JSON values")
        values = parameters.values() if isinstance(parameters, dict) else parameters
        if any(
            isinstance(value, int) and not -(2**63) <= value < 2**63 for value in values
        ):
            raise MetadataQueryError(
                "Integer parameters must fit a signed 64-bit SQLite integer"
            )
        cancel = cancel if cancel is not None else Event()
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        try:
            with self._connection(cancel) as (con, campaign, _columns):
                if cancel.is_set():
                    raise MetadataQueryError("Query cancelled")
                cursor = con.execute(sql, parameters)
                if cursor.description is None:
                    raise MetadataQueryError("Query must return rows")
                if len(cursor.description) > 100:
                    raise MetadataQueryError("Query results are limited to 100 columns")
                columns = [
                    {"name": item[0], "key": f"c{i}", "type": "unknown"}
                    for i, item in enumerate(cursor.description)
                ]
                rows, size, reason = [], 0, ""
                for raw in cursor:
                    if (
                        cancel.is_set()
                        or time.monotonic() - started > QUERY_TIMEOUT_SECONDS
                    ):
                        raise MetadataQueryError(
                            "Query cancelled or exceeded its time limit"
                        )
                    if len(rows) == MAX_QUERY_ROWS:
                        reason = "row_limit"
                        break
                    row = list(raw)
                    if any(
                        isinstance(value, bytes)
                        or isinstance(value, float)
                        and not math.isfinite(value)
                        for value in row
                    ):
                        raise MetadataQueryError(
                            "Query returned a blob or non-finite value"
                        )
                    size += len(_json(row).encode())
                    if size > MAX_QUERY_BYTES:
                        reason = "byte_limit"
                        break
                    rows.append(row)
                    for column, value in zip(columns, row):
                        if value is None:
                            continue
                        kind = "number" if isinstance(value, (int, float)) else "text"
                        if column["type"] == "unknown":
                            column["type"] = kind
                        elif column["type"] != kind:
                            column["type"] = "mixed"
                references = self._references(con, columns, rows)
            return {
                "schema_version": QUERY_SCHEMA_VERSION,
                "scope": "campaign",
                "request": request,
                "sql": sql,
                "parameters": parameters,
                "campaign": campaign,
                "columns": columns,
                "rows": rows,
                "references": references,
                "row_count": len(rows),
                "truncated": bool(reason),
                "truncation_reason": reason,
                "execution": {
                    "status": "success",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": time.monotonic() - started,
                    "sqlite_version": sqlite3.sqlite_version,
                },
            }
        except (sqlite3.Error, OSError) as error:
            message = (
                "Query cancelled or exceeded its time limit"
                if cancel.is_set() or time.monotonic() - started > QUERY_TIMEOUT_SECONDS
                else str(error)
            )
            raise MetadataQueryError(message) from error

    @staticmethod
    def _references(con, columns, rows):
        references = []
        for index, column in enumerate(columns):
            name = column["name"]
            view = {
                "source_ref": "q_sources",
                "representation_ref": "q_representations",
                "sample_ref": "q_samples",
            }.get(name)
            if view is None:
                continue
            candidates = sorted(
                {row[index] for row in rows if isinstance(row[index], str)}
            )
            verified = set()
            for start in range(0, len(candidates), 200):
                values = candidates[start : start + 200]
                placeholders = ",".join("?" for _ in values)
                verified.update(
                    row[0]
                    for row in con.execute(
                        f"select {name} from {view} where {name} in ({placeholders})",
                        values,
                    )
                )
            for row_index, row in enumerate(rows):
                value = row[index]
                if not isinstance(value, str) or value not in verified:
                    continue
                references.append(
                    {
                        "row": row_index,
                        "column": column["key"],
                        "kind": name,
                        "ref": value,
                    }
                )
        return references
