"""Validate the campaign's physical-time mapping for encoded movie frames."""

import json
import math
from itertools import pairwise


def normalize_video_timing(metadata, frame_count):
    mode = metadata.get(
        "time_mode", "physical_time" if "time_values" in metadata else "timestep"
    )
    if mode == "timestep":
        if any(key in metadata for key in ("time_values", "time_unit", "time_source")):
            raise ValueError("Movie physical-time metadata requires physical_time mode")
        return {}
    if mode != "physical_time":
        raise ValueError("Unsupported movie time mode")
    values = metadata.get("time_values")
    if not isinstance(values, (list, tuple)) or len(values) != frame_count:
        raise ValueError("Movie timing requires one physical time per encoded frame")
    try:
        times = [float(value) for value in values]
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Movie frame times must be finite numbers") from error
    if any(not math.isfinite(value) for value in times):
        raise ValueError("Movie frame times must be finite numbers")
    if any(right < left for left, right in pairwise(times)):
        raise ValueError("Movie frame times must be non-decreasing")
    unit = metadata.get("time_unit", "s")
    if not isinstance(unit, str) or not unit.strip() or len(unit) > 128:
        raise ValueError("Movie time_unit must be nonempty text")
    source = metadata.get("time_source", {"kind": "explicit"})
    if not isinstance(source, dict):
        raise ValueError("Movie time_source must be a JSON object")  # noqa: TRY004
    try:
        source = json.loads(json.dumps(source, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError("Movie time_source must contain finite JSON values") from error
    return {
        "time_mode": "physical_time",
        "time_values": times,
        "time_unit": unit.strip(),
        "time_source": source,
    }
