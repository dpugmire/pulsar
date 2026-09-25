"""Divertor target-total time-series plugin for XGC heatdiag data."""

from __future__ import annotations

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


PLUGIN_ID = "divertor_target_totals_timeseries"
LABEL = "Divertor target totals time series"
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
    """Return GUI controls for the divertor target-total analysis."""
    return [
        {"key": "data_dir", "type": "text", "label": "XGC data dir", "default": ""},
        {"key": "frame_index", "type": "number", "label": "Frame index", "default": ""},
        {"key": "step_range", "type": "text", "label": "Step range", "default": ""},
        {"key": "time_range_ms", "type": "text", "label": "Time range [ms]", "default": ""},
        {"key": "psi_window", "type": "text", "label": "psi_N", "default": "0.97,1.12"},
        {"key": "xlim", "type": "text", "label": "X limits [ms]", "default": ""},
        {"key": "particle_ylim", "type": "text", "label": "Particle flux [ptl/s]", "default": ""},
        {"key": "power_ylim_mw", "type": "text", "label": "Power [MW]", "default": ""},
        {"key": "show_particle", "type": "bool", "label": "Particle flux", "default": True},
        {"key": "show_power", "type": "bool", "label": "Power", "default": True},
        {"key": "show_outer", "type": "bool", "label": "Outer target", "default": True},
        {"key": "show_inner", "type": "bool", "label": "Inner target", "default": True},
        {"key": "show_total", "type": "bool", "label": "Total divertor", "default": True},
        {"key": "show_control", "type": "bool", "label": "Wall control", "default": True},
        {"key": "show_ions", "type": "bool", "label": "Ions", "default": True},
        {"key": "show_electrons", "type": "bool", "label": "Electrons", "default": True},
        {"key": "show_target_total", "type": "bool", "label": "Target total", "default": True},
        {"key": "include_sheath", "type": "bool", "label": "Sheath energy", "default": False},
    ]


def render(ctx):
    """Compute and render divertor target particle/power totals over time."""
    options = dict(ctx.get("options", {}) or {})
    show_particle = _as_bool(options, "show_particle", True)
    show_power = _as_bool(options, "show_power", True)
    show_outer = _as_bool(options, "show_outer", True)
    show_inner = _as_bool(options, "show_inner", True)
    show_total = _as_bool(options, "show_total", True)
    show_control = _as_bool(options, "show_control", True)

    if not show_particle and not show_power:
        raise ValueError("At least one of Particle flux or Power must be enabled")
    if not show_outer and not show_inner and not show_total and not show_control:
        raise ValueError("At least one target or control trace must be enabled")

    data_dir = _resolve_data_dir(ctx, options)
    compute_timeseries, plot_timeseries = _import_divertor_helpers(data_dir)
    step_range = _to_range_pair(options.get("step_range"))
    time_range_ms = _to_range_pair(options.get("time_range_ms"))
    frame_index = _to_optional_int(options.get("frame_index"))
    points = compute_timeseries(
        data_dir,
        include_sheath=_as_bool(options, "include_sheath", False),
        step_range=step_range,
        time_window=_milliseconds_to_seconds(time_range_ms),
        selected_frame_index=frame_index,
        psi_window=_to_range_pair(options.get("psi_window")) or (0.97, 1.12),
        show_outer=show_outer,
        show_inner=show_inner,
        show_total=show_total,
        show_wall=show_control,
    )
    fig = plot_timeseries(
        points,
        show_particle=show_particle,
        show_power=show_power,
        show_outer=show_outer,
        show_inner=show_inner,
        show_total=show_total,
        show_control=show_control,
        show_ions=_as_bool(options, "show_ions", True),
        show_electrons=_as_bool(options, "show_electrons", True),
        show_target_total=_as_bool(options, "show_target_total", True),
        xlim_ms=_to_range_pair(options.get("xlim")),
        particle_ylim=_to_range_pair(options.get("particle_ylim")),
        power_ylim_mw=_to_range_pair(options.get("power_ylim_mw")),
    )

    try:
        src = _figure_data_url(fig)
    finally:
        plt.close(fig)

    return {
        "media_type": "image",
        "display_title": "Divertor target totals time series",
        "src": src,
        "status": "ok",
        "note": f"plugin: {PLUGIN_ID}; {data_dir}; {_selection_note(step_range, time_range_ms, frame_index)}",
    }


def _import_divertor_helpers(data_dir: Path):
    """Import the XGC-Analysis target-total compute and plot helpers."""
    try:
        from xgc_analysis.divertor_eich import (
            compute_divertor_target_totals_timeseries,
            plot_divertor_target_totals_timeseries,
        )

        return compute_divertor_target_totals_timeseries, plot_divertor_target_totals_timeseries
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
                    compute_divertor_target_totals_timeseries,
                    plot_divertor_target_totals_timeseries,
                )

                return compute_divertor_target_totals_timeseries, plot_divertor_target_totals_timeseries
            except Exception:
                continue

        raise RuntimeError(
            "Divertor target totals require a current XGC-Analysis checkout. "
            "Install it, set PYTHONPATH, or set XGC_ANALYSIS_PATH."
        ) from first_exc
