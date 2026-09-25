"""Divertor Eich-profile plugin for XGC heatdiag data."""

from __future__ import annotations

import base64
import io
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt


PLUGIN_ID = "divertor_eich_profile"
LABEL = "Divertor Eich profile"
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
    "tindex",
    "r",
    "z",
    "psi",
    "ds",
    "strike_angle",
}


def supports(meta):
    """Support low-rank variables associated with xgc.heatdiag2.bp."""
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
    """Return GUI controls for the Eich-profile analysis."""
    return [
        {"key": "data_dir", "type": "text", "label": "XGC data dir", "default": ""},
        {"key": "frame_index", "type": "number", "label": "Frame index", "default": ""},
        {"key": "time_window", "type": "text", "label": "Average time [s]", "default": ""},
        {"key": "psi_window", "type": "text", "label": "psi_N", "default": "0.97,1.12"},
        {"key": "fit_window_mm", "type": "text", "label": "Fit window [mm]", "default": "-2,20"},
        {"key": "smoothing_sigma_mm", "type": "number", "label": "Smooth sigma [mm]", "default": "0"},
        {"key": "xlim", "type": "text", "label": "X limits [mm]", "default": ""},
        {"key": "ylim", "type": "text", "label": "Y limits", "default": ""},
        {"key": "show_particle", "type": "bool", "label": "Particle", "default": True},
        {"key": "show_energy", "type": "bool", "label": "Energy", "default": True},
        {"key": "show_ions", "type": "bool", "label": "Ions", "default": True},
        {"key": "show_electrons", "type": "bool", "label": "Electrons", "default": True},
        {"key": "show_total", "type": "bool", "label": "Total", "default": True},
        {"key": "show_outer", "type": "bool", "label": "Outer target", "default": True},
        {"key": "show_inner", "type": "bool", "label": "Inner target", "default": True},
        {"key": "include_sheath", "type": "bool", "label": "Sheath energy", "default": False},
    ]


def render(ctx):
    """Compute and render divertor Eich profiles as an image tile."""
    options = dict(ctx.get("options", {}) or {})
    show_particle = _as_bool(options, "show_particle", True)
    show_energy = _as_bool(options, "show_energy", True)
    show_ions = _as_bool(options, "show_ions", True)
    show_electrons = _as_bool(options, "show_electrons", True)
    show_total = _as_bool(options, "show_total", True)
    show_outer = _as_bool(options, "show_outer", True)
    show_inner = _as_bool(options, "show_inner", True)

    if not show_particle and not show_energy:
        raise ValueError("At least one of Particle or Energy must be enabled")
    if not show_ions and not show_electrons and not show_total:
        raise ValueError("At least one of Ions, Electrons, or Total must be enabled")
    if not show_outer and not show_inner:
        raise ValueError("At least one target must be enabled")

    data_dir = _resolve_data_dir(ctx, options)
    compute_profiles, plot_profiles = _import_divertor_helpers(data_dir)
    profiles = compute_profiles(
        data_dir,
        include_sheath=_as_bool(options, "include_sheath", False),
        time_window=_to_range_pair(options.get("time_window")),
        selected_frame_index=_to_optional_int(options.get("frame_index")),
        psi_window=_to_range_pair(options.get("psi_window")) or (0.97, 1.12),
        fit_window_mm=_to_range_pair(options.get("fit_window_mm")) or (-2.0, 20.0),
        smoothing_sigma_mm=max(0.0, _to_float(options.get("smoothing_sigma_mm"), 0.0)),
        show_outer=show_outer,
        show_inner=show_inner,
    )
    fig = plot_profiles(
        profiles,
        show_particle=show_particle,
        show_energy=show_energy,
        show_ions=show_ions,
        show_electrons=show_electrons,
        show_total=show_total,
        xlim=_to_range_pair(options.get("xlim")),
        ylim=_to_range_pair(options.get("ylim")),
    )

    try:
        src = _figure_data_url(fig)
    finally:
        plt.close(fig)

    time_window = _to_range_pair(options.get("time_window"))
    frame_index = _to_optional_int(options.get("frame_index"))
    if time_window:
        time_note = f"time window={time_window[0]:g},{time_window[1]:g}s"
    elif frame_index is not None:
        time_note = f"frame={frame_index}"
    else:
        time_note = "time average=all intervals"
    return {
        "media_type": "image",
        "display_title": "Divertor Eich profile",
        "src": src,
        "status": "ok",
        "note": f"plugin: {PLUGIN_ID}; {data_dir}; {time_note}",
    }


def _looks_like_heatdiag_source(meta: dict[str, Any]) -> bool:
    source_fields = dict(meta.get("source_fields", {}) or {})
    values = [
        meta.get("variable_id", ""),
        meta.get("variable_name", ""),
        meta.get("variable_path", ""),
        meta.get("source_dataset", ""),
        source_fields.get("source_dataset", ""),
        source_fields.get("schema_file_group", ""),
        source_fields.get("file", ""),
    ]
    if any("heatdiag2" in str(value or "").lower() for value in values):
        return True

    source_names = _source_variable_names(meta)
    required = {"e_number", "i_number", "e_para_energy", "i_para_energy"}
    return len(required.intersection(source_names)) >= 2


