"""Generate a current_z comparison and optionally show it as an unpublished result.

Uses the campaign read-only and requires only Pulsar's existing dependencies.
Run with --help for the local paths and optional running-viewer connection.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import adios2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pulsar.client import connect


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _colors(values):
    values = np.clip(values, -1.0, 1.0)
    rgb = np.stack(
        (1 + np.minimum(values, 0), 1 - np.abs(values), 1 - np.maximum(values, 0)),
        axis=-1,
    )
    return np.round(255 * rgb).astype(np.uint8)


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def generate_comparison(campaign, output, datasets, time_value):
    campaign = Path(campaign).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    started = datetime.now(timezone.utc).isoformat()
    campaign_hash = _sha256(campaign)
    fields, inputs = [], []
    with (
        adios2.FileReader(str(campaign)) as reader,
        sqlite3.connect(campaign.as_uri() + "?mode=ro", uri=True) as database,
    ):
        variables = reader.available_variables()
        for dataset in datasets:
            variable_path = dataset + "/current_z"
            time_path = dataset + "/time"
            count = int(variables[time_path]["AvailableStepsCount"])
            times = np.asarray(
                reader.read(time_path, step_selection=[0, count])
            ).reshape(-1)
            matching = np.flatnonzero(np.isclose(times, time_value, rtol=0, atol=1e-12))
            if not len(matching):
                raise ValueError(
                    f"{dataset} has no output at physical time {time_value}; no time interpolation is performed"
                )
            step = int(matching[0])
            field = np.asarray(
                reader.read(variable_path, step_selection=[step, 1]), dtype=float
            ).squeeze()
            if field.ndim != 2 or not np.isfinite(field).all():
                raise ValueError(f"{variable_path} must be a finite 2D field")
            dataset_uuid = database.execute(
                "select uuid from dataset where name=?", (dataset,)
            ).fetchone()
            fields.append(field)
            inputs.append(
                {
                    "campaign_path": str(campaign),
                    "campaign_sha256": campaign_hash,
                    "source_dataset": dataset,
                    "dataset_uuid": dataset_uuid[0] if dataset_uuid else None,
                    "variable_id": "current_z",
                    "variable_path": variable_path,
                    "time_variable_path": time_path,
                    "timestep": step,
                    "physical_time": float(times[step]),
                    "shape": list(field.shape),
                }
            )
    limit = max(float(np.max(np.abs(field))) for field in fields) or 1.0
    panel, gap, margin, top = 300, 55, 50, 90
    width = 2 * margin + len(fields) * panel + (len(fields) - 1) * gap
    image = Image.new("RGB", (width, 530), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (24, 14),
        f"current_z: HLL resolution comparison at t = {time_value:g}",
        fill="black",
        font=_font(24),
    )
    draw.text(
        (24, 48),
        "Native grids with a shared symmetric color scale",
        fill="#444444",
        font=_font(16),
    )
    for index, (field, source) in enumerate(zip(fields, inputs)):
        x = margin + index * (panel + gap)
        label = source["source_dataset"].split("/")[0]
        draw.text(
            (x, 68),
            f"{label}: {field.shape[1]} x {field.shape[0]}",
            fill="black",
            font=_font(16),
        )
        heatmap = Image.fromarray(_colors(np.flipud(field) / limit)).resize(
            (panel, panel), Image.Resampling.NEAREST
        )
        image.paste(heatmap, (x, top))
        draw.rectangle((x, top, x + panel, top + panel), outline="#444444")
        draw.text((x - 22, top), str(field.shape[0] - 1), fill="black", font=_font(12))
        draw.text((x - 12, top + panel - 12), "0", fill="black", font=_font(12))
        draw.text((x, top + panel + 4), "0", fill="black", font=_font(12))
        draw.text(
            (x + panel - 24, top + panel + 4),
            str(field.shape[1] - 1),
            fill="black",
            font=_font(12),
        )
        draw.text(
            (x + 95, top + panel + 4), "column index", fill="#444444", font=_font(12)
        )
        draw.text(
            (x, top + panel + 25),
            f"rms {np.sqrt(np.mean(field**2)):.4g}; max |value| {np.max(np.abs(field)):.4g}",
            fill="#444444",
            font=_font(13),
        )
    bar_width = min(520, width - 100)
    bar_x = (width - bar_width) // 2
    gradient = np.tile(np.linspace(-1, 1, bar_width), (18, 1))
    image.paste(Image.fromarray(_colors(gradient)), (bar_x, 455))
    for offset, value in ((0, -limit), (bar_width // 2, 0), (bar_width, limit)):
        draw.text(
            (bar_x + offset - 18, 477), f"{value:.4g}", fill="black", font=_font(13)
        )
    draw.text(
        (bar_x + bar_width // 2 - 35, 501), "current_z", fill="black", font=_font(14)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    parameters = {
        "datasets": list(datasets),
        "physical_time": time_value,
        "color_range": [-limit, limit],
        "spatial_sampling": "native grids",
        "pixel_scaling": "nearest-neighbor display",
    }
    provenance = {
        "intent": "Inspect current_z morphology across HLL resolutions at a common physical time",
        "intent_attribution": "example analysis script",
        "inputs": inputs,
        "execution": {
            "started_at_utc": started,
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "adios2": adios2.__version__,
        },
    }
    output.with_suffix(".provenance.json").write_text(
        json.dumps({"parameters": parameters, "provenance": provenance}, indent=2),
        encoding="utf-8",
    )
    return output, parameters, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--time", type=float, default=1.0)
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["hll_32/output.bp", "hll_64/output.bp", "hll_128/output.bp"],
    )
    parser.add_argument(
        "--session-file", help="Optionally register/display in a running Pulsar viewer"
    )
    args = parser.parse_args()
    output, parameters, provenance = generate_comparison(
        args.campaign, args.output, args.datasets, args.time
    )
    print(output)
    if args.session_file:
        viewer = connect(session_file=args.session_file)
        if (
            Path(viewer.context()["campaign"]["path"]).expanduser().resolve()
            != Path(args.campaign).expanduser().resolve()
        ):
            raise ValueError("The viewer is attached to another campaign")
        result = viewer.register_result(
            output,
            title=f"HLL current_z comparison at t={args.time:g}",
            script_path=__file__,
            parameters=parameters,
            provenance=provenance,
        )
        tab = viewer.create_tab("HLL resolution comparison")
        viewer.add_visualization("current_z", tab_id=tab["tab_id"])
        viewer.add_result(result["result_id"], tab_id=tab["tab_id"])
        viewer.save_workspace(output.with_suffix(".workspace.json"))
        print(f"Unpublished result: {result['result_id']}; tab: {tab['tab_id']}")


if __name__ == "__main__":
    main()
