import io
import json
import math
import sqlite3
import statistics
import threading
import zlib
from contextlib import ExitStack
from typing import Any, Dict, List, Optional, Set, Tuple

import contourpy
import numpy as np
from adios2 import FileReader
from PIL import Image, ImageColor, ImageDraw, ImageFont

from media_utils import png_bytes_to_data_uri
from query_parser import and_filter, mongo_filter_matches
from seurat.constants import SCALAR_FIELD_COLORMAP_OPTIONS


GENERATED_SCALAR_PLOT_VIS = "generated_timeseries"
GENERATED_SCALAR_PLOT_VERSION = 3
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
SCALAR_FIELD_VARIABLE_TYPE = "scalarField"
VISUALIZATION_PAYLOAD_VARIABLE_TYPES = ("image", SCALAR_FIELD_VARIABLE_TYPE)
SCALAR_FIELD_RENDER_MODES = ("colormap", "contours", "both")
SCALAR_FIELD_CONTOUR_LEVEL_MODES = ("range", "values")
SCALAR_FIELD_DEFAULT_CONTOUR_COUNT = 10
SCALAR_FIELD_MAX_CONTOUR_LEVELS = 100


def _dict_field(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_field(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _stops(values: List[List[int]]) -> np.ndarray:
    return np.array(values, dtype=np.float32)


_VIRIDIS_STOPS = _stops(
    [
        [68, 1, 84],
        [71, 44, 122],
        [59, 81, 139],
        [44, 113, 142],
        [33, 144, 141],
        [39, 173, 129],
        [92, 200, 99],
        [170, 220, 50],
        [253, 231, 37],
    ]
)
_TURBO_STOPS = _stops(
    [
        [48, 18, 59],
        [65, 69, 172],
        [70, 117, 237],
        [49, 155, 246],
        [36, 188, 221],
        [62, 211, 153],
        [133, 222, 71],
        [205, 214, 44],
        [245, 180, 49],
        [252, 120, 36],
        [224, 64, 28],
        [165, 24, 21],
        [122, 4, 3],
    ]
)
_SCALAR_FIELD_COLORMAP_STOPS = {
    "viridis": _VIRIDIS_STOPS,
    "plasma": _stops(
        [[13, 8, 135], [75, 3, 161], [125, 3, 168], [168, 34, 150], [203, 70, 121], [229, 107, 93], [248, 148, 65], [253, 195, 40], [240, 249, 33]]
    ),
    "inferno": _stops(
        [[0, 0, 4], [31, 12, 72], [85, 15, 109], [136, 34, 106], [186, 54, 85], [227, 89, 51], [249, 140, 10], [249, 201, 50], [252, 255, 164]]
    ),
    "magma": _stops(
        [[0, 0, 4], [28, 16, 68], [79, 18, 123], [129, 37, 129], [181, 54, 122], [229, 80, 100], [251, 135, 97], [254, 194, 135], [252, 253, 191]]
    ),
    "cividis": _stops(
        [[0, 34, 78], [0, 48, 96], [39, 66, 104], [73, 84, 109], [103, 102, 112], [132, 121, 113], [162, 142, 109], [196, 166, 95], [233, 196, 53], [255, 233, 69]]
    ),
    "turbo": _TURBO_STOPS,
    "jet": _stops(
        [[0, 0, 128], [0, 0, 255], [0, 128, 255], [0, 255, 255], [128, 255, 128], [255, 255, 0], [255, 128, 0], [255, 0, 0], [128, 0, 0]]
    ),
    "rainbow": _stops(
        [[150, 0, 90], [0, 0, 200], [0, 25, 255], [0, 152, 255], [44, 255, 150], [151, 255, 0], [255, 234, 0], [255, 111, 0], [255, 0, 0]]
    ),
    "coolwarm": _stops(
        [[59, 76, 192], [84, 111, 203], [113, 145, 211], [149, 174, 216], [185, 199, 217], [221, 221, 221], [234, 204, 190], [232, 163, 142], [214, 109, 95], [180, 4, 38]]
    ),
    "bwr": _stops([[0, 0, 255], [127, 127, 255], [255, 255, 255], [255, 127, 127], [255, 0, 0]]),
    "seismic": _stops(
        [[0, 0, 76], [0, 0, 180], [0, 76, 255], [153, 204, 255], [255, 255, 255], [255, 204, 153], [255, 76, 0], [180, 0, 0], [76, 0, 0]]
    ),
    "spectral": _stops(
        [[158, 1, 66], [213, 62, 79], [244, 109, 67], [253, 174, 97], [254, 224, 139], [255, 255, 191], [230, 245, 152], [171, 221, 164], [102, 194, 165], [50, 136, 189], [94, 79, 162]]
    ),
    "rdylbu": _stops(
        [[165, 0, 38], [215, 48, 39], [244, 109, 67], [253, 174, 97], [254, 224, 144], [255, 255, 191], [224, 243, 248], [171, 217, 233], [116, 173, 209], [69, 117, 180], [49, 54, 149]]
    ),
    "rdylgn": _stops(
        [[165, 0, 38], [215, 48, 39], [244, 109, 67], [253, 174, 97], [254, 224, 139], [255, 255, 191], [217, 239, 139], [166, 217, 106], [102, 189, 99], [26, 152, 80], [0, 104, 55]]
    ),
    "difference": _stops(
        [[49, 54, 149], [69, 117, 180], [116, 173, 209], [224, 243, 248], [255, 255, 255], [254, 224, 144], [244, 109, 67], [215, 48, 39], [165, 0, 38]]
    ),
    "gray": _stops([[0, 0, 0], [255, 255, 255]]),
    "hot": _stops([[0, 0, 0], [180, 0, 0], [255, 90, 0], [255, 220, 0], [255, 255, 255]]),
    "cool": _stops([[0, 255, 255], [255, 0, 255]]),
    "spring": _stops([[255, 0, 255], [255, 255, 0]]),
    "summer": _stops([[0, 128, 102], [255, 255, 102]]),
    "autumn": _stops([[255, 0, 0], [255, 255, 0]]),
    "winter": _stops([[0, 0, 255], [0, 255, 128]]),
    "copper": _stops([[0, 0, 0], [80, 50, 32], [160, 100, 64], [240, 150, 96], [255, 199, 127]]),
    "terrain": _stops([[51, 51, 153], [0, 153, 255], [0, 204, 102], [102, 153, 51], [230, 220, 170], [255, 255, 255]]),
    "ocean": _stops([[0, 0, 0], [0, 64, 128], [0, 128, 192], [0, 192, 192], [255, 255, 255]]),
}
SCALAR_FIELD_COLORMAPS = tuple(value for _, value in SCALAR_FIELD_COLORMAP_OPTIONS)
_SCALAR_FIELD_COLORMAP_ALIASES = {
    "grey": "gray",
    "grayscale": "gray",
    "rd_yl_bu": "rdylbu",
    "rd_yl_gn": "rdylgn",
}


def _scalar_field_colormap_css_gradient(stops: np.ndarray) -> str:
    if len(stops) <= 1:
        rgb = tuple(int(v) for v in stops[0])
        color = f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
        return f"linear-gradient(to top, {color} 0%, {color} 100%)"

    parts = []
    for i, rgb_values in enumerate(stops):
        rgb = tuple(int(v) for v in rgb_values)
        pct = (i / (len(stops) - 1)) * 100.0
        parts.append(f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]}) {pct:.3g}%")
    return "linear-gradient(to top, " + ", ".join(parts) + ")"


SCALAR_FIELD_COLORMAP_CSS_GRADIENTS = {
    name: _scalar_field_colormap_css_gradient(stops)
    for name, stops in _SCALAR_FIELD_COLORMAP_STOPS.items()
}


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        try:
            return float(str(value).strip())
        except Exception:
            return None


def _scalar_field_axis_value(value: float) -> str:
    return f"{float(value):.5g}"


def _scalar_field_axis_ticks(
    start_value: float,
    end_value: float,
) -> List[Dict[str, Any]]:
    values = (
        float(start_value),
        (float(start_value) + float(end_value)) * 0.5,
        float(end_value),
    )
    return [
        {
            "position": position,
            "value": value,
            "label": _scalar_field_axis_value(value),
        }
        for position, value in zip((0, 50, 100), values)
    ]


def _scalar_field_axis_bounds(
    bounds: Any,
) -> Optional[Tuple[float, float]]:
    if not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
        return None
    start = to_float(bounds[0])
    end = to_float(bounds[1])
    if (
        start is None
        or end is None
        or not math.isfinite(start)
        or not math.isfinite(end)
    ):
        return None
    return float(start), float(end)


