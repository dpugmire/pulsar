"""Pure source-row identity and selection operations."""

from typing import Any, Dict, Iterable, List


def source_row_keys(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [str(row.get("_key", "")) for row in rows if str(row.get("_key", ""))]


def normalize_source_keys(raw_keys) -> List[str]:
    if isinstance(raw_keys, str):
        items = [raw_keys]
    elif isinstance(raw_keys, (list, tuple)):
        items = list(raw_keys)
    else:
        items = []

    keys: List[str] = []
    for raw_key in items:
        key = str(raw_key or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def selected_source_label(
    all_rows: Iterable[Dict[str, Any]],
    visible_rows: Iterable[Dict[str, Any]],
    selected_keys,
) -> str:
    total = len(list(all_rows))
    shown = len(list(visible_rows))
    selected = len(normalize_source_keys(selected_keys))
    if total <= 0:
        label = "No sources"
    elif selected <= 0:
        label = "No sources selected"
    else:
        label = f"{selected} of {total} selected"
    if total > 0 and shown != total:
        label = f"{label} · {shown} shown"
    return label


def select_single_source(key: str, valid_keys: Iterable[str]) -> List[str]:
    normalized = str(key or "")
    valid = list(valid_keys)
    return [normalized] if normalized and normalized in valid else []


def toggle_source_selection(
    selected_keys,
    key: str,
    valid_keys: Iterable[str],
) -> List[str]:
    valid = list(valid_keys)
    normalized_key = str(key or "").strip()
    if not normalized_key or normalized_key not in valid:
        return [item for item in normalize_source_keys(selected_keys) if item in valid]
    selected = {
        item for item in normalize_source_keys(selected_keys) if item in valid
    }
    if normalized_key in selected:
        selected.remove(normalized_key)
    else:
        selected.add(normalized_key)
    return [item for item in valid if item in selected]


def select_visible_sources(
    selected_keys,
    visible_keys: Iterable[str],
    valid_keys: Iterable[str],
) -> List[str]:
    valid = list(valid_keys)
    selected = {
        item for item in normalize_source_keys(selected_keys) if item in valid
    }
    selected.update(item for item in visible_keys if item in valid)
    return [item for item in valid if item in selected]


def source_filter_from_row(row: Dict[str, Any]) -> Dict[str, str]:
    filt: Dict[str, str] = {}
    variable_id = str(row.get("variable_id", "") or "")
    if variable_id:
        filt["variable_id"] = variable_id

    source_collection_id = str(row.get("source_collection_id", "") or "")
    if source_collection_id:
        filt["source_collection_id"] = source_collection_id
        return filt

    schema_file_group = str(row.get("schema_file_group", "") or "")
    schema_mode = str(row.get("schema_mode", "") or "")
    if schema_file_group and schema_mode == "file_per_timestep":
        filt["schema_file_group"] = schema_file_group
        filt["schema_mode"] = schema_mode
        return filt

    source_dataset = str(row.get("source_dataset", "") or "")
    if source_dataset:
        filt["source_dataset"] = source_dataset
        return filt

    producer = str(row.get("producer", "") or "")
    casename = str(row.get("casename", "") or "")
    file_name = str(row.get("file", "") or "")
    if producer or casename or file_name:
        filt["producer"] = producer
        filt["casename"] = casename
    if file_name:
        filt["file"] = file_name
    return filt


def source_fields_from_row(row: Dict[str, Any]) -> Dict[str, str]:
    if not row:
        return {}
    source_id = str(
        row.get("source_id", "")
        or row.get("id", "")
        or row.get("_key", "")
        or ""
    )
    return {
        "source_id": source_id,
        "_source_key": source_id,
        "source_dataset": str(row.get("source_dataset", "") or ""),
        "source_collection_id": str(
            row.get("source_collection_id", "") or ""
        ),
        "schema_file_group": str(row.get("schema_file_group", "") or ""),
        "schema_mode": str(row.get("schema_mode", "") or ""),
        "producer": str(row.get("producer", "") or ""),
        "casename": str(row.get("casename", "") or ""),
        "file": str(row.get("file", "") or ""),
    }


def source_key_for_fields(row: Dict[str, Any]) -> str:
    source_collection_id = str(row.get("source_collection_id", "") or "")
    if source_collection_id:
        return f"collection|{row.get('variable_id', '')}|{source_collection_id}"
    schema_file_group = str(row.get("schema_file_group", "") or "")
    schema_mode = str(row.get("schema_mode", "") or "")
    if schema_file_group and schema_mode == "file_per_timestep":
        return f"schema|{row.get('variable_id', '')}|{schema_file_group}"
    return (
        "|".join(
            str(row.get(key, "") or "")
            for key in ("variable_id", "source_dataset", "producer", "casename", "file")
        ).strip("|")
        or str(row.get("source_dataset", "") or "")
        or f"{row.get('producer', '')}|{row.get('casename', '')}|{row.get('file', '')}"
    )
