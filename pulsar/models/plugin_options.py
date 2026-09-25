"""Pure conversion between plugin schemas and editable option rows."""

from typing import Any, Dict, List


def plugin_option_rows(
    schema: List[Dict[str, Any]],
    values: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows = []
    for item in schema or []:
        spec = dict(item or {})
        key = str(spec.get("key", "") or "").strip()
        if not key:
            continue
        option_type = str(spec.get("type", "text") or "text")
        value = values.get(
            key, spec.get("default", False if option_type == "bool" else "")
        )
        value = bool(value) if option_type == "bool" else str(value or "")
        rows.append(
            {
                "key": key,
                "label": str(spec.get("label", "") or key),
                "type": option_type,
                "value": value,
                "choices": list(spec.get("choices", []) or []),
            }
        )
    return rows


def plugin_options_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    options = {}
    for raw_row in rows or []:
        row = dict(raw_row or {})
        key = str(row.get("key", "") or "").strip()
        if not key:
            continue
        options[key] = (
            bool(row.get("value", False))
            if str(row.get("type", "") or "") == "bool"
            else str(row.get("value", "") or "").strip()
        )
    return options