def scalar_field_axis_spec(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return display-ready scalar-field axes from grid metadata or array indices."""

    raw = dict(metadata or {})
    grid_value = raw.get("grid", {})
    grid = dict(grid_value) if isinstance(grid_value, dict) else {}

    shape = grid.get("shape", raw.get("shape", []))
    if not isinstance(shape, (list, tuple)) or len(shape) < 2:
        return {}
    try:
        height = int(shape[0])
        width = int(shape[1])
    except (TypeError, ValueError):
        return {}
    if height <= 0 or width <= 0:
        return {}

    axes = grid.get("axes", [])
    if not isinstance(axes, (list, tuple)):
        axes = []
    column_axis = str(
        grid.get("column_axis", "")
        or (axes[0] if len(axes) > 0 else "")
        or "column"
    )
    row_axis = str(
        grid.get("row_axis", "")
        or (axes[1] if len(axes) > 1 else "")
        or "row"
    )

    bounds_value = grid.get("bounds", {})
    bounds = dict(bounds_value) if isinstance(bounds_value, dict) else {}
    x_bounds = _scalar_field_axis_bounds(bounds.get(column_axis))
    y_bounds = _scalar_field_axis_bounds(bounds.get(row_axis))

    if x_bounds is None:
        x_bounds = (0.0, float(max(0, width - 1)))
    if y_bounds is None:
        y_bounds = (0.0, float(max(0, height - 1)))

    x_start, x_end = x_bounds
    if str(grid.get("column_order", "ascending") or "ascending").lower() == "descending":
        x_start, x_end = x_end, x_start

    row_order = str(grid.get("row_order", "") or "").lower()
    if not row_order:
        row_order = "descending" if bounds.get(row_axis) is not None else "ascending"
    y_low, y_high = y_bounds
    y_start, y_end = (
        (y_high, y_low) if row_order == "ascending" else (y_low, y_high)
    )

    return {
        "x": {
            "label": column_axis,
            "start": x_start,
            "end": x_end,
            "ticks": _scalar_field_axis_ticks(x_start, x_end),
        },
        "y": {
            "label": row_axis,
            "start": y_start,
            "end": y_end,
            "ticks": _scalar_field_axis_ticks(y_start, y_end),
        },
    }


def valid_extrema(fmin: Optional[float], fmax: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if fmin is None or fmax is None:
        return None, None
    if not math.isfinite(fmin) or not math.isfinite(fmax):
        return None, None
    if fmin > fmax:
        return None, None
    return fmin, fmax


def adios_image_to_png_bytes(img: Any) -> bytes:
    """
    Convert an ADIOS image variable payload to PNG bytes.

    hpc-campaign image entries may already be encoded PNG byte arrays, or they
    may be pixel arrays. The viewer keeps the sidecar metadata-only and performs
    this conversion only for frames that are actually displayed.
    """
    if img is None:
        raise ValueError("img is None")

    arr = np.asarray(img)
    if arr.ndim == 1:
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8, copy=False)
        data = arr.tobytes()
        if not data.startswith(_PNG_SIG):
            raise ValueError(
                f"1D image payload does not look like PNG bytes. "
                f"len={len(data)} first8={data[:8]!r}"
            )
        return data

    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    if arr.ndim == 2:
        mode = "L"
    elif arr.ndim == 3 and arr.shape[2] == 3:
        mode = "RGB"
    elif arr.ndim == 3 and arr.shape[2] == 4:
        mode = "RGBA"
    else:
        raise ValueError(f"Unexpected image array shape: {arr.shape}, dtype={arr.dtype}")

    pil = Image.fromarray(arr, mode=mode)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _json_object_or_empty(text: Any) -> Dict[str, Any]:
    if isinstance(text, dict):
        return dict(text)
    if text is None:
        return {}
    try:
        value = json.loads(str(text))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _scalar_field_dtype(metadata: Dict[str, Any]) -> np.dtype:
    dtype_name = str(metadata.get("dtype", "float32") or "float32").strip()
    dtype = np.dtype(dtype_name)
    byte_order = str(metadata.get("byte_order", "little") or "little").strip().lower()
    if byte_order in {"little", "<"}:
        dtype = dtype.newbyteorder("<")
    elif byte_order in {"big", ">"}:
        dtype = dtype.newbyteorder(">")
    return dtype


def _read_scalar_field_payload(
    campaign_path: str,
    item_uuid: str = "",
    dataset_name: str = "",
) -> Tuple[bytes, Dict[str, Any]]:
    path = str(campaign_path or "").strip()
    if not path:
        raise ValueError("Missing campaign path for scalar field")
    if not item_uuid and not dataset_name:
        raise ValueError("Missing scalar field item UUID or dataset name")

    where = "d.uuid = ?" if item_uuid else "d.name = ?"
    value = item_uuid or dataset_name
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        has_scalar_table = (
            con.execute("select name from sqlite_master where type = 'table' and name = 'scalar_field'").fetchone()
            is not None
        )
        metadata_select = "sf.metadata as scalar_metadata" if has_scalar_table else "NULL as scalar_metadata"
        metadata_join = "left join scalar_field as sf on sf.datasetid = d.rowid" if has_scalar_table else ""
        row = con.execute(
            f"""
            select
                d.name as dataset_name,
                d.fileformat as fileformat,
                r.keyid as keyid,
                f.compression as file_compression,
                f.data as payload,
                {metadata_select}
            from dataset as d
            join replica as r on r.datasetid = d.rowid
            join repfiles as rf on rf.replicaid = r.rowid
            join file as f on f.fileid = rf.fileid
            {metadata_join}
            where {where}
              and d.deltime = 0
              and r.deltime = 0
              and f.data is not null
            order by r.rowid, f.fileid
            limit 1
            """,
            (value,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Scalar field payload not found: {value}")
        if int(row["keyid"] or 0) > 0:
            raise ValueError("Encrypted scalar field payloads are not supported by this viewer path")

        payload = bytes(row["payload"])
        compression = int(row["file_compression"] or 0)
        if compression == 1:
            payload = zlib.decompress(payload)
        elif compression != 0:
            raise ValueError(f"Unsupported file compression flag for scalar field: {compression}")

        return payload, _json_object_or_empty(row["scalar_metadata"])
    finally:
        con.close()


def _apply_colormap(values: np.ndarray, colormap: str) -> np.ndarray:
    clipped = np.clip(values, 0.0, 1.0)
    stops = _SCALAR_FIELD_COLORMAP_STOPS.get(colormap, _VIRIDIS_STOPS)
    scaled = clipped * (len(stops) - 1)
    lower = np.floor(scaled).astype(np.int32)
    upper = np.clip(lower + 1, 0, len(stops) - 1)
    frac = (scaled - lower)[..., None]
    rgb = stops[lower] * (1.0 - frac) + stops[upper] * frac
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _scalar_field_colormap(render_options: Optional[Dict[str, Any]], metadata: Dict[str, Any]) -> str:
    options = render_options if isinstance(render_options, dict) else {}
    value = str(options.get("colormap", "") or metadata.get("colormap", "") or "viridis").strip().lower()
    value = _SCALAR_FIELD_COLORMAP_ALIASES.get(value, value)
    return value if value in SCALAR_FIELD_COLORMAPS else "viridis"


def _scalar_field_background_rgb(
    render_options: Optional[Dict[str, Any]],
) -> np.ndarray:
    options = render_options if isinstance(render_options, dict) else {}
    background = str(options.get("background", "black") or "black").lower()
    if background == "white":
        return np.array([255, 255, 255], dtype=np.uint8)
    return np.array([0, 0, 0], dtype=np.uint8)


def _scalar_field_render_mode(
    render_options: Optional[Dict[str, Any]],
) -> str:
    options = render_options if isinstance(render_options, dict) else {}
    mode = str(options.get("render_mode", "colormap") or "colormap").lower()
    return mode if mode in SCALAR_FIELD_RENDER_MODES else "colormap"


def scalar_field_contour_levels(
    render_options: Optional[Dict[str, Any]],
    render_min: float,
    render_max: float,
) -> List[float]:
    """Resolve explicit or evenly spaced scalar-field contour levels."""

    options = render_options if isinstance(render_options, dict) else {}
    raw_contours = options.get("contours", {})
    contours = raw_contours if isinstance(raw_contours, dict) else {}
    level_mode = str(
        contours.get("level_mode", "range") or "range"
    ).strip().lower()

    if level_mode == "values":
        raw_values = contours.get("values", [])
        if not isinstance(raw_values, (list, tuple)):
            return []
        values = set()
        for value in raw_values:
            parsed = to_float(value)
            if parsed is not None and math.isfinite(parsed):
                values.add(float(parsed))
        return sorted(values)[:SCALAR_FIELD_MAX_CONTOUR_LEVELS]

    contour_min = to_float(contours.get("min", None))
    contour_max = to_float(contours.get("max", None))
    if contour_min is None or not math.isfinite(contour_min):
        contour_min = float(render_min)
    if contour_max is None or not math.isfinite(contour_max):
        contour_max = float(render_max)
    if contour_min >= contour_max:
        return []

    try:
        count = int(contours.get("count", SCALAR_FIELD_DEFAULT_CONTOUR_COUNT))
    except (TypeError, ValueError):
        count = SCALAR_FIELD_DEFAULT_CONTOUR_COUNT
    count = max(2, min(count, SCALAR_FIELD_MAX_CONTOUR_LEVELS))
    return [
        float(value) for value in np.linspace(contour_min, contour_max, count)
    ]


def _draw_scalar_field_contours(
    image: Image.Image,
    values: np.ndarray,
    levels: List[float],
    render_options: Optional[Dict[str, Any]],
) -> None:
    if not levels or values.shape[0] < 2 or values.shape[1] < 2:
        return

    masked_values = np.ma.masked_invalid(values)
    generator = contourpy.contour_generator(
        z=masked_values,
        name="serial",
        corner_mask=True,
        line_type="Separate",
    )
    options = render_options if isinstance(render_options, dict) else {}
    raw_contours = options.get("contours", {})
    contours = raw_contours if isinstance(raw_contours, dict) else {}
    try:
        parsed_color = ImageColor.getrgb(
            str(contours.get("color", "#ffffff") or "#ffffff")
        )
        line_color = tuple(parsed_color[:3])
    except (TypeError, ValueError):
        line_color = (255, 255, 255)
    draw = ImageDraw.Draw(image)

    for level in levels:
        for line in generator.lines(float(level)):
            if len(line) < 2:
                continue
            points = [(float(point[0]), float(point[1])) for point in line]
            draw.line(points, fill=line_color, width=1, joint="curve")


def _scalar_field_render_range(
    values: np.ndarray,
    finite: np.ndarray,
    metadata: Dict[str, Any],
    render_options: Optional[Dict[str, Any]],
) -> Tuple[float, float]:
    options = render_options if isinstance(render_options, dict) else {}
    range_mode = str(options.get("range_mode", "auto") or "auto").strip().lower()
    if range_mode == "manual":
        manual_min, manual_max = valid_extrema(
            to_float(options.get("min", None)),
            to_float(options.get("max", None)),
        )
        if manual_min is not None and manual_max is not None and manual_min < manual_max:
            return float(manual_min), float(manual_max)

    fmin, fmax = valid_extrema(to_float(metadata.get("min", None)), to_float(metadata.get("max", None)))
    if fmin is not None and fmax is not None:
        return float(fmin), float(fmax)

    finite_values = values[finite]
    return float(np.min(finite_values)), float(np.max(finite_values))


def scalar_field_to_png_bytes(
    payload: bytes,
    metadata: Dict[str, Any],
    render_options: Optional[Dict[str, Any]] = None,
) -> bytes:
    if str(metadata.get("kind", "") or "") != "scalarField":
        raise ValueError("Scalar field metadata.kind must be 'scalarField'")
    if str(metadata.get("encoding", "raw") or "raw").lower() != "raw":
        raise ValueError("Only raw scalar field encoding is supported")
    if str(metadata.get("compression", "none") or "none").lower() != "none":
        raise ValueError("Only compression='none' scalar field metadata is supported")
    if str(metadata.get("layout", "row-major") or "row-major").lower() != "row-major":
        raise ValueError("Only row-major scalar field layout is supported")
    if str(metadata.get("value_encoding", "direct") or "direct").lower() != "direct":
        raise ValueError("Only direct scalar field value encoding is supported")

    shape = metadata.get("shape", [])
    if not isinstance(shape, list) or len(shape) != 2:
        raise ValueError("Scalar field metadata.shape must be [height, width]")
    height = int(shape[0])
    width = int(shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("Scalar field shape dimensions must be positive")

    dtype = _scalar_field_dtype(metadata)
    expected = height * width * dtype.itemsize
    if len(payload) != expected:
        raise ValueError(f"Scalar field payload has {len(payload)} bytes; expected {expected}")

    arr = np.frombuffer(payload, dtype=dtype).reshape((height, width))
    values = arr.astype(np.float32, copy=False)
    finite = np.isfinite(values)
    if not np.any(finite):
        raise ValueError("Scalar field contains no finite values")

    fmin, fmax = _scalar_field_render_range(values, finite, metadata, render_options)

    render_mode = _scalar_field_render_mode(render_options)
    if render_mode == "contours":
        rgb = np.empty((*values.shape, 3), dtype=np.uint8)
        rgb[:] = _scalar_field_background_rgb(render_options)
    else:
        if fmax <= fmin:
            normalized = np.zeros_like(values, dtype=np.float32)
        else:
            normalized = (values - float(fmin)) / (float(fmax) - float(fmin))
        normalized = np.where(finite, normalized, 0.0)
        rgb = _apply_colormap(
            normalized,
            _scalar_field_colormap(render_options, metadata),
        )
    rgb[~finite] = _scalar_field_background_rgb(render_options)

    pil = Image.fromarray(rgb, mode="RGB")
    if render_mode in {"contours", "both"}:
        _draw_scalar_field_contours(
            pil,
            values,
            scalar_field_contour_levels(render_options, fmin, fmax),
            render_options,
        )
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


class CampaignDb:
    def __init__(self, collection):
        self.collection = collection
        self.ok = True
        self.last_error = ""
        self._campaign_readers: Dict[str, Any] = {}
        self._source_collection_axis_cache: Dict[
            Tuple[str, str, str, Tuple[str, ...]],
            Tuple[List[float], List[str]],
        ] = {}
        self._campaign_reader_lock = threading.RLock()

        try:
            _ = self.collection.database.client.admin.command("ping")
        except Exception as e:
            self.ok = False
            self.last_error = f"{type(e).__name__}: {e}"

    def close(self) -> None:
        with self._campaign_reader_lock:
            readers = list(self._campaign_readers.values())
            self._campaign_readers.clear()
            self._source_collection_axis_cache.clear()
        for reader in readers:
            close = getattr(reader, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception:
                pass

    @staticmethod
    def _metadata_ndims(metadata: Any) -> Optional[int]:
        if not isinstance(metadata, dict):
            return None

        single_value = metadata.get("SingleValue", None)
        if isinstance(single_value, bool) and single_value:
            return 0
        if isinstance(single_value, str) and single_value.strip().lower() in {"true", "1", "yes"}:
            return 0

        raw_shape = metadata.get("Shape", metadata.get("shape", None))
        if raw_shape is None:
            return None

        text = str(raw_shape).strip()
        if not text:
            return None

        cleaned = text
        for ch in "[]()":
            cleaned = cleaned.replace(ch, "")

        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        if not parts and cleaned:
            parts = [p.strip() for p in cleaned.split() if p.strip()]
        if not parts:
            return None

        dims: List[int] = []
        for p in parts:
            try:
                dims.append(int(float(p)))
            except Exception:
                continue

        if dims:
            if len(dims) == 1 and dims[0] <= 1:
                return 0
            return len(dims)

        return len(parts)

    @staticmethod
    def _metadata_shape(metadata: Any) -> List[int]:
        if not isinstance(metadata, dict):
            return []
        raw_shape = metadata.get("Shape", metadata.get("shape", None))
        if raw_shape is None:
            return []
        if isinstance(raw_shape, (list, tuple)):
            parts = list(raw_shape)
        else:
            text = str(raw_shape).strip()
            for char in "[](){}":
                text = text.replace(char, "")
            parts = [part.strip() for part in text.replace("x", ",").split(",")]
            if len(parts) == 1 and " " in parts[0]:
                parts = parts[0].split()
        shape: List[int] = []
        for part in parts:
            if part in (None, ""):
                continue
            try:
                value = int(float(str(part)))
            except Exception:
                return []
            if value < 0:
                return []
            shape.append(value)
        return shape

    @staticmethod
    def _variable_filter(variable_id: str, variable_type: Optional[str] = None) -> Dict[str, Any]:
        query: Dict[str, Any] = {"variable_id": variable_id}
        if variable_type:
            query["variable_type"] = variable_type
        return query

    @staticmethod
    def _variable_display_path(doc: Dict[str, Any]) -> str:
        variable_id = str(doc.get("variable_id", "") or "").strip("/")
        source_dataset = str(doc.get("source_dataset", "") or "").strip("/")
        if source_dataset and variable_id.startswith(source_dataset + "/"):
            return variable_id[len(source_dataset) + 1 :]
        return variable_id

    @staticmethod
    def _variable_parent_path(display_path: str) -> str:
        parts = [part for part in str(display_path or "").strip("/").split("/") if part]
        if len(parts) <= 1:
            return ""
        return "/".join(parts[:-1])

    @staticmethod
    def _adios_variable_read_path(doc: Dict[str, Any]) -> str:
        variable_id = str(doc.get("variable_id", "") or "").strip("/")
        source_dataset = str(doc.get("source_dataset", "") or "").strip("/")
        variable_path = str(doc.get("variable_path", "") or "").strip("/")

        if variable_id and source_dataset and variable_id.startswith(source_dataset + "/"):
            return variable_id
        if variable_id and source_dataset:
            return f"{source_dataset}/{variable_id}"
        if variable_id:
            return variable_id
        return variable_path

    @staticmethod
    def _metadata_steps_count(metadata: Any) -> int:
        if not isinstance(metadata, dict):
            return 1
        for key in ("AvailableStepsCount", "Steps", "steps"):
            raw = metadata.get(key, None)
            try:
                count = int(float(str(raw).strip()))
            except Exception:
                continue
            if count > 0:
                return count
        return 1

    @classmethod
    def _is_static_scalar_variable_doc(cls, doc: Dict[str, Any]) -> bool:
        if str(doc.get("variable_type", "") or "") != "variable":
            return False
        metadata = doc.get("metadata", {})
        ndims = cls._metadata_ndims(metadata)
        return ndims == 0 and cls._metadata_steps_count(metadata) <= 1

    @staticmethod
    def _plot_source_label(doc: Dict[str, Any]) -> str:
        collection_label = str(doc.get("source_collection_label", "") or "")
        if collection_label:
            return collection_label
        source_dataset = str(doc.get("source_dataset", "") or "")
        if source_dataset:
            return source_dataset
        producer = str(doc.get("producer", "") or "")
        casename = str(doc.get("casename", "") or "")
        file_name = str(doc.get("file", "") or "")
        parts = [p for p in (producer, casename, file_name) if p]
        return " / ".join(parts)

    @staticmethod
    def _file_navigation_label(value: str) -> str:
        label = str(value or "").strip()
        return label[:-3] if label.lower().endswith(".bp") else label

    @classmethod
    def _source_group_for_doc(cls, doc: Dict[str, Any]) -> Tuple[Tuple[str, str, str, str], Dict[str, Any]]:
        source_dataset = "" if doc.get("source_dataset", None) is None else str(doc.get("source_dataset"))
        producer = "" if doc.get("producer", None) is None else str(doc.get("producer"))
        casename = "" if doc.get("casename", None) is None else str(doc.get("casename"))
        file_name = "" if doc.get("file", None) is None else str(doc.get("file"))
        schema_file_group = "" if doc.get("schema_file_group", None) is None else str(doc.get("schema_file_group"))
        schema_mode = "" if doc.get("schema_mode", None) is None else str(doc.get("schema_mode"))
        schema_pattern = "" if doc.get("schema_pattern", None) is None else str(doc.get("schema_pattern"))
        source_collection_id = str(doc.get("source_collection_id", "") or "")
        source_collection_label = str(
            doc.get("source_collection_label", "") or source_collection_id
        )

        if source_collection_id:
            return (
                (
                    "source_collection",
                    str(doc.get("schema_name", "") or ""),
                    schema_file_group,
                    source_collection_id,
                ),
                {
                    "source_dataset": "",
                    "source_label": source_collection_label,
                    "source_collection_id": source_collection_id,
                    "source_collection_label": source_collection_label,
                    "source_collection_mode": str(
                        doc.get("source_collection_mode", "") or ""
                    ),
                    "source_collection_axis": str(
                        doc.get("source_collection_axis", "") or ""
                    ),
                    "source_collection_member_count": doc.get(
                        "source_collection_member_count", None
                    ),
                    "source_collection_total_length": doc.get(
                        "source_collection_total_length", None
                    ),
                    "schema_file_group": schema_file_group,
                    "schema_pattern": schema_pattern,
                    "schema_mode": schema_mode,
                    "schema_num_timesteps": doc.get("schema_num_timesteps", None),
                    "schema_name": str(doc.get("schema_name", "") or ""),
                    "schema_role": str(doc.get("schema_role", "") or ""),
                    "variable_id": str(doc.get("variable_id", "") or ""),
                    "variable_name": str(doc.get("variable_name", "") or ""),
                    "variable_type": str(doc.get("variable_type", "") or ""),
                    "producer": "",
                    "casename": "",
                    "file": "",
                    "visualization_name": str(doc.get("visualization_name", "") or ""),
                    "visualization_kind": str(doc.get("visualization_kind", "") or ""),
                    "visualization_source_dataset": "",
                    "visualization_variables": _list_field(
                        doc.get("visualization_variables", [])
                    ),
                    "visualization_roles": _list_field(
                        doc.get("visualization_roles", [])
                    ),
                    "visualization_sequence_metadata": _dict_field(
                        doc.get("visualization_sequence_metadata", {})
                    ),
                    "visualization_item_metadata": _dict_field(
                        doc.get("visualization_item_metadata", {})
                    ),
                    "activity_provenance": _dict_field(
                        doc.get("activity_provenance", {})
                    ),
                    "association_source": str(doc.get("association_source", "") or ""),
                    "campaign_path": str(doc.get("campaign_path", "") or ""),
                    "variable_location": str(doc.get("variable_location", "") or ""),
                    "variable_path": "",
                    "frame_index": None,
                    "min": None,
                    "max": None,
                    "_files_seen": set(),
                    "_source_datasets_seen": set(),
                },
            )

        if schema_file_group and schema_mode == "file_per_timestep":
            return (
                ("schema_file_group", "", "", schema_file_group),
                {
                    "source_dataset": "",
                    "source_label": cls._file_navigation_label(schema_pattern or schema_file_group),
                    "schema_file_group": schema_file_group,
                    "schema_pattern": schema_pattern,
                    "schema_mode": schema_mode,
                    "schema_num_timesteps": doc.get("schema_num_timesteps", None),
                    "schema_name": "" if doc.get("schema_name", None) is None else str(doc.get("schema_name")),
                    "schema_role": "" if doc.get("schema_role", None) is None else str(doc.get("schema_role")),
                    "variable_id": "" if doc.get("variable_id", None) is None else str(doc.get("variable_id")),
                    "variable_name": "" if doc.get("variable_name", None) is None else str(doc.get("variable_name")),
                    "variable_type": "" if doc.get("variable_type", None) is None else str(doc.get("variable_type")),
                    "producer": "",
                    "casename": "",
                    "file": "",
                    "visualization_name": str(doc.get("visualization_name", "") or ""),
                    "visualization_kind": str(doc.get("visualization_kind", "") or ""),
                    "visualization_source_dataset": "",
                    "visualization_variables": _list_field(
                        doc.get("visualization_variables", [])
                    ),
                    "visualization_roles": _list_field(
                        doc.get("visualization_roles", [])
                    ),
                    "visualization_sequence_metadata": _dict_field(
                        doc.get("visualization_sequence_metadata", {})
                    ),
                    "visualization_item_metadata": _dict_field(
                        doc.get("visualization_item_metadata", {})
                    ),
                    "activity_provenance": _dict_field(
                        doc.get("activity_provenance", {})
                    ),
                    "association_source": str(doc.get("association_source", "") or ""),
                    "campaign_path": str(doc.get("campaign_path", "") or ""),
                    "variable_location": str(doc.get("variable_location", "") or ""),
                    "variable_path": "",
                    "frame_index": None,
                    "min": None,
                    "max": None,
                    "_files_seen": set(),
                    "_source_datasets_seen": set(),
                },
            )

        source_label = source_dataset or file_name or " / ".join(part for part in (producer, casename) if part)
        return (
            ("source_dataset", source_dataset, producer, file_name),
            {
                "source_dataset": source_dataset,
                "source_label": source_label,
                "schema_file_group": schema_file_group,
                "schema_pattern": schema_pattern,
                "schema_mode": schema_mode,
                "schema_num_timesteps": doc.get("schema_num_timesteps", None),
                "schema_name": "" if doc.get("schema_name", None) is None else str(doc.get("schema_name")),
                "schema_role": "" if doc.get("schema_role", None) is None else str(doc.get("schema_role")),
                "variable_id": "" if doc.get("variable_id", None) is None else str(doc.get("variable_id")),
                "variable_name": "" if doc.get("variable_name", None) is None else str(doc.get("variable_name")),
                "variable_type": "" if doc.get("variable_type", None) is None else str(doc.get("variable_type")),
                "producer": producer,
                "casename": casename,
                "file": file_name,
                "visualization_name": str(doc.get("visualization_name", "") or ""),
                "visualization_kind": str(doc.get("visualization_kind", "") or ""),
                "visualization_source_dataset": str(doc.get("visualization_source_dataset", "") or ""),
                "visualization_variables": _list_field(
                    doc.get("visualization_variables", [])
                ),
                "visualization_roles": _list_field(
                    doc.get("visualization_roles", [])
                ),
                "visualization_sequence_metadata": _dict_field(
                    doc.get("visualization_sequence_metadata", {})
                ),
                "visualization_item_metadata": _dict_field(
                    doc.get("visualization_item_metadata", {})
                ),
                "activity_provenance": _dict_field(
                    doc.get("activity_provenance", {})
                ),
                "association_source": str(doc.get("association_source", "") or ""),
                "campaign_path": str(doc.get("campaign_path", "") or ""),
                "variable_location": str(doc.get("variable_location", "") or ""),
                "variable_path": str(doc.get("variable_path", "") or ""),
                "frame_index": doc.get("frame_index", None),
                "min": None,
                "max": None,
                "_files_seen": {file_name} if file_name else set(),
                "_source_datasets_seen": {source_dataset} if source_dataset else set(),
            },
        )

    @staticmethod
    def _update_source_min_max(source: Dict[str, Any], fmin: Optional[float], fmax: Optional[float]) -> None:
        if fmin is not None:
            current_min = source.get("min", None)
            source["min"] = fmin if current_min is None else min(float(current_min), fmin)
        if fmax is not None:
            current_max = source.get("max", None)
            source["max"] = fmax if current_max is None else max(float(current_max), fmax)

    @staticmethod
    def _finalize_sources(grouped: Dict[Tuple[str, str, str, str], Dict[str, Any]]) -> List[Dict[str, Any]]:
        sources: List[Dict[str, Any]] = []
        for source in grouped.values():
            files_seen = source.pop("_files_seen", set())
            datasets_seen = source.pop("_source_datasets_seen", set())
            files = sorted(str(file_name) for file_name in files_seen if str(file_name))
            source_datasets = sorted(str(name) for name in datasets_seen if str(name))
            source["files"] = files
            source["source_datasets"] = source_datasets
            if source.get("source_collection_id"):
                try:
                    total_length = int(
                        source.get("source_collection_total_length", 0) or 0
                    )
                except Exception:
                    total_length = 0
                source["num_timesteps"] = total_length
                try:
                    source["num_partitions"] = int(
                        source.get("source_collection_member_count", 0) or 0
                    )
                except Exception:
                    source["num_partitions"] = len(source_datasets) or len(files)
            elif source.get("schema_mode") == "file_per_timestep":
                try:
                    num_timesteps = int(source.get("schema_num_timesteps", 0) or 0)
                except Exception:
                    num_timesteps = 0
                source["num_timesteps"] = num_timesteps or len(source_datasets) or len(files) or 1
            else:
                source["num_timesteps"] = 1
            sources.append(source)
        sources.sort(key=lambda source: str(source.get("source_label", "")).lower())
        return sources

    @staticmethod
    def _source_restriction_identity(doc: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        source_collection_id = str(doc.get("source_collection_id", "") or "").strip()
        if source_collection_id:
            return ("source_collection", source_collection_id)
        schema_file_group = str(doc.get("schema_file_group", "") or "").strip()
        schema_mode = str(doc.get("schema_mode", "") or "").strip()
        if schema_file_group and schema_mode == "file_per_timestep":
            return ("schema_file_group", schema_file_group)

        source_dataset = str(doc.get("source_dataset", "") or "").strip()
        if source_dataset:
            return ("source_dataset", source_dataset)

        producer = str(doc.get("producer", "") or "").strip()
        casename = str(doc.get("casename", "") or "").strip()
        file_name = str(doc.get("file", "") or "").strip()
        if producer or casename or file_name:
            return ("legacy_source", f"{producer}\0{casename}\0{file_name}")

        return None

    @staticmethod
    def _source_restriction_filter_uses_extrema(filter_doc: Dict[str, Any]) -> bool:
        for key, value in (filter_doc or {}).items():
            if key in {"min", "max"}:
                return True
            if key in {"$and", "$or", "$nor"} and isinstance(value, (list, tuple)):
                if any(
                    isinstance(item, dict)
                    and CampaignDb._source_restriction_filter_uses_extrema(item)
                    for item in value
                ):
                    return True
        return False

    @staticmethod
    def _source_restriction_filter_terms(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, (list, tuple)):
            return []
        return [item for item in value if isinstance(item, dict)]

    @classmethod
    def _source_restriction_candidate_filter(
        cls,
        filter_doc: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return a broad document query for source-level extrema evaluation."""

        if not isinstance(filter_doc, dict):
            return {}

        result: Dict[str, Any] = {}
        for key, value in filter_doc.items():
            if key in {"min", "max"}:
                continue
            if key == "$and":
                parts = [
                    cls._source_restriction_candidate_filter(item)
                    for item in cls._source_restriction_filter_terms(value)
                ]
                parts = [part for part in parts if part]
                if parts:
                    result[key] = parts
                continue
            if key in {"$or", "$nor"}:
                if cls._source_restriction_filter_uses_extrema({key: value}):
                    return {}
                result[key] = cls._source_restriction_filter_terms(value)
                continue
            result[key] = value
        return result

    @staticmethod
    def _source_restriction_doc_extrema(
        doc: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[float]]:
        fmin = to_float(doc.get("min", None))
        fmax = to_float(doc.get("max", None))

        if fmin is None or fmax is None:
            metadata = doc.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            raw_min = metadata.get("Min", doc.get("Min", None))
            raw_max = metadata.get("Max", doc.get("Max", None))
            fmin = to_float(raw_min) if fmin is None else fmin
            fmax = to_float(raw_max) if fmax is None else fmax

        return valid_extrema(fmin, fmax)

    @staticmethod
    def _source_restriction_values_for_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
        variable_name = str(doc.get("variable_name", "") or "").strip()
        variable_id = str(doc.get("variable_id", "") or variable_name)
        if not variable_name and variable_id:
            variable_name = variable_id.strip("/").rsplit("/", 1)[-1]
        source_dataset = str(doc.get("source_dataset", "") or "")
        return {
            "variable_id": variable_id,
            "variable_name": variable_name,
            "variable_type": str(doc.get("variable_type", "") or ""),
            "source_dataset": source_dataset,
            "producer": str(doc.get("producer", "") or ""),
            "casename": str(doc.get("casename", "") or ""),
            "file": str(doc.get("file", "") or ""),
            "visualization_name": str(doc.get("visualization_name", "") or ""),
            "visualization_kind": str(doc.get("visualization_kind", "") or ""),
            "visualization_source_dataset": str(
                doc.get("visualization_source_dataset", "") or source_dataset
            ),
            "association_source": str(doc.get("association_source", "") or ""),
            "variable_path": str(doc.get("variable_path", "") or ""),
            "campaign_path": str(doc.get("campaign_path", "") or ""),
            "variable_location": str(doc.get("variable_location", "") or ""),
            "frame_index": doc.get("frame_index", None),
            "min": None,
            "max": None,
            "_has_variable_extrema": False,
        }

    @staticmethod
    def _source_restriction_merge_doc_values(
        values: Dict[str, Any],
        doc: Dict[str, Any],
    ) -> None:
        for field in (
            "variable_name",
            "source_dataset",
            "producer",
            "casename",
            "file",
            "visualization_name",
            "visualization_kind",
            "visualization_source_dataset",
            "association_source",
            "variable_path",
            "campaign_path",
            "variable_location",
        ):
            if not values.get(field) and doc.get(field):
                values[field] = str(doc.get(field, "") or "")

        variable_type = str(doc.get("variable_type", "") or "")
        if variable_type == "variable" or not values.get("variable_type"):
            values["variable_type"] = variable_type

        if values.get("frame_index", None) is None:
            values["frame_index"] = doc.get("frame_index", None)

        fmin, fmax = CampaignDb._source_restriction_doc_extrema(doc)
        if fmin is None or fmax is None:
            return

        use_variable_extrema = variable_type == "variable"
        if use_variable_extrema and not values.get("_has_variable_extrema"):
            values["min"] = None
            values["max"] = None
            values["_has_variable_extrema"] = True
        elif not use_variable_extrema and values.get("_has_variable_extrema"):
            return

        if fmin is not None:
            current_min = values.get("min", None)
            values["min"] = fmin if current_min is None else min(float(current_min), fmin)
        if fmax is not None:
            current_max = values.get("max", None)
            values["max"] = fmax if current_max is None else max(float(current_max), fmax)

    def _source_restriction_aggregate_identities(
        self,
        source_filter: Dict[str, Any],
        projection: Dict[str, int],
    ) -> Set[Tuple[str, str]]:
        candidate_filter = self._source_restriction_candidate_filter(
            source_filter or {}
        )
        groups: Dict[Tuple[Tuple[str, str], str], Dict[str, Any]] = {}

        for doc in self.collection.find(candidate_filter, projection):
            identity = self._source_restriction_identity(doc)
            if identity is None:
                continue

            variable_id = str(
                doc.get("variable_id", "") or doc.get("variable_name", "") or ""
            )
            key = (identity, variable_id)
            values = groups.setdefault(
                key,
                self._source_restriction_values_for_doc(doc),
            )
            self._source_restriction_merge_doc_values(values, doc)

        identities: Set[Tuple[str, str]] = set()
        for key, values in groups.items():
            if mongo_filter_matches(source_filter or {}, values):
                identity, _variable_id = key
                identities.add(identity)
        return identities

    @staticmethod
    def _source_restriction_filter_from_identities(
        identities: Set[Tuple[str, str]]
    ) -> Dict[str, Any]:
        if not identities:
            return {"_id": {"$in": []}}

        schema_file_groups = sorted(
            value for kind, value in identities if kind == "schema_file_group"
        )
        source_collections = sorted(
            value for kind, value in identities if kind == "source_collection"
        )
        producers = sorted(value for kind, value in identities if kind == "producer")
        source_datasets = sorted(value for kind, value in identities if kind == "source_dataset")
        legacy_sources = sorted(value for kind, value in identities if kind == "legacy_source")

        parts: List[Dict[str, Any]] = []
        if source_collections:
            parts.append({"source_collection_id": {"$in": source_collections}})
        if schema_file_groups:
            parts.append(
                {
                    "schema_file_group": {"$in": schema_file_groups},
                    "schema_mode": "file_per_timestep",
                }
            )
        if producers:
            parts.append({"producer": {"$in": producers}})
        if source_datasets:
            parts.append({"source_dataset": {"$in": source_datasets}})
        for value in legacy_sources:
            producer, casename, file_name = value.split("\0", 2)
            item: Dict[str, Any] = {}
            if producer:
                item["producer"] = producer
            if casename:
                item["casename"] = casename
            if file_name:
                item["file"] = file_name
            if item:
                parts.append(item)

        if not parts:
            return {"_id": {"$in": []}}
        if len(parts) == 1:
            return parts[0]
        return {"$or": parts}

    def source_restriction_summary(
        self,
        source_filters: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not source_filters:
            return {"filter": {}, "count": 0}
        if not self.ok:
            return {"filter": {"_id": {"$in": []}}, "count": 0}

        proj = {
            "_id": 0,
            "variable_id": 1,
            "variable_name": 1,
            "variable_type": 1,
            "source_dataset": 1,
            "producer": 1,
            "casename": 1,
            "file": 1,
            "visualization_name": 1,
            "visualization_kind": 1,
            "visualization_source_dataset": 1,
            "association_source": 1,
            "variable_path": 1,
            "campaign_path": 1,
            "variable_location": 1,
            "frame_index": 1,
            "Min": 1,
            "Max": 1,
            "min": 1,
            "max": 1,
            "metadata": 1,
            "schema_file_group": 1,
            "schema_mode": 1,
            "source_collection_id": 1,
        }

        matched: Optional[Set[Tuple[str, str]]] = None
        try:
            for source_filter in source_filters:
                if self._source_restriction_filter_uses_extrema(
                    source_filter or {}
                ):
                    identities = self._source_restriction_aggregate_identities(
                        source_filter or {},
                        proj,
                    )
                else:
                    identities = set()
                    for doc in self.collection.find(source_filter or {}, proj):
                        identity = self._source_restriction_identity(doc)
                        if identity is not None:
                            identities.add(identity)

                matched = identities if matched is None else matched.intersection(identities)
                if not matched:
                    break

            final_identities = matched or set()
            return {
                "filter": self._source_restriction_filter_from_identities(final_identities),
                "count": len(final_identities),
            }
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return {"filter": {"_id": {"$in": []}}, "count": 0}

    def _classify_variable_group(
        self,
        variable_id: str,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> str:
        vis_names = set(self.distinct_visualization_names_for_variable(variable_id, extra_filter=extra_filter))

        if vis_names.intersection({"heatmap", "contour", "heatmap_contour", "streamlines"}):
            return "2D"
        if vis_names and vis_names.issubset({"timeseries"}):
            return "Scalars"

        query = and_filter(self._variable_filter(variable_id, "variable"), extra_filter)
        try:
            one = self.collection.find_one(query, {"_id": 0, "metadata": 1})
        except Exception:
            one = None
        ndims = self._metadata_ndims((one or {}).get("metadata", {}))
        if ndims is not None:
            return "2D" if ndims >= 2 else "Scalars"

        if "timeseries" in vis_names:
            return "Scalars"
        return "2D"

    def distinct_variables(
        self,
        extra_filter: Optional[Dict[str, Any]] = None,
        only_visualized: bool = False,
    ) -> List[Dict[str, str]]:
        if not self.ok:
            return []
        try:
            image_query = and_filter(
                {
                    "variable_type": {"$in": list(VISUALIZATION_PAYLOAD_VARIABLE_TYPES)},
                    "visualization_name": {"$ne": ""},
                },
                extra_filter,
            )
            queries = [image_query] if only_visualized else [
                and_filter({"variable_type": "variable"}, extra_filter),
                image_query,
            ]
            proj = {
                "_id": 0,
                "variable_id": 1,
                "variable_name": 1,
                "variable_name_physical": 1,
                "variable_path": 1,
                "source_dataset": 1,
                "variable_type": 1,
                "variable_group": 1,
                "variable_group_order": 1,
                "role": 1,
                "display_name": 1,
                "metadata": 1,
            }

            by_id: Dict[str, Dict[str, Any]] = {}
            for query in queries:
                for doc in self.collection.find(query, proj):
                    if self._is_static_scalar_variable_doc(doc):
                        continue

                    variable_id = str(doc.get("variable_id", "") or "").strip()
                    if not variable_id:
                        variable_id = str(doc.get("variable_name", "") or "").strip()
                    if not variable_id or variable_id in by_id:
                        continue

                    name = str(doc.get("variable_name", "") or "").strip()
                    if not name:
                        physical = str(doc.get("variable_name_physical", "") or "").strip("/")
                        name = physical.rsplit("/", 1)[-1] if physical else variable_id.rsplit("/", 1)[-1]
                    label = (
                        str(doc.get("display_name", "") or "").strip() or name
                    )

                    display_path = self._variable_display_path({**doc, "variable_id": variable_id})
                    item: Dict[str, Any] = {
                        "id": variable_id,
                        "name": name,
                        "label": label,
                        "path": display_path,
                        "source_dataset": str(doc.get("source_dataset", "") or ""),
                    }
                    variable_group = str(doc.get("variable_group", "") or "")
                    if variable_group:
                        item["variable_group"] = variable_group
                        item["variable_group_order"] = int(
                            doc.get("variable_group_order", 0) or 0
                        )
                        item["role"] = str(doc.get("role", "") or "")
                    by_id[variable_id] = item

            counts: Dict[str, int] = {}
            for item in by_id.values():
                counts[item["label"]] = counts.get(item["label"], 0) + 1

            variables = list(by_id.values())
            for item in variables:
                if counts.get(item["label"], 0) <= 1:
                    continue
                parent = self._variable_parent_path(item.get("path", ""))
                if parent:
                    item["label"] = f"{item['label']} [{parent}]"

            variables.sort(
                key=lambda item: (
                    item["label"].lower(),
                    item["name"].lower(),
                    item["id"],
                )
            )
            return variables
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return []

    def distinct_variable_names(
        self,
        extra_filter: Optional[Dict[str, Any]] = None,
        only_visualized: bool = False,
    ) -> List[str]:
        return [
            item["id"]
            for item in self.distinct_variables(
                extra_filter=extra_filter,
                only_visualized=only_visualized,
            )
        ]

    def grouped_variable_names(
        self,
        extra_filter: Optional[Dict[str, Any]] = None,
        only_visualized: bool = False,
    ) -> List[Dict[str, Any]]:
        variables = self.distinct_variables(
            extra_filter=extra_filter,
            only_visualized=only_visualized,
        )
        schema_groups: Dict[str, Dict[str, Any]] = {}
        fallback_groups: Dict[str, List[Dict[str, Any]]] = {
            "Scalars": [],
            "2D": [],
        }

        for variable in variables:
            schema_group = str(variable.get("variable_group", "") or "")
            if schema_group:
                group = schema_groups.setdefault(
                    schema_group,
                    {
                        "name": schema_group,
                        "order": int(variable.get("variable_group_order", 0) or 0),
                        "variables": [],
                    },
                )
                group["variables"].append(variable)
                continue

            fallback_group = self._classify_variable_group(
                variable["id"],
                extra_filter=extra_filter,
            )
            if fallback_group not in fallback_groups:
                fallback_group = "2D"
            fallback_groups[fallback_group].append(variable)

        ordered = [
            {
                "name": str(group["name"]),
                "variables": list(group["variables"]),
            }
            for group in sorted(
                schema_groups.values(),
                key=lambda item: (
                    int(item.get("order", 0) or 0),
                    str(item.get("name", "") or ""),
                ),
            )
        ]
        if fallback_groups["Scalars"]:
            ordered.append(
                {"name": "0D", "variables": fallback_groups["Scalars"]}
            )
        if fallback_groups["2D"]:
            ordered.append({"name": "2D", "variables": fallback_groups["2D"]})
        return ordered

    def grouped_variables_by_source_dataset(
        self,
        extra_filter: Optional[Dict[str, Any]] = None,
        only_visualized: bool = False,
    ) -> List[Dict[str, Any]]:
        if not self.ok:
            return []

        try:
            image_query = and_filter(
                {
                    "variable_type": {"$in": list(VISUALIZATION_PAYLOAD_VARIABLE_TYPES)},
                    "visualization_name": {"$ne": ""},
                },
                extra_filter,
            )
            queries = [image_query] if only_visualized else [
                and_filter({"variable_type": "variable"}, extra_filter),
                image_query,
            ]
            projection = {
                "_id": 0,
                "variable_id": 1,
                "variable_name": 1,
                "variable_name_physical": 1,
                "variable_path": 1,
                "source_dataset": 1,
                "producer": 1,
                "casename": 1,
                "file": 1,
                "schema_file_group": 1,
                "schema_mode": 1,
                "schema_pattern": 1,
                "schema_num_timesteps": 1,
                "source_collection_id": 1,
                "source_collection_label": 1,
                "source_collection_member_count": 1,
                "source_collection_total_length": 1,
                "variable_type": 1,
                "display_name": 1,
                "metadata": 1,
            }

            grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
            seen: Set[Tuple[Tuple[str, str], str]] = set()

            for query in queries:
                for doc in self.collection.find(query, projection):
                    if self._is_static_scalar_variable_doc(doc):
                        continue

                    variable_id = str(doc.get("variable_id", "") or "").strip()
                    if not variable_id:
                        variable_id = str(doc.get("variable_name", "") or "").strip()
                    if not variable_id:
                        continue

                    source_dataset = str(doc.get("source_dataset", "") or "").strip()
                    schema_file_group = str(doc.get("schema_file_group", "") or "").strip()
                    schema_mode = str(doc.get("schema_mode", "") or "").strip()
                    schema_pattern = str(doc.get("schema_pattern", "") or "").strip()
                    source_collection_id = str(
                        doc.get("source_collection_id", "") or ""
                    ).strip()
                    source_collection_label = str(
                        doc.get("source_collection_label", "")
                        or source_collection_id
                    ).strip()
                    try:
                        schema_num_timesteps = int(doc.get("schema_num_timesteps", 0) or 0)
                    except Exception:
                        schema_num_timesteps = 0
                    producer = str(doc.get("producer", "") or "").strip()
                    casename = str(doc.get("casename", "") or "").strip()
                    file_name = str(doc.get("file", "") or "").strip()

                    if source_collection_id:
                        source_key = ("source_collection", source_collection_id)
                        source_label = source_collection_label
                        group_source_dataset = ""
                    elif schema_file_group and schema_mode == "file_per_timestep":
                        source_key = ("schema_file_group", schema_file_group)
                        source_label = self._file_navigation_label(
                            schema_pattern or schema_file_group
                        )
                        group_source_dataset = ""
                    elif source_dataset:
                        source_key = ("source_dataset", source_dataset)
                        source_label = self._file_navigation_label(source_dataset)
                        group_source_dataset = source_dataset
                    else:
                        fallback = " / ".join(part for part in (producer, casename, file_name) if part)
                        source_label = self._file_navigation_label(fallback) or "Unknown source"
                        source_key = ("legacy_source", source_label)
                        group_source_dataset = ""

                    group = grouped.setdefault(
                        source_key,
                        {
                            "name": source_label,
                            "source_dataset": group_source_dataset,
                            "variables": [],
                            "_source_files": set(),
                            "_schema_file_count": 0,
                            "source_collection_id": source_collection_id,
                        },
                    )
                    source_file = source_dataset or file_name or source_label
                    if schema_file_group and schema_mode == "file_per_timestep":
                        group["_schema_file_count"] = max(
                            int(group.get("_schema_file_count", 0) or 0),
                            schema_num_timesteps,
                        )
                    elif source_collection_id:
                        group["_schema_file_count"] = max(
                            int(group.get("_schema_file_count", 0) or 0),
                            int(doc.get("source_collection_member_count", 0) or 0),
                        )
                    if source_file and source_file != schema_file_group:
                        group["_source_files"].add(source_file)

                    seen_key = (source_key, variable_id)
                    if seen_key in seen:
                        continue
                    seen.add(seen_key)

                    name = str(doc.get("variable_name", "") or "").strip()
                    if not name:
                        physical = str(doc.get("variable_name_physical", "") or "").strip("/")
                        name = physical.rsplit("/", 1)[-1] if physical else variable_id.rsplit("/", 1)[-1]
                    label = (
                        str(doc.get("display_name", "") or "").strip() or name
                    )

                    group["variables"].append(
                        {
                            "id": variable_id,
                            "name": name,
                            "label": label,
                            "path": self._variable_display_path({**doc, "variable_id": variable_id}),
                            "source_dataset": source_dataset,
                        }
                    )

            groups = list(grouped.values())
            for group in groups:
                source_files = group.pop("_source_files", set())
                schema_file_count = int(group.pop("_schema_file_count", 0) or 0)
                file_count = schema_file_count or len(source_files)
                if file_count > 1:
                    group["file_count"] = file_count
                variables = list(group.get("variables", []) or [])
                counts: Dict[str, int] = {}
                for item in variables:
                    label = str(item.get("label", "") or "")
                    counts[label] = counts.get(label, 0) + 1
                for item in variables:
                    label = str(item.get("label", "") or "")
                    if counts.get(label, 0) <= 1:
                        continue
                    parent = self._variable_parent_path(str(item.get("path", "") or ""))
                    if parent:
                        item["label"] = f"{label} [{parent}]"
                variables.sort(
                    key=lambda item: (
                        str(item.get("label", "")).lower(),
                        str(item.get("name", "")).lower(),
                        str(item.get("id", "")),
                    )
                )
                group["variables"] = variables

            groups.sort(key=lambda group: str(group.get("name", "")).lower())
            return groups
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return []

    def _image_sources_for_variable(
        self,
        variable_id: str,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        base_query: Dict[str, Any] = {
            "variable_id": variable_id,
            "variable_type": {"$in": list(VISUALIZATION_PAYLOAD_VARIABLE_TYPES)},
            "visualization_name": {"$ne": ""},
        }
        query = and_filter(base_query, extra_filter)
        proj = {
            "_id": 0,
            "variable_id": 1,
            "variable_name": 1,
            "variable_type": 1,
            "variable_path": 1,
            "min": 1,
            "max": 1,
            "source_dataset": 1,
            "producer": 1,
            "casename": 1,
            "file": 1,
            "visualization_name": 1,
            "visualization_kind": 1,
            "visualization_source_dataset": 1,
            "visualization_variables": 1,
            "visualization_roles": 1,
            "visualization_sequence_metadata": 1,
            "visualization_item_metadata": 1,
            "association_source": 1,
            "campaign_path": 1,
            "variable_location": 1,
            "frame_index": 1,
            "schema_name": 1,
            "schema_file_group": 1,
            "schema_pattern": 1,
            "schema_role": 1,
            "schema_mode": 1,
            "schema_num_timesteps": 1,
            "source_collection_id": 1,
            "source_collection_label": 1,
            "source_collection_mode": 1,
            "source_collection_axis": 1,
            "source_collection_member_count": 1,
            "source_collection_total_length": 1,
        }

        cursor = self.collection.find(query, proj).sort(
            [("source_dataset", 1), ("producer", 1), ("casename", 1), ("file", 1)]
        )
        grouped: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        for doc in cursor:
            key, source = self._source_group_for_doc(doc)
            entry = grouped.setdefault(key, source)
            file_name = "" if doc.get("file", None) is None else str(doc.get("file"))
            source_dataset = "" if doc.get("source_dataset", None) is None else str(doc.get("source_dataset"))
            if file_name:
                entry.setdefault("_files_seen", set()).add(file_name)
            if source_dataset:
                entry.setdefault("_source_datasets_seen", set()).add(source_dataset)
            self._update_source_min_max(entry, to_float(doc.get("min", None)), to_float(doc.get("max", None)))
        return self._finalize_sources(grouped)

    def source_for_visualization(
        self,
        variable_id: str,
        visualization_name: str,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return one local source that provides a stored visualization."""

        if not self.ok or not variable_id or not visualization_name:
            return {}
        try:
            visualization_filter = {"visualization_name": visualization_name}
            query = (
                and_filter(extra_filter, visualization_filter)
                if extra_filter
                else visualization_filter
            )
            sources = self._image_sources_for_variable(
                variable_id,
                extra_filter=query,
            )
            return dict(sources[0]) if sources else {}
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return {}

    def distinct_visualization_names_for_variable(
        self,
        variable_id: str,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        if not self.ok or not variable_id:
            return []
        try:
            base_query: Dict[str, Any] = {
                "variable_id": variable_id,
                "variable_type": {"$in": list(VISUALIZATION_PAYLOAD_VARIABLE_TYPES)},
                "visualization_name": {"$ne": ""},
            }
            query = and_filter(base_query, extra_filter)
            names = self.collection.distinct("visualization_name", query)
            names = [n for n in names if isinstance(n, str) and n]
            names.sort()
            return names
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return []

    def scalar_plot_candidate(
        self,
        variable_id: str,
        source_filter: Optional[Dict[str, Any]] = None,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.ok or not variable_id:
            return {}

        base_query = self._variable_filter(variable_id, "variable")
        query = and_filter(base_query, source_filter) if source_filter else base_query
        query = and_filter(query, extra_filter)
        proj = {
            "_id": 0,
            "campaign_path": 1,
            "file": 1,
            "variable_id": 1,
            "variable_name": 1,
            "display_name": 1,
            "variable_name_physical": 1,
            "variable_path": 1,
            "source_dataset": 1,
            "producer": 1,
            "casename": 1,
            "schema_file_group": 1,
            "schema_mode": 1,
            "time_source": 1,
            "time_values": 1,
            "axes": 1,
            "dimension_axes": 1,
            "plot_x_axis": 1,
            "selection_axis": 1,
            "schema_default_axis": 1,
            "source_collection_id": 1,
            "source_collection_label": 1,
            "source_collection_mode": 1,
            "source_collection_axis": 1,
            "source_collection_member_index": 1,
            "source_collection_member_count": 1,
            "source_collection_offset": 1,
            "source_collection_length": 1,
            "source_collection_total_length": 1,
            "source_collection_partition_value": 1,
            "source_collection_partition_label": 1,
            "metadata": 1,
            "min": 1,
            "max": 1,
        }

        try:
            doc = self.collection.find_one(query, proj, sort=[("source_dataset", 1), ("_id", 1)])
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return {}

        if not doc:
            return {}

        metadata = doc.get("metadata", {})
        ndims = self._metadata_ndims(metadata)
        axes = doc.get("axes", {})
        if not isinstance(axes, dict):
            axes = {}
        plot_x_axis = str(doc.get("plot_x_axis", "") or "")
        selection_axis = str(doc.get("selection_axis", "") or "")
        is_axis_selected_waveform = (
            ndims == 2
            and plot_x_axis in axes
            and selection_axis in axes
            and plot_x_axis != selection_axis
        )
        if ndims is None or (ndims > 1 and not is_axis_selected_waveform):
            return {}

        read_path = self._adios_variable_read_path(doc)
        if not read_path:
            return {}

        source_fields = {
            "source_dataset": str(doc.get("source_dataset", "") or ""),
            "source_collection_id": str(
                doc.get("source_collection_id", "") or ""
            ),
            "schema_file_group": str(doc.get("schema_file_group", "") or ""),
            "schema_mode": str(doc.get("schema_mode", "") or ""),
            "producer": str(doc.get("producer", "") or ""),
            "casename": str(doc.get("casename", "") or ""),
            "file": str(doc.get("file", "") or ""),
        }
        source_filter_out: Dict[str, str] = {"variable_id": variable_id}
        if source_fields["source_collection_id"]:
            source_filter_out["source_collection_id"] = source_fields[
                "source_collection_id"
            ]
        elif source_fields["schema_file_group"] and source_fields["schema_mode"] == "file_per_timestep":
            source_filter_out["schema_file_group"] = source_fields["schema_file_group"]
            source_filter_out["schema_mode"] = source_fields["schema_mode"]
        elif source_fields["source_dataset"]:
            source_filter_out["source_dataset"] = source_fields["source_dataset"]
        else:
            for key in ("producer", "casename", "file"):
                if source_fields[key]:
                    source_filter_out[key] = source_fields[key]

        return {
            "variable_id": variable_id,
            "variable_name": str(doc.get("variable_name", "") or variable_id),
            "display_name": str(doc.get("display_name", "") or ""),
            "variable_path": read_path,
            "metadata": metadata,
            "source_fields": source_fields,
            "source_filter": source_filter_out,
            "source_label": self._plot_source_label(doc),
            "time_source": str(doc.get("time_source", "") or ""),
            "time_values": doc.get("time_values", []),
            "axes": axes,
            "dimension_axes": list(doc.get("dimension_axes", []) or []),
            "plot_x_axis": plot_x_axis,
            "selection_axis": selection_axis,
            "schema_default_axis": str(doc.get("schema_default_axis", "") or ""),
            "source_collection_id": str(
                doc.get("source_collection_id", "") or ""
            ),
            "source_collection_label": str(
                doc.get("source_collection_label", "") or ""
            ),
            "source_collection_mode": str(
                doc.get("source_collection_mode", "") or ""
            ),
            "source_collection_axis": str(
                doc.get("source_collection_axis", "") or ""
            ),
            "source_collection_member_index": int(
                doc.get("source_collection_member_index", 0) or 0
            ),
            "source_collection_member_count": int(
                doc.get("source_collection_member_count", 0) or 0
            ),
            "source_collection_offset": int(
                doc.get("source_collection_offset", 0) or 0
            ),
            "source_collection_length": int(
                doc.get("source_collection_length", 0) or 0
            ),
            "source_collection_total_length": int(
                doc.get("source_collection_total_length", 0) or 0
            ),
            "source_collection_partition_value": doc.get(
                "source_collection_partition_value", None
            ),
            "source_collection_partition_label": str(
                doc.get("source_collection_partition_label", "") or ""
            ),
            "min": doc.get("min", None),
            "max": doc.get("max", None),
        }

    @staticmethod
    def _draw_line_plot_png(
        x_values: Any,
        y_values: Any,
        title: str,
        x_label: str,
        y_label: str,
        width: int = 900,
        height: int = 750,
    ) -> bytes:
        return CampaignDb._draw_multi_line_plot_png(
            [(x_values, y_values)],
            title,
            x_label,
            y_label,
            width=width,
            height=height,
        )

    @staticmethod
    def _draw_multi_line_plot_png(
        series_values: List[Tuple[Any, Any]],
        title: str,
        x_label: str,
        y_label: str,
        width: int = 900,
        height: int = 750,
    ) -> bytes:
        series: List[Tuple[np.ndarray, np.ndarray]] = []
        for x_values, y_values in series_values:
            x = np.asarray(x_values, dtype=float).reshape(-1)
            y = np.asarray(y_values, dtype=float).reshape(-1)
            n = min(int(x.size), int(y.size))
            if n <= 0:
                continue
            x = x[:n]
            y = y[:n]
            mask = np.isfinite(x) & np.isfinite(y)
            x = x[mask]
            y = y[mask]
            if x.size > 0:
                series.append((x, y))
        if not series:
            raise ValueError("No finite values available for plot")

        width = max(360, int(width))
        height = max(300, int(height))
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        label_font = CampaignDb._plot_font(28)
        tick_font = CampaignDb._plot_font(26)

        left = 106
        right = 38
        top = 72
        bottom = 96
        plot_w = max(1, width - left - right)
        plot_h = max(1, height - top - bottom)

        all_x = np.concatenate([x for x, _ in series])
        all_y = np.concatenate([y for _, y in series])
        xmin = float(np.min(all_x))
        xmax = float(np.max(all_x))
        ymin = float(np.min(all_y))
        ymax = float(np.max(all_y))
        if math.isclose(xmin, xmax):
            xmin -= 0.5
            xmax += 0.5
        if math.isclose(ymin, ymax):
            pad = abs(ymin) * 0.05 if ymin else 1.0
            ymin -= pad
            ymax += pad
        else:
            pad = (ymax - ymin) * 0.06
            ymin -= pad
            ymax += pad

        def sx(value: float) -> float:
            return left + ((float(value) - xmin) / (xmax - xmin)) * plot_w

        def sy(value: float) -> float:
            return top + plot_h - ((float(value) - ymin) / (ymax - ymin)) * plot_h

        def fit_text(text: str, font: Any, max_width: float) -> str:
            text = str(text or "")
            if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
                return text
            ellipsis = "..."
            while text and draw.textbbox((0, 0), text + ellipsis, font=font)[2] > max_width:
                text = text[:-1]
            return text + ellipsis if text else ellipsis

        draw.rectangle([left, top, left + plot_w, top + plot_h], outline="#3f3f3f", width=2)
        for i in range(5):
            frac = i / 4.0
            gx = left + frac * plot_w
            gy = top + frac * plot_h
            draw.line([(gx, top), (gx, top + plot_h)], fill="#eeeeee", width=2)
            draw.line([(left, gy), (left + plot_w, gy)], fill="#eeeeee", width=2)

            xv = xmin + frac * (xmax - xmin)
            yv = ymax - frac * (ymax - ymin)
            x_text = f"{xv:.3g}"
            y_text = f"{yv:.3g}"
            x_bbox = draw.textbbox((0, 0), x_text, font=tick_font)
            y_bbox = draw.textbbox((0, 0), y_text, font=tick_font)
            draw.text(
                (gx - (x_bbox[2] - x_bbox[0]) / 2, top + plot_h + 14),
                x_text,
                fill="#333333",
                font=tick_font,
            )
            draw.text(
                (left - 16 - (y_bbox[2] - y_bbox[0]), gy - (y_bbox[3] - y_bbox[1]) / 2),
                y_text,
                fill="#333333",
                font=tick_font,
            )

        colors = (
            "#1565c0",
            "#c62828",
            "#2e7d32",
            "#ef6c00",
            "#6a1b9a",
            "#00838f",
            "#ad1457",
            "#5d4037",
        )
        for series_index, (x, y) in enumerate(series):
            color = colors[series_index % len(colors)]
            points = [(sx(xv), sy(yv)) for xv, yv in zip(x, y)]
            if len(points) == 1:
                px, py = points[0]
                draw.ellipse([px - 5, py - 5, px + 5, py + 5], fill=color)
            else:
                draw.line(points, fill=color, width=5 if len(series) > 1 else 6)
                for px, py in points[:: max(1, len(points) // 60)]:
                    draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=color)

        source_line = fit_text(title, label_font, plot_w)
        if source_line:
            draw.text((left, 24), source_line, fill="#555555", font=label_font)
        x_bbox = draw.textbbox((0, 0), x_label, font=label_font)
        draw.text(
            (left + plot_w / 2 - (x_bbox[2] - x_bbox[0]) / 2, height - 46),
            x_label,
            fill="#333333",
            font=label_font,
        )

        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    @staticmethod
    def _plot_font(size: int):
        for path in (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=size)
        except Exception:
            return ImageFont.load_default()

    @staticmethod
    def _plot_timeline_values(sample_count: int, explicit_time_values: Any = None) -> Tuple[np.ndarray, str]:
        steps = np.arange(max(0, int(sample_count)), dtype=float)
        if not isinstance(explicit_time_values, (list, tuple, np.ndarray)):
            return steps, "step"

        try:
            times = np.asarray(explicit_time_values, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            return steps, "step"

        if times.size != steps.size or not np.all(np.isfinite(times)):
            return steps, "step"
        return times, "time"

    @staticmethod
    def _plot_axis_label(axis: Any, fallback: str = "x") -> str:
        if not isinstance(axis, dict):
            return str(fallback or "x")
        label = str(axis.get("label", "") or fallback or "x")
        unit = str(axis.get("unit", "") or "").strip()
        return f"{label} ({unit})" if unit else label

    @staticmethod
    def _plot_axis_values(axis: Any) -> Optional[np.ndarray]:
        if not isinstance(axis, dict):
            return None
        raw_values = axis.get("values", None)
        if not isinstance(raw_values, (list, tuple, np.ndarray)):
            return None
        try:
            values = np.asarray(raw_values, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            return None
        return values if np.all(np.isfinite(values)) else None

    @staticmethod
    def _read_selected_array_row(
        fr: FileReader,
        variable_path: str,
        shape: List[int],
        selection_index: int,
    ) -> np.ndarray:
        if len(shape) != 2 or min(shape) <= 0:
            raise ValueError(
                f"Axis-selected plots require a non-empty rank-2 array: {shape}"
            )
        index = max(0, min(int(selection_index), shape[0] - 1))
        raw = np.asarray(
            fr.read(
                variable_path,
                start=[index, 0],
                count=[1, shape[1]],
            ),
            dtype=float,
        )
        if raw.ndim >= 2 and raw.shape[0] == shape[0] and shape[0] > 1:
            raw = raw[index]
        return raw.reshape(-1)

    @staticmethod
    def _read_plot_axis_values(
        fr: FileReader,
        axis: Dict[str, Any],
        selection_index: int,
    ) -> np.ndarray:
        cached = CampaignDb._plot_axis_values(axis)
        if cached is not None:
            return cached
        variable_path = str(axis.get("variable_path", "") or "")
        if not variable_path:
            raise ValueError("Plot axis has no coordinate variable path")
        raw_shape = axis.get("shape", [])
        shape = [int(value) for value in raw_shape] if isinstance(raw_shape, list) else []
        if len(shape) == 1:
            return np.asarray(fr.read(variable_path), dtype=float).reshape(-1)
        if len(shape) == 2:
            return CampaignDb._read_selected_array_row(
                fr,
                variable_path,
                shape,
                selection_index,
            )
        raise ValueError(
            f"Plot axis coordinate must be rank 1 or 2, got shape {shape}"
        )

    @staticmethod
    def _read_plot_series(
        campaign_path: str,
        variable_path: str,
        metadata: Any,
        explicit_time_values: Any = None,
        axes: Any = None,
        plot_x_axis: str = "",
        selection_axis: str = "",
        selection_index: int = 0,
    ) -> Tuple[np.ndarray, np.ndarray, str]:
        with FileReader(campaign_path) as fr:
            return CampaignDb._read_plot_series_from_reader(
                fr,
                variable_path,
                metadata,
                explicit_time_values,
                axes,
                plot_x_axis,
                selection_axis,
                selection_index,
            )

    @staticmethod
    def _read_plot_series_from_reader(
        fr: FileReader,
        variable_path: str,
        metadata: Any,
        explicit_time_values: Any = None,
        axes: Any = None,
        plot_x_axis: str = "",
        selection_axis: str = "",
        selection_index: int = 0,
    ) -> Tuple[np.ndarray, np.ndarray, str]:
        steps_count = CampaignDb._metadata_steps_count(metadata)
        ndims = CampaignDb._metadata_ndims(metadata)
        axis_descriptors = axes if isinstance(axes, dict) else {}
        plot_axis = axis_descriptors.get(str(plot_x_axis or ""), {})
        if ndims == 2 and plot_axis and selection_axis:
            shape = CampaignDb._metadata_shape(metadata)
            y = CampaignDb._read_selected_array_row(
                fr,
                variable_path,
                shape,
                selection_index,
            )
            x = CampaignDb._read_plot_axis_values(
                fr,
                dict(plot_axis),
                selection_index,
            )
            if x.size != y.size:
                raise ValueError(
                    f"Plot axis has {x.size} values but selected data row has "
                    f"{y.size} values"
                )
            return x, y, CampaignDb._plot_axis_label(plot_axis)

        kwargs = {"step_selection": [0, steps_count]} if steps_count > 1 else {}
        y_raw = np.asarray(fr.read(variable_path, **kwargs), dtype=float)

        if ndims == 0:
            y = y_raw.reshape(-1)
            x, x_label = CampaignDb._plot_timeline_values(
                y.size,
                explicit_time_values,
            )
            return x, y, x_label

        if ndims == 1:
            y = y_raw.reshape(-1)
            axis_values = CampaignDb._plot_axis_values(plot_axis)
            if axis_values is not None and axis_values.size == y.size:
                return (
                    axis_values,
                    y,
                    CampaignDb._plot_axis_label(plot_axis),
                )
            x, x_label = CampaignDb._plot_timeline_values(
                y.size,
                explicit_time_values,
            )
            return x, y, x_label

        if y_raw.ndim >= 2:
            y = np.asarray(y_raw[-1], dtype=float).reshape(-1)
        else:
            y = y_raw.reshape(-1)
        x = np.arange(y.size, dtype=float)
        return x, y, "index"

    def _read_plot_series_cached(
        self,
        campaign_path: str,
        variable_path: str,
        metadata: Any,
        explicit_time_values: Any = None,
        axes: Any = None,
        plot_x_axis: str = "",
        selection_axis: str = "",
        selection_index: int = 0,
    ) -> Tuple[np.ndarray, np.ndarray, str]:
        path = str(campaign_path or "")
        with self._campaign_reader_lock:
            reader = self._campaign_readers.get(path)
            if reader is None:
                reader = FileReader(path)
                self._campaign_readers[path] = reader
            return self._read_plot_series_from_reader(
                reader,
                variable_path,
                metadata,
                explicit_time_values,
                axes,
                plot_x_axis,
                selection_axis,
                selection_index,
            )

    @staticmethod
    def _axis_tile_fields(
        candidate: Dict[str, Any],
        selection_index: int,
    ) -> Dict[str, Any]:
        axes = candidate.get("axes", {})
        if not isinstance(axes, dict) or not axes:
            return {}
        selection_axis_name = str(candidate.get("selection_axis", "") or "")
        plot_axis_name = str(candidate.get("plot_x_axis", "") or "")
        selection_axis = axes.get(selection_axis_name, {})
        plot_axis = axes.get(plot_axis_name, {})
        if not isinstance(selection_axis, dict):
            selection_axis = {}
        if not isinstance(plot_axis, dict):
            plot_axis = {}

        result: Dict[str, Any] = {
            "axes": axes,
            "dimension_axes": list(candidate.get("dimension_axes", []) or []),
            "plot_x_axis": plot_axis_name,
            "plot_axis_key": str(plot_axis.get("key", "") or ""),
            "schema_default_axis": str(
                candidate.get("schema_default_axis", "") or ""
            ),
        }
        if selection_axis:
            descriptor = dict(selection_axis)
            descriptor["default"] = bool(
                selection_axis_name
                and selection_axis_name
                == str(candidate.get("schema_default_axis", "") or "")
            )
            values = descriptor.get("values", [])
            if isinstance(values, list) and values:
                index = max(0, min(int(selection_index), len(values) - 1))
                descriptor["index"] = index
                descriptor["value"] = values[index]
            result["selection_axis"] = descriptor
        return result

    @staticmethod
    def _clean_plot_series(x_values: Any, y_values: Any) -> Tuple[np.ndarray, np.ndarray]:
        x = np.asarray(x_values, dtype=float).reshape(-1)
        y = np.asarray(y_values, dtype=float).reshape(-1)
        n = min(int(x.size), int(y.size))
        if n <= 0:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        x = x[:n]
        y = y[:n]
        mask = np.isfinite(x) & np.isfinite(y)
        return x[mask], y[mask]

    @staticmethod
    def _plot1d_payload(series_values: List[Dict[str, Any]], x_label: str, y_label: str) -> Dict[str, Any]:
        colors = (
            "#1565c0",
            "#c62828",
            "#2e7d32",
            "#ef6c00",
            "#6a1b9a",
            "#00838f",
            "#ad1457",
            "#5d4037",
        )
        series: List[Dict[str, Any]] = []
        all_x: List[np.ndarray] = []
        all_y: List[np.ndarray] = []

        for i, item in enumerate(series_values):
            x, y = CampaignDb._clean_plot_series(item.get("x", []), item.get("y", []))
            if x.size <= 0:
                continue
            all_x.append(x)
            all_y.append(y)
            series.append(
                {
                    "x": [float(v) for v in x],
                    "y": [float(v) for v in y],
                    "source_label": str(item.get("source_label", "") or ""),
                    "source_key": str(item.get("source_key", "") or ""),
                    "color": colors[(len(series)) % len(colors)],
                    **(
                        {
                            "breaks": [
                                int(value)
                                for value in item.get("breaks", []) or []
                                if 0 < int(value) < int(x.size)
                            ]
                        }
                        if item.get("breaks")
                        else {}
                    ),
                    **(
                        {
                            "point_label_ranges": [
                                dict(value)
                                for value in item.get("point_label_ranges", []) or []
                                if isinstance(value, dict)
                            ]
                        }
                        if item.get("point_label_ranges")
                        else {}
                    ),
                }
            )

        if not series:
            raise ValueError("No finite values available for plot")

        x_values = np.concatenate(all_x)
        y_values = np.concatenate(all_y)
        xmin = float(np.min(x_values))
        xmax = float(np.max(x_values))
        ymin = float(np.min(y_values))
        ymax = float(np.max(y_values))

        x_axis_min = xmin
        x_axis_max = xmax
        if math.isclose(x_axis_min, x_axis_max):
            x_axis_min -= 0.5
            x_axis_max += 0.5

        y_axis_min = ymin
        y_axis_max = ymax
        if math.isclose(y_axis_min, y_axis_max):
            pad = abs(y_axis_min) * 0.05 if y_axis_min else 1.0
            y_axis_min -= pad
            y_axis_max += pad
        else:
            pad = (y_axis_max - y_axis_min) * 0.06
            y_axis_min -= pad
            y_axis_max += pad

        return {
            "x_label": str(x_label or "x"),
            "y_label": str(y_label or ""),
            "x_min": x_axis_min,
            "x_max": x_axis_max,
            "y_min": y_axis_min,
            "y_max": y_axis_max,
            "data_x_min": xmin,
            "data_x_max": xmax,
            "data_y_min": ymin,
            "data_y_max": ymax,
            "series": series,
        }

    def _source_collection_plot_candidates(
        self,
        variable_id: str,
        source_filter: Dict[str, Any],
        extra_filter: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        collection_id = str(source_filter.get("source_collection_id", "") or "")
        if not collection_id:
            return []
        query = and_filter(
            self._variable_filter(variable_id, "variable"),
            source_filter,
        )
        query = and_filter(query, extra_filter)
        projection = {
            "_id": 0,
            "source_dataset": 1,
            "source_collection_member_index": 1,
        }
        docs = list(self.collection.find(query, projection))
        docs.sort(
            key=lambda doc: (
                int(doc.get("source_collection_member_index", 0) or 0),
                str(doc.get("source_dataset", "") or ""),
            )
        )
        candidates: List[Dict[str, Any]] = []
        for doc in docs:
            source_dataset = str(doc.get("source_dataset", "") or "")
            if not source_dataset:
                continue
            candidate = self.scalar_plot_candidate(
                variable_id,
                source_filter={"source_dataset": source_dataset},
                extra_filter=extra_filter,
            )
            if (
                candidate
                and str(candidate.get("source_collection_id", "") or "")
                == collection_id
            ):
                candidates.append(candidate)
        return candidates

    def _source_collection_members_for_candidate(
        self,
        candidate: Dict[str, Any],
        fallback_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        collection_id = str(candidate.get("source_collection_id", "") or "")
        selection_axis_name = str(candidate.get("selection_axis", "") or "")
        selection_axis = dict(
            (candidate.get("axes", {}) or {}).get(selection_axis_name, {}) or {}
        )
        coordinate_variable = str(selection_axis.get("variable", "") or "").strip("/")
        docs: List[Dict[str, Any]] = []
        if collection_id and coordinate_variable:
            docs = list(
                self.collection.find(
                    {
                        "variable_id": coordinate_variable,
                        "variable_type": "variable",
                        "source_collection_id": collection_id,
                    },
                    {
                        "_id": 0,
                        "source_dataset": 1,
                        "source_collection_member_index": 1,
                        "source_collection_offset": 1,
                        "source_collection_length": 1,
                        "source_collection_partition_value": 1,
                        "source_collection_partition_label": 1,
                    },
                )
            )

        if not docs:
            for item in fallback_candidates or [candidate]:
                source_fields = dict(item.get("source_fields", {}) or {})
                docs.append(
                    {
                        "source_dataset": str(
                            source_fields.get("source_dataset", "") or ""
                        ),
                        "source_collection_member_index": item.get(
                            "source_collection_member_index", 0
                        ),
                        "source_collection_offset": item.get(
                            "source_collection_offset", 0
                        ),
                        "source_collection_length": item.get(
                            "source_collection_length", 0
                        ),
                        "source_collection_partition_value": item.get(
                            "source_collection_partition_value", None
                        ),
                        "source_collection_partition_label": item.get(
                            "source_collection_partition_label", ""
                        ),
                    }
                )

        members: List[Dict[str, Any]] = []
        seen = set()
        for doc in docs:
            source_dataset = str(doc.get("source_dataset", "") or "")
            if not source_dataset or source_dataset in seen:
                continue
            seen.add(source_dataset)
            members.append(
                {
                    "source_dataset": source_dataset,
                    "member_index": int(
                        doc.get("source_collection_member_index", 0) or 0
                    ),
                    "offset": int(
                        doc.get("source_collection_offset", 0) or 0
                    ),
                    "length": int(
                        doc.get("source_collection_length", 0) or 0
                    ),
                    "partition_value": doc.get(
                        "source_collection_partition_value", None
                    ),
                    "partition_label": str(
                        doc.get("source_collection_partition_label", "") or ""
                    ),
                }
            )
        members.sort(
            key=lambda item: (
                int(item.get("member_index", 0) or 0),
                str(item.get("source_dataset", "") or ""),
            )
        )
        return members

    def _source_collection_axis_values(
        self,
        campaign_path: str,
        candidate: Dict[str, Any],
        members: List[Dict[str, Any]],
    ) -> Tuple[List[float], List[str]]:
        selection_axis_name = str(candidate.get("selection_axis", "") or "")
        selection_axis = dict(
            (candidate.get("axes", {}) or {}).get(selection_axis_name, {}) or {}
        )
        coordinate_variable = str(selection_axis.get("variable", "") or "").strip("/")
        collection_id = str(candidate.get("source_collection_id", "") or "")
        member_names = tuple(
            str(member.get("source_dataset", "") or "") for member in members
        )
        cache_key = (
            str(campaign_path or ""),
            collection_id,
            coordinate_variable,
            member_names,
        )
        with self._campaign_reader_lock:
            cached = self._source_collection_axis_cache.get(cache_key)
            if cached is not None:
                return list(cached[0]), list(cached[1])

            reader = self._campaign_readers.get(str(campaign_path or ""))
            if reader is None:
                reader = FileReader(campaign_path)
                self._campaign_readers[str(campaign_path or "")] = reader

            coordinates: List[float] = []
            labels: List[str] = []
            axis_label = str(selection_axis.get("label", "") or "Selection")
            total_length = sum(
                int(member.get("length", 0) or 0) for member in members
            )
            for member in members:
                source_dataset = str(member.get("source_dataset", "") or "").strip("/")
                expected_length = int(member.get("length", 0) or 0)
                if not source_dataset or not coordinate_variable:
                    raise ValueError(
                        f"Source collection {collection_id!r} has no coordinate variable"
                    )
                path = f"{source_dataset}/{coordinate_variable}"
                values = np.asarray(reader.read(path), dtype=float).reshape(-1)
                if int(values.size) != expected_length:
                    raise ValueError(
                        f"Source collection {collection_id!r} member "
                        f"{source_dataset!r} has {values.size} axis values; "
                        f"expected {expected_length}"
                    )
                partition_label = str(member.get("partition_label", "") or source_dataset)
                for value in values:
                    coordinate = float(value)
                    coordinates.append(coordinate)
                    value_label = (
                        str(int(coordinate))
                        if coordinate.is_integer()
                        else f"{coordinate:g}"
                    )
                    labels.append(
                        f"{len(coordinates)} / {total_length} · "
                        f"{partition_label} · {axis_label} {value_label}"
                    )

            cached_value = (list(coordinates), list(labels))
            self._source_collection_axis_cache[cache_key] = cached_value
            return coordinates, labels

    @staticmethod
    def _source_collection_member_for_index(
        members: List[Dict[str, Any]],
        selection_index: int,
    ) -> Tuple[Dict[str, Any], int]:
        for member in members:
            offset = int(member.get("offset", 0) or 0)
            length = int(member.get("length", 0) or 0)
            if offset <= selection_index < offset + length:
                return member, selection_index - offset
        raise ValueError(
            f"Collection selection index {selection_index} is outside the available range"
        )

    def _source_collection_axis_fields(
        self,
        campaign_path: str,
        candidate: Dict[str, Any],
        members: List[Dict[str, Any]],
        selection_index: int,
    ) -> Dict[str, Any]:
        fields = self._axis_tile_fields(candidate, 0)
        selection_axis_name = str(candidate.get("selection_axis", "") or "")
        axes = dict(fields.get("axes", {}) or {})
        descriptor = dict(axes.get(selection_axis_name, {}) or {})
        coordinates, labels = self._source_collection_axis_values(
            campaign_path,
            candidate,
            members,
        )
        values = [float(index) for index in range(len(coordinates))]
        index = max(0, min(int(selection_index), max(0, len(values) - 1)))
        descriptor.update(
            {
                "values": values,
                "labels": labels,
                "index": index,
                "value": values[index] if values else 0.0,
                "coordinate_value": coordinates[index] if coordinates else None,
                "collection_total_length": len(values),
            }
        )
        axes[selection_axis_name] = descriptor
        fields["axes"] = axes
        fields["selection_axis"] = descriptor
        if str(candidate.get("plot_x_axis", "") or "") == selection_axis_name:
            fields["plot_axis_key"] = str(descriptor.get("key", "") or "")
        return fields

    def _get_source_collection_plot_tile(
        self,
        campaign_path: str,
        variable_id: str,
        source_filter: Dict[str, Any],
        extra_filter: Optional[Dict[str, Any]],
        selection_index: int,
    ) -> Dict[str, Any]:
        candidates = self._source_collection_plot_candidates(
            variable_id,
            source_filter,
            extra_filter,
        )
        if not candidates:
            return {}

        first = candidates[0]
        members = self._source_collection_members_for_candidate(
            first,
            fallback_candidates=candidates,
        )
        if not members:
            return {}
        total_length = sum(int(member.get("length", 0) or 0) for member in members)
        selection_index = max(0, min(int(selection_index), max(0, total_length - 1)))
        by_dataset = {
            str(candidate.get("source_fields", {}).get("source_dataset", "") or ""): candidate
            for candidate in candidates
        }
        selected = first
        series_values: List[Dict[str, Any]] = []
        x_label = "Collection position"
        collection_id = str(first.get("source_collection_id", "") or "")
        collection_label = str(
            first.get("source_collection_label", "") or collection_id
        )
        selection_axis_name = str(first.get("selection_axis", "") or "")
        plot_axis_name = str(first.get("plot_x_axis", "") or "")
        ndims = self._metadata_ndims(first.get("metadata", {}))

        if ndims == 2 and selection_axis_name and plot_axis_name != selection_axis_name:
            member, local_index = self._source_collection_member_for_index(
                members,
                selection_index,
            )
            source_dataset = str(member.get("source_dataset", "") or "")
            selected = by_dataset.get(source_dataset, {})
            if not selected:
                raise ValueError(
                    f"{variable_id} is unavailable for "
                    f"{member.get('partition_label', source_dataset)}"
                )
            x, y, x_label = self._read_plot_series_cached(
                campaign_path,
                str(selected.get("variable_path", "") or ""),
                selected.get("metadata", {}),
                selected.get("time_values", []),
                selected.get("axes", {}),
                str(selected.get("plot_x_axis", "") or ""),
                str(selected.get("selection_axis", "") or ""),
                local_index,
            )
            series_values.append(
                {
                    "x": x,
                    "y": y,
                    "source_label": str(member.get("partition_label", "") or ""),
                }
            )
        else:
            selection_axis = dict(
                (first.get("axes", {}) or {}).get(selection_axis_name, {}) or {}
            )
            axis_label = str(selection_axis.get("label", "") or "Selection")
            x_label = f"{axis_label} sequence"
            collection_x: List[float] = []
            collection_y: List[float] = []
            collection_point_label_ranges: List[Dict[str, Any]] = []
            collection_breaks: List[int] = []
            for member in members:
                source_dataset = str(member.get("source_dataset", "") or "")
                candidate = by_dataset.get(source_dataset)
                if not candidate:
                    continue
                _local_x, y, _local_label = self._read_plot_series_cached(
                    campaign_path,
                    str(candidate.get("variable_path", "") or ""),
                    candidate.get("metadata", {}),
                    candidate.get("time_values", []),
                    candidate.get("axes", {}),
                    str(candidate.get("plot_x_axis", "") or ""),
                    str(candidate.get("selection_axis", "") or ""),
                    0,
                )
                values = np.asarray(y, dtype=float).reshape(-1)
                length = min(int(member.get("length", 0) or 0), int(values.size))
                offset = int(member.get("offset", 0) or 0)
                segment_x, segment_y = self._clean_plot_series(
                    np.arange(offset, offset + length, dtype=float),
                    values[:length],
                )
                if not segment_x.size:
                    continue
                if collection_x:
                    collection_breaks.append(len(collection_x))
                partition_label = str(
                    member.get("partition_label", "") or source_dataset
                )
                label_start = len(collection_x)
                collection_x.extend(float(value) for value in segment_x)
                collection_y.extend(float(value) for value in segment_y)
                collection_point_label_ranges.append(
                    {
                        "start": label_start,
                        "end": len(collection_x),
                        "label": partition_label,
                    }
                )
            if collection_x:
                series_values.append(
                    {
                        "x": collection_x,
                        "y": collection_y,
                        "source_label": collection_label,
                        "breaks": collection_breaks,
                        "point_label_ranges": collection_point_label_ranges,
                    }
                )

        variable_name = str(selected.get("variable_name", "") or variable_id)
        display_name = str(selected.get("display_name", "") or variable_name)
        plot = self._plot1d_payload(series_values, x_label, display_name)
        plot_axis = dict(
            (selected.get("axes", {}) or {}).get(
                str(selected.get("plot_x_axis", "") or ""),
                {},
            )
            or {}
        )
        if plot_axis:
            plot["x_axis_key"] = str(plot_axis.get("key", "") or "")

        tile = {
            "variable_name": display_name,
            "display_title": display_name,
            "variable_id": variable_id,
            "visualization_name": GENERATED_SCALAR_PLOT_VIS,
            "selected_visualization": GENERATED_SCALAR_PLOT_VIS,
            "visualization_options": [GENERATED_SCALAR_PLOT_VIS],
            "source_dataset": "",
            "source_collection_id": collection_id,
            "source_collection_label": collection_label,
            "producer": "",
            "casename": "",
            "file": "",
            "src": "",
            "media_type": "plot1d",
            "plot": plot,
            "status": "ok",
            "note": (
                f"generated collection plot ({len(members)} "
                f"partition{'s' if len(members) != 1 else ''})"
            ),
            "source_count": 1,
        }
        tile.update(
            self._source_collection_axis_fields(
                campaign_path,
                selected,
                members,
                selection_index,
            )
        )
        return tile

    def get_or_create_generated_scalar_plot_tile(
        self,
        campaign_path: str,
        variable_id: str,
        source_filter: Optional[Dict[str, Any]] = None,
        extra_filter: Optional[Dict[str, Any]] = None,
        selection_index: int = 0,
    ) -> Dict[str, Any]:
        if source_filter and source_filter.get("source_collection_id"):
            return self._get_source_collection_plot_tile(
                campaign_path,
                variable_id,
                dict(source_filter),
                extra_filter,
                selection_index,
            )
        candidate = self.scalar_plot_candidate(variable_id, source_filter=source_filter, extra_filter=extra_filter)
        if not candidate:
            return {}

        source_fields = dict(candidate.get("source_fields", {}) or {})
        x, y, x_label = self._read_plot_series_cached(
            campaign_path,
            str(candidate.get("variable_path", "") or ""),
            candidate.get("metadata", {}),
            candidate.get("time_values", []),
            candidate.get("axes", {}),
            str(candidate.get("plot_x_axis", "") or ""),
            str(candidate.get("selection_axis", "") or ""),
            selection_index,
        )
        variable_name = str(candidate.get("variable_name", "") or variable_id)
        display_name = str(candidate.get("display_name", "") or variable_name)
        plot = self._plot1d_payload(
            [
                {
                    "x": x,
                    "y": y,
                    "source_label": str(candidate.get("source_label", "") or ""),
                }
            ],
            x_label,
            display_name,
        )
        plot_axis = dict(
            (candidate.get("axes", {}) or {}).get(
                str(candidate.get("plot_x_axis", "") or ""),
                {},
            )
            or {}
        )
        if plot_axis:
            plot["x_axis_key"] = str(plot_axis.get("key", "") or "")

        tile = {
            "variable_name": display_name,
            "display_title": display_name,
            "variable_id": variable_id,
            "visualization_name": GENERATED_SCALAR_PLOT_VIS,
            "selected_visualization": GENERATED_SCALAR_PLOT_VIS,
            "visualization_options": [GENERATED_SCALAR_PLOT_VIS],
            "source_dataset": str(source_fields.get("source_dataset", "") or ""),
            "producer": str(source_fields.get("producer", "") or ""),
            "casename": str(source_fields.get("casename", "") or ""),
            "file": str(source_fields.get("file", "") or ""),
            "src": "",
            "media_type": "plot1d",
            "plot": plot,
            "status": "ok",
            "note": "generated scalar plot",
            "source_count": 1,
        }
        tile.update(self._axis_tile_fields(candidate, selection_index))
        return tile

    def get_generated_scalar_plot_tile_for_sources(
        self,
        campaign_path: str,
        variable_id: str,
        source_filters: List[Dict[str, Any]],
        extra_filter: Optional[Dict[str, Any]] = None,
        selection_index: int = 0,
    ) -> Dict[str, Any]:
        if not source_filters:
            return {}
        collection_filters = [
            source_filter
            for source_filter in source_filters
            if source_filter.get("source_collection_id")
        ]
        if collection_filters:
            if len(source_filters) == 1:
                return self._get_source_collection_plot_tile(
                    campaign_path,
                    variable_id,
                    dict(collection_filters[0]),
                    extra_filter,
                    selection_index,
                )
            raise ValueError(
                "Source collections have independent selection axes and cannot "
                "be combined into one synchronized plot"
            )

        candidates: List[Dict[str, Any]] = []
        series: List[Dict[str, Any]] = []
        x_labels: List[str] = []
        seen = set()

        for source_filter in source_filters:
            candidate = self.scalar_plot_candidate(
                variable_id,
                source_filter=source_filter or None,
                extra_filter=extra_filter,
            )
            if not candidate:
                continue

            source_fields = dict(candidate.get("source_fields", {}) or {})
            key = (
                str(candidate.get("variable_path", "") or ""),
                str(source_fields.get("source_dataset", "") or ""),
                str(source_fields.get("producer", "") or ""),
                str(source_fields.get("casename", "") or ""),
                str(source_fields.get("file", "") or ""),
            )
            if key in seen:
                continue
            seen.add(key)

            try:
                x, y, x_label = self._read_plot_series_cached(
                    campaign_path,
                    str(candidate.get("variable_path", "") or ""),
                    candidate.get("metadata", {}),
                    candidate.get("time_values", []),
                    candidate.get("axes", {}),
                    str(candidate.get("plot_x_axis", "") or ""),
                    str(candidate.get("selection_axis", "") or ""),
                    selection_index,
                )
            except Exception:
                continue

            candidates.append(candidate)
            series.append(
                {
                    "x": x,
                    "y": y,
                    "source_label": str(candidate.get("source_label", "") or ""),
                }
            )
            x_labels.append(str(x_label or ""))

        if not candidates or not series:
            return {}

        selection_axis_keys = {
            str(
                ((candidate.get("axes", {}) or {}).get(
                    str(candidate.get("selection_axis", "") or ""),
                    {},
                ) or {}).get("key", "")
                or ""
            )
            for candidate in candidates
        }
        selection_axis_keys.discard("")
        if len(selection_axis_keys) > 1:
            raise ValueError(
                "Cannot combine sources with incompatible selection axes"
            )
        plot_axis_keys = {
            str(
                ((candidate.get("axes", {}) or {}).get(
                    str(candidate.get("plot_x_axis", "") or ""),
                    {},
                ) or {}).get("key", "")
                or ""
            )
            for candidate in candidates
        }
        plot_axis_keys.discard("")
        if len(plot_axis_keys) > 1:
            raise ValueError("Cannot combine sources with incompatible plot axes")

        x_label_values = {label for label in x_labels if label}
        x_label = x_labels[0] if len(x_label_values) <= 1 else "x"
        first = candidates[0]
        first_source_fields = dict(first.get("source_fields", {}) or {})
        variable_name = str(first.get("variable_name", "") or variable_id)
        display_name = str(first.get("display_name", "") or variable_name)
        plot = self._plot1d_payload(
            series,
            x_label,
            display_name,
        )
        first_plot_axis = dict(
            (first.get("axes", {}) or {}).get(
                str(first.get("plot_x_axis", "") or ""),
                {},
            )
            or {}
        )
        if first_plot_axis:
            plot["x_axis_key"] = str(first_plot_axis.get("key", "") or "")

        tile = {
            "variable_name": display_name,
            "display_title": display_name,
            "variable_id": variable_id,
            "visualization_name": GENERATED_SCALAR_PLOT_VIS,
            "selected_visualization": GENERATED_SCALAR_PLOT_VIS,
            "visualization_options": [GENERATED_SCALAR_PLOT_VIS],
            "source_dataset": str(first_source_fields.get("source_dataset", "") or ""),
            "producer": str(first_source_fields.get("producer", "") or ""),
            "casename": str(first_source_fields.get("casename", "") or ""),
            "file": str(first_source_fields.get("file", "") or ""),
            "src": "",
            "media_type": "plot1d",
            "plot": plot,
            "status": "ok",
            "note": f"generated scalar plot ({len(series)} source{'s' if len(series) != 1 else ''})",
            "source_count": len(series),
        }
        tile.update(self._axis_tile_fields(first, selection_index))
        return tile

    @staticmethod
    def _representation_shape(metadata: Any) -> str:
        if not isinstance(metadata, dict):
            return ""

        grid = metadata.get("grid", {})
        if not isinstance(grid, dict):
            grid = {}
        raw_shape = grid.get(
            "shape",
            metadata.get("shape", metadata.get("Shape", "")),
        )
        if isinstance(raw_shape, (list, tuple)):
            return " × ".join(str(value) for value in raw_shape)

        shape = str(raw_shape or "").strip().strip("[]()")
        if not shape:
            return ""
        parts = [
            part.strip()
            for part in shape.replace("×", ",").replace("x", ",").split(",")
            if part.strip()
        ]
        return " × ".join(parts) if len(parts) > 1 else shape

    @staticmethod
    def _representation_axes(metadata: Any) -> str:
        if not isinstance(metadata, dict):
            return ""

        grid = metadata.get("grid", {})
        if not isinstance(grid, dict):
            grid = {}
        axes = grid.get("axes", metadata.get("axes", []))
        if isinstance(axes, (list, tuple)):
            labels = [str(axis).strip() for axis in axes if str(axis).strip()]
            if labels:
                return " × ".join(labels)

        column_axis = str(grid.get("column_axis", "") or "").strip()
        row_axis = str(grid.get("row_axis", "") or "").strip()
        return " × ".join(axis for axis in (column_axis, row_axis) if axis)

    @staticmethod
    def _representation_statistics(
        mins: List[float],
        maxs: List[float],
    ) -> Dict[str, Optional[float]]:
        if not mins or not maxs:
            return {
                "global_min": None,
                "global_max": None,
                "mean_min": None,
                "mean_max": None,
                "median_min": None,
                "median_max": None,
            }
        return {
            "global_min": min(mins),
            "global_max": max(maxs),
            "mean_min": statistics.fmean(mins),
            "mean_max": statistics.fmean(maxs),
            "median_min": statistics.median(mins),
            "median_max": statistics.median(maxs),
        }

    def _source_representation_summary(
        self,
        source_docs: List[Dict[str, Any]],
        mins: List[float],
        maxs: List[float],
        num_sources: int,
    ) -> Dict[str, Any]:
        if not source_docs:
            return {}

        metadata = next(
            (
                doc.get("metadata", {})
                for doc in source_docs
                if isinstance(doc.get("metadata", {}), dict)
            ),
            {},
        )
        data_model = next(
            (
                str(doc.get("data_model", "") or "").strip()
                for doc in source_docs
                if str(doc.get("data_model", "") or "").strip()
            ),
            "",
        )
        if not data_model and isinstance(metadata, dict):
            data_model = str(metadata.get("data_model", "") or "").strip()

        num_frames = 0
        for doc in source_docs:
            doc_metadata = doc.get("metadata", {})
            schema_num_timesteps = to_float(
                doc.get("schema_num_timesteps", None)
            )
            schema_frames = (
                int(schema_num_timesteps)
                if schema_num_timesteps is not None
                and math.isfinite(schema_num_timesteps)
                else 0
            )
            num_frames = max(
                num_frames,
                self._metadata_steps_count(doc_metadata),
                schema_frames,
            )

        result: Dict[str, Any] = {
            "id": "source",
            "label": (
                "Source coefficients"
                if "coefficient" in data_model.lower()
                else "Source data"
            ),
            "kind": "source",
            "data_model": data_model,
            "shape": self._representation_shape(metadata),
            "axes": self._representation_axes(metadata),
            "num_frames": num_frames,
            "num_sources": num_sources,
        }
        result.update(self._representation_statistics(mins, maxs))
        return result

    def _derived_representation_summaries(
        self,
        variable_id: str,
        extra_filter: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        query = and_filter(
            self._variable_filter(variable_id, SCALAR_FIELD_VARIABLE_TYPE),
            extra_filter,
        )
        projection = {
            "_id": 0,
            "source_dataset": 1,
            "producer": 1,
            "casename": 1,
            "file": 1,
            "visualization_name": 1,
            "scalar_field_metadata": 1,
            "min": 1,
            "max": 1,
            "frame_index": 1,
        }
        groups: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

        for doc in self.collection.find(query, projection):
            metadata = doc.get("scalar_field_metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            visualization_name = str(doc.get("visualization_name", "") or "")
            data_model = str(metadata.get("data_model", "") or "")
            shape = self._representation_shape(metadata)
            axes = self._representation_axes(metadata)
            key = (visualization_name, data_model, shape, axes)
            group = groups.setdefault(
                key,
                {
                    "id": visualization_name or data_model or "derived-scalar-field",
                    "label": "Derived scalar field",
                    "kind": "derived",
                    "data_model": data_model,
                    "source_data_model": str(
                        metadata.get("source_data_model", "") or ""
                    ),
                    "shape": shape,
                    "axes": axes,
                    "_mins": [],
                    "_maxs": [],
                    "_frames_by_source": {},
                },
            )

            fmin, fmax = valid_extrema(
                to_float(doc.get("min", metadata.get("min", None))),
                to_float(doc.get("max", metadata.get("max", None))),
            )
            if fmin is not None and fmax is not None:
                group["_mins"].append(fmin)
                group["_maxs"].append(fmax)

            source_key = (
                str(doc.get("source_dataset", "") or ""),
                str(doc.get("producer", "") or ""),
                str(doc.get("casename", "") or ""),
                str(doc.get("file", "") or ""),
            )
            frames = group["_frames_by_source"].setdefault(source_key, set())
            frames.add(doc.get("frame_index", len(frames)))

        summaries: List[Dict[str, Any]] = []
        multiple = len(groups) > 1
        for key in sorted(groups):
            group = groups[key]
            frames_by_source = group.pop("_frames_by_source")
            mins = group.pop("_mins")
            maxs = group.pop("_maxs")
            group["num_sources"] = len(frames_by_source)
            group["num_frames"] = max(
                (len(frames) for frames in frames_by_source.values()),
                default=0,
            )
            if multiple and key[0]:
                group["label"] = f"Derived scalar field ({key[0]})"
            group.update(self._representation_statistics(mins, maxs))
            summaries.append(group)
        return summaries

    def variable_min_max_summary(
        self,
        variable_id: str,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.ok or not variable_id:
            return {}

        base_query = self._variable_filter(variable_id, "variable")
        query = and_filter(base_query, extra_filter)

        proj = {
            "_id": 0,
            "variable_id": 1,
            "source_dataset": 1,
            "producer": 1,
            "casename": 1,
            "file": 1,
            "variable_name": 1,
            "variable_type": 1,
            "variable_name_physical": 1,
            "variable_path": 1,
            "campaign_path": 1,
            "variable_location": 1,
            "metadata": 1,
            "activity_provenance": 1,
            "Min": 1,
            "Max": 1,
            "min": 1,
            "max": 1,
            "schema_name": 1,
            "schema_file_group": 1,
            "schema_pattern": 1,
            "schema_role": 1,
            "schema_mode": 1,
            "schema_num_timesteps": 1,
            "source_collection_id": 1,
            "source_collection_label": 1,
            "source_collection_mode": 1,
            "source_collection_axis": 1,
            "source_collection_member_count": 1,
            "source_collection_total_length": 1,
            "data_model": 1,
        }

        try:
            source_docs = list(self.collection.find(query, proj))

            mins: List[float] = []
            maxs: List[float] = []
            num_docs = 0
            source_groups: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

            for doc in source_docs:
                num_docs += 1

                fmin = to_float(doc.get("min", None))
                fmax = to_float(doc.get("max", None))

                if fmin is None or fmax is None:
                    md = doc.get("metadata", {})
                    if not isinstance(md, dict):
                        md = {}
                    raw_min = md.get("Min", doc.get("Min", None))
                    raw_max = md.get("Max", doc.get("Max", None))
                    fmin = to_float(raw_min) if fmin is None else fmin
                    fmax = to_float(raw_max) if fmax is None else fmax

                fmin, fmax = valid_extrema(fmin, fmax)
                if (fmin is not None) and (fmax is not None):
                    mins.append(fmin)
                    maxs.append(fmax)

                key, source = self._source_group_for_doc(doc)
                entry = source_groups.setdefault(key, source)
                file_name = "" if doc.get("file", None) is None else str(doc.get("file"))
                source_dataset = "" if doc.get("source_dataset", None) is None else str(doc.get("source_dataset"))
                if file_name:
                    entry.setdefault("_files_seen", set()).add(file_name)
                if source_dataset:
                    entry.setdefault("_source_datasets_seen", set()).add(source_dataset)
                self._update_source_min_max(entry, fmin, fmax)

            valid = len(mins)
            sources = self._finalize_sources(source_groups)
            source_representation = self._source_representation_summary(
                source_docs,
                mins,
                maxs,
                len(sources),
            )
            derived_representations = self._derived_representation_summaries(
                variable_id,
                extra_filter,
            )

            # Stage 2 support: if this variable has no ADIOS variable docs, but does
            # have visualization payload docs, return those source rows so the
            # viewer can still browse visualizations.
            if num_docs == 0:
                image_sources = self._image_sources_for_variable(variable_id, extra_filter=extra_filter)
                image_mins: List[float] = []
                image_maxs: List[float] = []
                for source in image_sources:
                    fmin, fmax = valid_extrema(to_float(source.get("min", None)), to_float(source.get("max", None)))
                    if fmin is not None and fmax is not None:
                        image_mins.append(fmin)
                        image_maxs.append(fmax)
                image_valid = len(image_mins)
                return {
                    "variable": variable_id,
                    "num_sources": len(image_sources),
                    "global_min": min(image_mins) if image_valid else None,
                    "global_max": max(image_maxs) if image_valid else None,
                    "mean_min": statistics.fmean(image_mins) if image_valid else None,
                    "mean_max": statistics.fmean(image_maxs) if image_valid else None,
                    "median_min": statistics.median(image_mins) if image_valid else None,
                    "median_max": statistics.median(image_maxs) if image_valid else None,
                    "sources": image_sources,
                    "derived_representations": derived_representations,
                }

            return {
                "variable": variable_id,
                "num_sources": len(sources),
                "global_min": min(mins) if valid else None,
                "global_max": max(maxs) if valid else None,
                "mean_min": statistics.fmean(mins) if valid else None,
                "mean_max": statistics.fmean(maxs) if valid else None,
                "median_min": statistics.median(mins) if valid else None,
                "median_max": statistics.median(maxs) if valid else None,
                "sources": sources,
                "source_representation": source_representation,
                "derived_representations": derived_representations,
            }

        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return {}

    def get_movie_frames_for_stream(
        self,
        variable_id: str,
        visualization_name: str,
        producer: str,
        casename: str,
        file: str = "",
        source_dataset: str = "",
        extra_filter: Optional[Dict[str, Any]] = None,
        limit_frames: int = 240,
        scalar_field_options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[bytes], int, List[int], List[Any], str]:
        if not self.ok or not variable_id:
            return ([], 0, [], [], "timestep")

        base_query: Dict[str, Any] = {
            "variable_id": variable_id,
            "variable_type": {"$in": list(VISUALIZATION_PAYLOAD_VARIABLE_TYPES)},
            "visualization_name": visualization_name,
        }
        if source_dataset:
            base_query["source_dataset"] = source_dataset
        elif producer or casename or file:
            base_query["producer"] = producer
            base_query["casename"] = casename
            if file:
                base_query["file"] = file

        query = and_filter(base_query, extra_filter)

        proj = {
            "_id": 1,
            "campaign_path": 1,
            "variable_path": 1,
            "variable_type": 1,
            "image_bytes": 1,
            "frame_index": 1,
            "time_index": 1,
            "physical_time": 1,
            "axes": 1,
            "selection_axis": 1,
            "scalar_field_metadata": 1,
            "visualization_item_uuid": 1,
        }

        try:
            total = int(self.collection.count_documents(query))
            cursor = (
                self.collection.find(query, proj)
                .sort([("frame_index", 1), ("_id", 1)])
            )
            docs = list(cursor)

            selection_axis_values: List[Any] = []
            if docs:
                first_axes = docs[0].get("axes", {})
                selection_axis_name = str(docs[0].get("selection_axis", "") or "")
                if isinstance(first_axes, dict):
                    first_axis = first_axes.get(selection_axis_name, {})
                    if isinstance(first_axis, dict) and isinstance(
                        first_axis.get("values", []), list
                    ):
                        selection_axis_values = list(first_axis.get("values", []))

            frames: List[bytes] = []
            frame_indices: List[int] = []
            time_values: List[Any] = []
            has_physical_time = False
            seen_frame_indices: Set[int] = set()

            def append_frame(png_bytes: bytes, doc: Dict[str, Any]) -> None:
                nonlocal has_physical_time
                frames.append(png_bytes)
                try:
                    frame_index = int(doc.get("frame_index", len(frame_indices)))
                except Exception:
                    frame_index = len(frame_indices)
                frame_indices.append(frame_index)

                physical_time = to_float(doc.get("physical_time", None))
                if physical_time is not None:
                    time_values.append(physical_time)
                    has_physical_time = True
                    return

                time_index = doc.get("time_index", None)
                try:
                    time_values.append(int(time_index))
                    return
                except Exception:
                    pass
                time_values.append(frame_index)

            with ExitStack() as stack:
                readers: Dict[str, Any] = {}
                for doc in docs:
                    try:
                        frame_index = int(doc.get("frame_index", len(frames)))
                    except Exception:
                        frame_index = len(frames)
                    if frame_index in seen_frame_indices:
                        continue

                    img = doc.get("image_bytes", None)
                    if img:
                        try:
                            append_frame(bytes(img), doc)
                            seen_frame_indices.add(frame_index)
                            if len(frames) >= int(limit_frames):
                                break
                        except Exception:
                            continue
                        continue

                    campaign_path = str(
                        doc.get("campaign_path", "")
                        or getattr(self.collection, "campaign_path", "")
                        or ""
                    ).strip()
                    variable_path = str(doc.get("variable_path", "") or "").strip()
                    if not campaign_path or not variable_path:
                        continue

                    try:
                        if str(doc.get("variable_type", "") or "") == SCALAR_FIELD_VARIABLE_TYPE:
                            payload, stored_metadata = _read_scalar_field_payload(
                                campaign_path,
                                item_uuid=str(doc.get("visualization_item_uuid", "") or ""),
                                dataset_name=variable_path,
                            )
                            doc_metadata = dict(doc.get("scalar_field_metadata", {}) or {})
                            metadata = {**stored_metadata, **doc_metadata}
                            append_frame(
                                scalar_field_to_png_bytes(payload, metadata, scalar_field_options),
                                doc,
                            )
                            seen_frame_indices.add(frame_index)
                            if len(frames) >= int(limit_frames):
                                break
                            continue

                        reader = readers.get(campaign_path)
                        if reader is None:
                            reader = stack.enter_context(FileReader(campaign_path))
                            readers[campaign_path] = reader
                        append_frame(adios_image_to_png_bytes(reader.read(variable_path)), doc)
                        seen_frame_indices.add(frame_index)
                        if len(frames) >= int(limit_frames):
                            break
                    except Exception:
                        continue

            if selection_axis_values and len(selection_axis_values) >= len(frames):
                time_values = selection_axis_values[: len(frames)]
                has_physical_time = True

            return (
                frames,
                len(frames) if frames else total,
                frame_indices,
                time_values,
                "physical_time" if has_physical_time else "timestep",
            )

        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return ([], 0, [], [], "timestep")

    def get_first_movie_tiles_for_variable(
        self,
        variable_id: str,
        extra_filter: Optional[Dict[str, Any]] = None,
        limit: int = 4,
        limit_frames: int = 240,
        fps: int = 24,
        scalar_field_options: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.ok or not variable_id:
            return []

        base_query: Dict[str, Any] = {
            "variable_id": variable_id,
            "variable_type": {"$in": list(VISUALIZATION_PAYLOAD_VARIABLE_TYPES)},
            "visualization_name": {"$ne": ""},
        }
        query = and_filter(base_query, extra_filter)

        proj = {
            "_id": 1,
            "source_dataset": 1,
            "schema_file_group": 1,
            "schema_mode": 1,
            "schema_name": 1,
            "schema_role": 1,
            "variable_id": 1,
            "variable_name": 1,
            "producer": 1,
            "casename": 1,
            "file": 1,
            "visualization_name": 1,
            "variable_type": 1,
            "payload_type": 1,
            "visualization_item_type": 1,
            "scalar_field_metadata": 1,
            "visualization_kind": 1,
            "visualization_variables": 1,
            "visualization_roles": 1,
            "visualization_sequence_metadata": 1,
            "visualization_item_metadata": 1,
            "min": 1,
            "max": 1,
            "axes": 1,
            "dimension_axes": 1,
            "plot_x_axis": 1,
            "selection_axis": 1,
            "schema_default_axis": 1,
        }

        try:
            cursor = self.collection.find(query, proj).sort([("_id", 1)])

            seen = set()
            tiles: List[Dict[str, Any]] = []

            for doc in cursor:
                vis = str(doc.get("visualization_name", "") or "")
                source_dataset = str(doc.get("source_dataset", "") or "")
                schema_file_group = str(doc.get("schema_file_group", "") or "")
                schema_mode = str(doc.get("schema_mode", "") or "")
                producer = str(doc.get("producer", "") or "")
                casename = str(doc.get("casename", "") or "")
                file = str(doc.get("file", "") or "")

                if not vis:
                    continue

                key = (
                    (vis, "schema", schema_file_group)
                    if schema_file_group and schema_mode == "file_per_timestep"
                    else ((vis, source_dataset) if source_dataset else (vis, producer, casename, file))
                )
                if key in seen:
                    continue
                seen.add(key)

                grouped_schema_source = bool(schema_file_group and schema_mode == "file_per_timestep")
                frames, total, frame_indices, time_values, time_mode = self.get_movie_frames_for_stream(
                    variable_id,
                    visualization_name=vis,
                    producer="" if grouped_schema_source else producer,
                    casename="" if grouped_schema_source else casename,
                    file="" if grouped_schema_source else file,
                    source_dataset="" if grouped_schema_source else source_dataset,
                    extra_filter=extra_filter,
                    limit_frames=limit_frames,
                    scalar_field_options=scalar_field_options,
                )

                src = ""
                media_type = "video"
                status = "ok"
                note = ""
                frame_count = len(frames)
                frame_sources: List[str] = []

                if not frames:
                    status = "no-frames"
                    note = "no frames"
                elif len(frames) == 1:
                    src = png_bytes_to_data_uri(frames[0])
                    frame_sources = [src]
                    media_type = "image"
                    note = "1 frame (rendered as image)"
                else:
                    frame_sources = [png_bytes_to_data_uri(frame) for frame in frames]
                    src = frame_sources[0] if frame_sources else ""
                    media_type = "image_sequence"
                    note = f"{len(frames)} of {total} frames" if total > len(frames) else f"{len(frames)} frames"

                tile = {
                        "variable_name": str(doc.get("variable_name", "") or variable_id),
                        "variable_id": variable_id,
                        "visualization_name": vis,
                        "source_dataset": source_dataset,
                        "schema_name": str(doc.get("schema_name", "") or ""),
                        "schema_file_group": schema_file_group,
                        "schema_role": str(doc.get("schema_role", "") or ""),
                        "schema_mode": schema_mode,
                        "producer": producer,
                        "casename": casename,
                        "file": file,
                        "min": doc.get("min", None),
                        "max": doc.get("max", None),
                        "variable_type": str(doc.get("variable_type", "") or ""),
                        "payload_type": str(doc.get("payload_type", "") or ""),
                        "visualization_item_type": str(doc.get("visualization_item_type", "") or ""),
                        "visualization_kind": str(doc.get("visualization_kind", "") or ""),
                        "visualization_variables": _list_field(
                            doc.get("visualization_variables", [])
                        ),
                        "visualization_roles": _list_field(
                            doc.get("visualization_roles", [])
                        ),
                        "visualization_sequence_metadata": _dict_field(
                            doc.get("visualization_sequence_metadata", {})
                        ),
                        "visualization_item_metadata": _dict_field(
                            doc.get("visualization_item_metadata", {})
                        ),
                        "scalar_field_axes": scalar_field_axis_spec(
                            doc.get("scalar_field_metadata", {})
                        ),
                        "src": src,
                        "media_type": media_type,
                        "status": status,
                        "note": note,
                        "fps": int(fps),
                        "frame_count": frame_count,
                        "frame_indices": frame_indices,
                        "time_values": time_values,
                        "time_mode": time_mode,
                        "frame_sources": frame_sources,
                    }
                tile.update(self._axis_tile_fields(doc, 0))
                tiles.append(tile)

                if len(tiles) >= int(limit):
                    break

            return tiles

        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.ok = False
            return []
