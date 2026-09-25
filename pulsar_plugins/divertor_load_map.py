"""Mapped divertor-load plugin for XGC heatdiag data."""

from __future__ import annotations

import math
import os
from pathlib import Path
import sys

import matplotlib.pyplot as plt

from .divertor_eich_profile import (
    _as_bool,
    _figure_data_url,
    _looks_like_heatdiag_source,
    _resolve_data_dir,
    _to_optional_int,
    _to_range_pair,
    _variable_basename,
)
from .divertor_lambda_q_timeseries import (
    _HEATDIAG_VARIABLES,
    _clear_xgc_analysis_modules,
    _milliseconds_to_seconds,
    _selection_note,
)


PLUGIN_ID = "divertor_load_map"
LABEL = "Divertor load map"
PLUGIN_SCOPE = "source"


def supports(meta):
    """Support variables associated with xgc.heatdiag2.bp."""
    if not _looks_like_heatdiag_source(meta):
        return False

    name = _variable_basename(meta)
    if not name:
        return True
    return name in _HEATDIAG_VARIABLES or "heatdiag2" in name.lower()


def supports_context(meta):
    """Support source/run contexts associated with xgc.heatdiag2.bp."""
    return supports(meta)


def options_schema(meta):
    """Return GUI controls for the mapped divertor-load analysis."""
    return [
        {"key": "data_dir", "type": "text", "label": "XGC data dir", "default": ""},
        {"key": "frame_index", "type": "number", "label": "Frame index", "default": ""},
        {"key": "step_range", "type": "text", "label": "Step range", "default": ""},
        {"key": "time_range_ms", "type": "text", "label": "Time range [ms]", "default": ""},
        {"key": "psi_window", "type": "text", "label": "psi_N", "default": "0.97,1.12"},
        {"key": "delta_sep_range", "type": "text", "label": "Delta_sep [mm]", "default": ""},
        {"key": "toroidal_range", "type": "text", "label": "Toroidal angle [deg]", "default": ""},
        {"key": "clim", "type": "text", "label": "Color scale", "default": ""},
        {"key": "contour_count", "type": "number", "label": "Filled contours", "default": "256"},
        {"key": "view", "type": "select", "label": "View", "choices": ["time", "toroidal"], "default": "time"},
        {"key": "channel", "type": "select", "label": "Load", "choices": ["energy", "particle"], "default": "energy"},
        {"key": "target", "type": "select", "label": "Target", "choices": ["outer", "inner"], "default": "outer"},
        {
            "key": "component",
            "type": "select",
            "label": "Component",
            "choices": ["total", "ion", "electron"],
            "default": "total",
        },
        {"key": "include_sheath", "type": "bool", "label": "Sheath energy", "default": False},
    ]


def render(ctx):
    """Compute and render a mapped divertor load contour plot."""
    options = dict(ctx.get("options", {}) or {})
    view = _choice(options, "view", {"time", "toroidal"}, "time")
    channel = _choice(options, "channel", {"energy", "particle"}, "energy")
    target = _choice(options, "target", {"outer", "inner"}, "outer")
    component = _choice(options, "component", {"total", "ion", "electron"}, "total")

    data_dir = _resolve_data_dir(ctx, options)
    compute_map, plot_map = _import_divertor_helpers(data_dir)
    step_range = _to_range_pair(options.get("step_range"))
    time_range_ms = _to_range_pair(options.get("time_range_ms"))
    frame_index = _to_optional_int(options.get("frame_index"))
    load_map = compute_map(
        data_dir,
        include_sheath=_as_bool(options, "include_sheath", False),
        view=view,
        channel=channel,
        target=target,
        component=component,
        step_range=step_range,
        time_window=_milliseconds_to_seconds(time_range_ms),
        selected_frame_index=frame_index,
        psi_window=_to_range_pair(options.get("psi_window")) or (0.97, 1.12),
    )
    fig = plot_map(
        load_map,
        xlim=_to_range_pair(options.get("delta_sep_range")),
        ylim=(
            _to_range_pair(options.get("toroidal_range"))
            if view == "toroidal"
            else time_range_ms
        ),
        clim=_to_range_pair(options.get("clim")),
        contour_count=_to_int(options.get("contour_count"), 256),
        cmap="seismic",
    )

    try:
        src = _figure_data_url(fig)
    finally:
        plt.close(fig)

    return {
        "media_type": "image",
        "display_title": f"{target.title()} divertor {component} {channel} load",
        "src": src,
        "status": "ok",
        "note": (
            f"plugin: {PLUGIN_ID}; {data_dir}; view={view}; "
            f"{_selection_note(step_range, time_range_ms, frame_index)}"
        ),
    }


def _choice(options, key, choices, default):
    """Return one validated select-option value."""
    value = str(options.get(key, default) or default).strip().lower()
    if value not in choices:
        raise ValueError(f"Invalid {key}: {value!r}")
    return value


def _to_int(value, default):
    """Parse an integer option with a finite fallback."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return int(default)
    if not math.isfinite(numeric):
        return int(default)
    return int(numeric)


def _import_divertor_helpers(data_dir: Path):
    """Import the XGC-Analysis divertor-load compute and plot helpers."""
    try:
        from xgc_analysis.divertor_eich import compute_divertor_load_map, plot_divertor_load_map

        return compute_divertor_load_map, plot_divertor_load_map
    except Exception as first_exc:
        search_paths = []
        env_path = os.environ.get("XGC_ANALYSIS_PATH", "").strip()
        if env_path:
            search_paths.append(Path(env_path).expanduser())
        search_paths.append(Path.cwd().parent / "XGC-Analysis")
        search_paths.append(data_dir.parent / "XGC-Analysis")
        search_paths.append(data_dir.parent.parent / "XGC-Analysis")

        for candidate in search_paths:
            if not (candidate / "xgc_analysis").is_dir():
                continue
            candidate_text = str(candidate.resolve())
            if candidate_text not in sys.path:
                sys.path.insert(0, candidate_text)
            try:
                _clear_xgc_analysis_modules()
                from xgc_analysis.divertor_eich import compute_divertor_load_map, plot_divertor_load_map

                return compute_divertor_load_map, plot_divertor_load_map
            except Exception:
                continue

        raise RuntimeError(
            "Divertor load map requires a current XGC-Analysis checkout. "
            "Install it, set PYTHONPATH, or set XGC_ANALYSIS_PATH."
        ) from first_exc
