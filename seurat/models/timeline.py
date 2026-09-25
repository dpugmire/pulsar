"""Pure timeline-driver selection rules."""

import math
from typing import Any, Dict, Iterable, List, Optional


def _finite_float(value: Any):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def selection_axis_descriptor(cell: Dict[str, Any]) -> Dict[str, Any]:
    axis = cell.get("selection_axis", {})
    if isinstance(axis, dict):
        return dict(axis)
    axis_name = str(axis or "").strip()
    axes = cell.get("axes", {})
    if axis_name and isinstance(axes, dict):
        descriptor = axes.get(axis_name, {})
        if isinstance(descriptor, dict):
            return dict(descriptor)
    return {}


def selection_axis_values(cell: Dict[str, Any]) -> List[float]:
    descriptor = selection_axis_descriptor(cell)
    raw_values = descriptor.get("values", [])
    if not isinstance(raw_values, list):
        return []
    values: List[float] = []
    for raw_value in raw_values:
        value = _finite_float(raw_value)
        if value is None:
            return []
        values.append(value)
    return values


def selection_axis_key(cell: Dict[str, Any]) -> str:
    descriptor = selection_axis_descriptor(cell)
    return str(descriptor.get("key", "") or descriptor.get("id", "") or "").strip()


def selection_axis_index_for_value(
    cell: Dict[str, Any],
    value: Any,
) -> Optional[int]:
    target = _finite_float(value)
    values = selection_axis_values(cell)
    if target is None or not values:
        return None
    for index, candidate in enumerate(values):
        tolerance = max(1e-12, 1e-9 * max(1.0, abs(target), abs(candidate)))
        if abs(candidate - target) <= tolerance:
            return index
    return None


def cell_has_timeline_samples(cell: Dict[str, Any]) -> bool:
    if selection_axis_values(cell):
        return True

    time_values = cell.get("time_values", [])
    if isinstance(time_values, list) and any(
        _finite_float(value) is not None for value in time_values
    ):
        return True

    plot = cell.get("plot", {})
    if not isinstance(plot, dict):
        return False
    x_label = str(plot.get("x_label", "") or "").strip().lower()
    if x_label not in {"time", "physical time"}:
        return False
    for item in plot.get("series", []) or []:
        if not isinstance(item, dict):
            continue
        x_values = item.get("x", [])
        if isinstance(x_values, list) and any(
            _finite_float(value) is not None for value in x_values
        ):
            return True
    return False


def toggle_timeline_driver(
    cells: List[Dict[str, Any]],
    current_index: int,
    target_index: int,
) -> int:
    if target_index < 0 or target_index >= len(cells):
        return current_index
    cell = cells[target_index] or {}
    has_variable = str(
        cell.get("variable_id", "") or cell.get("variable_name", "") or ""
    ).strip()
    if not has_variable or not cell_has_timeline_samples(cell):
        return current_index
    return -1 if current_index == target_index else target_index


def clear_timeline_driver(current_index: int, cleared_indices: Iterable[int]) -> int:
    return -1 if current_index in set(cleared_indices) else current_index
