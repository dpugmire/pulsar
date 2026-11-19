"""Time-series plugin for scalar and rank-1 ADIOS variables."""

from __future__ import annotations

import numpy as np


PLUGIN_ID = "profile_timeseries"
LABEL = "Scalar/profile time series"


def supports(meta):
    """Support scalar and rank-1 variables with more than one ADIOS step."""
    return int(meta.get("ndims", -1)) in (0, 1) and int(
        meta.get("steps_count", 1) or 1
    ) > 1


def options_schema(meta):
    """Return user-editable plotting options."""
    shape = list(meta.get("shape", []) or [])
    n_profile = int(shape[0]) if shape else 1
    schema = []
    if int(meta.get("ndims", -1)) == 1:
        schema.append(
            {
                "key": "profile_indices",
                "type": "text",
                "label": "Profile indices",
                "default": _default_indices(n_profile),
            }
        )
    schema.extend(
        [
            {
                "key": "x_axis",
                "type": "select",
                "label": "X axis",
                "choices": ["adios_step", "time", "step", "tindex"],
                "default": "time",
            },
            {
                "key": "normalize",
                "type": "bool",
                "label": "Normalize",
                "default": False,
            },
        ]
    )
    return schema


def render(ctx):
    """Return a Pulsar plot1d tile for selected profile indices over time."""
    helpers = ctx["helpers"]
    variable_path = str(ctx.get("variable_path", "") or "")
    variable_name = str(ctx.get("variable_name", "") or ctx.get("variable_id", "") or variable_path)
    steps_count = int(ctx.get("steps_count", 1) or 1)
    if steps_count <= 1:
        raise ValueError("Profile time series requires more than one ADIOS step")

    raw = np.asarray(helpers.read_variable(variable_path, step_selection=(0, steps_count)))
    if np.iscomplexobj(raw):
        raise ValueError("Complex-valued profile time series are not supported")

    data = np.asarray(raw, dtype=float)
    if data.ndim == 1:
        if data.size % steps_count != 0:
            raise ValueError(f"Cannot reshape {data.size} values into {steps_count} steps")
        data = data.reshape(steps_count, data.size // steps_count)
    elif data.shape[0] != steps_count:
        data = data.reshape(steps_count, -1)
    if data.ndim != 2:
        raise ValueError(f"Expected time x profile data, got shape {data.shape}")

    options = dict(ctx.get("options", {}) or {})
    indices = _parse_indices(options.get("profile_indices"), data.shape[1])
    x_axis_name = str(options.get("x_axis", "adios_step") or "adios_step")
    x_values, x_label = _x_axis(ctx, helpers, x_axis_name, steps_count)
    normalize = bool(options.get("normalize", False))
    is_scalar = int(ctx.get("ndims", -1)) == 0

    series = []
    for index in indices:
        y = np.asarray(data[:, index], dtype=float)
        label = variable_name if is_scalar else f"index {index}"
        if normalize:
            y = _normalize(y)
            label = f"{label} normalized"
        series.append(
            {
                "x": x_values,
                "y": y,
                "source_label": label,
                "source_key": "scalar" if is_scalar else f"profile_index:{index}",
            }
        )

    y_label = f"{variable_name} / initial" if normalize else variable_name
    plot = helpers.plot1d_payload(series, x_label=x_label, y_label=y_label)
    note = f"plugin: {PLUGIN_ID}"
    if x_axis_name != "adios_step" and _has_duplicate_or_nonmonotonic_x(x_values):
        note = f"{note}; {x_axis_name} axis has duplicate or non-monotonic values"

    return {
        "media_type": "plot1d",
        "display_title": (
            f"{variable_name} time series"
            if is_scalar
            else f"{variable_name} profile time series"
        ),
        "plot": plot,
        "status": "ok",
        "note": note,
    }


def _default_indices(n_profile):
    n_profile = max(1, int(n_profile or 1))
    candidates = [0, n_profile // 4, n_profile // 2, (3 * n_profile) // 4, n_profile - 1]
    out = []
    for value in candidates:
        value = max(0, min(int(value), n_profile - 1))
        if value not in out:
            out.append(value)
    return ",".join(str(value) for value in out)


def _parse_indices(raw, n_profile):
    text = str(raw or "").strip() or _default_indices(n_profile)
    indices = []
    for item in text.split(","):
        token = item.strip()
        if not token:
            continue
        try:
            index = int(token)
        except ValueError as exc:
            raise ValueError("Profile indices must be comma-separated integers") from exc
        if index < 0 or index >= n_profile:
            raise ValueError(f"Profile index {index} is outside [0, {n_profile - 1}]")
        if index not in indices:
            indices.append(index)
    if not indices:
        raise ValueError("At least one profile index is required")
    return indices


def _x_axis(ctx, helpers, x_axis_name, steps_count):
    axes = ctx.get("axes", {}) or {}
    plot_axis_name = str(ctx.get("plot_x_axis", "") or "")
    plot_axis = axes.get(plot_axis_name, {})
    if x_axis_name in {"time", "adios_step"}:
        timeline_values = ctx.get("time_values", [])
        if isinstance(timeline_values, (list, tuple, np.ndarray)):
            x = np.asarray(timeline_values, dtype=float).reshape(-1)
            if x.size == steps_count and np.all(np.isfinite(x)):
                label = (
                    str(plot_axis.get("label", "") or "Time")
                    if isinstance(plot_axis, dict)
                    else "Time"
                )
                return x, label

    if isinstance(plot_axis, dict):
        axis_kind = str(plot_axis.get("kind", "") or "").strip().lower()
        if axis_kind in {"time", "time_series", "physical_time"}:
            label = str(plot_axis.get("label", "") or "Time")
            for raw_values in (
                ctx.get("time_values", []),
                plot_axis.get("values", []),
            ):
                if isinstance(raw_values, (list, tuple, np.ndarray)):
                    x = np.asarray(raw_values, dtype=float).reshape(-1)
                    if x.size == steps_count and np.all(np.isfinite(x)):
                        return x, label

            variable_name = str(plot_axis.get("variable", "") or "").strip()
            if variable_name:
                try:
                    values = helpers.read_source_variable(
                        variable_name,
                        step_selection=(0, steps_count),
                    )
                    x = np.asarray(values, dtype=float).reshape(-1)
                    if x.size == steps_count and np.all(np.isfinite(x)):
                        return x, label
                except Exception:
                    pass

    if x_axis_name == "adios_step":
        return np.arange(steps_count, dtype=float), "adios_step"

    variable_name = x_axis_name
    label = x_axis_name
    if x_axis_name == "time":
        metadata = ctx.get("metadata", {}) or {}
        variable_name = str(
            metadata.get("time_axis_variable", "") or x_axis_name
        ).strip()
        label = "Time" if variable_name != x_axis_name else x_axis_name

    try:
        values = helpers.read_source_variable(
            variable_name,
            step_selection=(0, steps_count),
        )
    except Exception:
        return np.arange(steps_count, dtype=float), "adios_step"
    x = np.asarray(values, dtype=float).reshape(-1)
    if x.size != steps_count:
        return np.arange(steps_count, dtype=float), "adios_step"
    if not np.all(np.isfinite(x)):
        return np.arange(steps_count, dtype=float), "adios_step"
    return x, label


def _normalize(values):
    y = np.asarray(values, dtype=float)
    finite = y[np.isfinite(y)]
    if finite.size == 0:
        return y
    baseline = finite[0]
    if baseline == 0.0:
        scale = np.max(np.abs(finite))
        return y if scale == 0.0 else y / scale
    return y / baseline


def _has_duplicate_or_nonmonotonic_x(values):
    x = np.asarray(values, dtype=float).reshape(-1)
    if x.size <= 1:
        return False
    return np.unique(x).size != x.size or bool(np.any(np.diff(x) <= 0))
