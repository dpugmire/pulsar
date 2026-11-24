"""Generate a deterministic, ephemeral campaign for Pulsar demonstrations."""

from __future__ import annotations

import io
import math
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import adios2
import numpy as np
from PIL import Image
from PIL import ImageDraw

from db import scalar_field_to_png_bytes


DEMO_VARIABLES_1D = (
    "traveling_wave_1d",
    "moving_pulse_1d",
    "damped_mode_1d",
)
DEMO_VARIABLES_SCALAR = (
    "scalar/moving_pulse_position",
    "scalar/damped_mode_energy",
)
DEMO_VARIABLES_2D = (
    "traveling_wave_2d",
    "moving_blob_2d",
    "rotating_vortex_2d",
)
DEFAULT_DEMO_SOURCE_COUNT = 5
MAX_DEMO_SOURCE_COUNT = 49


class DemoDependencyError(RuntimeError):
    """Raised when demo mode cannot use the required hpc-campaign API."""


@dataclass(frozen=True)
class DemoConfig:
    steps: int = 20
    samples_1d: int = 256
    shape_2d: tuple[int, int] = (96, 96)
    source_count: int = DEFAULT_DEMO_SOURCE_COUNT

    def validate(self) -> None:
        if self.steps <= 1:
            raise ValueError("Demo steps must be greater than one")
        if self.samples_1d <= 1:
            raise ValueError("Demo 1D sample count must be greater than one")
        if len(self.shape_2d) != 2 or any(value <= 1 for value in self.shape_2d):
            raise ValueError("Demo 2D shape must contain two dimensions greater than one")
        if not 1 <= self.source_count <= MAX_DEMO_SOURCE_COUNT:
            raise ValueError(
                f"Demo source count must be between 1 and {MAX_DEMO_SOURCE_COUNT}"
            )


@dataclass(frozen=True)
class DemoSource:
    name: str
    amplitude: float = 1.0
    phase: float = 0.0
    speed: float = 1.0
    offset: float = 0.0
    width_scale: float = 1.0


DEMO_SOURCES = (
    DemoSource("baseline"),
    DemoSource("high_amplitude", amplitude=1.35),
    DemoSource("phase_shifted", phase=math.pi / 3.0),
    DemoSource("fast_dynamics", speed=1.5),
    DemoSource("elevated_offset", offset=0.5, width_scale=1.15),
)


def demo_sources(source_count: int) -> tuple[DemoSource, ...]:
    """Return ``source_count`` deterministic synthetic source definitions."""

    config = DemoConfig(source_count=source_count)
    config.validate()
    if source_count <= len(DEMO_SOURCES):
        return DEMO_SOURCES[:source_count]

    sources = list(DEMO_SOURCES)
    for index in range(len(sources), source_count):
        fraction = float(index) / float(MAX_DEMO_SOURCE_COUNT - 1)
        sources.append(
            DemoSource(
                f"variant_{index + 1:02d}",
                amplitude=0.8 + 0.8 * fraction,
                phase=2.0 * math.pi * ((index * 0.61803398875) % 1.0),
                speed=0.75 + fraction,
                offset=-0.25 + 0.5 * fraction,
                width_scale=0.8 + 0.4 * fraction,
            )
        )
    return tuple(sources)


@dataclass(frozen=True)
class GeneratedDemoCampaign:
    root: Path
    campaign_path: Path
    sidecar_path: Path


def _hpc_campaign_api():
    try:
        from hpc_campaign import Manager  # type: ignore
    except ImportError as exc:
        raise DemoDependencyError(
            "Demo mode requires unified hpc-campaign support. "
            "Install Pulsar with: python -m pip install -e '.[schema,demo]'"
        ) from exc

    required = (
        "add_variable",
        "visualization",
        "visualization_sequence",
        "video",
        "scalar_field_data",
        "data",
        "set_schema",
    )
    missing = [name for name in required if not hasattr(Manager, name)]
    if missing:
        raise DemoDependencyError(
            "The installed hpc-campaign does not provide the visualization API "
            f"required by demo mode (missing: {', '.join(missing)})."
        )
    return Manager


