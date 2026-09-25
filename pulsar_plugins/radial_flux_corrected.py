"""Derived radial-flux plugin using matching grad_psi_sqr profiles."""

from __future__ import annotations

import numpy as np

from ._xgc_1d import (
    default_indices,
    grad_psi_sqr_name,
    has_duplicate_or_nonmonotonic_x,
    is_radial_flux_name,
    normalize,
    parse_indices,
    rank1_multistep,
    read_profile_stack,
    source_variable_names,
    variable_basename,
    x_axis,
)


PLUGIN_ID = "radial_flux_corrected"
LABEL = "Radial flux corrected"


def supports(meta):
    """Support XGC radial-flux profiles with a matching grad_psi_sqr profile."""
    if not rank1_multistep(meta):
        return False
    name = variable_basename(meta)
    grad_name = grad_psi_sqr_name(name)
    return bool(is_radial_flux_name(name) and grad_name in source_variable_names(meta))


def options_schema(meta):
    """Return user-editable plotting options."""
    shape = list(meta.get("shape", []) or [])
    n_profile = int(shape[0]) if shape else 1
    return [
        {
            "key": "profile_indices",
            "type": "text",
            "label": "Profile indices",
            "default": default_indices(n_profile),
        },
        {
            "key": "x_axis",
            "type": "select",
            "label": "X axis",
            "choices": ["adios_step", "time", "step", "tindex"],
            "default": "time",
        },
        {
            "key": "mode",
            "type": "select",
            "label": "Series",
            "choices": ["corrected", "raw", "both"],
            "default": "corrected",
        },
        {
            "key": "normalize",
            "type": "bool",
            "label": "Normalize",
            "default": False,
        },
    ]


def render(ctx):
    """Return a Pulsar plot1d tile for flux / sqrt(grad_psi_sqr)."""
    helpers = ctx["helpers"]
    variable_path = str(ctx.get("variable_path", "") or "")
    flux_name = variable_basename(ctx)
    grad_name = grad_psi_sqr_name(flux_name)
    if not grad_name:
        raise ValueError("Selected variable is not an XGC species radial-flux profile")

    steps_count = int(ctx.get("steps_count", 1) or 1)
    flux = read_profile_stack(helpers.read_variable, variable_path, steps_count)
    grad = read_profile_stack(helpers.read_source_variable, grad_name, steps_count)
    if flux.shape != grad.shape:
        raise ValueError(f"Flux and grad_psi_sqr shapes differ: {flux.shape} vs {grad.shape}")

    corrected = np.divide(
        flux,
        np.sqrt(grad),
        out=np.full_like(flux, np.nan, dtype=float),
        where=np.asarray(grad, dtype=float) > 0.0,
    )

    options = dict(ctx.get("options", {}) or {})
    indices = parse_indices(options.get("profile_indices"), flux.shape[1])
    x_axis_name = str(options.get("x_axis", "adios_step") or "adios_step")
    x_values, x_label = x_axis(ctx, helpers, x_axis_name, steps_count)
    mode = str(options.get("mode", "corrected") or "corrected")
    normalize_series = bool(options.get("normalize", False))

    datasets = []
    if mode in {"corrected", "both"}:
        datasets.append(("corrected", corrected, f"{flux_name} / sqrt({grad_name})"))
    if mode in {"raw", "both"}:
        datasets.append(("raw", flux, flux_name))
    if not datasets:
        raise ValueError(f"Unknown radial flux display mode: {mode}")

    series = []
    for mode_name, data, data_label in datasets:
        for index in indices:
            y = np.asarray(data[:, index], dtype=float)
            label = f"{data_label} index {index}"
            if normalize_series:
                y = normalize(y)
                label = f"{label} normalized"
            series.append(
                {
                    "x": x_values,
                    "y": y,
                    "source_label": label,
                    "source_key": f"{mode_name}:{flux_name}:profile_index:{index}",
                }
            )

    y_label = f"{flux_name} / sqrt({grad_name})"
    if mode == "raw":
        y_label = flux_name
    elif mode == "both":
        y_label = "radial flux"
    if normalize_series:
        y_label = f"{y_label} / initial"

    plot = helpers.plot1d_payload(series, x_label=x_label, y_label=y_label)
    note = f"plugin: {PLUGIN_ID}; corrected using {grad_name}"
    if x_axis_name != "adios_step" and has_duplicate_or_nonmonotonic_x(x_values):
        note = f"{note}; {x_axis_name} axis has duplicate or non-monotonic values"

    return {
        "media_type": "plot1d",
        "display_title": f"{flux_name} corrected radial flux",
        "plot": plot,
        "status": "ok",
        "note": note,
    }
