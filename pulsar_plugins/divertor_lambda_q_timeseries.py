"""Divertor Eich-width time-series plugin for XGC heatdiag data."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

import matplotlib.pyplot as plt

from .divertor_eich_profile import (
    _as_bool,
    _figure_data_url,
    _looks_like_heatdiag_source,
    _resolve_data_dir,
    _to_float,
    _to_optional_int,
    _to_range_pair,
    _variable_basename,
)


PLUGIN_ID = "divertor_lambda_q_timeseries"
LABEL = "Divertor lambda_q time series"
PLUGIN_SCOPE = "source"


_HEATDIAG_VARIABLES = {
    "e_number",
    "i_number",
    "e_para_energy",
    "e_perp_energy",
    "e_potential",
    "i_para_energy",
    "i_perp_energy",
    "i_potential",
    "time",
    "step",
    "gstep",
    "tindex",
    "r",
    "z",
    "psi",
    "ds",
    "strike_angle",
}


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
    """Return GUI controls for the lambda_q time-series analysis."""
    return [
        {"key": "data_dir", "type": "text", "label": "XGC data dir", "default": ""},
        {"key": "frame_index", "type": "number", "label": "Frame index", "default": ""},
        {"key": "step_range", "type": "text", "label": "Step range", "default": ""},
        {"key": "time_range_ms", "type": "text", "label": "Time range [ms]", "default": ""},
        {"key": "psi_window", "type": "text", "label": "psi_N", "default": "0.97,1.12"},
        {"key": "fit_window_mm", "type": "text", "label": "Fit window [mm]", "default": "-2,20"},
        {"key": "smoothing_sigma_mm", "type": "number", "label": "Smooth sigma [mm]", "default": "0"},
        {"key": "ylim", "type": "text", "label": "lambda_q [mm]", "default": ""},
        {"key": "show_outer", "type": "bool", "label": "Outer target", "default": True},
        {"key": "show_inner", "type": "bool", "label": "Inner target", "default": True},
        {"key": "show_lines", "type": "bool", "label": "Lines", "default": True},
        {"key": "show_symbols", "type": "bool", "label": "Symbols", "default": False},
    ]


def render(ctx):
    """Compute and render divertor lambda_q versus heatdiag time."""
    options = dict(ctx.get("options", {}) or {})
    show_outer = _as_bool(options, "show_outer", True)
    show_inner = _as_bool(options, "show_inner", True)
    show_lines = _as_bool(options, "show_lines", True)
    show_symbols = _as_bool(options, "show_symbols", False)

    if not show_outer and not show_inner:
        raise ValueError("At least one target must be enabled")
    if not show_lines and not show_symbols:
        raise ValueError("At least one of Lines or Symbols must be enabled")

    data_dir = _resolve_data_dir(ctx, options)
    compute_timeseries, plot_timeseries = _import_divertor_helpers(data_dir)
    step_range = _to_range_pair(options.get("step_range"))
    time_range_ms = _to_range_pair(options.get("time_range_ms"))
    frame_index = _to_optional_int(options.get("frame_index"))
    points = compute_timeseries(
        data_dir,
        include_sheath=False,
        step_range=step_range,
        time_window=_milliseconds_to_seconds(time_range_ms),
        selected_frame_index=frame_index,
        psi_window=_to_range_pair(options.get("psi_window")) or (0.97, 1.12),
        fit_window_mm=_to_range_pair(options.get("fit_window_mm")) or (-2.0, 20.0),
        smoothing_sigma_mm=max(0.0, _to_float(options.get("smoothing_sigma_mm"), 0.0)),
        show_outer=show_outer,
        show_inner=show_inner,
    )
    fig = plot_timeseries(
        points,
        ylim=_to_range_pair(options.get("ylim")),
        show_lines=show_lines,
        show_symbols=show_symbols,
    )

    try:
        src = _figure_data_url(fig)
    finally:
        plt.close(fig)

    return {
        "media_type": "image",
        "display_title": "Divertor lambda_q time series",
        "src": src,
        "status": "ok",
        "note": f"plugin: {PLUGIN_ID}; {data_dir}; {_selection_note(step_range, time_range_ms, frame_index)}",
    }


def _milliseconds_to_seconds(value):
    """Convert an optional millisecond range to seconds."""
    if value is None:
        return None
    return value[0]*1.0e-3, value[1]*1.0e-3


def _selection_note(step_range, time_range_ms, frame_index):
    """Return a compact description of the selected heatdiag intervals."""
    if step_range is not None:
        return f"steps={step_range[0]:g},{step_range[1]:g}"
    if time_range_ms is not None:
        return f"time={time_range_ms[0]:g},{time_range_ms[1]:g}ms"
    if frame_index is not None:
        return f"frame={frame_index}"
    return "all intervals"


def _clear_xgc_analysis_modules() -> None:
    """Remove cached XGC-Analysis modules before trying another checkout."""
    for name in list(sys.modules):
        if name == "xgc_analysis" or name.startswith("xgc_analysis."):
            sys.modules.pop(name, None)


def _import_divertor_helpers(data_dir: Path):
    """Import the XGC-Analysis lambda_q compute and plot helpers."""
    try:
        from xgc_analysis.divertor_eich import (
            compute_divertor_lambda_q_timeseries,
            plot_divertor_lambda_q_timeseries,
        )

        return compute_divertor_lambda_q_timeseries, plot_divertor_lambda_q_timeseries
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
                from xgc_analysis.divertor_eich import (
                    compute_divertor_lambda_q_timeseries,
                    plot_divertor_lambda_q_timeseries,
                )

                return compute_divertor_lambda_q_timeseries, plot_divertor_lambda_q_timeseries
            except Exception:
                continue

        raise RuntimeError(
            "Divertor lambda_q time series requires a current XGC-Analysis checkout. "
            "Install it, set PYTHONPATH, or set XGC_ANALYSIS_PATH."
        ) from first_exc