def _source_variable_names(meta: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in meta.get("source_variables", []) or []:
        if not isinstance(item, dict):
            continue
        for key in ("variable_id", "variable_name", "variable_path"):
            name = _basename(str(item.get(key, "") or ""))
            if name:
                names.add(name)
    return names


def _variable_basename(meta: dict[str, Any]) -> str:
    for key in ("variable_name", "variable_id", "variable_path"):
        name = _basename(str(meta.get(key, "") or ""))
        if name:
            return name
    return ""


def _basename(value: str) -> str:
    return str(value or "").strip("/").rsplit("/", 1)[-1]


def _resolve_data_dir(ctx: dict[str, Any], options: dict[str, Any]) -> Path:
    explicit = str(options.get("data_dir", "") or "").strip()
    candidates = []
    if explicit:
        candidates.append(explicit)

    env_data_dir = os.environ.get("XGC_DATA_DIR", "").strip()
    if env_data_dir:
        candidates.append(env_data_dir)

    source_fields = dict(ctx.get("source_fields", {}) or {})
    candidates.extend(
        [
            source_fields.get("source_dataset", ""),
            source_fields.get("file", ""),
            ctx.get("source_dataset", ""),
            ctx.get("variable_path", ""),
        ]
    )

    campaign_parent = Path(str(ctx.get("campaign_path", "") or ".")).expanduser().resolve().parent
    for candidate in _candidate_paths(candidates, campaign_parent):
        run_dir = _as_run_dir(candidate)
        if run_dir is not None:
            return run_dir

    raise RuntimeError(
        "Could not resolve an XGC data directory containing xgc.heatdiag2.bp. "
        "Set the plugin 'XGC data dir' option or export XGC_DATA_DIR."
    )


def _candidate_paths(raw_values: Iterable[Any], campaign_parent: Path) -> Iterable[Path]:
    seen: set[str] = set()
    for raw in raw_values:
        text = str(raw or "").strip()
        if not text:
            continue
        for trimmed in _trim_to_bp_paths(text):
            paths = [Path(trimmed).expanduser()]
            if not paths[0].is_absolute():
                paths.append(campaign_parent / trimmed)
            for path in paths:
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    yield path


def _trim_to_bp_paths(text: str) -> Iterable[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    yield cleaned

    parts = cleaned.split("/")
    for idx, part in enumerate(parts):
        if part.endswith(".bp"):
            yield "/".join(parts[: idx + 1])


def _as_run_dir(path: Path) -> Path | None:
    expanded = path.expanduser()
    if expanded.is_dir() and (expanded / "xgc.heatdiag2.bp").exists():
        return expanded.resolve()
    if expanded.name == "xgc.heatdiag2.bp" and expanded.exists():
        return expanded.parent.resolve()
    if expanded.is_file() and expanded.parent.joinpath("xgc.heatdiag2.bp").exists():
        return expanded.parent.resolve()
    return None


def _import_divertor_helpers(data_dir: Path):
    try:
        from xgc_analysis.divertor_eich import compute_divertor_eich_profiles, plot_divertor_eich_profiles

        return compute_divertor_eich_profiles, plot_divertor_eich_profiles
    except Exception as first_exc:
        search_paths = []
        env_path = os.environ.get("XGC_ANALYSIS_PATH", "").strip()
        if env_path:
            search_paths.append(Path(env_path).expanduser())
        search_paths.append(Path.cwd().parent / "XGC-Analysis")
        search_paths.append(data_dir.parent / "XGC-Analysis")
        search_paths.append(data_dir.parent.parent / "XGC-Analysis")

        for candidate in search_paths:
            package_dir = candidate / "xgc_analysis"
            if not package_dir.is_dir():
                continue
            candidate_text = str(candidate.resolve())
            if candidate_text not in sys.path:
                sys.path.insert(0, candidate_text)
            try:
                from xgc_analysis.divertor_eich import compute_divertor_eich_profiles, plot_divertor_eich_profiles

                return compute_divertor_eich_profiles, plot_divertor_eich_profiles
            except Exception:
                continue

        raise RuntimeError(
            "Divertor Eich profile requires XGC-Analysis. Install it, set PYTHONPATH, "
            "or set XGC_ANALYSIS_PATH to the XGC-Analysis checkout."
        ) from first_exc


def _as_bool(options: dict[str, Any], key: str, default: bool) -> bool:
    value = options.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _to_range_pair(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        parts = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Expected a comma-separated range, got {value!r}")
    try:
        lo = float(parts[0])
        hi = float(parts[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric range: {value!r}") from exc
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _to_optional_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError as exc:
        raise ValueError(f"Invalid frame index: {value!r}") from exc


def _to_float(value: Any, default: float) -> float:
    text = str(value or "").strip()
    if not text:
        return float(default)
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid number: {value!r}") from exc


def _figure_data_url(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.04, dpi=150)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
