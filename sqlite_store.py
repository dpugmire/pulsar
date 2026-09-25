import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SIDECAR_SCHEMA_VERSION = 3

INDEXED_FIELDS = {
    "campaign_path": "campaign_path",
    "variable_id": "variable_id",
    "variable_name": "variable_name",
    "variable_type": "variable_type",
    "source_dataset": "source_dataset",
    "source_collection_id": "source_collection_id",
    "producer": "producer",
    "casename": "casename",
    "file": "file",
    "visualization_name": "visualization_name",
    "visualization_kind": "visualization_kind",
    "visualization_source_dataset": "visualization_source_dataset",
    "association_source": "association_source",
    "variable_path": "variable_path",
    "variable_location": "variable_location",
    "frame_index": "frame_index",
    "schema_name": "schema_name",
    "schema_file_group": "schema_file_group",
    "schema_role": "schema_role",
    "schema_mode": "schema_mode",
    "schema_frame_index": "schema_frame_index",
    "schema_step_index": "schema_step_index",
    "time_index": "time_index",
    "physical_time": "physical_time",
    "time_source": "time_source",
    "min": "min_value",
    "max": "max_value",
}

TEXT_FIELDS = {
    "campaign_path",
    "variable_id",
    "variable_name",
    "variable_type",
    "source_dataset",
    "source_collection_id",
    "producer",
    "casename",
    "file",
    "visualization_name",
    "visualization_kind",
    "visualization_source_dataset",
    "association_source",
    "variable_path",
    "variable_location",
    "schema_name",
    "schema_file_group",
    "schema_role",
    "schema_mode",
    "time_source",
}

NUMERIC_FIELDS = {
    "frame_index",
    "schema_frame_index",
    "schema_step_index",
    "time_index",
    "physical_time",
    "min",
    "max",
}

ADDED_COLUMNS = {
    "source_collection_id": "text",
    "schema_name": "text",
    "schema_file_group": "text",
    "schema_role": "text",
    "schema_mode": "text",
    "schema_frame_index": "integer",
    "schema_step_index": "integer",
    "time_index": "integer",
    "physical_time": "real",
    "time_source": "text",
}


def _safe_filename(value: str) -> str:
    text = Path(value or "campaign").name or "campaign"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def sqlite_sidecar_path(campaign_path: str, db_path: Optional[str] = None) -> Path:
    explicit = db_path or os.getenv("SEURAT_SQLITE_DB", "").strip()
    campaign = Path(campaign_path or "campaign").expanduser()
    if explicit:
        path = Path(explicit).expanduser()
        if path.suffix == "":
            path = path / f"{_safe_filename(str(campaign))}.seurat.sqlite"
        return path

    cache_dir = Path(os.getenv("SEURAT_CACHE_DIR", "~/.cache/seurat")).expanduser()
    try:
        key_source = str(campaign.resolve())
    except Exception:
        key_source = str(campaign.absolute())
    digest = hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{_safe_filename(str(campaign))}.{digest}.seurat.sqlite"


def open_sqlite_collection(campaign_path: str, db_path: Optional[str] = None):
    return SQLiteCampaignCollection(sqlite_sidecar_path(campaign_path, db_path), campaign_path)


def _json_default(value: Any):
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _to_json(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, default=_json_default, separators=(",", ":"), sort_keys=True)


def _from_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    value = json.loads(text)
    return value if isinstance(value, dict) else {}


