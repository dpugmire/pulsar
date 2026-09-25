"""Pure geometry helpers for the freeform, grid-snapped canvas."""

from __future__ import annotations

from copy import deepcopy
from math import floor, isfinite
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


CANVAS_COLUMNS = 24
CANVAS_COLUMN_CHOICES = (12, 24, 36, 48)
CANVAS_ROW_HEIGHT = 24
CANVAS_ZOOM_DEFAULT = 1.0
CANVAS_ZOOM_MIN = 0.25
CANVAS_ZOOM_MAX = 2.0
CANVAS_ZOOM_STEP = 0.25
CANVAS_DEFAULT_DROP_WIDTH = 2
CANVAS_MIN_DROP_WIDTH = 2
CANVAS_MAX_DROP_WIDTH = 12
CANVAS_DWELL_MS = 260
CANVAS_SNAP_DEAD_ZONE = 0.55
CANVAS_TRANSITION_MS = 120
CANVAS_MAX_TILES = 256

CANVAS_TILE_MINIMUMS: Dict[str, Tuple[int, int]] = {
    "field": (2, 3),
    "plot": (2, 3),
    "kpi": (4, 3),
    "stats": (5, 4),
}
CANVAS_DEFAULT_MINIMUM = (2, 3)
CANVAS_TILE_DEFAULTS: Dict[str, Tuple[int, int]] = {
    "field": (8, 9),
    "plot": (8, 6),
    "kpi": (6, 4),
    "stats": (8, 5),
}
CANVAS_DEFAULT_SIZE = (8, 6)


Geometry = Dict[str, Any]


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if isfinite(number) else float(default)


def normalize_columns(value: Any, default: int = CANVAS_COLUMNS) -> int:
    """Return one of the supported canvas column counts."""

    try:
        columns = int(value)
    except (TypeError, ValueError):
        columns = int(default)
    return columns if columns in CANVAS_COLUMN_CHOICES else CANVAS_COLUMNS


def normalize_zoom(value: Any) -> float:
    """Return a finite canvas zoom within the supported manual range."""

    zoom = _finite_number(value, CANVAS_ZOOM_DEFAULT)
    return round(max(CANVAS_ZOOM_MIN, min(CANVAS_ZOOM_MAX, zoom)), 4)


def normalize_drop_width(value: Any) -> int:
    """Return a valid workspace-wide width for newly dropped plots."""

    try:
        width = int(round(float(value)))
    except (TypeError, ValueError):
        width = CANVAS_DEFAULT_DROP_WIDTH
    return max(CANVAS_MIN_DROP_WIDTH, min(CANVAS_MAX_DROP_WIDTH, width))


def tile_type(value: Any) -> str:
    candidate = str(value or "plot").strip().lower()
    return candidate if candidate in CANVAS_TILE_MINIMUMS else "plot"


def tile_type_for_cell(cell: Mapping[str, Any]) -> str:
    explicit = str(cell.get("tile_type", "") or "").strip().lower()
    if explicit in CANVAS_TILE_MINIMUMS:
        return explicit
    if (
        str(cell.get("variable_type", "") or "") == "scalarField"
        or str(cell.get("payload_type", "") or "") == "SCALAR_FIELD"
        or str(cell.get("visualization_item_type", "") or "") == "SCALAR_FIELD"
    ):
        return "field"
    return "plot"


def minimum_size(kind: Any) -> Tuple[int, int]:
    return CANVAS_TILE_MINIMUMS.get(tile_type(kind), CANVAS_DEFAULT_MINIMUM)


def default_size(kind: Any) -> Tuple[int, int]:
    return CANVAS_TILE_DEFAULTS.get(tile_type(kind), CANVAS_DEFAULT_SIZE)


