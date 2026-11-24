"""Metadata for the campaign overview and result package inspector."""

import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


OVERVIEW_PREVIEW_LIMIT = 3


def _finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _recorded_time(doc):
    """Use explicit timing metadata; never interpret a frame number as physical time."""
    metadata = {
        **(doc.get("visualization_sequence_metadata") or {}),
        **(doc.get("visualization_item_metadata") or {}),
        **doc,
    }
    axes = metadata.get("axes") or {}
    if not isinstance(axes, dict):
        axes = {}
    time_variable = metadata.get("time_axis_variable") or metadata.get("x_axis_variable")
    axis = next((item for item in axes.values() if isinstance(item, dict) and (
        (time_variable and item.get("variable") == time_variable)
        or (not time_variable and item.get("kind") in {"time", "physical_time"})
    )), {})
    unit = str(metadata.get("time_unit") or axis.get("unit") or "")
    label = "t" if axis.get("kind", "time") in {"time", "physical_time"} else str(axis.get("label") or axis.get("kind"))
    values = metadata.get("time_values")
    if isinstance(values, (list, tuple)) and values:
        times = [_finite_number(value) for value in values]
        if all(value is not None for value in times):
            return times, unit, label
    time = _finite_number(metadata.get("physical_time"))
    return ([time] if time is not None else []), unit, label


def _coverage(doc):
    times, unit, label = _recorded_time(doc)
    count = None
    metadata = doc.get("metadata") or {}
    # A file-per-timestep schema count describes the whole collection, not this BP file.
    candidates = [len(times)] if len(times) > 1 and label == "t" else []
    if doc.get("schema_mode") != "file_per_timestep" and label == "t":
        candidates.append(doc.get("schema_num_timesteps"))
    candidates.extend(metadata.get(key) for key in ("AvailableStepsCount", "Steps", "steps"))
    for value in candidates:
        number = _finite_number(value)
        if number is not None and number > 0 and number.is_integer():
            count = int(number)
            break
    return {"steps": count, "start": min(times) if times else None,
            "end": max(times) if times else None, "unit": unit, "label": label}


def _coverage_text(coverage):
    parts = []
    count = coverage.get("steps")
    if count:
        parts.append(f"{count} {'step' if count == 1 else 'steps'}")
    if coverage.get("start") is not None:
        start, end = coverage["start"], coverage["end"]
        span = f"{start:g}" if start == end else f"{start:g}–{end:g}"
        unit = f" {coverage['unit']}" if coverage.get("unit") else ""
        parts.append(f"{coverage['label']} = {span}{unit}")
    return " · ".join(parts)


def _source_coverage(documents):
    coverages = [_coverage(doc) for doc in documents]
    known = [item for item in coverages if _coverage_text(item)]
    if not known:
        return ""
    # Static variables may accompany a time-dependent field. Report ranges rather
    # than adding variable counts or pretending every variable has the same extent.
    counts = sorted({item["steps"] for item in known if item["steps"]})
    parts = []
    if counts:
        parts.append(f"{counts[0]}–{counts[-1]} steps by variable" if len(counts) > 1
                     else f"{counts[0]} {'step' if counts[0] == 1 else 'steps'}")
    timed = [item for item in known if item["start"] is not None]
    spans = {_coverage_text({**item, "steps": None}) for item in timed}
    if len(spans) == 1:
        parts.append(spans.pop())
    elif spans:
        parts.append("Time coverage varies by variable")
    return " · ".join(parts)


def _timestamp_ns(value):
    if not isinstance(value, int) or value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value // 1_000_000_000, timezone.utc).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def _recorded_replicas(con):
    try:
        rows = con.execute(
            "select r.datasetid, r.name, r.modtime, r.size, h.hostname, dir.name as directory "
            "from replica r left join host h on h.rowid=r.hostid "
            "left join directory dir on dir.rowid=r.dirid where r.deltime=0 order by r.rowid"
        ).fetchall()
    except sqlite3.Error:
        return {}
    replicas = {}
    for row in rows:
        size = row["size"]
        replicas.setdefault(row["datasetid"], []).append({
            "host": row["hostname"] or "", "directory": row["directory"] or "",
            "name": row["name"], "modified_at": _timestamp_ns(row["modtime"]),
            "path": str(PurePosixPath(row["directory"] or "") / row["name"]),
            "size_bytes": size if isinstance(size, int) and size > 0 else None,
        })
    return replicas


