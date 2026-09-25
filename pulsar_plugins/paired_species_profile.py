"""Paired electron/ion profile time-series plugin for XGC 1D variables."""

from __future__ import annotations

import numpy as np

from ._xgc_1d import (
    default_indices,
    has_duplicate_or_nonmonotonic_x,
    is_species_profile_name,
    normalize,
    opposite_species_name,
    parse_indices,
    rank1_multistep,
    read_profile_stack,
    source_variable_names,
    variable_basename,
    x_axis,
)


PLUGIN_ID = "paired_species_profile"
LABEL = "Paired species profile"


def supports(meta):
    """Support XGC e/i rank-1 profiles when the opposite species is present."""
    if not rank1_multistep(meta):
        return False
    name = variable_basename(meta)
    counterpart = opposite_species_name(name)
    return bool(is_species_profile_name(name) and counterpart in source_variable_names(meta))


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
            "key": "show_selected",
            "type": "bool",
            "label": "Selected species",
            "default": True,
        },
        {
            "key": "show_counterpart",
            "type": "bool",
            "label": "Counterpart species",
            "default": True,
        },
        {
            "key": "normalize",
            "type": "bool",
            "label": "Normalize",
            "default": False,
        },
    ]


def render(ctx):
    """Return a Pulsar plot1d tile comparing selected and opposite species."""
    helpers = ctx["helpers"]
    variable_path = str(ctx.get("variable_path", "") or "")
    selected_name = variable_basename(ctx)
    counterpart_name = opposite_species_name(selected_name)
    if not counterpart_name:
        raise ValueError("Selected variable is not an e/i species profile")

    steps_count = int(ctx.get("steps_count", 1) or 1)
    selected = read_profile_stack(helpers.read_variable, variable_path, steps_count)
    counterpart = read_profile_stack(helpers.read_source_variable, counterpart_name, steps_count)
    if selected.shape != counterpart.shape:
        raise ValueError(
            f"Selected and counterpart shapes differ: {selected_name}={selected.shape}, "
            f"{counterpart_name}={counterpart.shape}"
        )

    options = dict(ctx.get("options", {}) or {})
    indices = parse_indices(options.get("profile_indices"), selected.shape[1])
    x_axis_name = str(options.get("x_axis", "adios_step") or "adios_step")
    x_values, x_label = x_axis(ctx, helpers, x_axis_name, steps_count)
    normalize_series = bool(options.get("normalize", False))
    show_selected = bool(options.get("show_selected", True))
    show_counterpart = bool(options.get("show_counterpart", True))
    if not show_selected and not show_counterpart:
        raise ValueError("At least one species must be enabled")

    series = []
    for data_name, data, enabled in (
        (selected_name, selected, show_selected),
        (counterpart_name, counterpart, show_counterpart),
    ):
        if not enabled:
            continue
        for index in indices:
            y = np.asarray(data[:, index], dtype=float)
            label = f"{data_name} index {index}"
            if normalize_series:
                y = normalize(y)
                label = f"{label} normalized"
            series.append(
                {
                    "x": x_values,
                    "y": y,
                    "source_label": label,
                    "source_key": f"{data_name}:profile_index:{index}",
                }
            )

    base_label = selected_name[2:] if selected_name[:2] in {"e_", "i_"} else selected_name
    y_label = f"{base_label} / initial" if normalize_series else base_label
    plot = helpers.plot1d_payload(series, x_label=x_label, y_label=y_label)
    note = f"plugin: {PLUGIN_ID}; paired {selected_name} with {counterpart_name}"
    if x_axis_name != "adios_step" and has_duplicate_or_nonmonotonic_x(x_values):
        note = f"{note}; {x_axis_name} axis has duplicate or non-monotonic values"

    return {
        "media_type": "plot1d",
        "display_title": f"{selected_name} / {counterpart_name} profile comparison",
        "plot": plot,
        "status": "ok",
        "note": note,
    }
