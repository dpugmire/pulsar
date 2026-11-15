"""Heatmap plugin for the 2D Orszag-Tang magnetic divergence field."""

from __future__ import annotations

import base64
from io import BytesIO

import numpy as np
from PIL import Image


PLUGIN_ID = "mhd_divergence_heatmap"
LABEL = "MHD div(B) heatmap"


def supports(meta):
    """Support multi-step 2D variables whose basename is ``div_b``."""
    try:
        ndims = int(meta.get("ndims", -1))
        steps_count = int(meta.get("steps_count", 0) or 0)
    except (TypeError, ValueError):
        return False
    name = str(
        meta.get("variable_name", "")
        or meta.get("variable_id", "")
        or meta.get("variable_path", "")
    ).strip("/")
    return ndims == 2 and steps_count > 0 and name.rsplit("/", 1)[-1] == "div_b"


def options_schema(meta):
    steps_count = max(1, int(meta.get("steps_count", 1) or 1))
    return [
        {
            "key": "step",
            "type": "number",
            "label": "ADIOS step",
            "default": 0,
            "min": 0,
            "max": steps_count - 1,
        },
        {
            "key": "symmetric",
            "type": "bool",
            "label": "Symmetric color range",
            "default": True,
        },
    ]


def render(ctx):
    helpers = ctx["helpers"]
    steps_count = int(ctx.get("steps_count", 0) or 0)
    if steps_count <= 0:
        raise ValueError("div_b has no ADIOS steps")

    options = dict(ctx.get("options", {}) or {})
    try:
        step = int(options.get("step", 0) or 0)
    except (TypeError, ValueError):
        step = 0
    step = max(0, min(step, steps_count - 1))
    raw = np.asarray(
        helpers.read_variable(
            str(ctx.get("variable_path", "") or ""),
            step_selection=(step, step + 1),
        ),
        dtype=float,
    )
    field = np.squeeze(raw)
    if field.ndim != 2:
        raise ValueError(f"Expected div_b to be 2D after selection, got {field.shape}")

    finite = field[np.isfinite(field)]
    if finite.size == 0:
        raise ValueError("div_b contains no finite values")
    low = float(np.min(finite))
    high = float(np.max(finite))
    symmetric = bool(options.get("symmetric", True))
    if symmetric:
        limit = max(abs(low), abs(high))
        low, high = -limit, limit
    if high <= low:
        high = low + 1.0

    normalized = np.clip((field - low) / (high - low), 0.0, 1.0)
    normalized = np.nan_to_num(normalized, nan=0.5)
    pixels = _blue_white_red(normalized)
    image = Image.fromarray(pixels, mode="RGB")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    src = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")

    mean = float(np.mean(finite))
    rms = float(np.sqrt(np.mean(np.square(finite))))
    return {
        "media_type": "image",
        "display_title": f"MHD div(B) heatmap · step {step}",
        "src": src,
        "status": "ok",
        "note": (
            f"plugin: {PLUGIN_ID}; step={step}; min={float(np.min(finite)):.6g}; "
            f"max={float(np.max(finite)):.6g}; mean={mean:.6g}; rms={rms:.6g}"
        ),
    }


def _blue_white_red(values):
    """Map [0, 1] to a compact diverging blue-white-red RGB image."""
    values = np.asarray(values, dtype=float)
    red = np.where(values <= 0.5, values * 2.0, 1.0)
    green = np.where(values <= 0.5, values * 2.0, (1.0 - values) * 2.0)
    blue = np.where(values <= 0.5, 1.0, (1.0 - values) * 2.0)
    return np.rint(np.stack((red, green, blue), axis=-1) * 255.0).astype(np.uint8)