def geometry(
    tile_id: str,
    kind: Any,
    x: Any,
    y: Any,
    w: Any,
    h: Any,
    *,
    snap: bool = True,
    columns: int = CANVAS_COLUMNS,
) -> Geometry:
    """Return clamped geometry in integer or fractional grid units."""

    normalized_kind = tile_type(kind)
    min_w, min_h = minimum_size(normalized_kind)
    if snap:
        width = max(min_w, int(round(_finite_number(w, min_w))))
        height = max(min_h, int(round(_finite_number(h, min_h))))
        left = int(round(_finite_number(x, 0)))
        top = int(round(_finite_number(y, 0)))
    else:
        width = max(float(min_w), round(_finite_number(w, min_w), 4))
        height = max(float(min_h), round(_finite_number(h, min_h), 4))
        left = round(_finite_number(x, 0), 4)
        top = round(_finite_number(y, 0), 4)

    width = min(width, columns)
    left = max(0, min(left, columns - width))
    top = max(0, top)
    return {
        "tile_id": str(tile_id or ""),
        "tile_type": normalized_kind,
        "x": left,
        "y": top,
        "w": width,
        "h": height,
    }


def geometry_from_cell(
    cell: Mapping[str, Any],
    *,
    fallback_id: str,
    fallback_index: int = 0,
    snap: bool = True,
    columns: int = CANVAS_COLUMNS,
) -> Geometry:
    kind = tile_type_for_cell(cell)
    default_w, default_h = default_size(kind)
    default_x = (fallback_index * default_w) % max(default_w, columns)
    default_y = (fallback_index * default_w // columns) * default_h
    return geometry(
        str(cell.get("tile_id", "") or fallback_id),
        kind,
        cell.get("canvas_x", default_x),
        cell.get("canvas_y", default_y),
        cell.get("canvas_w", default_w),
        cell.get("canvas_h", default_h),
        snap=snap,
        columns=columns,
    )


def geometry_to_cell(cell: Mapping[str, Any], item: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(cell or {})
    result.update(
        {
            "tile_id": str(item.get("tile_id", "") or ""),
            "tile_type": tile_type(item.get("tile_type", "plot")),
            "canvas_x": item.get("x", 0),
            "canvas_y": item.get("y", 0),
            "canvas_w": item.get("w", CANVAS_DEFAULT_SIZE[0]),
            "canvas_h": item.get("h", CANVAS_DEFAULT_SIZE[1]),
        }
    )
    return result


def overlaps(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    return bool(
        first["x"] < second["x"] + second["w"]
        and first["x"] + first["w"] > second["x"]
        and first["y"] < second["y"] + second["h"]
        and first["y"] + first["h"] > second["y"]
    )


def vertically_overlaps(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    return bool(
        first["y"] < second["y"] + second["h"]
        and first["y"] + first["h"] > second["y"]
    )


def validate_layout(
    items: Sequence[Mapping[str, Any]],
    *,
    columns: int = CANVAS_COLUMNS,
) -> Tuple[bool, str]:
    seen: set[str] = set()
    for index, item in enumerate(items):
        tile_id = str(item.get("tile_id", "") or "")
        if not tile_id:
            return False, f"Tile {index + 1} has no stable id"
        if tile_id in seen:
            return False, f"Duplicate tile id: {tile_id}"
        seen.add(tile_id)
        kind = tile_type(item.get("tile_type", "plot"))
        min_w, min_h = minimum_size(kind)
        values = {
            name: _finite_number(item.get(name), -1)
            for name in ("x", "y", "w", "h")
        }
        if values["x"] < 0 or values["y"] < 0:
            return False, f"Tile {tile_id} is outside the canvas"
        if values["w"] < min_w or values["h"] < min_h:
            return False, f"Tile {tile_id} is smaller than its minimum"
        if values["x"] + values["w"] > columns + 1e-9:
            return False, f"Tile {tile_id} exceeds the canvas width"

    for index, first in enumerate(items):
        for second in items[index + 1 :]:
            if overlaps(first, second):
                return False, (
                    f"Tiles {first.get('tile_id')} and {second.get('tile_id')} overlap"
                )
    return True, ""


def sticky_snap(continuous: float, current: Optional[float]) -> int:
    if current is None:
        return int(round(continuous))
    if abs(float(continuous) - float(current)) < CANVAS_SNAP_DEAD_ZONE:
        return int(round(current))
    return int(round(continuous))


def insertion_zone(
    items: Sequence[Mapping[str, Any]],
    dragged_id: str,
    pointer_x: float,
    pointer_y: float,
    *,
    x_tolerance: float = 0.0,
    y_tolerance: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """Return the row or column insertion seam nearest the pointer.

    Shared seams are checked first so the gutter between adjacent tiles remains
    an unambiguous insertion target. The tolerance values are grid units; the
    browser derives them from a fixed pixel hit band.
    """

    epsilon = 1e-9
    pointer_x = _finite_number(pointer_x)
    pointer_y = _finite_number(pointer_y)
    x_tolerance = max(0.0, _finite_number(x_tolerance))
    y_tolerance = max(0.0, _finite_number(y_tolerance))
    others = [
        item
        for item in items
        if str(item.get("tile_id", "")) != str(dragged_id)
    ]
    shared: List[Tuple[float, int, Dict[str, Any]]] = []

    for left in others:
        seam = _finite_number(left.get("x")) + _finite_number(left.get("w"))
        for right in others:
            if left is right or abs(seam - _finite_number(right.get("x"))) > epsilon:
                continue
            overlap_start = max(
                _finite_number(left.get("y")),
                _finite_number(right.get("y")),
            )
            overlap_end = min(
                _finite_number(left.get("y")) + _finite_number(left.get("h")),
                _finite_number(right.get("y")) + _finite_number(right.get("h")),
            )
            distance = abs(pointer_x - seam)
            if (
                overlap_end - overlap_start > epsilon
                and distance <= x_tolerance + epsilon
                and overlap_start - epsilon <= pointer_y <= overlap_end + epsilon
            ):
                normalized_distance = distance / max(x_tolerance, epsilon)
                shared.append(
                    (
                        normalized_distance,
                        0,
                        {
                            "orientation": "column",
                            "seam": seam,
                            "anchor_x": _finite_number(right.get("x")),
                            "anchor_y": _finite_number(right.get("y")),
                            "edge": "shared",
                        },
                    )
                )

    for top in others:
        seam = _finite_number(top.get("y")) + _finite_number(top.get("h"))
        for bottom in others:
            if top is bottom or abs(seam - _finite_number(bottom.get("y"))) > epsilon:
                continue
            overlap_start = max(
                _finite_number(top.get("x")),
                _finite_number(bottom.get("x")),
            )
            overlap_end = min(
                _finite_number(top.get("x")) + _finite_number(top.get("w")),
                _finite_number(bottom.get("x")) + _finite_number(bottom.get("w")),
            )
            distance = abs(pointer_y - seam)
            if (
                overlap_end - overlap_start > epsilon
                and distance <= y_tolerance + epsilon
                and overlap_start - epsilon <= pointer_x <= overlap_end + epsilon
            ):
                normalized_distance = distance / max(y_tolerance, epsilon)
                shared.append(
                    (
                        normalized_distance,
                        1,
                        {
                            "orientation": "row",
                            "seam": seam,
                            "anchor_x": _finite_number(bottom.get("x")),
                            "anchor_y": _finite_number(bottom.get("y")),
                            "edge": "shared",
                        },
                    )
                )

    if shared:
        return min(shared, key=lambda candidate: candidate[:2])[2]

    def has_far_side_tile(
        orientation: str,
        seam: float,
        hovered: Mapping[str, Any],
    ) -> bool:
        if orientation == "row":
            return any(
                abs(_finite_number(item.get("y")) - seam) <= epsilon
                and _finite_number(item.get("x"))
                < _finite_number(hovered.get("x")) + _finite_number(hovered.get("w"))
                and _finite_number(item.get("x")) + _finite_number(item.get("w"))
                > _finite_number(hovered.get("x"))
                for item in others
            )
        return any(
            abs(_finite_number(item.get("x")) - seam) <= epsilon
            and _finite_number(item.get("y"))
            < _finite_number(hovered.get("y")) + _finite_number(hovered.get("h"))
            and _finite_number(item.get("y")) + _finite_number(item.get("h"))
            > _finite_number(hovered.get("y"))
            for item in others
        )

    for item in others:
        left = _finite_number(item.get("x"))
        top = _finite_number(item.get("y"))
        width = _finite_number(item.get("w"), 1)
        height = _finite_number(item.get("h"), 1)
        if not (
            left <= pointer_x < left + width
            and top <= pointer_y < top + height
        ):
            continue
        edges = (
            ((pointer_x - left) / width, "left"),
            ((left + width - pointer_x) / width, "right"),
            ((pointer_y - top) / height, "top"),
            ((top + height - pointer_y) / height, "bottom"),
        )
        edge = min(edges, key=lambda candidate: candidate[0])[1]
        if edge == "top":
            return {
                "orientation": "row",
                "seam": top,
                "anchor_x": left,
                "anchor_y": top,
                "edge": edge,
            }
        if edge == "bottom":
            seam = top + height
            if has_far_side_tile("row", seam, item):
                return {
                    "orientation": "row",
                    "seam": seam,
                    "anchor_x": left,
                    "anchor_y": top,
                    "edge": edge,
                }
            return None
        if edge == "left":
            return {
                "orientation": "column",
                "seam": left,
                "anchor_x": left,
                "anchor_y": top,
                "edge": edge,
            }
        seam = left + width
        if has_far_side_tile("column", seam, item):
            return {
                "orientation": "column",
                "seam": seam,
                "anchor_x": left,
                "anchor_y": top,
                "edge": edge,
            }
        return None
    return None


def fit_rectangle(
    anchor_x: int,
    anchor_y: int,
    desired_w: int,
    desired_h: int,
    others: Sequence[Mapping[str, Any]],
    *,
    columns: int = CANVAS_COLUMNS,
) -> Geometry:
    """Largest free integer rectangle anchored at the requested top-left."""

    best_w = 0
    best_h = 0
    best_area = -1
    running_width = float("inf")
    for height in range(1, max(0, int(desired_h)) + 1):
        row = int(anchor_y) + height - 1
        free_width = min(int(desired_w), columns - int(anchor_x))
        for other in others:
            if other["y"] <= row < other["y"] + other["h"]:
                if other["x"] <= anchor_x < other["x"] + other["w"]:
                    free_width = 0
                elif other["x"] > anchor_x:
                    free_width = min(free_width, int(other["x"] - anchor_x))
        running_width = min(running_width, max(0, free_width))
        area = height * running_width
        if running_width > 0 and (
            area > best_area or (area == best_area and height > best_h)
        ):
            best_w = int(running_width)
            best_h = height
            best_area = area
    return {"x": anchor_x, "y": anchor_y, "w": best_w, "h": best_h}


def nearest_free(
    target: Mapping[str, Any],
    others: Sequence[Mapping[str, Any]],
    *,
    columns: int = CANVAS_COLUMNS,
    radius_limit: int = 120,
) -> Geometry:
    base = deepcopy(dict(target))

    def fits(x: int, y: int) -> bool:
        candidate = {**base, "x": x, "y": y}
        return bool(
            x >= 0
            and y >= 0
            and x + candidate["w"] <= columns
            and not any(overlaps(candidate, other) for other in others)
        )

    start_x = int(round(_finite_number(base.get("x"), 0)))
    start_y = int(round(_finite_number(base.get("y"), 0)))
    if fits(start_x, start_y):
        return {**base, "x": start_x, "y": start_y}
    for radius in range(1, radius_limit + 1):
        for delta_y in range(-radius, radius + 1):
            for delta_x in range(-radius, radius + 1):
                if abs(delta_x) + abs(delta_y) != radius:
                    continue
                x = start_x + delta_x
                y = start_y + delta_y
                if fits(x, y):
                    return {**base, "x": x, "y": y}
    return base


def scale_layout_columns(
    items: Sequence[Mapping[str, Any]],
    old_columns: Any,
    new_columns: Any,
    *,
    snap: bool = True,
) -> List[Geometry]:
    """Scale horizontal geometry and resolve minimum-size rounding collisions.

    Candidate positions on the current row are preferred, ordered by distance
    from the proportionally scaled location. A tile moves down only when no
    horizontal position can accommodate it.
    """

    old_count = normalize_columns(old_columns)
    new_count = normalize_columns(new_columns)
    ratio = new_count / old_count
    scaled = [
        geometry(
            str(item.get("tile_id", "") or ""),
            item.get("tile_type", "plot"),
            _finite_number(item.get("x")) * ratio,
            item.get("y", 0),
            _finite_number(item.get("w")) * ratio,
            item.get("h", 0),
            snap=snap,
            columns=new_count,
        )
        for item in items
    ]
    if old_count == new_count:
        return scaled

    source_order = {
        str(item.get("tile_id", "")): index for index, item in enumerate(scaled)
    }
    placed: List[Geometry] = []
    for item in sorted(scaled, key=lambda value: (value["y"], value["x"])):
        target_x = item["x"]
        target_y = item["y"]
        y_candidates = sorted(
            {
                target_y,
                *(
                    other["y"] + other["h"]
                    for other in placed
                    if other["y"] + other["h"] >= target_y
                ),
            }
        )
        positioned = False
        for top in y_candidates:
            row_items = [
                other
                for other in placed
                if top < other["y"] + other["h"]
                and top + item["h"] > other["y"]
            ]
            x_candidates = {
                max(0, min(target_x, new_count - item["w"])),
                0,
                new_count - item["w"],
            }
            for other in row_items:
                x_candidates.add(other["x"] + other["w"])
                x_candidates.add(other["x"] - item["w"])
            for left in sorted(x_candidates, key=lambda value: abs(value - target_x)):
                candidate = {**item, "x": left, "y": top}
                if (
                    left >= 0
                    and left + item["w"] <= new_count
                    and not any(overlaps(candidate, other) for other in placed)
                ):
                    item.update({"x": left, "y": top})
                    positioned = True
                    break
            if positioned:
                break
        if not positioned:
            item = nearest_free(item, placed, columns=new_count)
        placed.append(item)

    return sorted(
        placed,
        key=lambda item: source_order[str(item.get("tile_id", ""))],
    )


def vertical_push(
    items: Sequence[Mapping[str, Any]],
    priority_id: str,
) -> List[Geometry]:
    """Push collisions downward while leaving the priority tile fixed."""

    copied = [deepcopy(dict(item)) for item in items]
    priority = next(
        (item for item in copied if str(item.get("tile_id", "")) == priority_id),
        None,
    )
    if priority is None:
        return copied
    rest = sorted(
        (item for item in copied if item is not priority),
        key=lambda item: (item["y"], item["x"]),
    )
    placed = [priority]
    for item in rest:
        guard = 0
        while guard < 1000:
            collisions = [other for other in placed if overlaps(item, other)]
            if not collisions:
                break
            item["y"] = max(other["y"] + other["h"] for other in collisions)
            guard += 1
        placed.append(item)
    order = {str(item.get("tile_id", "")): index for index, item in enumerate(items)}
    return sorted(copied, key=lambda item: order[str(item.get("tile_id", ""))])


def horizontal_resize_push(
    items: Sequence[Mapping[str, Any]],
    priority_id: str,
    *,
    original_right: float,
    columns: int = CANVAS_COLUMNS,
) -> List[Geometry]:
    """Push right-side resize collisions horizontally without leaving the canvas.

    Any gap is consumed before a neighbor moves. If the connected chain reaches
    the right boundary, the priority tile's growth is reduced by the overflow.
    """

    source = [deepcopy(dict(item)) for item in items]
    priority = next(
        (
            item
            for item in source
            if str(item.get("tile_id", "")) == str(priority_id)
        ),
        None,
    )
    if priority is None:
        return source
    min_w, _min_h = minimum_size(priority.get("tile_type", "plot"))
    original_width = max(min_w, float(original_right) - float(priority["x"]))
    target_width = max(original_width, float(priority["w"]))
    order = {
        str(item.get("tile_id", "")): index for index, item in enumerate(items)
    }

    def resolve(width: float) -> Tuple[List[Geometry], float]:
        result = [deepcopy(dict(item)) for item in source]
        resized = next(
            item
            for item in result
            if str(item.get("tile_id", "")) == str(priority_id)
        )
        resized["w"] = width
        placed = [resized]
        movable = sorted(
            (
                item
                for item in result
                if item is not resized and float(item["x"]) >= float(original_right)
            ),
            key=lambda item: (item["x"], item["y"]),
        )
        for item in movable:
            guard = 0
            while guard < len(movable) + 1:
                collisions = [
                    other
                    for other in placed
                    if vertically_overlaps(item, other) and overlaps(item, other)
                ]
                if not collisions:
                    break
                next_x = max(
                    float(item["x"]),
                    *(float(other["x"]) + float(other["w"]) for other in collisions),
                )
                if next_x <= float(item["x"]) + 1e-9:
                    break
                item["x"] = next_x
                guard += 1
            placed.append(item)
        overflow = max(
            0.0,
            max(
                (float(item["x"]) + float(item["w"]) - columns for item in movable),
                default=0.0,
            ),
        )
        return (
            sorted(
                result,
                key=lambda item: order[str(item.get("tile_id", ""))],
            ),
            overflow,
        )

    result: List[Geometry] = source
    for _attempt in range(4):
        result, overflow = resolve(target_width)
        if overflow <= 1e-9:
            return result
        adjusted_width = max(original_width, target_width - overflow)
        if adjusted_width >= target_width - 1e-9:
            break
        target_width = adjusted_width
    result, _overflow = resolve(original_width)
    return result


def connected_column_move_set(
    items: Sequence[Mapping[str, Any]],
    *,
    seam: int,
    anchor_y: int,
    dragged_height: int,
    excluded_id: str = "",
) -> List[str]:
    candidates = [
        item
        for item in items
        if str(item.get("tile_id", "")) != excluded_id and item["x"] >= seam
    ]
    move: List[Mapping[str, Any]] = [
        item
        for item in candidates
        if item["y"] < anchor_y + dragged_height
        and item["y"] + item["h"] > anchor_y
    ]
    moved_ids = {str(item.get("tile_id", "")) for item in move}
    changed = True
    while changed:
        changed = False
        for candidate in candidates:
            candidate_id = str(candidate.get("tile_id", ""))
            if candidate_id in moved_ids:
                continue
            if any(
                vertically_overlaps(candidate, member)
                and candidate["x"] >= member["x"]
                for member in move
            ):
                move.append(candidate)
                moved_ids.add(candidate_id)
                changed = True
    return [str(item.get("tile_id", "")) for item in move]


def column_insertion_size(
    dragged: Mapping[str, Any],
    move_items: Sequence[Mapping[str, Any]],
    seam: int,
    *,
    columns: int = CANVAS_COLUMNS,
) -> Optional[Geometry]:
    max_right = max(
        (item["x"] + item["w"] for item in move_items),
        default=seam,
    )
    max_shift = columns - max_right
    if max_shift >= dragged["w"]:
        return {"w": dragged["w"], "h": dragged["h"], "mode": "push"}
    if not move_items:
        return None
    remaining = columns - seam
    minimum_scale = max(
        minimum_size(item.get("tile_type", "plot"))[0] / item["w"]
        for item in move_items
    )
    width_cap = floor(remaining * (1 - minimum_scale))
    min_w, min_h = minimum_size(dragged.get("tile_type", "plot"))
    if width_cap < min_w:
        return None
    width = min(dragged["w"], width_cap)
    height = (
        max(min_h, int(round(dragged["h"] * width / dragged["w"])))
        if width < dragged["w"]
        else dragged["h"]
    )
    return {"w": width, "h": height, "mode": "shrink"}


def apply_column_insertion(
    items: Sequence[Mapping[str, Any]],
    *,
    dragged_id: str,
    seam: int,
    anchor_y: int,
    move_ids: Iterable[str],
    width: int,
    height: int,
    mode: str,
    columns: int = CANVAS_COLUMNS,
) -> List[Geometry]:
    result = [deepcopy(dict(item)) for item in items]
    dragged = next(
        item for item in result if str(item.get("tile_id", "")) == dragged_id
    )
    dragged.update({"x": seam, "y": anchor_y, "w": width, "h": height})
    selected = set(move_ids)
    if mode == "shrink":
        remaining = columns - seam
        scale = (remaining - width) / remaining

        def transform(value: float) -> float:
            return seam + width + (value - seam) * scale

        for item in result:
            if str(item.get("tile_id", "")) not in selected:
                continue
            new_x = int(round(transform(item["x"])))
            new_right = int(round(transform(item["x"] + item["w"])))
            min_w, _min_h = minimum_size(item.get("tile_type", "plot"))
            item["x"] = new_x
            item["w"] = max(min_w, new_right - new_x)
    else:
        for item in result:
            if str(item.get("tile_id", "")) in selected:
                item["x"] += width
    return vertical_push(result, dragged_id)


def max_bottom(items: Sequence[Mapping[str, Any]], minimum: int = 12) -> int:
    return max([minimum, *[int(item["y"] + item["h"]) for item in items]])
