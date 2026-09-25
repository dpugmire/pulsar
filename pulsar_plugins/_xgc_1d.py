"""Shared helpers for XGC rank-1 profile plugins."""

from __future__ import annotations

import re

import numpy as np


def rank1_multistep(meta):
    return int(meta.get("ndims", -1) or -1) == 1 and int(meta.get("steps_count", 1) or 1) > 1


def variable_basename(meta_or_name):
    if isinstance(meta_or_name, dict):
        raw = str(
            meta_or_name.get("variable_name", "")
            or meta_or_name.get("variable_id", "")
            or meta_or_name.get("variable_path", "")
            or ""
        )
    else:
        raw = str(meta_or_name or "")
    return raw.strip("/").rsplit("/", 1)[-1]


def source_variable_names(meta):
    names = set()
    for item in meta.get("source_variables", []) or []:
        if not isinstance(item, dict):
            continue
        for key in ("variable_id", "variable_name", "variable_path"):
            name = variable_basename(item.get(key, ""))
            if name:
                names.add(name)
    return names


def opposite_species_name(name):
    base = variable_basename(name)
    if base.startswith("e_"):
        return "i_" + base[2:]
    if base.startswith("i_"):
        return "e_" + base[2:]
    return ""


def is_species_profile_name(name):
    return bool(re.match(r"^[ei]_.+_1d$", variable_basename(name)))


def grad_psi_sqr_name(name):
    base = variable_basename(name)
    if not re.match(r"^[ei]_.+_1d$", base):
        return ""
    species = base[:1]
    suffix = "_df_1d" if base.endswith("_df_1d") else "_1d"
    return f"{species}_grad_psi_sqr{suffix}"


def is_radial_flux_name(name):
    base = variable_basename(name)
    if not re.match(r"^[ei]_.+_1d$", base):
        return False
    if "grad_psi_sqr" in base:
        return False
    return "radial" in base and "flux" in base


def default_indices(n_profile):
    n_profile = max(1, int(n_profile or 1))
    candidates = [0, n_profile // 4, n_profile // 2, (3 * n_profile) // 4, n_profile - 1]
    out = []
    for value in candidates:
        value = max(0, min(int(value), n_profile - 1))
        if value not in out:
            out.append(value)
    return ",".join(str(value) for value in out)


def parse_indices(raw, n_profile):
    text = str(raw or "").strip() or default_indices(n_profile)
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


def read_profile_stack(read_fn, name, steps_count):
    raw = np.asarray(read_fn(name, step_selection=(0, steps_count)))
    if np.iscomplexobj(raw):
        raise ValueError(f"Complex-valued profile data are not supported: {name}")

    data = np.asarray(raw, dtype=float)
    if data.ndim == 1:
        if data.size % steps_count != 0:
            raise ValueError(f"Cannot reshape {data.size} values into {steps_count} steps")
        data = data.reshape(steps_count, data.size // steps_count)
    elif data.shape[0] != steps_count:
        data = data.reshape(steps_count, -1)
    if data.ndim != 2:
        raise ValueError(f"Expected time x profile data for {name}, got shape {data.shape}")
    return data


def x_axis(ctx, helpers, x_axis_name, steps_count):
    if x_axis_name == "adios_step":
        return np.arange(steps_count, dtype=float), "adios_step"

    try:
        values = helpers.read_source_variable(x_axis_name, step_selection=(0, steps_count))
    except Exception:
        return np.arange(steps_count, dtype=float), "adios_step"
    x = np.asarray(values, dtype=float).reshape(-1)
    if x.size != steps_count:
        return np.arange(steps_count, dtype=float), "adios_step"
    if not np.all(np.isfinite(x)):
        return np.arange(steps_count, dtype=float), "adios_step"
    return x, x_axis_name


def normalize(values):
    y = np.asarray(values, dtype=float)
    finite = y[np.isfinite(y)]
    if finite.size == 0:
        return y
    baseline = finite[0]
    if baseline == 0.0:
        scale = np.max(np.abs(finite))
        return y if scale == 0.0 else y / scale
    return y / baseline


def has_duplicate_or_nonmonotonic_x(values):
    x = np.asarray(values, dtype=float).reshape(-1)
    if x.size <= 1:
        return False
    return np.unique(x).size != x.size or bool(np.any(np.diff(x) <= 0))