def _quiet_hpc_call(function, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def _periodic_distance(values: np.ndarray, center: float) -> np.ndarray:
    return (values - center + 0.5) % 1.0 - 0.5


def analytical_step(
    source: DemoSource,
    step: int,
    config: DemoConfig,
) -> dict[str, np.ndarray]:
    """Return all analytical quantities for one source and time step."""

    if not 0 <= step < config.steps:
        raise ValueError(f"Demo step {step} is outside [0, {config.steps - 1}]")

    tau = float(step) / float(config.steps)
    temporal_phase = 2.0 * math.pi * source.speed * tau
    x_1d = np.linspace(0.0, 1.0, config.samples_1d, endpoint=False, dtype=np.float32)

    traveling_wave_1d = source.offset + source.amplitude * np.sin(
        2.0 * math.pi * x_1d - temporal_phase + source.phase
    )

    pulse_center = (0.2 + source.speed * tau + source.phase / (2.0 * math.pi)) % 1.0
    pulse_width = 0.075 * source.width_scale
    pulse_distance = _periodic_distance(x_1d, pulse_center)
    moving_pulse_1d = source.offset + source.amplitude * np.exp(
        -0.5 * (pulse_distance / pulse_width) ** 2
    )

    damped_mode_1d = source.offset + source.amplitude * math.exp(-1.4 * tau) * np.sin(
        3.0 * math.pi * x_1d + source.phase
    ) * math.cos(temporal_phase)

    pulse_weights = moving_pulse_1d - source.offset
    circular_moment = np.sum(
        pulse_weights * np.exp(2.0j * math.pi * x_1d)
    ) / np.sum(pulse_weights)
    moving_pulse_position = (np.angle(circular_moment) / (2.0 * math.pi)) % 1.0
    damped_mode_energy = np.mean((damped_mode_1d - source.offset) ** 2)

    height, width = config.shape_2d
    x_2d = np.linspace(-1.0, 1.0, width, dtype=np.float32)
    y_2d = np.linspace(-1.0, 1.0, height, dtype=np.float32)
    xx, yy = np.meshgrid(x_2d, y_2d)

    traveling_wave_2d = source.offset + source.amplitude * np.sin(
        math.pi * (2.0 * xx - source.speed * tau) + source.phase
    ) * np.cos(2.0 * math.pi * yy + 0.5 * source.phase)

    orbit_angle = temporal_phase + source.phase
    center_x = 0.45 * math.cos(orbit_angle)
    center_y = 0.45 * math.sin(orbit_angle)
    sigma = 0.22 * source.width_scale
    moving_blob_2d = source.offset + source.amplitude * (1.0 + 0.08 * tau) * np.exp(
        -((xx - center_x) ** 2 + (yy - center_y) ** 2) / (2.0 * sigma * sigma)
    )

    radius = np.sqrt(xx * xx + yy * yy)
    polar_angle = np.arctan2(yy, xx)
    rotating_vortex_2d = (
        source.offset
        + 2.8
        * source.amplitude
        * (1.0 - 0.08 * tau)
        * radius
        * np.exp(-3.0 * radius * radius)
        * np.sin(polar_angle - temporal_phase + source.phase)
    )

    return {
        "traveling_wave_1d": np.asarray(traveling_wave_1d, dtype=np.float32),
        "moving_pulse_1d": np.asarray(moving_pulse_1d, dtype=np.float32),
        "damped_mode_1d": np.asarray(damped_mode_1d, dtype=np.float32),
        "scalar/moving_pulse_position": np.asarray(
            moving_pulse_position, dtype=np.float32
        ),
        "scalar/damped_mode_energy": np.asarray(
            damped_mode_energy, dtype=np.float32
        ),
        "traveling_wave_2d": np.asarray(traveling_wave_2d, dtype=np.float32),
        "moving_blob_2d": np.asarray(moving_blob_2d, dtype=np.float32),
        "rotating_vortex_2d": np.asarray(rotating_vortex_2d, dtype=np.float32),
    }


def _source_steps(source: DemoSource, config: DemoConfig) -> list[dict[str, np.ndarray]]:
    return [analytical_step(source, step, config) for step in range(config.steps)]


def _write_source(path: Path, steps: list[dict[str, np.ndarray]]) -> None:
    with adios2.Stream(str(path), "w") as stream:
        for fields in steps:
            stream.begin_step()
            for name, values in fields.items():
                if values.ndim == 0:
                    stream.write(name, values)
                    continue
                shape = list(values.shape)
                stream.write(name, values, shape, [0] * values.ndim, shape)
            stream.end_step()


def _field_metadata(
    frames: list[np.ndarray],
    config: DemoConfig,
    visualization_name: str,
) -> dict[str, Any]:
    global_min = min(float(np.min(frame)) for frame in frames)
    global_max = max(float(np.max(frame)) for frame in frames)
    height, width = config.shape_2d
    return {
        "kind": "scalarField",
        "visualization_name": visualization_name,
        "visualization_kind": "field_2d",
        "frame_count": config.steps,
        "encoding": "raw",
        "compression": "none",
        "layout": "row-major",
        "value_encoding": "direct",
        "dtype": "float32",
        "byte_order": "little",
        "shape": [height, width],
        "min": global_min,
        "max": global_max,
        "grid": {
            "shape": [height, width],
            "axes": ["x", "y"],
            "column_axis": "x",
            "row_axis": "y",
            "column_order": "ascending",
            "row_order": "descending",
            "bounds": {"x": [-1.0, 1.0], "y": [-1.0, 1.0]},
        },
    }


def _heatmap_images(frames: list[np.ndarray], metadata: dict[str, Any]) -> list[Image.Image]:
    images: list[Image.Image] = []
    for frame in frames:
        payload = np.asarray(frame, dtype="<f4").tobytes(order="C")
        png = scalar_field_to_png_bytes(payload, metadata)
        with Image.open(io.BytesIO(png)) as image:
            images.append(image.convert("RGB").copy())
    return images


def _standalone_visualization(title: str, lines: list[str], accent: tuple[int, int, int]) -> Image.Image:
    """Create a small campaign-level illustration with no variable inputs."""
    image = Image.new("RGB", (640, 360), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 612, 332), radius=18, fill="white", outline="#c9d6e2", width=2)
    draw.rounded_rectangle((28, 28, 612, 104), radius=18, fill=accent)
    draw.rectangle((28, 78, 612, 104), fill=accent)
    draw.text((54, 52), title, fill="white", font_size=28)
    for index, line in enumerate(lines):
        y = 145 + index * 48
        draw.ellipse((58, y + 3, 78, y + 23), fill=accent)
        draw.text((98, y), line, fill="#24384b", font_size=21)
    return image


