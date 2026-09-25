"""Pure normalization helpers for generated one-dimensional plots."""

import math
import re
from typing import Any, Dict, List, Optional, Tuple


_DEFAULT_PALETTE = (
    "#1565c0",
    "#c62828",
    "#2e7d32",
    "#ef6c00",
    "#6a1b9a",
    "#00838f",
    "#ad1457",
    "#5d4037",
)


def plot_series_key(item: Dict[str, Any], index: int) -> str:
    key = str(item.get("source_key", "") or "").strip()
    if key:
        return key
    label = str(item.get("source_label", "") or "").strip()
    return label or f"series:{index}"


def plot_series_label(item: Dict[str, Any], index: int) -> str:
    label = str(item.get("source_label", "") or "").strip()
    if label:
        return label
    key = str(item.get("source_key", "") or "").strip()
    return key or f"Series {index + 1}"


def _number(value: Any) -> Optional[float]:
    try:
        number = float(str(value).strip())
    except Exception:
        return None
    return number if math.isfinite(number) else None


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6g}"


def _rgb_component(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("%"):
        number = _number(text[:-1])
        if number is None or number < 0 or number > 100:
            return None
        return f"{_format_number(number)}%"
    number = _number(text)
    if number is None or number < 0 or number > 255:
        return None
    return _format_number(number)


def _hsl_hue(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text.endswith("deg"):
        text = text[:-3].strip()
    number = _number(text)
    return None if number is None else _format_number(number)


def _hsl_percent(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("%"):
        number = _number(text[:-1])
    else:
        number = _number(text)
        if number is not None and 0 <= number <= 1:
            number *= 100
    if number is None or number < 0 or number > 100:
        return None
    return f"{_format_number(number)}%"


def _css_color_args(value: str) -> List[str]:
    if "/" in value:
        return []
    parts = (
        [part.strip() for part in value.split(",")] if "," in value else value.split()
    )
    return [part for part in parts if part]


def clean_plot_color(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        alpha = _number(value.get("a")) if "a" in value else None
        if alpha is not None and abs(alpha - 1.0) > 1e-9:
            return fallback
        if {"r", "g", "b"}.issubset(value):
            red = _rgb_component(value.get("r"))
            green = _rgb_component(value.get("g"))
            blue = _rgb_component(value.get("b"))
            return (
                f"rgb({red}, {green}, {blue})" if red and green and blue else fallback
            )
        if {"h", "s", "l"}.issubset(value):
            hue = _hsl_hue(value.get("h"))
            saturation = _hsl_percent(value.get("s"))
            lightness = _hsl_percent(value.get("l"))
            return (
                f"hsl({hue}, {saturation}, {lightness})"
                if hue and saturation and lightness
                else fallback
            )
        for field in ("hex", "css", "value"):
            if field in value:
                return clean_plot_color(value.get(field), fallback)
        return fallback

    color = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", color):
        return color

    rgb_match = re.fullmatch(r"rgb\((.*)\)", color, flags=re.IGNORECASE)
    if rgb_match:
        parts = _css_color_args(rgb_match.group(1))
        if len(parts) == 3:
            red, green, blue = (_rgb_component(part) for part in parts)
            if red and green and blue:
                return f"rgb({red}, {green}, {blue})"

    hsl_match = re.fullmatch(r"hsl\((.*)\)", color, flags=re.IGNORECASE)
    if hsl_match:
        parts = _css_color_args(hsl_match.group(1))
        if len(parts) == 3:
            hue = _hsl_hue(parts[0])
            saturation = _hsl_percent(parts[1])
            lightness = _hsl_percent(parts[2])
            if hue and saturation and lightness:
                return f"hsl({hue}, {saturation}, {lightness})"

    return fallback


def clean_line_style(value: Any, fallback: str = "solid") -> str:
    style = str(value or "").strip().lower().replace("_", "-")
    return style if style in {"solid", "dash", "dot", "dash-dot"} else fallback


def to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    return default


def finite_float(value: Any) -> Optional[float]:
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


def plot_series(tile: Dict[str, Any]) -> List[Dict[str, Any]]:
    plot = dict(tile.get("plot", {}) or {})
    return [
        dict(item or {})
        for item in (plot.get("series", []) or [])
        if isinstance(item, dict)
    ]


def assign_plot_series_keys(
    tile: Dict[str, Any], source_keys: List[str]
) -> Dict[str, Any]:
    plot = dict(tile.get("plot", {}) or {})
    series = []
    for index, raw_item in enumerate(plot.get("series", []) or []):
        item = dict(raw_item or {})
        if not str(item.get("source_key", "") or "").strip() and index < len(
            source_keys
        ):
            item["source_key"] = str(source_keys[index] or "")
        series.append(item)
    plot["series"] = series
    tile["plot"] = plot
    return tile


def normalize_plot_settings(
    tile: Dict[str, Any],
    raw_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = dict(raw_settings or {})
    raw_colors = raw.get("series_colors", {})
    raw_colors = raw_colors if isinstance(raw_colors, dict) else {}
    raw_styles = raw.get("series_styles", {})
    raw_styles = raw_styles if isinstance(raw_styles, dict) else {}

    series_colors: Dict[str, str] = {}
    series_styles: Dict[str, Dict[str, str]] = {}
    for index, item in enumerate(plot_series(tile)):
        key = plot_series_key(item, index)
        raw_style = raw_styles.get(key, {})
        raw_style = raw_style if isinstance(raw_style, dict) else {}
        fallback = (
            str(item.get("color", "") or "")
            or _DEFAULT_PALETTE[index % len(_DEFAULT_PALETTE)]
        )
        color = clean_plot_color(
            raw_style.get("color", raw_colors.get(key, "")), fallback
        )
        line_style = clean_line_style(raw_style.get("line_style", "solid"))
        series_colors[key] = color
        series_styles[key] = {"color": color, "line_style": line_style}

    def scale_value(key: str) -> str:
        value = str(raw.get(key, "linear") or "linear").strip().lower()
        return value if value in {"linear", "log"} else "linear"

    line_width = finite_float(raw.get("line_width", 2.5))
    line_width = 2.5 if line_width is None else max(0.5, min(8.0, line_width))

    return {
        "x_auto": to_bool(raw.get("x_auto", True), True),
        "x_min": finite_float(raw.get("x_min")),
        "x_max": finite_float(raw.get("x_max")),
        "x_scale": scale_value("x_scale"),
        "y_auto": to_bool(raw.get("y_auto", True), True),
        "y_min": finite_float(raw.get("y_min")),
        "y_max": finite_float(raw.get("y_max")),
        "y_scale": scale_value("y_scale"),
        "series_colors": series_colors,
        "series_styles": series_styles,
        "line_width": line_width,
        "show_grid": to_bool(raw.get("show_grid", True), True),
        "show_cursor": to_bool(raw.get("show_cursor", True), True),
        "background_color": clean_plot_color(
            raw.get("background_color", ""), "#ffffff"
        ),
        "grid_color": clean_plot_color(raw.get("grid_color", ""), "#e8e8e8"),
        "cursor_color": clean_plot_color(raw.get("cursor_color", ""), "#111111"),
    }


def existing_plot_settings(
    existing_cell: Dict[str, Any], variable_id: str
) -> Dict[str, Any]:
    if not isinstance(existing_cell, dict):
        return {}
    existing_var = str(
        existing_cell.get("variable_id", "")
        or existing_cell.get("variable_name", "")
        or ""
    )
    if (
        existing_var != str(variable_id or "")
        or existing_cell.get("media_type") != "plot1d"
    ):
        return {}
    settings = existing_cell.get("plot_settings", {})
    return dict(settings or {}) if isinstance(settings, dict) else {}


def plot_series_rows_for_tile(
    tile: Dict[str, Any],
    settings: Dict[str, Any],
) -> List[Dict[str, str]]:
    colors = settings.get("series_colors", {})
    colors = colors if isinstance(colors, dict) else {}
    styles = settings.get("series_styles", {})
    styles = styles if isinstance(styles, dict) else {}
    rows = []
    for index, item in enumerate(plot_series(tile)):
        key = plot_series_key(item, index)
        style = styles.get(key, {})
        style = style if isinstance(style, dict) else {}
        rows.append(
            {
                "key": key,
                "label": plot_series_label(item, index),
                "color": clean_plot_color(
                    style.get("color", colors.get(key, "")),
                    str(item.get("color", "") or "#1565c0"),
                ),
                "line_style": clean_line_style(style.get("line_style", "solid")),
            }
        )
    return rows


def axis_has_positive_data(tile: Dict[str, Any], axis: str) -> bool:
    field = "x" if axis == "x" else "y"
    return any(
        value is not None and value > 0
        for item in plot_series(tile)
        for value in (finite_float(raw) for raw in (item.get(field, []) or []))
    )


def settings_value_text(value: Any) -> str:
    number = finite_float(value)
    return "" if number is None else f"{number:.12g}"


def valid_extrema(fmin: Any, fmax: Any) -> Tuple[Optional[float], Optional[float]]:
    min_value = finite_float(fmin)
    max_value = finite_float(fmax)
    if min_value is None or max_value is None or min_value > max_value:
        return None, None
    return min_value, max_value
