"""Pure grid track sizing and CSS template calculations."""

from typing import Any, List

from .grid import clamp_int
from .plot import finite_float


GRID_MIN_ROWS = 1
GRID_MIN_COLS = 1
GRID_MAX_ROWS = 8
GRID_MAX_COLS = 8
GRID_HEADER_HEIGHT = 32
GRID_MIN_TRACK_WEIGHT = 0.05
GRID_MAX_TRACK_WEIGHT = 100.0


def size_values(raw_sizes) -> List[Any]:
    if isinstance(raw_sizes, str):
        return [part.strip() for part in raw_sizes.replace(";", ",").split(",")]
    if isinstance(raw_sizes, (list, tuple)):
        return list(raw_sizes)
    return []


def normalize_size_list(
    raw_sizes,
    count: int,
    default: int,
    minimum: int,
    maximum: int,
) -> List[int]:
    values = size_values(raw_sizes)
    return [
        clamp_int(
            values[index] if index < len(values) else default, default, minimum, maximum
        )
        for index in range(count)
    ]


def normalize_weight_list(
    raw_weights,
    count: int,
    default: float = 1.0,
) -> List[float]:
    values = size_values(raw_weights)
    weights = []
    for index in range(count):
        raw = values[index] if index < len(values) else default
        value = finite_float(raw)
        if value is None or value <= 0:
            value = default
        value = max(GRID_MIN_TRACK_WEIGHT, min(GRID_MAX_TRACK_WEIGHT, float(value)))
        weights.append(round(value, 6))
    return weights


def grid_template_from_sizes(sizes: List[int]) -> str:
    return " ".join(f"{int(size)}px" for size in sizes)


def grid_fit_template_from_weights(weights: List[float], min_size: int) -> str:
    safe_min = max(1, int(min_size))
    return " ".join(
        f"minmax({safe_min}px, {float(weight):.6g}fr)" for weight in weights
    )