def _add_standalone_visualizations(
    manager, config: DemoConfig, images: list[Image.Image], root: Path,
) -> None:
    """Register one still, one image sequence, and one movie without variables."""
    _quiet_hpc_call(
        manager.visualization,
        images=[_standalone_visualization(
            "Synthetic campaign guide",
            [
                f"{config.source_count} synthetic source files",
                f"{config.steps} recorded time steps per source",
                "Campaign-level visualization with no variable inputs",
            ],
            (45, 104, 154),
        )],
        sequence_name="campaign_visualizations/campaign_overview",
        variables=[],
        metadata={"representation_kind": "image", "title": "Synthetic campaign guide"},
        store=True,
    )
    _quiet_hpc_call(
        manager.visualization,
        images=images,
        sequence_name="campaign_visualizations/moving_blob_sequence",
        variables=[],
        steps=list(range(config.steps)),
        metadata={"representation_kind": "image", "title": "Moving blob (image sequence)"},
        store=True,
    )
    # Encode the same baseline heatmaps used by the variable-associated movie.
    # Padding makes even-sized H.264 frames without changing the source images.
    with tempfile.TemporaryDirectory(prefix="campaign-movie-", dir=root) as movie_dir:
        movie_dir = Path(movie_dir)
        for index, image in enumerate(images):
            image.save(movie_dir / f"frame-{index:04d}.png")
        movie = movie_dir / "moving_blob.mp4"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-framerate", "2", "-i", str(movie_dir / "frame-%04d.png"),
                    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(movie),
                ],
                capture_output=True, check=True, timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise DemoDependencyError("Could not encode the demo MP4 with ffmpeg") from exc
        _quiet_hpc_call(
            manager.video,
            movie,
            name="campaign_visualizations/moving_blob.mp4",
            sequence_name="campaign_visualizations/Moving blob (MP4)",
            variables=[],
            vis_type="movie",
            frame_count=config.steps,
            frame_times=[float(step) for step in range(config.steps)],
            store=True,
        )


def _store_scalar_fields(
    manager,
    source_name: str,
    variable_name: str,
    frames: list[np.ndarray],
    metadata: dict[str, Any],
) -> list[str]:
    chunk_names: list[str] = []
    for step, frame in enumerate(frames):
        payload_name = (
            f"representations/{source_name}/{variable_name}/scalar-field/"
            f"frame-{step:04d}.raw"
        )
        _quiet_hpc_call(
            manager.scalar_field_data,
            np.asarray(frame, dtype="<f4"),
            name=payload_name,
            metadata=metadata,
        )
        chunk_names.append(payload_name)
    return chunk_names


def _schema_text() -> str:
    return """schema_version: 1
name: pulsar_synthetic_demo

files:
  synthetic_sources:
    role: time_series
    mode: append
    pattern: "sources/*.bp"
    time:
      index: step_index

variable_groups:
  1D Profiles:
    file: synthetic_sources
    pattern: "*_1d"
    role: profile

  Scalar Time Series:
    file: synthetic_sources
    pattern: "scalar/*"
    role: scalar_trace

  2D Fields:
    file: synthetic_sources
    pattern: "*_2d"
    role: field
"""