def archive_file_history(path, name):
    """Read a bounded list of changes for the current dataset identity on demand."""
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as con:
            rows = con.execute(
                "select log.timestamp_ns, log.action from dataset d "
                "join entity_identity identity on identity.kind='dataset' "
                "and identity.local_id=d.rowid and identity.active=1 "
                "join change_log log on log.kind='dataset' and log.entity_uuid=identity.uuid "
                "where d.name=? and d.deltime=0 order by log.timestamp_ns desc limit 20", (name,)
            ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    return [{"timestamp": _timestamp_ns(timestamp), "action": action} for timestamp, action in rows]


def midpoint_frame_index(times):
    """Choose the nearest saved time to the time span's midpoint, or its middle frame."""
    middle = len(times) // 2
    if not times:
        return 0
    try:
        values = [float(value) for value in times]
    except (TypeError, ValueError, OverflowError):
        return middle
    if not all(math.isfinite(value) for value in values) or min(values) == max(values):
        return middle
    target = (min(values) + max(values)) / 2
    # Prefer the later frame when two saved times are equally close.
    return min(reversed(range(len(values))), key=lambda index: abs(values[index] - target))


def _image_preview_frame(path, doc, sequence_metadata):
    order = doc.get("visualization_item_order", doc.get("frame_index"))
    try:
        order = int(order)
    except (TypeError, ValueError, OverflowError):
        order = None
    times, unit, label = _recorded_time(doc)
    time = _finite_number(doc.get("physical_time", (doc.get("visualization_item_metadata") or {}).get("physical_time")))
    if not times:
        times, unit, label = _recorded_time(sequence_metadata)
    if time is None and order is not None and isinstance(times, (list, tuple)) and 0 <= order < len(times):
        time = times[order]
    return {
        "campaign_path": path,
        "uuid": str(doc.get("visualization_item_uuid", "") or ""),
        "variable_path": str(doc.get("variable_path", "") or ""),
        "frame_index": order,
        "physical_time": time,
        "time_unit": unit,
        "time_label": label,
    }


def _video_preview_frame(path, dataset_uuid, metadata):
    times = metadata.get("time_values", [])
    try:
        count = int(metadata.get("frame_count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        count = 0
    if isinstance(times, (list, tuple)) and len(times) == count and count > 0:
        index = midpoint_frame_index(times)
    else:
        index = count // 2 if count > 0 else None
    return {
        "campaign_path": path,
        "uuid": str(metadata.get("poster_uuid", "") or ""),
        "variable_path": "",
        "video_uuid": dataset_uuid,
        "video_frame_index": index,
    }


def campaign_overview_card(campaign):
    """Group BP files and their visualization samples by directory."""
    directories = {}
    dataset_directories = {}
    for dataset in campaign["datasets"]:
        if str(dataset.get("fileformat", "")).strip().upper() != "ADIOS":
            continue
        path = PurePosixPath(dataset["name"])
        parent = str(path.parent)
        directory = directories.setdefault(parent, {
            "path": parent,
            "name": "Campaign root" if parent == "." else parent,
            "datasets": [],
            "results": [],
        })
        directory["datasets"].append({
            "name": dataset["name"], "label": path.name,
            "explorable": dataset["explorable"],
            "added_at": dataset.get("added_at", ""),
            "modified_at": dataset.get("modified_at", ""),
            "coverage": dataset.get("coverage", ""),
            "parameters": dataset.get("parameters", []),
        })
        dataset_directories[str(path)] = parent

    ungrouped = []
    for result in campaign["results"]:
        if not (result.get("preview") or result.get("video")):
            continue
        parents = {
            dataset_directories[str(PurePosixPath(item["source"]))]
            for item in result.get("inputs", [])
            if str(PurePosixPath(item["source"])) in dataset_directories
        }
        if not parents:
            parents = {
                dataset_directories[str(PurePosixPath(item["name"]))]
                for item in result.get("artifacts", [])
                if str(PurePosixPath(item["name"])) in dataset_directories
            }
        if not parents and result.get("dataset_path"):
            # Use a recorded storage directory only when there are no BP links.
            stored = PurePosixPath(result["dataset_path"])
            matches = [parent for parent in directories
                       if parent != "." and stored.is_relative_to(parent)]
            if matches:
                parents = {max(matches, key=lambda parent: len(PurePosixPath(parent).parts))}
            elif str(stored.parent) == "." and "." in directories:
                parents = {"."}
        preview = {key: result[key] for key in ("id", "title", "kind", "preview")}
        preview["caption"] = result.get("caption", "Time not recorded")
        if not parents:
            ungrouped.append(preview)
        for parent in parents:
            samples = directories[parent]["results"]
            if len(samples) < OVERVIEW_PREVIEW_LIMIT:
                samples.append(preview)

    ordered = [directories[parent] for parent in sorted(directories)]
    for directory in ordered:
        files = directory["datasets"]
        directory["modified_at"] = max((item["modified_at"] for item in files), default="")
        # A partial set of addition dates cannot establish the first addition.
        directory["added_at"] = min(item["added_at"] for item in files) if all(item["added_at"] for item in files) else ""
        coverages = {item["coverage"] for item in files if item["coverage"]}
        if len(coverages) == 1 and all(item["coverage"] for item in files):
            directory["coverage"] = next(iter(coverages)) + (" per BP file" if len(files) > 1 else "")
        elif coverages:
            directory["coverage"] = "Coverage varies by file" if all(item["coverage"] for item in files) else "Partial coverage metadata"
        else:
            directory["coverage"] = ""
        common = files[0]["parameters"] if files else []
        directory["parameters"] = [item for item in common if all(item in file["parameters"] for file in files)]
    if ungrouped:
        ordered.append({
            "path": "", "name": "Other visualizations", "datasets": [],
            "results": ungrouped[:OVERVIEW_PREVIEW_LIMIT],
            "coverage": "", "parameters": [],
            "modified_at": "", "added_at": "",
        })
    return {
        "id": campaign["id"],
        "path": campaign["path"],
        "name": campaign["name"],
        "error": campaign["error"],
        "modified_at": max((directory["modified_at"] for directory in ordered), default=""),
        "added_at": "",  # File addition history is not the campaign's creation date.
        "directories": ordered,
    }


def campaign_key(path):
    return hashlib.sha256(str(path).encode()).hexdigest()[:24]


def _dataset_added_times(con):
    """Return insertion times for current dataset identities, excluding upgrade baselines."""
    try:
        rows = con.execute(
            "select d.name, min(log.timestamp_ns) as added_ns "
            "from dataset d "
            "join entity_identity identity on identity.kind='dataset' "
            "and identity.local_id=d.rowid and identity.active=1 "
            "join change_log log on log.kind='dataset' and log.entity_uuid=identity.uuid "
            "and log.action='insert' "
            "where d.deltime=0 group by d.rowid, d.name"
        ).fetchall()
    except sqlite3.Error:
        # Older archives have no insertion history. Never substitute source mtime.
        return {}
    times = {}
    for row in rows:
        times[row["name"]] = _timestamp_ns(row["added_ns"])
    return times


def archive_inventory(path):
    """Read the dataset inventory without reading media or creating an archive."""
    inventory = {"uuid": "", "datasets": [], "error": ""}
    try:
        uri = Path(path).expanduser().resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as con:
            con.row_factory = sqlite3.Row
            columns = {row["name"] for row in con.execute("pragma table_info(dataset)")}
            modified_column = "modtime" if "modtime" in columns else "null as modtime"
            rows = con.execute(
                f"select rowid, name, uuid, fileformat, {modified_column} from dataset where deltime = 0 order by name"
            ).fetchall()
            added = _dataset_added_times(con)
            replicas = _recorded_replicas(con)
            for row in rows:
                locations = replicas.get(row["rowid"], [])
                modified = max((item["modified_at"] for item in locations if item["modified_at"]), default="")
                inventory["datasets"].append({
                    "name": row["name"], "uuid": row["uuid"], "fileformat": row["fileformat"],
                    "added_at": added.get(row["name"], ""),
                    "modified_at": modified or _timestamp_ns(row["modtime"]),
                    "locations": locations,
                })
            if con.execute(
                "select 1 from sqlite_master where type='table' and name='campaign_identity'"
            ).fetchone():
                row = con.execute("select uuid from campaign_identity where singleton = 1").fetchone()
                inventory["uuid"] = str(row[0]) if row else ""
    except (OSError, sqlite3.Error) as error:
        inventory["error"] = str(error)
    return inventory


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def campaign_summary(path, documents, inventory=None):
    """Group results by recorded sequence, and retain explicit file references."""
    documents = list(documents)
    inventory = archive_inventory(path) if inventory is None else inventory
    key = campaign_key(path)
    sources = {}
    source_documents = {}
    parameters = {}
    results = {}
    for doc in documents:
        source = str(doc.get("source_dataset", "") or "")
        variable = str(doc.get("variable_id", "") or "")
        kind = str(doc.get("variable_type", "") or "")
        if source and kind == "variable":
            sources.setdefault(source, set()).add(variable)
            source_documents.setdefault(source, []).append(doc)
        if source:
            for metadata in (doc.get("metadata"), doc.get("visualization_sequence_metadata"), doc.get("visualization_item_metadata")):
                recorded = (metadata or {}).get("run_parameters")
                if isinstance(recorded, dict):
                    for name, value in recorded.items():
                        parameter = {"name": str(name), "value": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}
                        if parameter not in parameters.setdefault(source, []):
                            parameters[source].append(parameter)
        if kind not in {"image", "video", "scalarField"}:
            continue
        sequence = str(doc.get("visualization_sequence_name", "") or "")
        name = str(doc.get("visualization_name", "") or "")
        if not name:
            continue
        if sequence:
            identity = (sequence,)
        elif doc.get("association_source") == "publication":
            identity = ("publication", name)
        else:
            identity = (name, source, kind)
        sequence_metadata = dict(doc.get("visualization_sequence_metadata", {}) or {})
        item_metadata = dict(doc.get("visualization_item_metadata", {}) or {})
        if identity not in results:
            result_id = campaign_key(json.dumps([path, identity]))
            results[identity] = {
                "id": result_id,
                "campaign_path": path,
                "campaign_name": Path(path).stem,
                "title": str(sequence_metadata.get("title") or doc.get("display_name") or name),
                "dataset_path": str(doc.get("archive_dataset_path") or doc.get("variable_path") or ""),
                "kind": {"image": "Image sequence", "video": "Movie", "scalarField": "Scalar field"}[kind],
                "preview": f"/pulsar-campaign-preview/{result_id}" if kind != "scalarField" else "",
                "video": (
                    f"/pulsar-media/{doc['visualization_item_uuid']}?campaign={key}"
                    if kind == "video" and doc.get("visualization_item_uuid") else ""
                ),
                "inputs": [],
                "artifacts": [],
                "records": [],
                "_preview": _video_preview_frame(
                    path, str(doc.get("visualization_item_uuid", "") or ""),
                    {**item_metadata, **{key: doc[key] for key in ("frame_count", "time_values") if key in doc}},
                ) if kind == "video" else {},
                "_frames": {},
                "_time_coverage": _coverage(doc),
                "_variables": set(),
            }
        result = results[identity]
        if variable and not variable.startswith(("published-image:", "published-video:")):
            result["_variables"].add(variable)
        if kind == "image":
            frame = _image_preview_frame(path, doc, sequence_metadata)
            frame_key = (frame["frame_index"], frame["uuid"] or frame["variable_path"])
            if frame_key not in result["_frames"]:
                result["_frames"][frame_key] = frame
        if source and variable and not variable.startswith(("published-image:", "published-video:")):
            item = {"source": source, "variable": variable}
            if item not in result["inputs"]:
                result["inputs"].append(item)
        record = {
            "sequence_name": sequence,
            "dataset_uuid": str(doc.get("visualization_item_uuid", "") or ""),
            "dataset_path": str(doc.get("variable_path", "") or ""),
            "sequence": sequence_metadata,
            "item": item_metadata,
            "associations": doc.get("visualization_variables", []),
            "provenance": doc.get("visualization_activity_provenance", {}) or doc.get("activity_provenance", {}),
        }
        if not result["records"]:
            result["records"].append(record)
        # Only exact references in recorded metadata establish a package link.
        references = set(_strings(record))
        item_uuid = str(doc.get("visualization_item_uuid", "") or "")
        for dataset in inventory["datasets"]:
            if str(dataset.get("fileformat", "")).upper() in {"IMAGE", "VIDEO"}:
                continue
            if dataset["name"] in references or (dataset.get("uuid") and dataset["uuid"] in references):
                if dataset not in result["artifacts"] and dataset.get("uuid") != item_uuid:
                    result["artifacts"].append(dataset)

    represented_media = {str(doc.get("visualization_item_uuid", "")) for doc in documents}
    represented_media.update(
        str((doc.get("visualization_item_metadata") or {}).get("poster_uuid", ""))
        for doc in documents
    )
    for dataset in inventory["datasets"]:
        kind = str(dataset.get("fileformat", "")).upper()
        if kind not in {"IMAGE", "VIDEO"} or dataset.get("uuid") in represented_media:
            continue
        result_id = campaign_key(json.dumps([path, dataset["uuid"]]))
        results[(dataset["uuid"],)] = {
            "id": result_id, "campaign_path": path, "campaign_name": Path(path).stem,
            "title": dataset["name"], "kind": "Image" if kind == "IMAGE" else "Movie",
            "dataset_path": dataset["name"],
            "preview": f"/pulsar-campaign-preview/{result_id}",
            "video": f"/pulsar-media/{dataset['uuid']}?campaign={key}" if kind == "VIDEO" else "",
            "inputs": [], "artifacts": [], "records": [],
            "_preview": (
                _video_preview_frame(path, dataset["uuid"], {}) if kind == "VIDEO"
                else {"campaign_path": path, "uuid": dataset["uuid"], "variable_path": ""}
            ),
        }
    datasets = []
    supporting_files = []
    for raw in inventory["datasets"]:
        dataset = {**raw, "variables": sorted(sources.get(raw["name"], set()))}
        docs = source_documents.get(raw["name"], [])
        dataset["coverage"] = _source_coverage(docs)
        dataset["parameters"] = parameters.get(raw["name"], [])
        details = []
        for doc in docs:
            metadata = doc.get("metadata") or {}
            shape = metadata.get("Shape", metadata.get("shape"))
            if isinstance(shape, (list, tuple)):
                shape = " × ".join(str(value) for value in shape)
            item = {
                "name": doc["variable_id"], "type": str(metadata.get("Type", "")),
                "shape": str(shape) if shape else ("scalar" if shape is not None else ""),
                "coverage": _coverage_text(_coverage(doc)),
            }
            if item not in details:
                details.append(item)
        dataset["variable_details"] = sorted(details, key=lambda item: item["name"])
        dataset["metadata_text"] = json.dumps([
            {"variable": doc["variable_id"], "metadata": doc.get("metadata", {}),
             "provenance": doc.get("activity_provenance", {})}
            for doc in docs
        ], indent=2, ensure_ascii=False)
        dataset["explorable"] = bool(dataset["variables"])
        fileformat = str(raw.get("fileformat", "") or "").upper()
        if fileformat in {"IMAGE", "VIDEO"}:
            continue
        if fileformat in {"TEXT", "JSON", "YAML"}:
            supporting_files.append(dataset)
        else:
            datasets.append(dataset)
    known = {item["name"] for item in datasets}
    for source, variables in sources.items():
        if source not in known:
            datasets.append({
                "name": source, "uuid": "", "fileformat": "", "variables": sorted(variables),
                "explorable": True, "coverage": "", "parameters": [], "variable_details": [],
                "locations": [], "metadata_text": "[]",
            })
    try:
        updated = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except OSError:
        updated = "Unknown"
    for result in results.values():
        frames = list(result.pop("_frames", {}).values())
        if frames:
            # Stable ordering also handles legacy frames without an explicit order.
            frames.sort(key=lambda frame: frame["frame_index"] if frame["frame_index"] is not None else 0)
            result["_preview"] = frames[midpoint_frame_index([frame["physical_time"] for frame in frames])]
        variables = sorted(result.pop("_variables", set()))
        caption = ", ".join(variables[:3])
        if len(variables) > 3:
            caption += f" +{len(variables) - 3}"
        frame = result["_preview"]
        time_coverage = result.pop("_time_coverage", {})
        if "video_uuid" in frame:
            # Describe the movie's recorded time range, including when decoding
            # falls back to its poster, rather than claim a precise displayed time.
            timing = _coverage_text({**time_coverage, "steps": None})
            timing = f"Movie: {timing}" if timing else "Movie time not recorded"
        elif _finite_number(frame.get("physical_time")) is not None:
            timing = f"{frame.get('time_label', 't')} = {float(frame['physical_time']):g}" + (f" {frame['time_unit']}" if frame.get("time_unit") else "")
        elif frames:
            timing = f"Frame {frames.index(frame) + 1} of {len(frames)} · time not recorded"
        else:
            timing = "Time not recorded"
        result["caption"] = " · ".join(part for part in (caption, timing) if part)
        result["metadata_text"] = json.dumps(result.pop("records"), indent=2, ensure_ascii=False)
        result["explorable_sources"] = sorted(sources)
    return {
        "id": key, "path": path, "name": Path(path).stem,
        "uuid": inventory["uuid"], "updated": updated, "error": inventory["error"],
        "datasets": sorted(datasets, key=lambda item: item["name"]),
        "supporting_files": supporting_files,
        "results": list(results.values()),
    }


def build_campaign_overview(collection, paths):
    campaigns = []
    for path in paths:
        documents = list(collection.find({"campaign_path": path}, {"image_bytes": 0}))
        inventory = archive_inventory(path)
        if not documents and not inventory["error"]:
            # Inventory and registered packages remain inspectable when an
            # external data replica or the ADIOS campaign reader is unavailable.
            documents = archive_result_documents(path)
        campaigns.append(campaign_summary(path, documents, inventory))
    return campaigns


def archive_result_documents(path):
    from ingest_campaign import _load_visualization_api_index

    documents = []
    try:
        entries = _load_visualization_api_index(path).values()
    except sqlite3.Error:
        return []
    for entry in entries:
        kind = {"IMAGE": "image", "VIDEO": "video", "SCALAR_FIELD": "scalarField"}.get(entry["item_type"])
        if kind is None:
            continue
        for variable in entry.get("variables") or [{}]:
            documents.append({
                "variable_type": kind,
                "variable_id": variable.get("name", ""),
                "source_dataset": variable.get("source_dataset", ""),
                "visualization_name": entry["visualization_name"],
                "visualization_sequence_name": entry["sequence_name"],
                "visualization_item_uuid": entry["item_uuid"],
                "visualization_sequence_metadata": entry["sequence_metadata"],
                "visualization_item_metadata": entry["item_metadata"],
                "visualization_item_order": entry["item_order"],
                "archive_dataset_path": entry["item_dataset_name"],
                "variable_path": "",  # No ADIOS variable path was resolved.
            })
    return documents