def _text_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _int_value(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(float(str(value)))
        except Exception:
            return None


def _float_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        try:
            return float(str(value))
        except Exception:
            return None


def _sqlite_regexp(pattern: Any, value: Any) -> int:
    if pattern is None or value is None:
        return 0
    text_pattern = str(pattern)
    if len(text_pattern) > 2048:
        return 0
    try:
        return int(re.search(text_pattern, str(value)) is not None)
    except re.error:
        return 0


class _SQLiteAdmin:
    def command(self, name: str):
        if str(name).lower() != "ping":
            raise ValueError(f"Unsupported SQLite admin command: {name}")
        return {"ok": 1}


class _SQLiteClient:
    def __init__(self):
        self.admin = _SQLiteAdmin()


class _SQLiteDatabase:
    def __init__(self):
        self.client = _SQLiteClient()


class SQLiteCursor:
    def __init__(self, collection, query=None, projection=None):
        self._collection = collection
        self._query = query or {}
        self._projection = projection
        self._sort_spec: List[Tuple[str, int]] = []
        self._limit: Optional[int] = None
        self._docs: Optional[List[Dict[str, Any]]] = None

    def sort(self, spec):
        self._sort_spec = self._collection.normalize_sort(spec)
        self._docs = None
        return self

    def limit(self, count: int):
        try:
            self._limit = max(0, int(count))
        except Exception:
            self._limit = None
        self._docs = None
        return self

    def _ensure_docs(self) -> List[Dict[str, Any]]:
        if self._docs is None:
            self._docs = self._collection.execute_find(
                self._query,
                self._projection,
                self._sort_spec,
                self._limit,
            )
        return self._docs

    def __iter__(self):
        return iter(self._ensure_docs())

    def __len__(self):
        return len(self._ensure_docs())


class SQLiteCampaignCollection:
    def __init__(self, path: Path, campaign_path: str = ""):
        self.path = Path(path).expanduser()
        self.campaign_path = str(campaign_path or "")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.database = _SQLiteDatabase()
        self._con = sqlite3.connect(str(self.path))
        self._con.row_factory = sqlite3.Row
        self._con.create_function(
            "regexp",
            2,
            _sqlite_regexp,
            deterministic=True,
        )
        self.ok = True
        self.last_error = ""
        self._init_schema()
        self._record_campaign()

    def _init_schema(self):
        self._con.executescript(
            """
            pragma journal_mode = wal;
            pragma synchronous = normal;

            create table if not exists seurat_meta (
              key text primary key,
              value text
            );

            create table if not exists campaign_source (
              id integer primary key check (id = 1),
              path text not null,
              mtime_ns integer,
              size_bytes integer
            );

            create table if not exists campaign_entries (
              id integer primary key autoincrement,
              campaign_path text,
              variable_id text,
              variable_name text,
              variable_type text,
              source_dataset text,
              source_collection_id text,
              producer text,
              casename text,
              file text,
              visualization_name text,
              visualization_kind text,
              visualization_source_dataset text,
              association_source text,
              variable_path text,
              variable_location text,
              frame_index integer,
              schema_name text,
              schema_file_group text,
              schema_role text,
              schema_mode text,
              schema_frame_index integer,
              schema_step_index integer,
              time_index integer,
              physical_time real,
              time_source text,
              min_value real,
              max_value real,
              doc_json text not null,
              image_bytes blob
            );

            create index if not exists idx_campaign_entries_var
              on campaign_entries(variable_id, variable_type);
            create index if not exists idx_campaign_entries_vis
              on campaign_entries(variable_id, variable_type, visualization_name);
            create index if not exists idx_campaign_entries_source
              on campaign_entries(source_dataset, producer, casename, file);
            create index if not exists idx_campaign_entries_frame
              on campaign_entries(variable_id, visualization_name, source_dataset, frame_index);
            create index if not exists idx_campaign_entries_minmax
              on campaign_entries(min_value, max_value);
            """
        )
        existing = {
            str(row["name"])
            for row in self._con.execute("pragma table_info(campaign_entries)").fetchall()
        }
        for column, ddl_type in ADDED_COLUMNS.items():
            if column not in existing:
                self._con.execute(f"alter table campaign_entries add column {column} {ddl_type}")
        self._con.execute(
            """
            create index if not exists idx_campaign_entries_source_collection
              on campaign_entries(source_collection_id, variable_id, variable_type)
            """
        )
        self._con.execute(
            """
            create index if not exists idx_campaign_entries_schema_group
              on campaign_entries(variable_id, schema_file_group, schema_mode, frame_index)
            """
        )
        self._con.execute(
            """
            create index if not exists idx_campaign_entries_physical_time
              on campaign_entries(variable_id, physical_time)
            """
        )
        self._con.execute(
            "insert or replace into seurat_meta(key, value) values (?, ?)",
            ("schema_version", str(SIDECAR_SCHEMA_VERSION)),
        )
        self._con.commit()

    def _record_campaign(self):
        path = Path(self.campaign_path).expanduser() if self.campaign_path else None
        mtime_ns = None
        size_bytes = None
        if path and path.exists():
            try:
                stat = path.stat()
                mtime_ns = int(stat.st_mtime_ns)
                size_bytes = int(stat.st_size)
            except Exception:
                pass
        self._con.execute(
            """
            insert or replace into campaign_source(id, path, mtime_ns, size_bytes)
            values (1, ?, ?, ?)
            """,
            (self.campaign_path, mtime_ns, size_bytes),
        )
        self._con.commit()

    def drop(self):
        self._con.execute("delete from campaign_entries")
        self._con.commit()

    def close(self):
        self._con.close()

    def delete_many(self, query):
        where_sql, params = self._where_sql(query or {})
        cur = self._con.execute(f"delete from campaign_entries where {where_sql}", params)
        self._con.commit()
        return SimpleNamespace(deleted_count=cur.rowcount)

    def insert_one(self, document: Dict[str, Any]):
        doc = dict(document or {})
        image_bytes = doc.pop("image_bytes", None)
        if image_bytes is not None:
            image_bytes = bytes(image_bytes)

        values = {
            "campaign_path": _text_value(doc.get("campaign_path")),
            "variable_id": _text_value(doc.get("variable_id")),
            "variable_name": _text_value(doc.get("variable_name")),
            "variable_type": _text_value(doc.get("variable_type")),
            "source_dataset": _text_value(doc.get("source_dataset")),
            "source_collection_id": _text_value(doc.get("source_collection_id")),
            "producer": _text_value(doc.get("producer")),
            "casename": _text_value(doc.get("casename")),
            "file": _text_value(doc.get("file")),
            "visualization_name": _text_value(doc.get("visualization_name")),
            "visualization_kind": _text_value(doc.get("visualization_kind")),
            "visualization_source_dataset": _text_value(doc.get("visualization_source_dataset")),
            "association_source": _text_value(doc.get("association_source")),
            "variable_path": _text_value(doc.get("variable_path")),
            "variable_location": _text_value(doc.get("variable_location")),
            "frame_index": _int_value(doc.get("frame_index")),
            "schema_name": _text_value(doc.get("schema_name")),
            "schema_file_group": _text_value(doc.get("schema_file_group")),
            "schema_role": _text_value(doc.get("schema_role")),
            "schema_mode": _text_value(doc.get("schema_mode")),
            "schema_frame_index": _int_value(doc.get("schema_frame_index")),
            "schema_step_index": _int_value(doc.get("schema_step_index")),
            "time_index": _int_value(doc.get("time_index")),
            "physical_time": _float_value(doc.get("physical_time")),
            "time_source": _text_value(doc.get("time_source")),
            "min_value": _float_value(doc.get("min")),
            "max_value": _float_value(doc.get("max")),
            "doc_json": _to_json(doc),
            "image_bytes": image_bytes,
        }
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = f"insert into campaign_entries({', '.join(columns)}) values ({placeholders})"
        cur = self._con.execute(sql, [values[col] for col in columns])
        self._con.commit()
        return SimpleNamespace(inserted_id=cur.lastrowid)

    def find(self, query=None, projection=None):
        return SQLiteCursor(self, query or {}, projection)

    def find_one(self, query=None, projection=None, sort=None):
        cursor = SQLiteCursor(self, query or {}, projection)
        if sort:
            cursor.sort(sort)
        cursor.limit(1)
        docs = list(cursor)
        return docs[0] if docs else None

    def count_documents(self, query=None) -> int:
        where_sql, params = self._where_sql(query or {})
        row = self._con.execute(f"select count(*) as count from campaign_entries where {where_sql}", params).fetchone()
        return int(row["count"] if row else 0)

    def distinct(self, field: str, query=None) -> List[Any]:
        column = self._field_column(field)
        if not column:
            seen = set()
            values: List[Any] = []
            for doc in self.find(query or {}, {field: 1, "_id": 0}):
                value = doc.get(field)
                marker = json.dumps(value, default=_json_default, sort_keys=True)
                if marker in seen:
                    continue
                seen.add(marker)
                values.append(value)
            return values

        where_sql, params = self._where_sql(query or {})
        rows = self._con.execute(
            f"select distinct {column} as value from campaign_entries where {where_sql}",
            params,
        ).fetchall()
        return [row["value"] for row in rows]

    @staticmethod
    def normalize_sort(spec) -> List[Tuple[str, int]]:
        if not spec:
            return []
        if isinstance(spec, tuple) and len(spec) == 2:
            return [(str(spec[0]), int(spec[1]))]
        items = []
        for item in spec:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                try:
                    direction = int(item[1])
                except Exception:
                    direction = 1
                items.append((str(item[0]), direction))
        return items

    def execute_find(self, query, projection, sort_spec, limit) -> List[Dict[str, Any]]:
        where_sql, params = self._where_sql(query or {})
        include_image = self._projection_needs_image(projection)
        select_image = ", image_bytes" if include_image else ""
        order_sql = self._order_sql(sort_spec)
        limit_sql = ""
        if limit is not None:
            limit_sql = " limit ?"
            params = [*params, int(limit)]
        sql = f"select id, doc_json{select_image} from campaign_entries where {where_sql}{order_sql}{limit_sql}"
        rows = self._con.execute(sql, params).fetchall()
        return [self._row_to_doc(row, projection, include_image) for row in rows]

    def _field_column(self, field: str) -> Optional[str]:
        if field == "_id":
            return "id"
        return INDEXED_FIELDS.get(str(field or ""))

    def _where_sql(self, query: Dict[str, Any]) -> Tuple[str, List[Any]]:
        if not query:
            return ("1", [])
        return self._compile_query(query)

    def _compile_query(self, query: Dict[str, Any]) -> Tuple[str, List[Any]]:
        parts: List[str] = []
        params: List[Any] = []
        for key, value in (query or {}).items():
            if key == "$and":
                subparts = [self._compile_query(item) for item in self._iter_dicts(value)]
                if not subparts:
                    continue
                parts.append("(" + " and ".join(sql for sql, _ in subparts) + ")")
                for _, subparams in subparts:
                    params.extend(subparams)
                continue
            if key == "$or":
                subparts = [self._compile_query(item) for item in self._iter_dicts(value)]
                if not subparts:
                    parts.append("0")
                    continue
                parts.append("(" + " or ".join(sql for sql, _ in subparts) + ")")
                for _, subparams in subparts:
                    params.extend(subparams)
                continue
            if key == "$nor":
                subparts = [self._compile_query(item) for item in self._iter_dicts(value)]
                if not subparts:
                    continue
                parts.append("not (" + " or ".join(sql for sql, _ in subparts) + ")")
                for _, subparams in subparts:
                    params.extend(subparams)
                continue

            sql, subparams = self._compile_field_condition(key, value)
            parts.append(sql)
            params.extend(subparams)

        return (" and ".join(parts) if parts else "1", params)

    @staticmethod
    def _iter_dicts(value: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, dict):
                    yield item

    def _compile_field_condition(self, field: str, value: Any) -> Tuple[str, List[Any]]:
        column = self._field_column(field)
        if not column:
            raise ValueError(f"Unsupported SQLite query field: {field}")

        if isinstance(value, dict):
            parts: List[str] = []
            params: List[Any] = []
            for op, raw in value.items():
                sql, subparams = self._compile_operator(column, str(op), raw)
                parts.append(sql)
                params.extend(subparams)
            return ("(" + " and ".join(parts) + ")" if parts else "1", params)

        if value is None:
            return (f"{column} is null", [])
        return (f"{column} = ?", [value])

    def _compile_operator(self, column: str, op: str, value: Any) -> Tuple[str, List[Any]]:
        if op == "$ne":
            if value is None:
                return (f"{column} is not null", [])
            return (f"({column} != ? or {column} is null)", [value])
        if op == "$in":
            values = list(value or [])
            if not values:
                return ("0", [])
            return (f"{column} in ({', '.join('?' for _ in values)})", values)
        if op == "$nin":
            values = list(value or [])
            if not values:
                return ("1", [])
            return (f"({column} not in ({', '.join('?' for _ in values)}) or {column} is null)", values)
        if op == "$gt":
            return (f"{column} > ?", [value])
        if op == "$gte":
            return (f"{column} >= ?", [value])
        if op == "$lt":
            return (f"{column} < ?", [value])
        if op == "$lte":
            return (f"{column} <= ?", [value])
        if op == "$regex":
            return (f"regexp(?, {column})", [str(value)])
        if op == "$exists":
            return (f"{column} is {'not ' if bool(value) else ''}null", [])
        raise ValueError(f"Unsupported SQLite query operator: {op}")

    def _order_sql(self, sort_spec: Sequence[Tuple[str, int]]) -> str:
        parts: List[str] = []
        for field, direction in sort_spec or []:
            column = self._field_column(field)
            if not column:
                continue
            order = "desc" if int(direction) < 0 else "asc"
            parts.append(f"{column} {order}")
        return " order by " + ", ".join(parts) if parts else ""

    @staticmethod
    def _projection_needs_image(projection) -> bool:
        if projection is None:
            return True
        return bool(projection.get("image_bytes"))

    def _row_to_doc(self, row: sqlite3.Row, projection, include_image: bool) -> Dict[str, Any]:
        doc = _from_json(row["doc_json"])
        doc["_id"] = row["id"]
        if include_image and "image_bytes" in row.keys() and row["image_bytes"] is not None:
            doc["image_bytes"] = bytes(row["image_bytes"])
        return self._apply_projection(doc, projection)

    @staticmethod
    def _apply_projection(doc: Dict[str, Any], projection) -> Dict[str, Any]:
        if projection is None:
            return doc

        include_fields = {str(k) for k, v in projection.items() if v and str(k) != "_id"}
        excludes = {str(k) for k, v in projection.items() if not v}

        if include_fields:
            out = {field: doc[field] for field in include_fields if field in doc}
            if projection.get("_id", 1) and "_id" in doc:
                out["_id"] = doc["_id"]
            return out

        out = dict(doc)
        for field in excludes:
            out.pop(field, None)
        return out