def _store_campaign_schema(manager, schema_path: Path, root: Path) -> None:
    _quiet_hpc_call(manager.set_schema, schema_path.relative_to(root))


def generate_demo_campaign(
    root: Path,
    config: DemoConfig = DemoConfig(),
) -> GeneratedDemoCampaign:
    """Generate one complete synthetic campaign below ``root``."""

    config.validate()
    Manager = _hpc_campaign_api()
    if not shutil.which("ffmpeg"):
        raise DemoDependencyError("Demo mode requires ffmpeg on PATH to create its MP4 example")
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    sources_dir = root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    campaign_path = root / "synthetic-demo.aca"

    previous_directory = Path.cwd()
    os.chdir(root)
    manager = None
    try:
        sources = demo_sources(config.source_count)
        manager = Manager(str(campaign_path), campaign_store="", verbose=0)
        _quiet_hpc_call(manager.open, create=True, truncate=True)
        print(
            "Generating Pulsar demo campaign "
            f"({len(sources)} sources, {config.steps} steps)..."
        )
        campaign_images = []
        for source in sources:
            print(f"  synthetic source: {source.name}")
            steps = _source_steps(source, config)
            source_path = sources_dir / f"{source.name}.bp"
            source_dataset = f"sources/{source.name}.bp"
            _write_source(source_path, steps)
            _quiet_hpc_call(
                manager.data,
                source_path.relative_to(root),
                name=source_dataset,
            )

            for variable_name in (
                *DEMO_VARIABLES_1D,
                *DEMO_VARIABLES_SCALAR,
                *DEMO_VARIABLES_2D,
            ):
                _quiet_hpc_call(
                    manager.add_variable,
                    dataset=source_dataset,
                    variable=variable_name,
                    definition=variable_name.rsplit("/", 1)[-1],
                )

            representation_dataset = f"representations/{source.name}"
            for variable_name in DEMO_VARIABLES_2D:
                frames = [step_fields[variable_name] for step_fields in steps]
                heatmap_metadata = _field_metadata(frames, config, "heatmap")
                images = _heatmap_images(frames, heatmap_metadata)
                if source == sources[0] and variable_name == "moving_blob_2d":
                    campaign_images = images
                _quiet_hpc_call(
                    manager.visualization,
                    images=images,
                    sequence_name=f"{representation_dataset}/{variable_name}/heatmap",
                    variables=[{
                        "name": variable_name,
                        "source_dataset": source_dataset,
                        "role": "color-by",
                    }],
                    steps=list(range(config.steps)),
                    metadata={
                        **heatmap_metadata,
                        "representation_kind": "image",
                    },
                    store=True,
                )

                scalar_metadata = _field_metadata(frames, config, "scalar_field")
                scalar_chunks = _store_scalar_fields(
                    manager,
                    source.name,
                    variable_name,
                    frames,
                    scalar_metadata,
                )
                _quiet_hpc_call(
                    manager.visualization_sequence,
                    name=f"{representation_dataset}/{variable_name}/scalar_field",
                    vis_type="scalar_field",
                    variables=[{
                        "name": variable_name,
                        "source_dataset": source_dataset,
                        "role": "color-by",
                    }],
                    items=[
                        {
                            "type": "SCALAR_FIELD",
                            "name": chunk_name,
                            "metadata": {"frame_index": index},
                        }
                        for index, chunk_name in enumerate(scalar_chunks)
                    ],
                    metadata={**scalar_metadata, "representation_kind": "scalar_field"},
                )

        _add_standalone_visualizations(manager, config, campaign_images, root)

        schema_path = root / "__campaign_schema.yaml"
        schema_path.write_text(_schema_text(), encoding="utf-8")
        _store_campaign_schema(manager, schema_path, root)
        print("Synthetic campaign ready.")
    finally:
        if manager is not None:
            manager.close()
        os.chdir(previous_directory)

    return GeneratedDemoCampaign(
        root=root,
        campaign_path=campaign_path,
        sidecar_path=root / "synthetic-demo.pulsar.sqlite",
    )


@contextmanager
def temporary_demo_campaign(
    config: DemoConfig = DemoConfig(),
) -> Iterator[GeneratedDemoCampaign]:
    """Yield an ephemeral generated campaign and remove it on exit."""

    with tempfile.TemporaryDirectory(prefix="pulsar-demo-") as temp_dir:
        yield generate_demo_campaign(Path(temp_dir), config=config)
