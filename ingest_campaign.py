import os, re, json, sqlite3, fnmatch, zlib
import argparse
from pathlib import Path
from adios2 import FileReader

import numpy as np
from typing import Optional, Any, Dict, List, Pattern

from sqlite_store import open_sqlite_collection


DEFAULT_CAMPAIGN_PATH = os.getenv("CAMPAIGN_PATH", "kh.aca")


def get_collection(campaign_path: Optional[str] = None):
    return open_sqlite_collection(campaign_path or DEFAULT_CAMPAIGN_PATH)


def clear_collection(campaign_path: Optional[str] = None):
    get_collection(campaign_path).delete_many({})


def _to_simple_string(input: str) -> str:
    return input.translate(str.maketrans("", "", '"'))


def _load_image_association_schema_text(schema_path: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Load an optional image association schema text/YAML file.
    Returns (resolved_path_str, text) or (None, None) when schema_path is not set.
    """
    if not schema_path:
        return (None, None)

    p = Path(schema_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Image association schema file not found: {p}")
    if not p.is_file():
        raise ValueError(f"Image association schema path is not a file: {p}")

    text = p.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Image association schema file is empty: {p}")

    return (str(p), text)


_IMAGE_ASSOC_MODES = {"first_match_wins", "all_matches"}
_IMAGE_ASSOC_UNMATCHED = {"warn", "error", "ignore"}
_IMAGE_SIZE_SEGMENT_RE = re.compile(r"^\d+x\d+$")
_ADIOS_DATASET_SEGMENT_RE = re.compile(r"\.bp\d*$", re.IGNORECASE)
# hpc-campaign writes the visualization API into the ACA SQLite database.
# All four tables are needed to map an image item back to its source variables.
_VISUALIZATION_API_TABLES = {
    "visualization_sequence",
    "visualization_variable",
    "visualization_item",
    "dataset",
}
_UNIFIED_VARIABLE_TABLES = {
    "action_spec",
    "activity",
    "activity_input",
    "activity_input_step_mapping",
    "activity_kind",
    "activity_output",
    "campaign_run",
    "logical_variable",
    "variable_chunk",
    "variable_definition",
    "dataset",
}
_CAMPAIGN_SCHEMA_TABLES = {
    "dataset",
    "replica",
    "repfiles",
    "file",
}
_CAMPAIGN_SCHEMA_DATASET_NAMES = (
    "__campaign_schema.yaml",
    "schema.yaml",
)
_DISPLAY_ROLE_PRIORITY = {
    "color-by": 0,
    "y-axis": 1,
    "contour-by": 2,
    "streamline-by": 3,
    "variable": 4,
    "primary": 5,
    "x-axis": 90,
}
_NONDISPLAY_ROLES = {"x-axis"}
SCALAR_FIELD_ITEM_TYPE = "SCALAR_FIELD"
SCALAR_FIELD_VARIABLE_TYPE = "scalarField"


def _sqlite_table_names(con: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in con.execute("select name from sqlite_master where type = 'table'")
    }


def _read_campaign_schema_text(campaign_path: str) -> Optional[str]:
    path = Path(campaign_path).expanduser()
    if not path.exists():
        return None

    try:
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(f"[warn] could not open ACA SQLite metadata for campaign schema: {e}")
        return None

    try:
        if not _CAMPAIGN_SCHEMA_TABLES.issubset(_sqlite_table_names(con)):
            return None

        row = con.execute(
            """
            select
                d.name as dataset_name,
                r.keyid as keyid,
                f.compression as compression,
                f.data as data
            from dataset as d
            join replica as r on r.datasetid = d.rowid
            join repfiles as rf on rf.replicaid = r.rowid
            join file as f on f.fileid = rf.fileid
            where d.name in (?, ?) and d.fileformat = 'TEXT' and d.deltime = 0 and r.deltime = 0
            order by
                case d.name when ? then 0 else 1 end,
                r.rowid desc,
                f.fileid desc
            limit 1
            """,
            (
                _CAMPAIGN_SCHEMA_DATASET_NAMES[0],
                _CAMPAIGN_SCHEMA_DATASET_NAMES[1],
                _CAMPAIGN_SCHEMA_DATASET_NAMES[0],
            ),
        ).fetchone()
        if row is None:
            return None

        if int(row["keyid"] or 0) > 0:
            raise ValueError(
                f"{row['dataset_name']} is encrypted; Seurat cannot read it without a keyfile"
            )

        data = bytes(row["data"])
        if int(row["compression"] or 0):
            data = zlib.decompress(data)
        return data.decode("utf-8")
    finally:
        con.close()


def _load_campaign_dataset_rows(campaign_path: str) -> List[Dict[str, str]]:
    path = Path(campaign_path).expanduser()
    if not path.exists():
        return []

    try:
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(f"[warn] could not open ACA SQLite metadata for dataset list: {e}")
        return []

    try:
        if "dataset" not in _sqlite_table_names(con):
            return []
        rows = con.execute(
            """
            select name, fileformat
            from dataset
            where deltime = 0
            order by name
            """
        ).fetchall()
        return [
            {
                "name": str(row["name"] or ""),
                "fileformat": str(row["fileformat"] or ""),
            }
            for row in rows
        ]
    finally:
        con.close()


def _load_campaign_timeseries(campaign_path: str) -> Dict[str, List[str]]:
    path = Path(campaign_path).expanduser()
    if not path.exists():
        return {}

    try:
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(f"[warn] could not open ACA SQLite metadata for time series: {e}")
        return {}

    try:
        tables = _sqlite_table_names(con)
        if "timeseries" not in tables or "dataset" not in tables:
            return {}
        rows = con.execute(
            """
            select t.name as timeseries_name, d.name as dataset_name
            from timeseries as t
            join dataset as d on d.tsid = t.tsid
            where d.deltime = 0
            order by t.name, d.tsorder
            """
        ).fetchall()
        membership: Dict[str, List[str]] = {}
        for row in rows:
            name = str(row["timeseries_name"] or "")
            dataset = str(row["dataset_name"] or "")
            if name and dataset:
                membership.setdefault(name, []).append(dataset)
        return membership
    finally:
        con.close()


def _schema_mapping(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _schema_nonempty_string(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _schema_time_fields(time_spec: Any, field_name: str) -> Dict[str, str]:
    time_map = _schema_mapping(time_spec, field_name)
    variable = str(time_map.get("variable", "") or "").strip()
    index = str(time_map.get("index", "") or "").strip()
    has_variable = bool(variable)
    has_index = bool(index)
    if has_variable == has_index:
        raise ValueError(f"{field_name} requires exactly one of variable or index")
    return {"variable": variable} if has_variable else {"index": index}


def _schema_group_time(time_spec: Any, field_name: str) -> Dict[str, str]:
    time_map = _schema_mapping(time_spec, field_name)
    if "file" in time_map:
        raise ValueError(f"{field_name}.file is not supported; file group is implicit")
    return _schema_time_fields(time_map, field_name)


def _schema_root_time(time_spec: Any, file_groups: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    time_map = _schema_mapping(time_spec, "time")
    result = _schema_time_fields(time_map, "time")
    if "file" in time_map:
        file_group = _schema_nonempty_string(time_map.get("file"), "time.file")
        group = file_groups.get(file_group)
        if group is None:
            raise ValueError(f"time.file references unknown group: {file_group}")
        if group.get("role") != "time_series":
            raise ValueError(f"time.file references non-time_series group: {file_group}")
        result["file"] = file_group
    return result


def _apply_root_time(time_spec: Any, file_groups: Dict[str, Dict[str, Any]]) -> None:
    if time_spec in (None, {}):
        return

    root_time = _schema_root_time(time_spec, file_groups)
    root_group = root_time.get("file", "")
    group_time = {key: value for key, value in root_time.items() if key != "file"}

    if root_group:
        file_groups[root_group].setdefault("time", dict(group_time))
        return

    for group in file_groups.values():
        if group.get("role") == "time_series":
            group.setdefault("time", dict(group_time))


def _schema_optional_mapping(value: Any, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    return _schema_mapping(value, field_name)


def _schema_file_group_reference(
    value: Any,
    field_name: str,
    file_groups: Dict[str, Dict[str, Any]],
) -> str:
    file_group = _schema_nonempty_string(value, field_name)
    if file_group not in file_groups:
        raise ValueError(f"{field_name} references unknown file group: {file_group}")
    return file_group


def _interpret_schema_axes(
    raw_axes: Any,
    file_groups: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    axes: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_axis in _schema_optional_mapping(raw_axes, "axes").items():
        name = _schema_nonempty_string(raw_name, "axes name")
        axis = _schema_mapping(raw_axis, f"axes.{name}")
        has_variable = "variable" in axis
        has_template = "variable_template" in axis
        if has_variable == has_template:
            raise ValueError(
                f"axes.{name} requires exactly one of variable or variable_template"
            )

        normalized: Dict[str, Any] = {
            "file": _schema_file_group_reference(
                axis.get("file"),
                f"axes.{name}.file",
                file_groups,
            ),
            "kind": _schema_nonempty_string(axis.get("kind"), f"axes.{name}.kind"),
        }
        variable_key = "variable" if has_variable else "variable_template"
        normalized[variable_key] = _schema_nonempty_string(
            axis.get(variable_key),
            f"axes.{name}.{variable_key}",
        )

        for key in ("label", "unit"):
            if key in axis:
                normalized[key] = _schema_nonempty_string(
                    axis.get(key),
                    f"axes.{name}.{key}",
                )

        if "dimension" in axis:
            dimension = axis.get("dimension")
            if isinstance(dimension, bool):
                raise ValueError(f"axes.{name}.dimension must be a non-negative integer")
            try:
                dimension = int(dimension)
            except Exception as e:
                raise ValueError(
                    f"axes.{name}.dimension must be a non-negative integer"
                ) from e
            if dimension < 0:
                raise ValueError(f"axes.{name}.dimension must be a non-negative integer")
            normalized["dimension"] = dimension

        layout = str(axis.get("layout", "shared") or "shared").strip().lower()
        if layout not in {"shared", "per_selection"}:
            raise ValueError(
                f"axes.{name}.layout must be 'shared' or 'per_selection'"
            )
        normalized["layout"] = layout
        axes[name] = normalized
    return axes


def _interpret_schema_source_collections(
    raw_collections: Any,
    file_groups: Dict[str, Dict[str, Any]],
    axes: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    collections: Dict[str, Dict[str, Any]] = {}
    claimed_datasets: Dict[tuple[str, str], str] = {}
    for raw_name, raw_collection in _schema_optional_mapping(
        raw_collections,
        "source_collections",
    ).items():
        name = _schema_nonempty_string(raw_name, "source_collections name")
        field_name = f"source_collections.{name}"
        collection = _schema_mapping(raw_collection, field_name)
        file_group = _schema_file_group_reference(
            collection.get("file"),
            f"{field_name}.file",
            file_groups,
        )
        pattern = _schema_nonempty_string(
            collection.get("pattern"),
            f"{field_name}.pattern",
        )
        combine = _schema_mapping(
            collection.get("combine"),
            f"{field_name}.combine",
        )
        mode = _schema_nonempty_string(
            combine.get("mode"),
            f"{field_name}.combine.mode",
        ).lower()
        if mode != "concatenate":
            raise ValueError(
                f"{field_name}.combine.mode must be 'concatenate'"
            )
        axis_name = _schema_axis_reference(
            combine.get("axis"),
            f"{field_name}.combine.axis",
            file_group,
            axes,
        )
        if "variable" not in axes[axis_name]:
            raise ValueError(
                f"{field_name}.combine.axis must reference an axis with a "
                "fixed variable"
            )

        order_by = _schema_mapping(
            combine.get("order_by"),
            f"{field_name}.combine.order_by",
        )
        order_variable = _schema_nonempty_string(
            order_by.get("variable"),
            f"{field_name}.combine.order_by.variable",
        ).strip("/")
        order_reduce = str(order_by.get("reduce", "first") or "first").strip().lower()
        if order_reduce != "first":
            raise ValueError(
                f"{field_name}.combine.order_by.reduce must be 'first'"
            )

        partition_label: Dict[str, str] = {}
        if "partition_label" in combine:
            label_spec = _schema_mapping(
                combine.get("partition_label"),
                f"{field_name}.combine.partition_label",
            )
            label_variable = _schema_nonempty_string(
                label_spec.get("variable"),
                f"{field_name}.combine.partition_label.variable",
            ).strip("/")
            label_template = _schema_nonempty_string(
                label_spec.get("template"),
                f"{field_name}.combine.partition_label.template",
            )
            try:
                label_template.format(value="example")
            except (KeyError, ValueError) as e:
                raise ValueError(
                    f"Invalid {field_name}.combine.partition_label.template "
                    f"{label_template!r}: {e}"
                ) from e
            partition_label = {
                "variable": label_variable,
                "template": label_template,
            }

        group_datasets = [
            str(dataset)
            for dataset in (file_groups[file_group].get("datasets", []) or [])
        ]
        datasets = sorted(
            dataset for dataset in group_datasets if fnmatch.fnmatch(dataset, pattern)
        )
        for dataset in datasets:
            claim_key = (file_group, dataset)
            previous = claimed_datasets.get(claim_key)
            if previous is not None:
                raise ValueError(
                    f"{field_name}.pattern overlaps source collection "
                    f"{previous!r} for dataset {dataset!r}"
                )
            claimed_datasets[claim_key] = name

        collections[name] = {
            "label": str(collection.get("label", "") or name).strip() or name,
            "file": file_group,
            "pattern": pattern,
            "datasets": datasets,
            "combine": {
                "mode": mode,
                "axis": axis_name,
                "order_by": {
                    "variable": order_variable,
                    "reduce": order_reduce,
                },
                **(
                    {"partition_label": partition_label}
                    if partition_label
                    else {}
                ),
            },
        }
    return collections


def _schema_string_list(value: Any, field_name: str) -> List[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    return [_schema_nonempty_string(item, f"{field_name} item") for item in value]


def _interpret_schema_meshes(
    raw_meshes: Any,
    file_groups: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    meshes: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_mesh in _schema_optional_mapping(raw_meshes, "meshes").items():
        name = _schema_nonempty_string(raw_name, "meshes name")
        mesh = _schema_mapping(raw_mesh, f"meshes.{name}")
        normalized: Dict[str, Any] = {
            "file": _schema_file_group_reference(
                mesh.get("file"),
                f"meshes.{name}.file",
                file_groups,
            ),
            "variable": _schema_nonempty_string(
                mesh.get("variable"),
                f"meshes.{name}.variable",
            ),
            "model": _schema_nonempty_string(mesh.get("model"), f"meshes.{name}.model"),
        }
        if "columns" in mesh:
            normalized["columns"] = _schema_string_list(
                mesh.get("columns"),
                f"meshes.{name}.columns",
            )
        meshes[name] = normalized
    return meshes


def _interpret_schema_basis(
    raw_basis: Any,
    file_groups: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    basis: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_spec in _schema_optional_mapping(raw_basis, "basis").items():
        name = _schema_nonempty_string(raw_name, "basis name")
        spec = _schema_mapping(raw_spec, f"basis.{name}")
        raw_variables = _schema_mapping(
            spec.get("variables"),
            f"basis.{name}.variables",
        )
        if not raw_variables:
            raise ValueError(f"basis.{name}.variables must not be empty")
        variables = {
            _schema_nonempty_string(
                role,
                f"basis.{name}.variables role",
            ): _schema_nonempty_string(
                variable,
                f"basis.{name}.variables.{role}",
            )
            for role, variable in raw_variables.items()
        }
        basis[name] = {
            "file": _schema_file_group_reference(
                spec.get("file"),
                f"basis.{name}.file",
                file_groups,
            ),
            "variables": variables,
            "model": _schema_nonempty_string(spec.get("model"), f"basis.{name}.model"),
        }
    return basis


def _compile_schema_variable_pattern(pattern: str, field_name: str) -> Pattern[str]:
    parts = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                parts.append(".*")
                index += 2
            else:
                parts.append("[^/]*")
                index += 1
            continue
        if char == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(char))
        index += 1
    parts.append("$")
    try:
        return re.compile("".join(parts))
    except re.error as e:
        raise ValueError(f"Invalid {field_name}: {e}") from e


def _schema_named_reference(
    value: Any,
    field_name: str,
    targets: Dict[str, Any],
) -> str:
    name = _schema_nonempty_string(value, field_name)
    if name not in targets:
        raise ValueError(f"{field_name} references unknown name: {name}")
    return name


def _schema_axis_reference(
    value: Any,
    field_name: str,
    group_file: str,
    axes: Dict[str, Dict[str, Any]],
) -> str:
    name = _schema_named_reference(value, field_name, axes)
    if axes[name]["file"] != group_file:
        raise ValueError(
            f"{field_name} references axis {name!r} from a different file group"
        )
    return name


def _interpret_schema_variable_groups(
    raw_groups: Any,
    file_groups: Dict[str, Dict[str, Any]],
    axes: Dict[str, Dict[str, Any]],
    meshes: Dict[str, Dict[str, Any]],
    basis: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    variable_groups: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_group in _schema_optional_mapping(
        raw_groups,
        "variable_groups",
    ).items():
        name = _schema_nonempty_string(raw_name, "variable_groups name")
        group = _schema_mapping(raw_group, f"variable_groups.{name}")
        file_group = _schema_file_group_reference(
            group.get("file"),
            f"variable_groups.{name}.file",
            file_groups,
        )
        pattern = _schema_nonempty_string(
            group.get("pattern"),
            f"variable_groups.{name}.pattern",
        )
        _compile_schema_variable_pattern(
            pattern,
            f"variable_groups.{name}.pattern",
        )
        normalized: Dict[str, Any] = {
            "file": file_group,
            "pattern": pattern,
            "role": _schema_nonempty_string(
                group.get("role"),
                f"variable_groups.{name}.role",
            ),
        }

        if "data_model" in group:
            normalized["data_model"] = _schema_nonempty_string(
                group.get("data_model"),
                f"variable_groups.{name}.data_model",
            )

        if "display_name_template" in group:
            field_name = f"variable_groups.{name}.display_name_template"
            display_name_template = _schema_nonempty_string(
                group.get("display_name_template"),
                field_name,
            )
            _schema_display_name_for_variable(
                display_name_template,
                "example/variable",
                field_name,
            )
            normalized["display_name_template"] = display_name_template

        for key, targets in (("mesh", meshes), ("basis", basis)):
            if key not in group:
                continue
            reference = _schema_named_reference(
                group.get(key),
                f"variable_groups.{name}.{key}",
                targets,
            )
            if targets[reference]["file"] != file_group:
                raise ValueError(
                    f"variable_groups.{name}.{key} references "
                    f"{reference!r} from a different file group"
                )
            normalized[key] = reference

        for key in ("time_axis", "x_axis", "timestep_axis"):
            if key in group:
                normalized[key] = _schema_axis_reference(
                    group.get(key),
                    f"variable_groups.{name}.{key}",
                    file_group,
                    axes,
                )

        if "dimension_axes" in group:
            dimension_axes = _schema_string_list(
                group.get("dimension_axes"),
                f"variable_groups.{name}.dimension_axes",
            )
            if len(set(dimension_axes)) != len(dimension_axes):
                raise ValueError(
                    f"variable_groups.{name}.dimension_axes must not contain duplicates"
                )
            normalized["dimension_axes"] = [
                _schema_axis_reference(
                    axis_name,
                    f"variable_groups.{name}.dimension_axes",
                    file_group,
                    axes,
                )
                for axis_name in dimension_axes
            ]

        for key in ("plot_x_axis", "selection_axis"):
            if key in group:
                normalized[key] = _schema_axis_reference(
                    group.get(key),
                    f"variable_groups.{name}.{key}",
                    file_group,
                    axes,
                )

        declared_dimensions = set(normalized.get("dimension_axes", []))
        if declared_dimensions:
            for key in ("plot_x_axis", "selection_axis"):
                axis_name = normalized.get(key)
                if axis_name and axis_name not in declared_dimensions:
                    raise ValueError(
                        f"variable_groups.{name}.{key} must appear in dimension_axes"
                    )

        if "static" in group:
            if not isinstance(group.get("static"), bool):
                raise ValueError(f"variable_groups.{name}.static must be a boolean")
            normalized["static"] = bool(group.get("static"))
        if normalized.get("static") and any(
            key in normalized
            for key in (
                "time_axis",
                "x_axis",
                "timestep_axis",
                "plot_x_axis",
                "selection_axis",
                "dimension_axes",
            )
        ):
            raise ValueError(
                f"variable_groups.{name} is static and cannot reference an axis"
            )

        variable_groups[name] = normalized
    return variable_groups


def _schema_declared_exact_variables(
    axes: Dict[str, Dict[str, Any]],
    meshes: Dict[str, Dict[str, Any]],
    basis: Dict[str, Dict[str, Any]],
) -> set[str]:
    variables = {
        str(axis["variable"])
        for axis in axes.values()
        if "variable" in axis
    }
    variables.update(mesh["variable"] for mesh in meshes.values())
    for spec in basis.values():
        variables.update(str(variable) for variable in spec["variables"].values())
    return variables


def _schema_declares_variable(
    variable: str,
    exact_variables: set[str],
    variable_groups: Dict[str, Dict[str, Any]],
) -> bool:
    if variable in exact_variables:
        return True
    return any(
        _compile_schema_variable_pattern(
            str(group["pattern"]),
            f"variable_groups.{name}.pattern",
        ).fullmatch(variable)
        for name, group in variable_groups.items()
    )


def _interpret_schema_visualization_templates(
    raw_templates: Any,
    axes: Dict[str, Dict[str, str]],
    meshes: Dict[str, Dict[str, Any]],
    basis: Dict[str, Dict[str, Any]],
    variable_groups: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if raw_templates is None:
        return []
    if not isinstance(raw_templates, (list, tuple)):
        raise ValueError("visualization_templates must be a list")

    exact_variables = _schema_declared_exact_variables(axes, meshes, basis)
    templates: List[Dict[str, Any]] = []
    names: set[str] = set()
    for index, raw_template in enumerate(raw_templates):
        field_name = f"visualization_templates[{index}]"
        template = _schema_mapping(raw_template, field_name)
        name = _schema_nonempty_string(template.get("name"), f"{field_name}.name")
        if name in names:
            raise ValueError(f"Duplicate visualization template name: {name}")
        names.add(name)

        raw_variables = template.get("variables")
        if not isinstance(raw_variables, (list, tuple)) or not raw_variables:
            raise ValueError(f"{field_name}.variables must be a non-empty list")
        variables = []
        for variable_index, raw_variable in enumerate(raw_variables):
            variable_field = f"{field_name}.variables[{variable_index}]"
            variable_spec = _schema_mapping(raw_variable, variable_field)
            variable = _schema_nonempty_string(
                variable_spec.get("variable"),
                f"{variable_field}.variable",
            )
            if not _schema_declares_variable(
                variable,
                exact_variables,
                variable_groups,
            ):
                raise ValueError(
                    f"{variable_field}.variable is not declared by the schema: "
                    f"{variable}"
                )
            variables.append(
                {
                    "role": _schema_nonempty_string(
                        variable_spec.get("role"),
                        f"{variable_field}.role",
                    ),
                    "variable": variable,
                }
            )

        normalized = dict(template)
        normalized.update(
            {
                "name": name,
                "kind": _schema_nonempty_string(
                    template.get("kind"),
                    f"{field_name}.kind",
                ),
                "variables": variables,
            }
        )
        templates.append(normalized)
    return templates


def _interpret_schema_optional_metadata(
    schema: Dict[str, Any],
    file_groups: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    axes = _interpret_schema_axes(schema.get("axes"), file_groups)
    if "axes" in schema:
        result["axes"] = axes

    source_collections = _interpret_schema_source_collections(
        schema.get("source_collections"),
        file_groups,
        axes,
    )
    if "source_collections" in schema:
        result["source_collections"] = source_collections

    if "timeline" in schema:
        timeline = _schema_mapping(schema.get("timeline"), "timeline")
        normalized_timeline: Dict[str, Any] = {}
        if "default_axis" in timeline:
            normalized_timeline["default_axis"] = _schema_named_reference(
                timeline.get("default_axis"),
                "timeline.default_axis",
                axes,
            )
        result["timeline"] = normalized_timeline

    meshes = _interpret_schema_meshes(schema.get("meshes"), file_groups)
    if "meshes" in schema:
        result["meshes"] = meshes

    basis = _interpret_schema_basis(schema.get("basis"), file_groups)
    if "basis" in schema:
        result["basis"] = basis

    variable_groups = _interpret_schema_variable_groups(
        schema.get("variable_groups"),
        file_groups,
        axes,
        meshes,
        basis,
    )
    if "variable_groups" in schema:
        result["variable_groups"] = variable_groups

    templates = _interpret_schema_visualization_templates(
        schema.get("visualization_templates"),
        axes,
        meshes,
        basis,
        variable_groups,
    )
    if "visualization_templates" in schema:
        result["visualization_templates"] = templates

    return result


def _schema_extract_step_indices(group_name: str, group: Dict[str, Any], datasets: List[str]) -> List[int]:
    pattern = _schema_nonempty_string(group.get("step_from_filename"), f"files.{group_name}.step_from_filename")
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid files.{group_name}.step_from_filename regex: {e}") from e

    steps: List[int] = []
    for dataset in datasets:
        match = regex.search(dataset)
        if match is None:
            raise ValueError(f"files.{group_name}.step_from_filename did not match dataset: {dataset}")
        if not match.groups():
            raise ValueError(f"files.{group_name}.step_from_filename must capture a step number")
        try:
            steps.append(int(match.group(1)))
        except Exception as e:
            raise ValueError(
                f"files.{group_name}.step_from_filename captured a non-integer step "
                f"for {dataset}: {match.group(1)}"
            ) from e
    return steps


def _resolve_schema_time_series_datasets(
    group_name: str,
    pattern: str,
    dataset_names: List[str],
    timeseries: Dict[str, List[str]],
) -> List[str]:
    matches = {name for name in dataset_names if fnmatch.fnmatch(name, pattern)}
    if not matches:
        return []

    ordered = timeseries.get(group_name, [])
    if not ordered:
        return sorted(matches)

    result: List[str] = []
    for dataset in ordered:
        if dataset not in matches:
            raise ValueError(f"timeseries.{group_name} dataset does not match files.{group_name}.pattern: {dataset}")
        result.append(dataset)
    return result


def _schema_layout_dataset_count(layout: Dict[str, Any]) -> int:
    return sum(
        len(group.get("datasets", []) or [])
        for group in (layout.get("file_groups", {}) or {}).values()
    )


def _schema_immediate_child_prefixes(dataset_names: List[str]) -> List[str]:
    prefixes = {
        name.split("/", 1)[0]
        for name in dataset_names
        if "/" in name and name.split("/", 1)[0]
    }
    return sorted(prefixes)


def _strip_schema_scope_prefix(prefix: str, dataset_names: List[str]) -> List[str]:
    prefix_slash = f"{prefix}/"
    return [
        name[len(prefix_slash) :]
        for name in dataset_names
        if name.startswith(prefix_slash)
    ]


def _strip_schema_timeseries_scope_prefix(
    prefix: str,
    timeseries: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    prefix_slash = f"{prefix}/"
    scoped: Dict[str, List[str]] = {}
    for name, datasets in timeseries.items():
        scoped_datasets = [
            dataset[len(prefix_slash) :]
            for dataset in datasets
            if dataset.startswith(prefix_slash)
        ]
        if not scoped_datasets:
            continue
        scoped_name = name[len(prefix_slash) :] if name.startswith(prefix_slash) else name
        scoped[scoped_name] = scoped_datasets
    return scoped


def _prefix_schema_layout_datasets(prefix: str, layout: Dict[str, Any]) -> Dict[str, Any]:
    prefixed = dict(layout)
    prefixed["scope"] = prefix
    file_groups: Dict[str, Dict[str, Any]] = {}
    for group_name, group in (layout.get("file_groups", {}) or {}).items():
        prefixed_group = dict(group)
        prefixed_group["datasets"] = [
            f"{prefix}/{dataset}" for dataset in group.get("datasets", []) or []
        ]
        file_groups[str(group_name)] = prefixed_group
    prefixed["file_groups"] = file_groups
    source_collections: Dict[str, Dict[str, Any]] = {}
    for collection_name, collection in (
        layout.get("source_collections", {}) or {}
    ).items():
        prefixed_collection = dict(collection)
        prefixed_collection["datasets"] = [
            f"{prefix}/{dataset}"
            for dataset in collection.get("datasets", []) or []
        ]
        source_collections[str(collection_name)] = prefixed_collection
    if source_collections:
        prefixed["source_collections"] = source_collections
    return prefixed


def _merge_scoped_schema_layouts(
    schema: Dict[str, Any],
    layouts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    file_groups: Dict[str, Dict[str, Any]] = {}
    for layout in layouts:
        for group_name, group in (layout.get("file_groups", {}) or {}).items():
            group_key = str(group_name)
            if group_key not in file_groups:
                merged_group = dict(group)
                merged_group["datasets"] = []
                if "step_indices" in merged_group:
                    merged_group["step_indices"] = []
                file_groups[group_key] = merged_group

            target = file_groups[group_key]
            target["datasets"].extend(group.get("datasets", []) or [])
            if "step_indices" in target:
                target["step_indices"].extend(group.get("step_indices", []) or [])

    layout = {
        "schema_version": int(schema.get("schema_version", 0)),
        "schema_name": str(schema.get("name", "") or ""),
        "schema_scope_prefixes": [
            str(layout.get("scope", "") or "") for layout in layouts
        ],
        "file_groups": file_groups,
    }
    layout.update(_interpret_schema_optional_metadata(schema, file_groups))
    merged_collections = layout.get("source_collections", {}) or {}
    for collection_name, collection in merged_collections.items():
        collection["datasets"] = [
            dataset
            for scoped_layout in layouts
            for dataset in (
                (scoped_layout.get("source_collections", {}) or {})
                .get(collection_name, {})
                .get("datasets", [])
                or []
            )
        ]
    return layout


def _interpret_campaign_schema_at_root(
    schema: Dict[str, Any],
    dataset_names: List[str],
    timeseries: Dict[str, List[str]],
) -> Dict[str, Any]:
    try:
        schema_version = int(schema.get("schema_version", 0))
    except Exception as e:
        raise ValueError("schema_version must be an integer") from e
    if schema_version != 1:
        raise ValueError(f"Unsupported schema_version={schema_version}; expected 1")

    files = _schema_mapping(schema.get("files"), "files")
    file_groups: Dict[str, Dict[str, Any]] = {}

    for raw_group_name, raw_group in files.items():
        group_name = str(raw_group_name)
        group = _schema_mapping(raw_group, f"files.{group_name}")
        role = _schema_nonempty_string(group.get("role"), f"files.{group_name}.role")
        if role not in {"static", "time_series"}:
            raise ValueError(f"Unsupported files.{group_name}.role={role!r}")

        if role == "static":
            if "time" in group:
                raise ValueError(f"files.{group_name}.time is only valid for time_series groups")
            if group.get("path"):
                path = _schema_nonempty_string(group.get("path"), f"files.{group_name}.path")
                datasets = [path] if path in dataset_names else []
            else:
                pattern = _schema_nonempty_string(group.get("pattern"), f"files.{group_name}.path or pattern")
                datasets = sorted(name for name in dataset_names if fnmatch.fnmatch(name, pattern))
            result: Dict[str, Any] = {"role": role, "mode": "none", "datasets": datasets}
        else:
            mode = _schema_nonempty_string(group.get("mode"), f"files.{group_name}.mode")
            if mode == "append":
                path = str(group.get("path", "") or "").strip()
                pattern = str(group.get("pattern", "") or "").strip()
                if bool(path) == bool(pattern):
                    raise ValueError(
                        f"files.{group_name} requires exactly one of path or pattern for append mode"
                    )
                if path:
                    datasets = [path] if path in dataset_names else []
                else:
                    datasets = sorted(name for name in dataset_names if fnmatch.fnmatch(name, pattern))
                result = {"role": role, "mode": mode, "datasets": datasets}
            elif mode == "file_per_timestep":
                pattern = _schema_nonempty_string(group.get("pattern"), f"files.{group_name}.pattern")
                datasets = _resolve_schema_time_series_datasets(group_name, pattern, dataset_names, timeseries)
                result = {
                    "role": role,
                    "mode": mode,
                    "pattern": pattern,
                    "datasets": datasets,
                    "step_indices": _schema_extract_step_indices(group_name, group, datasets) if datasets else [],
                }
            else:
                raise ValueError(f"Unsupported files.{group_name}.mode={mode!r}")

        associations = group.get("associations", {}) or {}
        if associations:
            assoc_map = _schema_mapping(associations, f"files.{group_name}.associations")
            result["associations"] = {str(role_name): str(target) for role_name, target in assoc_map.items()}
        if "time" in group:
            result["time"] = _schema_group_time(group.get("time"), f"files.{group_name}.time")
        file_groups[group_name] = result

    _apply_root_time(schema.get("time"), file_groups)
    layout = {
        "schema_version": schema_version,
        "schema_name": str(schema.get("name", "") or ""),
        "file_groups": file_groups,
    }
    layout.update(_interpret_schema_optional_metadata(schema, file_groups))
    return layout


def _interpret_campaign_schema(
    schema: Dict[str, Any],
    dataset_names: List[str],
    timeseries: Dict[str, List[str]],
) -> Dict[str, Any]:
    root_layout = _interpret_campaign_schema_at_root(
        schema,
        dataset_names,
        timeseries,
    )
    if _schema_layout_dataset_count(root_layout) > 0:
        return root_layout

    scoped_layouts: List[Dict[str, Any]] = []
    for prefix in _schema_immediate_child_prefixes(dataset_names):
        scoped_dataset_names = _strip_schema_scope_prefix(prefix, dataset_names)
        scoped_timeseries = _strip_schema_timeseries_scope_prefix(prefix, timeseries)
        scoped_layout = _interpret_campaign_schema_at_root(
            schema,
            scoped_dataset_names,
            scoped_timeseries,
        )
        if _schema_layout_dataset_count(scoped_layout) <= 0:
            continue
        scoped_layouts.append(_prefix_schema_layout_datasets(prefix, scoped_layout))

    if scoped_layouts:
        return _merge_scoped_schema_layouts(schema, scoped_layouts)

    return root_layout


def _load_campaign_schema(
    campaign_path: str,
    dataset_names: List[str],
    timeseries: Dict[str, List[str]],
    campaign_schema_path: Optional[str] = None,
) -> Dict[str, Any]:
    schema_source = "embedded campaign schema"
    if campaign_schema_path:
        schema_file = Path(campaign_schema_path).expanduser().resolve()
        if not schema_file.exists():
            raise FileNotFoundError(f"Campaign schema file not found: {schema_file}")
        if not schema_file.is_file():
            raise ValueError(f"Campaign schema path is not a file: {schema_file}")
        schema_text = schema_file.read_text(encoding="utf-8")
        if not schema_text.strip():
            raise ValueError(f"Campaign schema file is empty: {schema_file}")
        schema_source = str(schema_file)
    else:
        schema_text = _read_campaign_schema_text(campaign_path)
    if not schema_text:
        return {}

    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError("Campaign schema requires PyYAML. Install with: pip install pyyaml") from e

    try:
        schema = yaml.safe_load(schema_text)
    except Exception as e:
        raise ValueError(f"Invalid campaign schema {schema_source}: {e}") from e

    if not isinstance(schema, dict):
        raise ValueError(f"Campaign schema {schema_source} must contain a mapping")

    return _interpret_campaign_schema(schema, dataset_names, timeseries)


def _read_numeric_array(fr: FileReader, varpath: str, varinfo: Optional[Dict[str, Any]] = None) -> List[float]:
    try:
        steps = 0
        if isinstance(varinfo, dict):
            try:
                steps = int(str(varinfo.get("AvailableStepsCount", "0") or "0"))
            except Exception:
                steps = 0
        data = fr.read(varpath, step_selection=[0, steps]) if steps > 1 else fr.read(varpath)
    except Exception as e:
        print(f"[warn] could not read time variable {varpath!r}: {type(e).__name__}: {e}")
        return []

    try:
        arr = np.asarray(data).reshape(-1)
    except Exception:
        return []

    values: List[float] = []
    for value in arr:
        fvalue = _to_float(value)
        if fvalue is None:
            return []
        values.append(fvalue)
    return values


def _schema_variable_shape(varinfo: Any) -> List[int]:
    if not isinstance(varinfo, dict):
        return []
    raw_shape = varinfo.get("Shape", varinfo.get("shape", ""))
    if isinstance(raw_shape, (list, tuple)):
        parts = list(raw_shape)
    else:
        text = str(raw_shape or "").strip().strip("[](){}")
        parts = [part.strip() for part in text.replace("x", ",").split(",")]
    shape: List[int] = []
    for part in parts:
        if part in (None, ""):
            continue
        try:
            value = int(part)
        except Exception:
            return []
        if value < 0:
            return []
        shape.append(value)
    return shape


def _schema_axis_variable_for_data(axis: Dict[str, Any], data_variable: str) -> str:
    if "variable" in axis:
        return str(axis.get("variable", "") or "").strip("/")

    variable = str(data_variable or "").strip("/")
    parent, _, name = variable.rpartition("/")
    template = str(axis.get("variable_template", "") or "")
    try:
        resolved = template.format(
            variable=variable,
            variable_parent=parent,
            variable_name=name,
        )
    except (KeyError, ValueError) as e:
        raise ValueError(
            f"Invalid axis variable_template {template!r}: {e}"
        ) from e
    return _schema_nonempty_string(resolved, "axis variable_template result").strip("/")


def _schema_display_name_for_variable(
    template: str,
    data_variable: str,
    field_name: str = "display_name_template",
) -> str:
    variable = str(data_variable or "").strip("/")
    parent, _, name = variable.rpartition("/")
    parent_name = parent.rsplit("/", 1)[-1] if parent else ""
    try:
        resolved = template.format(
            variable=variable,
            variable_parent=parent,
            variable_parent_name=parent_name,
            variable_name=name,
        )
    except (KeyError, ValueError) as e:
        raise ValueError(f"Invalid {field_name} {template!r}: {e}") from e
    return _schema_nonempty_string(resolved, f"{field_name} result")


def _schema_axis_label(axis_name: str, axis: Dict[str, Any]) -> str:
    label = str(axis.get("label", "") or "").strip()
    if label:
        return label
    kind = str(axis.get("kind", "") or "").strip().lower()
    if kind == "time":
        return "Time"
    if kind == "timestep_index":
        return "Timestep"
    return str(axis_name or "axis").replace("_", " ").strip().title()


def _schema_scalar_label(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _schema_axis_descriptor(
    context: Dict[str, Any],
    fr: FileReader,
    vars_dict: Dict[str, Any],
    dataset: str,
    data_variable: str,
    axis_name: str,
    include_values: bool = False,
) -> Dict[str, Any]:
    axis = dict(context["axes"][axis_name])
    coordinate_variable = _schema_axis_variable_for_data(axis, data_variable)
    path = _schema_required_variable_path(
        vars_dict,
        dataset,
        coordinate_variable,
        f"axes.{axis_name}",
    )
    shape = _schema_variable_shape(vars_dict.get(path))
    collection = dict(
        context.get("dataset_collections", {}).get(dataset, {}) or {}
    )
    axis_key_group = str(axis.get("file", "") or "")
    if collection and str(collection.get("source_collection_axis", "") or "") == axis_name:
        axis_key_group = str(collection.get("source_collection_id", "") or axis_key_group)
    descriptor: Dict[str, Any] = {
        "id": str(axis_name),
        "key": ":".join(
            part
            for part in (
                str(context.get("schema_name", "") or ""),
                axis_key_group,
                str(axis_name),
            )
            if part
        ),
        "kind": str(axis.get("kind", "") or ""),
        "label": _schema_axis_label(axis_name, axis),
        "unit": str(axis.get("unit", "") or ""),
        "layout": str(axis.get("layout", "shared") or "shared"),
        "variable": coordinate_variable,
        "variable_path": path,
        "shape": shape,
    }
    if "dimension" in axis:
        descriptor["dimension"] = int(axis["dimension"])
    if collection and str(collection.get("source_collection_axis", "") or "") == axis_name:
        descriptor.update(
            {
                "source_collection_id": str(
                    collection.get("source_collection_id", "") or ""
                ),
                "collection_offset": int(
                    collection.get("source_collection_offset", 0) or 0
                ),
                "collection_length": int(
                    collection.get("source_collection_length", 0) or 0
                ),
                "collection_total_length": int(
                    collection.get("source_collection_total_length", 0) or 0
                ),
            }
        )
    if include_values:
        if len(shape) > 1:
            raise ValueError(
                f"Selection axis {axis_name!r} must be one-dimensional; "
                f"coordinate {path!r} has shape {shape}"
            )
        descriptor["values"] = _schema_axis_values(
            context,
            fr,
            vars_dict,
            dataset,
            axis_name,
            data_variable=data_variable,
        )
    return descriptor


def _schema_dataset_variables(
    vars_dict: Dict[str, Any],
    dataset: str,
) -> Dict[str, Any]:
    prefix = f"{str(dataset or '').strip('/')}/"
    if not prefix or prefix == "/":
        return {}
    return {
        str(path)[len(prefix) :]: info
        for path, info in vars_dict.items()
        if str(path).startswith(prefix)
    }


def _schema_required_variable_path(
    vars_dict: Dict[str, Any],
    dataset: str,
    variable: str,
    field_name: str,
) -> str:
    path = f"{str(dataset or '').strip('/')}/{str(variable or '').strip('/')}"
    if path not in vars_dict:
        raise ValueError(
            f"{field_name} references missing ADIOS variable "
            f"{variable!r} in dataset {dataset!r}"
        )
    return path


def _schema_axis_values(
    context: Dict[str, Any],
    fr: FileReader,
    vars_dict: Dict[str, Any],
    dataset: str,
    axis_name: str,
    data_variable: str = "",
) -> List[float]:
    axis = context["axes"][axis_name]
    variable = _schema_axis_variable_for_data(axis, data_variable)
    cache_key = f"{dataset}\0{axis_name}\0{variable}"
    cached = context["axis_values"].get(cache_key)
    if isinstance(cached, list):
        return list(cached)

    path = _schema_required_variable_path(
        vars_dict,
        dataset,
        variable,
        f"axes.{axis_name}.variable",
    )
    values = _read_numeric_array(fr, path, vars_dict.get(path))
    if not values:
        raise ValueError(
            f"axes.{axis_name}.variable could not be read as a numeric axis: "
            f"{path}"
        )
    context["axis_values"][cache_key] = list(values)
    return values


def _validate_schema_resource_variables(
    schema_layout: Dict[str, Any],
    context: Dict[str, Any],
    vars_dict: Dict[str, Any],
) -> None:
    resources: List[tuple[str, str, List[str]]] = []
    for name, axis in context["axes"].items():
        if "variable" not in axis:
            continue
        resources.append(
            (
                f"axes.{name}",
                str(axis.get("file", "") or ""),
                [str(axis.get("variable", "") or "")],
            )
        )
    for name, mesh in context["meshes"].items():
        resources.append(
            (
                f"meshes.{name}",
                str(mesh.get("file", "") or ""),
                [str(mesh.get("variable", "") or "")],
            )
        )
    for name, spec in context["basis"].items():
        resources.append(
            (
                f"basis.{name}",
                str(spec.get("file", "") or ""),
                [str(variable) for variable in spec.get("variables", {}).values()],
            )
        )

    file_groups = schema_layout.get("file_groups", {}) or {}
    for field_name, file_group, variables in resources:
        datasets = list((file_groups.get(file_group, {}) or {}).get("datasets", []) or [])
        for dataset in datasets:
            for variable in variables:
                _schema_required_variable_path(
                    vars_dict,
                    str(dataset),
                    variable,
                    field_name,
                )


def _build_schema_variable_context(
    schema_layout: Dict[str, Any],
    context: Dict[str, Any],
    fr: FileReader,
    vars_dict: Dict[str, Any],
) -> None:
    if not context["variable_groups"]:
        return

    _validate_schema_resource_variables(schema_layout, context, vars_dict)
    file_groups = schema_layout.get("file_groups", {}) or {}
    matched_variables: set[str] = set()

    for group_order, (group_name, group) in enumerate(
        context["variable_groups"].items()
    ):
        file_group = str(group.get("file", "") or "")
        datasets = list((file_groups.get(file_group, {}) or {}).get("datasets", []) or [])
        matcher = _compile_schema_variable_pattern(
            str(group.get("pattern", "") or ""),
            f"variable_groups.{group_name}.pattern",
        )

        for raw_dataset in datasets:
            dataset = str(raw_dataset)
            relative_variables = _schema_dataset_variables(vars_dict, dataset)
            matches = sorted(
                variable
                for variable in relative_variables
                if matcher.fullmatch(variable)
            )
            if not matches:
                raise ValueError(
                    f"variable_groups.{group_name}.pattern matched no ADIOS "
                    f"variables in dataset {dataset!r}: {group.get('pattern')}"
                )

            for variable in matches:
                existing = context["variable_metadata"].setdefault(dataset, {}).get(variable)
                if existing is not None:
                    raise ValueError(
                        f"ADIOS variable {variable!r} in dataset {dataset!r} "
                        f"matches multiple variable groups: "
                        f"{existing.get('variable_group')} and {group_name}"
                    )

                metadata: Dict[str, Any] = {
                    "variable_group": str(group_name),
                    "variable_group_order": group_order,
                    "role": str(group.get("role", "") or ""),
                    "static": bool(group.get("static", False)),
                }
                display_name_template = str(
                    group.get("display_name_template", "") or ""
                )
                if display_name_template:
                    metadata["display_name"] = _schema_display_name_for_variable(
                        display_name_template,
                        variable,
                        f"variable_groups.{group_name}.display_name_template",
                    )
                for key in (
                    "data_model",
                    "mesh",
                    "basis",
                    "time_axis",
                    "x_axis",
                    "timestep_axis",
                    "dimension_axes",
                    "plot_x_axis",
                    "selection_axis",
                ):
                    if key in group:
                        metadata[key] = group[key]

                variable_path = f"{dataset}/{variable}"
                variable_shape = _schema_variable_shape(vars_dict.get(variable_path))
                dimension_axes = list(group.get("dimension_axes", []) or [])
                if variable_shape and dimension_axes and len(variable_shape) != len(
                    dimension_axes
                ):
                    raise ValueError(
                        f"variable_groups.{group_name}.dimension_axes has "
                        f"{len(dimension_axes)} entries but {variable_path!r} has "
                        f"shape {variable_shape}"
                    )
                for dimension, axis_name in enumerate(dimension_axes):
                    axis_dimension = context["axes"][axis_name].get("dimension")
                    if axis_dimension is not None and int(axis_dimension) != dimension:
                        raise ValueError(
                            f"axes.{axis_name}.dimension={axis_dimension} does not "
                            f"match its position {dimension} in "
                            f"variable_groups.{group_name}.dimension_axes"
                        )

                plot_axis_name = str(
                    group.get("plot_x_axis", group.get("x_axis", "")) or ""
                )
                selection_axis_name = str(
                    group.get(
                        "selection_axis",
                        group.get("time_axis", plot_axis_name),
                    )
                    or ""
                )
                referenced_axes: List[str] = []
                for axis_name in (
                    *dimension_axes,
                    plot_axis_name,
                    selection_axis_name,
                ):
                    if axis_name and axis_name not in referenced_axes:
                        referenced_axes.append(axis_name)

                axis_descriptors: Dict[str, Dict[str, Any]] = {}
                for axis_name in referenced_axes:
                    axis = context["axes"][axis_name]
                    include_axis_values = axis_name == selection_axis_name or (
                        axis_name == plot_axis_name
                        and str(axis.get("layout", "shared") or "shared") == "shared"
                    )
                    axis_descriptors[axis_name] = _schema_axis_descriptor(
                        context,
                        fr,
                        vars_dict,
                        dataset,
                        variable,
                        axis_name,
                        include_values=include_axis_values,
                    )
                if axis_descriptors:
                    metadata["axes"] = axis_descriptors
                if dimension_axes:
                    metadata["dimension_axes"] = dimension_axes
                if plot_axis_name:
                    metadata["plot_x_axis"] = plot_axis_name
                if selection_axis_name:
                    metadata["selection_axis"] = selection_axis_name
                default_axis = str(
                    context.get("timeline", {}).get("default_axis", "") or ""
                )
                if default_axis:
                    metadata["schema_default_axis"] = default_axis

                time_axis_name = str(
                    group.get("time_axis", group.get("x_axis", "")) or ""
                )
                if time_axis_name:
                    axis = context["axes"][time_axis_name]
                    metadata["time_values"] = _schema_axis_values(
                        context,
                        fr,
                        vars_dict,
                        dataset,
                        time_axis_name,
                    )
                    metadata["time_source"] = (
                        f"variable:{str(axis.get('variable', '') or '')}"
                    )
                    metadata["schema_num_timesteps"] = len(metadata["time_values"])
                    if "time_axis" in group:
                        metadata["time_axis_variable"] = str(
                            axis.get("variable", "") or ""
                        )
                    if "x_axis" in group:
                        metadata["x_axis_variable"] = str(
                            axis.get("variable", "") or ""
                        )
                elif metadata["static"]:
                    metadata["schema_num_timesteps"] = 1

                timestep_axis_name = str(group.get("timestep_axis", "") or "")
                if timestep_axis_name:
                    axis = context["axes"][timestep_axis_name]
                    metadata["timestep_values"] = _schema_axis_values(
                        context,
                        fr,
                        vars_dict,
                        dataset,
                        timestep_axis_name,
                    )
                    metadata["timestep_axis_variable"] = str(
                        axis.get("variable", "") or ""
                    )

                context["variable_metadata"][dataset][variable] = metadata
                matched_variables.add(variable)

    for template in context["visualization_templates"]:
        for variable_spec in template.get("variables", []) or []:
            variable = str(variable_spec.get("variable", "") or "")
            if variable not in matched_variables and not any(
                variable
                in _schema_dataset_variables(vars_dict, str(dataset))
                for group in file_groups.values()
                for dataset in group.get("datasets", []) or []
            ):
                raise ValueError(
                    f"Visualization template {template.get('name')!r} "
                    f"references missing ADIOS variable: {variable}"
                )

    for dataset, variable_map in context["variable_metadata"].items():
        for variable, metadata in variable_map.items():
            template_refs = []
            for template in context["visualization_templates"]:
                roles = [
                    str(spec.get("role", "") or "")
                    for spec in template.get("variables", []) or []
                    if str(spec.get("variable", "") or "") == variable
                ]
                if roles:
                    template_refs.append(
                        {
                            "name": str(template.get("name", "") or ""),
                            "kind": str(template.get("kind", "") or ""),
                            "roles": roles,
                        }
                    )
            if template_refs:
                metadata["visualization_templates"] = template_refs


def _build_schema_time_context(
    schema_layout: Dict[str, Any],
    fr: FileReader,
    vars_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not schema_layout:
        return {}

    context: Dict[str, Any] = {
        "schema_name": str(schema_layout.get("schema_name", "") or ""),
        "dataset_metadata": {},
        "group_metadata": {},
        "group_step_metadata": {},
        "group_frame_metadata": {},
        "file_groups": schema_layout.get("file_groups", {}) or {},
        "source_collections": schema_layout.get("source_collections", {}) or {},
        "dataset_collections": {},
        "source_collection_members": {},
        "axes": schema_layout.get("axes", {}) or {},
        "timeline": schema_layout.get("timeline", {}) or {},
        "meshes": schema_layout.get("meshes", {}) or {},
        "basis": schema_layout.get("basis", {}) or {},
        "variable_groups": schema_layout.get("variable_groups", {}) or {},
        "visualization_templates": (
            schema_layout.get("visualization_templates", []) or []
        ),
        "axis_values": {},
        "variable_metadata": {},
    }

    for group_name, group in context["file_groups"].items():
        datasets = [str(name) for name in (group.get("datasets", []) or [])]
        step_indices = list(group.get("step_indices", []) or [])
        mode = str(group.get("mode", "") or "")
        role = str(group.get("role", "") or "")
        time_spec = group.get("time", {}) if isinstance(group.get("time", {}), dict) else {}
        group_time_values: List[float] = []
        append_time_values: Dict[str, List[float]] = {}
        time_source = ""

        if "variable" in time_spec:
            time_var = str(time_spec.get("variable", "") or "").strip()
            if time_var:
                time_source = f"variable:{time_var}"
                if mode == "append":
                    for dataset in datasets:
                        time_path = f"{dataset}/{time_var}"
                        if not vars_dict or time_path in vars_dict:
                            values = _read_numeric_array(fr, time_path, (vars_dict or {}).get(time_path))
                            if values:
                                append_time_values[dataset] = values
                    if len(datasets) == 1:
                        group_time_values = list(append_time_values.get(datasets[0], []))
                elif mode == "file_per_timestep":
                    time_path = f"{group_name}/{time_var}"
                    if not vars_dict or time_path in vars_dict:
                        group_time_values = _read_numeric_array(fr, time_path, (vars_dict or {}).get(time_path))
        elif "index" in time_spec:
            time_index_name = str(time_spec.get("index", "") or "").strip()
            time_source = f"index:{time_index_name}"
            if mode == "append" and time_index_name == "step_index":
                for dataset in datasets:
                    step_counts: List[int] = []
                    for varinfo in _schema_dataset_variables(
                        vars_dict or {},
                        dataset,
                    ).values():
                        if not isinstance(varinfo, dict):
                            continue
                        try:
                            count = int(
                                str(
                                    varinfo.get("AvailableStepsCount", "0")
                                    or "0"
                                )
                            )
                        except Exception:
                            count = 0
                        if count > 0:
                            step_counts.append(count)
                    if step_counts:
                        append_time_values[dataset] = list(
                            range(max(step_counts))
                        )

        group_num_timesteps = len(datasets)
        if mode == "append":
            append_lengths = {len(values) for values in append_time_values.values()}
            group_num_timesteps = append_lengths.pop() if len(append_lengths) == 1 else 0

        group_metadata: Dict[str, Any] = {
            "schema_name": context["schema_name"],
            "schema_file_group": str(group_name),
            "schema_role": role,
            "schema_mode": mode,
            "schema_pattern": str(group.get("pattern", "") or ""),
            "schema_num_timesteps": group_num_timesteps,
        }
        if time_source:
            group_metadata["time_source"] = time_source
        if group_time_values:
            group_metadata["time_values"] = list(group_time_values)
        context["group_metadata"][str(group_name)] = group_metadata

        for index, dataset in enumerate(datasets):
            step_index = step_indices[index] if index < len(step_indices) else None
            dataset_time_values = append_time_values.get(dataset, [])
            dataset_num_timesteps = (
                len(dataset_time_values)
                if mode == "append"
                else len(datasets)
            )
            metadata: Dict[str, Any] = {
                "schema_name": context["schema_name"],
                "schema_file_group": str(group_name),
                "schema_role": role,
                "schema_mode": mode,
                "schema_pattern": str(group.get("pattern", "") or ""),
                "schema_num_timesteps": dataset_num_timesteps,
                "schema_frame_index": 0 if mode == "append" else index,
                "time_index": 0 if mode == "append" else index,
            }
            if isinstance(step_index, int):
                metadata["schema_step_index"] = step_index
            if isinstance(group.get("associations", None), dict):
                metadata["schema_associations"] = dict(group.get("associations") or {})
            if time_source:
                metadata["time_source"] = time_source
            if mode == "append" and dataset_time_values:
                metadata["time_values"] = list(dataset_time_values)

            if "variable" in time_spec:
                time_var = str(time_spec.get("variable", "") or "").strip()
                if time_var and mode == "file_per_timestep":
                    if index < len(group_time_values):
                        metadata["physical_time"] = group_time_values[index]
                    else:
                        time_path = f"{dataset}/{time_var}"
                        values = []
                        if not vars_dict or time_path in vars_dict:
                            values = _read_numeric_array(fr, time_path, (vars_dict or {}).get(time_path))
                        if values:
                            metadata["physical_time"] = values[0]
            elif str(time_spec.get("index", "") or "").strip() == "step_index" and isinstance(step_index, int):
                metadata["time_index"] = step_index

            context["dataset_metadata"][dataset] = metadata
            context["group_frame_metadata"].setdefault(str(group_name), {})[index] = metadata
            if isinstance(step_index, int):
                context["group_step_metadata"].setdefault(str(group_name), {})[step_index] = metadata

    for collection_name, collection in context["source_collections"].items():
        combine = dict(collection.get("combine", {}) or {})
        axis_name = str(combine.get("axis", "") or "")
        order_by = dict(combine.get("order_by", {}) or {})
        order_variable = str(order_by.get("variable", "") or "").strip("/")
        partition_spec = dict(combine.get("partition_label", {}) or {})
        partition_variable = str(
            partition_spec.get("variable", "") or ""
        ).strip("/")
        partition_template = str(
            partition_spec.get("template", "{value}") or "{value}"
        )
        members: List[Dict[str, Any]] = []

        for dataset in collection.get("datasets", []) or []:
            dataset_name = str(dataset)
            axis_values = _schema_axis_values(
                context,
                fr,
                vars_dict or {},
                dataset_name,
                axis_name,
            )
            if not axis_values:
                raise ValueError(
                    f"source_collections.{collection_name} axis could not be read "
                    f"for dataset {dataset_name!r}"
                )

            order_path = _schema_required_variable_path(
                vars_dict or {},
                dataset_name,
                order_variable,
                f"source_collections.{collection_name}.combine.order_by.variable",
            )
            order_values = _read_numeric_array(
                fr,
                order_path,
                (vars_dict or {}).get(order_path),
            )
            if not order_values:
                raise ValueError(
                    f"source_collections.{collection_name} ordering variable "
                    f"could not be read for dataset {dataset_name!r}"
                )
            order_value = float(order_values[0])

            partition_value = order_value
            if partition_variable:
                if partition_variable == order_variable:
                    partition_values = order_values
                else:
                    partition_path = _schema_required_variable_path(
                        vars_dict or {},
                        dataset_name,
                        partition_variable,
                        f"source_collections.{collection_name}.combine.partition_label.variable",
                    )
                    partition_values = _read_numeric_array(
                        fr,
                        partition_path,
                        (vars_dict or {}).get(partition_path),
                    )
                if not partition_values:
                    raise ValueError(
                        f"source_collections.{collection_name} partition label "
                        f"variable could not be read for dataset {dataset_name!r}"
                    )
                partition_value = float(partition_values[0])

            members.append(
                {
                    "source_dataset": dataset_name,
                    "length": len(axis_values),
                    "order_value": order_value,
                    "partition_value": partition_value,
                    "partition_label": partition_template.format(
                        value=_schema_scalar_label(partition_value)
                    ),
                }
            )

        members.sort(
            key=lambda item: (
                float(item.get("order_value", 0.0) or 0.0),
                str(item.get("source_dataset", "") or ""),
            )
        )
        offset = 0
        for member_index, member in enumerate(members):
            member["member_index"] = member_index
            member["offset"] = offset
            offset += int(member.get("length", 0) or 0)

        total_length = offset
        member_count = len(members)
        public_members = [dict(member) for member in members]
        context["source_collection_members"][str(collection_name)] = public_members
        for member in members:
            dataset_name = str(member.get("source_dataset", "") or "")
            collection_metadata = {
                "source_collection_id": str(collection_name),
                "source_collection_label": str(
                    collection.get("label", "") or collection_name
                ),
                "source_collection_mode": str(
                    combine.get("mode", "") or ""
                ),
                "source_collection_axis": axis_name,
                "source_collection_member_index": int(
                    member.get("member_index", 0) or 0
                ),
                "source_collection_member_count": member_count,
                "source_collection_offset": int(member.get("offset", 0) or 0),
                "source_collection_length": int(member.get("length", 0) or 0),
                "source_collection_total_length": total_length,
                "source_collection_partition_value": float(
                    member.get("partition_value", 0.0) or 0.0
                ),
                "source_collection_partition_label": str(
                    member.get("partition_label", "") or ""
                ),
            }
            context["dataset_collections"][dataset_name] = collection_metadata
            context["dataset_metadata"].setdefault(dataset_name, {}).update(
                collection_metadata
            )

    if vars_dict:
        _build_schema_variable_context(
            schema_layout,
            context,
            fr,
            dict(vars_dict),
        )

    return context


def _schema_metadata_for_frame(
    schema_context: Dict[str, Any],
    metadata: Dict[str, Any],
    frame_index: Optional[int],
) -> Dict[str, Any]:
    result = dict(metadata)
    if frame_index is not None and metadata.get("schema_mode") == "file_per_timestep":
        try:
            frame_value = int(frame_index)
        except Exception:
            frame_value = -1
        group_name = str(metadata.get("schema_file_group", "") or "")
        step_metadata = schema_context.get("group_step_metadata", {}).get(group_name, {}).get(frame_value)
        if isinstance(step_metadata, dict):
            result = dict(step_metadata)
        else:
            frame_metadata = schema_context.get("group_frame_metadata", {}).get(group_name, {}).get(frame_value)
            if isinstance(frame_metadata, dict):
                result = dict(frame_metadata)
    return result


def _finalize_schema_axis_metadata(
    metadata: Dict[str, Any],
    frame_index: Optional[int],
    include_time_values: bool,
) -> Dict[str, Any]:
    result = dict(metadata)
    time_values = result.pop("time_values", None)
    timestep_values = result.pop("timestep_values", None)
    if include_time_values and isinstance(time_values, list):
        result["time_values"] = list(time_values)
    if include_time_values and isinstance(timestep_values, list):
        result["timestep_values"] = list(timestep_values)

    if frame_index is not None:
        try:
            idx = int(frame_index)
        except Exception:
            idx = -1
        if isinstance(time_values, list) and 0 <= idx < len(time_values):
            result["physical_time"] = time_values[idx]
            result["time_index"] = idx
        if isinstance(timestep_values, list) and 0 <= idx < len(timestep_values):
            result["simulation_timestep"] = timestep_values[idx]

    return result


def _schema_metadata_for_file(
    schema_context: Dict[str, Any],
    file_name: str,
    frame_index: Optional[int] = None,
    include_time_values: bool = True,
) -> Dict[str, Any]:
    if not schema_context:
        return {}

    base = schema_context.get("dataset_metadata", {}).get(str(file_name or ""), None)
    if base is None:
        base = schema_context.get("group_metadata", {}).get(str(file_name or ""), None)
    if not isinstance(base, dict):
        return {}

    metadata = _schema_metadata_for_frame(
        schema_context,
        dict(base),
        frame_index,
    )
    return _finalize_schema_axis_metadata(
        metadata,
        frame_index,
        include_time_values,
    )


def _schema_metadata_for_variable(
    schema_context: Dict[str, Any],
    source_dataset: str,
    variable_id: str,
    frame_index: Optional[int] = None,
    include_time_values: bool = True,
) -> Dict[str, Any]:
    metadata = _schema_metadata_for_file(
        schema_context,
        source_dataset,
        frame_index=frame_index,
        include_time_values=True,
    )
    if not schema_context:
        return metadata

    dataset = str(source_dataset or "").strip("/")
    variable = str(variable_id or "").strip("/")
    if dataset and variable.startswith(dataset + "/"):
        variable = variable[len(dataset) + 1 :]
    variable_metadata = (
        schema_context.get("variable_metadata", {})
        .get(dataset, {})
        .get(variable)
    )
    if not isinstance(variable_metadata, dict):
        return _finalize_schema_axis_metadata(
            metadata,
            frame_index,
            include_time_values,
        )

    for key in (
        "time_values",
        "timestep_values",
        "time_source",
        "physical_time",
        "time_index",
        "simulation_timestep",
    ):
        metadata.pop(key, None)
    metadata.update(variable_metadata)
    if metadata.get("static"):
        metadata.pop("time_source", None)

    return _finalize_schema_axis_metadata(
        metadata,
        frame_index,
        include_time_values,
    )


def _visualization_record_matches_frame(
    schema_context: Dict[str, Any],
    source_dataset: str,
    frame_index: Optional[int],
    item_order: Optional[int],
) -> bool:
    if not schema_context:
        return True

    base = schema_context.get("dataset_metadata", {}).get(str(source_dataset or ""), None)
    if not isinstance(base, dict) or base.get("schema_mode") != "file_per_timestep":
        return True

    step_index = base.get("schema_step_index", None)
    if frame_index is not None and step_index is not None:
        try:
            return int(step_index) == int(frame_index)
        except Exception:
            return True

    schema_frame_index = base.get("schema_frame_index", None)
    if item_order is not None and schema_frame_index is not None:
        try:
            return int(schema_frame_index) == int(item_order)
        except Exception:
            return True

    return True


def _compile_path_template(path_template: str) -> Pattern[str]:
    """
    Compile a path_template supporting:
      - glob tokens: *, **, ?
      - named captures: {name} -> one path segment ([^/]+)
    """
    template = str(path_template or "").strip()
    if not template:
        raise ValueError("Empty path_template")

    parts: List[str] = ["^"]
    i = 0
    seen_fields = set()

    while i < len(template):
        ch = template[i]
        if ch == "{":
            end = template.find("}", i + 1)
            if end < 0:
                raise ValueError(f"Unclosed '{{' in path_template: {path_template!r}")
            field = template[i + 1 : end].strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field or ""):
                raise ValueError(f"Invalid capture field '{field}' in path_template: {path_template!r}")
            if field in seen_fields:
                parts.append(f"(?P={field})")
            else:
                parts.append(f"(?P<{field}>[^/]+)")
                seen_fields.add(field)
            i = end + 1
            continue

        if ch == "*":
            if (i + 1) < len(template) and template[i + 1] == "*":
                parts.append(".*")
                i += 2
            else:
                parts.append("[^/]*")
                i += 1
            continue

        if ch == "?":
            parts.append("[^/]")
            i += 1
            continue

        parts.append(re.escape(ch))
        i += 1

    parts.append("$")
    return re.compile("".join(parts))


def _load_image_association_schema(schema_file: str, schema_text: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Image association schema requires PyYAML. "
            "Install with: pip install pyyaml"
        ) from e

    try:
        data = yaml.safe_load(schema_text)
    except Exception as e:
        raise ValueError(f"Invalid YAML in schema file {schema_file}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Schema root must be a mapping: {schema_file}")

    try:
        schema_version = int(data.get("schema_version", 0))
    except Exception as e:
        raise ValueError(f"schema_version must be an integer in {schema_file}") from e
    if schema_version != 1:
        raise ValueError(f"Unsupported schema_version={schema_version} in {schema_file}; expected 1")

    matching = data.get("matching", {}) or {}
    if not isinstance(matching, dict):
        raise ValueError(f"'matching' must be a mapping in {schema_file}")

    mode = str(matching.get("mode", "first_match_wins") or "first_match_wins").strip()
    if mode not in _IMAGE_ASSOC_MODES:
        raise ValueError(f"Unsupported matching.mode={mode!r} in {schema_file}")

    on_unmatched = str(matching.get("on_unmatched", "warn") or "warn").strip()
    if on_unmatched not in _IMAGE_ASSOC_UNMATCHED:
        raise ValueError(f"Unsupported matching.on_unmatched={on_unmatched!r} in {schema_file}")

    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError(f"'rules' must be a list in {schema_file}")

    rules: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ValueError(f"Rule at index {idx} is not a mapping in {schema_file}")

        rule_id = str(raw.get("id", f"rule_{idx + 1}") or f"rule_{idx + 1}").strip()
        if not rule_id:
            rule_id = f"rule_{idx + 1}"

        try:
            priority = int(raw.get("priority", 1000))
        except Exception as e:
            raise ValueError(f"Rule '{rule_id}' has non-integer priority in {schema_file}") from e

        path_template = str(raw.get("path_template", "") or "").strip()
        if not path_template:
            raise ValueError(f"Rule '{rule_id}' missing path_template in {schema_file}")

        associate = raw.get("associate", {}) or {}
        if not isinstance(associate, dict):
            raise ValueError(f"Rule '{rule_id}' has non-mapping 'associate' in {schema_file}")

        variable_from = str(associate.get("variable_from", "") or "").strip()
        visualization_from = str(associate.get("visualization_from", "") or "").strip()
        fixed_variable = str(associate.get("variable", "") or "").strip()
        fixed_visualization = str(associate.get("visualization", "") or "").strip()

        if not (variable_from or fixed_variable):
            raise ValueError(
                f"Rule '{rule_id}' requires associate.variable_from or associate.variable in {schema_file}"
            )
        if not (visualization_from or fixed_visualization):
            raise ValueError(
                f"Rule '{rule_id}' requires associate.visualization_from or associate.visualization in {schema_file}"
            )

        compiled = _compile_path_template(path_template)
        rules.append(
            {
                "id": rule_id,
                "priority": priority,
                "order": idx,
                "path_template": path_template,
                "pattern": compiled,
                "variable_from": variable_from,
                "visualization_from": visualization_from,
                "fixed_variable": fixed_variable,
                "fixed_visualization": fixed_visualization,
            }
        )

    raw_name_map = data.get("physical_to_logical", {}) or {}
    exact_name_map: Dict[str, str] = {}
    regex_name_map: List[Dict[str, Any]] = []
    if raw_name_map:
        if not isinstance(raw_name_map, dict):
            raise ValueError(f"'physical_to_logical' must be a mapping in {schema_file}")

        # Shorthand form:
        # physical_to_logical:
        #   hll_pressure: pressure
        has_structured_keys = "exact" in raw_name_map or "regex" in raw_name_map
        if not has_structured_keys:
            for physical_name, logical_name in raw_name_map.items():
                p = str(physical_name or "").strip()
                l = str(logical_name or "").strip()
                if not p or not l:
                    continue
                exact_name_map[p] = l
        else:
            raw_exact = raw_name_map.get("exact", {}) or {}
            if not isinstance(raw_exact, dict):
                raise ValueError(f"'physical_to_logical.exact' must be a mapping in {schema_file}")
            for physical_name, logical_name in raw_exact.items():
                p = str(physical_name or "").strip()
                l = str(logical_name or "").strip()
                if not p or not l:
                    continue
                exact_name_map[p] = l

            raw_regex = raw_name_map.get("regex", []) or []
            if not isinstance(raw_regex, list):
                raise ValueError(f"'physical_to_logical.regex' must be a list in {schema_file}")
            for idx, item in enumerate(raw_regex):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"'physical_to_logical.regex[{idx}]' must be a mapping in {schema_file}"
                    )
                pattern_text = str(item.get("pattern", "") or "").strip()
                replace_text = str(item.get("replace", "") or "")
                if not pattern_text:
                    raise ValueError(
                        f"'physical_to_logical.regex[{idx}].pattern' is required in {schema_file}"
                    )
                try:
                    compiled_pattern = re.compile(pattern_text)
                except Exception as e:
                    raise ValueError(
                        f"Invalid regex pattern in physical_to_logical.regex[{idx}] "
                        f"for {schema_file}: {e}"
                    ) from e
                regex_name_map.append(
                    {
                        "pattern": compiled_pattern,
                        "replace": replace_text,
                    }
                )

    rules.sort(key=lambda r: (int(r["priority"]), int(r["order"])))
    return {
        "schema_file": schema_file,
        "schema_version": schema_version,
        "mode": mode,
        "on_unmatched": on_unmatched,
        "rules": rules,
        "physical_to_logical_exact": exact_name_map,
        "physical_to_logical_regex": regex_name_map,
    }


def _map_physical_to_logical_name(physical_name: str, schema: Optional[Dict[str, Any]]) -> str:
    name = str(physical_name or "")
    if not schema:
        return name

    exact_map = schema.get("physical_to_logical_exact", {}) or {}
    mapped = exact_map.get(name, None)
    if isinstance(mapped, str) and mapped:
        return mapped

    regex_rules = schema.get("physical_to_logical_regex", []) or []
    for rule in regex_rules:
        pattern = rule.get("pattern", None)
        replace = str(rule.get("replace", "") or "")
        if pattern is None:
            continue
        if pattern.search(name):
            out = pattern.sub(replace, name, count=1)
            if out:
                return out

    return name


def _display_name_from_physical_name(physical_name: str, schema: Optional[Dict[str, Any]]) -> str:
    mapped = _map_physical_to_logical_name(physical_name, schema)
    if mapped != physical_name:
        return mapped

    parts = [part for part in str(mapped or "").strip("/").split("/") if part]
    if parts:
        return parts[-1]

    return mapped


def _join_variable_id(source_dataset: str, variable_name: str) -> str:
    source = str(source_dataset or "").strip("/")
    name = str(variable_name or "").strip("/")
    if not name:
        return source
    if source and (name == source or name.startswith(source + "/")):
        return name
    return f"{source}/{name}".strip("/") if source else name


def _raw_variable_id(varpath: str, variable_name: str) -> str:
    return _join_variable_id(str(varpath or ""), str(variable_name or ""))


def _image_path_candidates(varpath: str) -> List[str]:
    """
    Build candidate logical paths for matching.
    Some campaigns append '/<width>x<height>' after image.<t>.png.
    """
    p = str(varpath or "").replace("\\", "/").strip("/")
    if not p:
        return []

    candidates = [p]
    parts = p.split("/")
    if parts and _IMAGE_SIZE_SEGMENT_RE.fullmatch(parts[-1]):
        trimmed = "/".join(parts[:-1]).strip("/")
        if trimmed and trimmed not in candidates:
            candidates.append(trimmed)
    return candidates


def _match_image_association(varpath: str, schema: Dict[str, Any]) -> Optional[Dict[str, str]]:
    candidates = _image_path_candidates(varpath)
    if not candidates:
        return None

    mode = str(schema.get("mode", "first_match_wins"))
    matches: List[Dict[str, str]] = []

    for rule in schema.get("rules", []):
        pattern = rule.get("pattern")
        if not pattern:
            continue

        for candidate in candidates:
            m = pattern.match(candidate)
            if not m:
                continue

            groups = m.groupdict()
            variable_name = str(rule.get("fixed_variable", "") or "")
            visualization_name = str(rule.get("fixed_visualization", "") or "")

            variable_from = str(rule.get("variable_from", "") or "")
            if variable_from:
                variable_name = str(groups.get(variable_from, "") or "")

            visualization_from = str(rule.get("visualization_from", "") or "")
            if visualization_from:
                visualization_name = str(groups.get(visualization_from, "") or "")

            matched = {
                "rule_id": str(rule.get("id", "") or ""),
                "candidate": candidate,
                "variable_name": variable_name,
                "visualization_name": visualization_name,
            }
            matches.append(matched)
            break

        if matches and mode == "first_match_wins":
            return matches[0]

    if not matches:
        return None

    if len(matches) > 1:
        first = matches[0]
        for m in matches[1:]:
            if (
                m.get("variable_name", "") != first.get("variable_name", "")
                or m.get("visualization_name", "") != first.get("visualization_name", "")
            ):
                print(
                    "[warn] conflicting image association matches for "
                    f"{varpath!r}; using first rule '{first.get('rule_id', '')}'"
                )
                break
    return matches[0]


def _json_object_or_empty(value: Any) -> Dict[str, Any]:
    """
    Decode JSON metadata stored by hpc-campaign visualization tables.

    The current API stores dictionaries, but this helper is intentionally
    forgiving so older or hand-written metadata does not break ingestion.
    """
    if value is None:
        return {}

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")

    if not isinstance(value, str):
        return {}

    text = value.strip()
    if not text:
        return {}

    try:
        decoded = json.loads(text)
    except Exception:
        return {"raw": text}

    if isinstance(decoded, dict):
        return decoded
    return {"value": decoded}


def _json_list_or_empty(value: Any) -> List[Any]:
    if value is None:
        return []

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")

    if isinstance(value, list):
        return list(value)

    if not isinstance(value, str):
        return []

    text = value.strip()
    if not text:
        return []

    try:
        decoded = json.loads(text)
    except Exception:
        return []

    return list(decoded) if isinstance(decoded, list) else []


def _activity_source_step(row: sqlite3.Row, chunk_index: int) -> int:
    if row["mapping_id"] is None:
        return chunk_index

    try:
        output_start = int(row["mapping_output_start"])
        count = int(row["mapping_count"])
    except Exception:
        return chunk_index

    offset = chunk_index - output_start
    if offset < 0 or offset >= count:
        return chunk_index

    encoding = str(row["mapping_encoding"] or "").strip().lower()
    if encoding in {"identity", "stride"}:
        try:
            source_start = int(row["mapping_source_start"])
            stride = int(row["mapping_stride"])
        except Exception:
            return chunk_index
        return source_start + offset * stride

    if encoding == "explicit":
        steps = _json_list_or_empty(row["mapping_explicit_steps"])
        if offset < len(steps):
            try:
                return int(steps[offset])
            except Exception:
                return chunk_index

    return chunk_index


def _visualization_short_name(sequence_name: str) -> str:
    """
    Convert a full sequence path to the user-facing visualization token.

    New API sequences are typically named:
      <dataset>/visualizations/<name>

    The viewer should show and filter on <name>, not the entire dataset path.
    """
    name = str(sequence_name or "").strip("/")
    marker = "/visualizations/"
    if marker in name:
        token = name.split(marker, 1)[1].strip("/")
        if token:
            return token

    if "/" in name:
        return name.rsplit("/", 1)[-1]
    return name


def _role_sort_key(role: str) -> tuple[int, str]:
    role_norm = str(role or "").strip().lower()
    return (_DISPLAY_ROLE_PRIORITY.get(role_norm, 50), role_norm)


def _normalize_visualization_variables(variables: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Dedupe visualization variables while preserving all roles per variable.

    A heatmap_contour visualization may reference the same variable twice with
    roles color-by and contour-by. The viewer only needs one document per
    variable, but keeping all roles makes the association inspectable later.
    """
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}

    for spec in variables:
        name = str(spec.get("name", "") or "").strip()
        if not name:
            continue

        source_dataset = str(spec.get("source_dataset", "") or "").strip()
        role = str(spec.get("role", "") or "variable").strip()
        role_norm = role.lower()
        key = (name, source_dataset)

        entry = grouped.setdefault(
            key,
            {
                "name": name,
                "source_dataset": source_dataset,
                "roles": [],
            },
        )
        if role_norm and role_norm not in entry["roles"]:
            entry["roles"].append(role_norm)

    normalized = list(grouped.values())
    for entry in normalized:
        entry["roles"].sort(key=_role_sort_key)

    normalized.sort(
        key=lambda entry: (
            min((_role_sort_key(role)[0] for role in entry.get("roles", [])), default=50),
            str(entry.get("name", "")),
            str(entry.get("source_dataset", "")),
        )
    )
    return normalized


def _display_visualization_variables(variables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Pick variables that should appear in the viewer's variable list.

    Axis variables like time are metadata for a plot, not usually the data a
    scientist wants to browse. If x-axis is the only role present, keep it as a
    fallback so the image remains reachable.
    """
    display_variables = [
        entry
        for entry in variables
        if set(entry.get("roles", [])) - _NONDISPLAY_ROLES
    ]
    return display_variables or variables


def _load_visualization_api_index(campaign_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Load hpc-campaign visualization API associations from the ACA SQLite tables.

    FileReader exposes image payloads as ADIOS variables, while SCALAR_FIELD
    payloads are stored as embedded ACA blobs. In both cases the semantic
    source-variable association lives in SQLite tables:

      visualization_sequence -> visualization_variable -> visualization_item

    The returned dictionary is keyed by visualization item dataset name. Image
    variables read through ADIOS may append a trailing '/<width>x<height>', so
    image callers should use _image_path_candidates() when looking up entries.
    """
    path = Path(campaign_path).expanduser()
    if not path.exists():
        return {}

    try:
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(f"[warn] could not open ACA SQLite metadata for visualization API: {e}")
        return {}

    try:
        available_tables = {
            str(row["name"])
            for row in con.execute("select name from sqlite_master where type = 'table'")
        }
        if not _VISUALIZATION_API_TABLES.issubset(available_tables):
            return {}

        scalar_metadata_select = "sf.metadata as scalar_field_metadata"
        scalar_metadata_join = "left join scalar_field as sf on sf.datasetid = item_dataset.rowid"
        if "scalar_field" not in available_tables:
            scalar_metadata_select = "NULL as scalar_field_metadata"
            scalar_metadata_join = ""

        # The visualization API describes payloads semantically, while the
        # payload datasets hold either rendered images or raw scalar fields.
        # This join builds the bridge: sequence -> item dataset, plus sequence
        # -> source vars.
        rows = con.execute(
            f"""
            select
                vs.visid as visid,
                vs.name as sequence_name,
                vs.vistype as visualization_kind,
                vs.metadata as sequence_metadata,
                vi.item_order as item_order,
                vi.item_type as item_type,
                vi.item_uuid as item_uuid,
                vi.metadata as item_metadata,
                item_dataset.name as item_name,
                item_dataset.fileformat as item_fileformat,
                {scalar_metadata_select},
                source_dataset.name as source_dataset,
                vv.variable_name as variable_name,
                vv.role as role
            from visualization_sequence as vs
            join visualization_item as vi on vi.visid = vs.visid
            left join dataset as item_dataset on item_dataset.uuid = vi.item_uuid
            {scalar_metadata_join}
            left join visualization_variable as vv on vv.visid = vs.visid
            left join dataset as source_dataset on source_dataset.rowid = vv.datasetid
            where upper(vi.item_type) in ('IMAGE', 'SCALAR_FIELD')
            order by vs.visid, vi.item_order, vv.variable_name, vv.role
            """
        )

        index: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            item_name = str(row["item_name"] or "").strip("/")
            if not item_name:
                continue

            sequence_name = str(row["sequence_name"] or "")
            # Key by the item dataset path because that is what FileReader gives
            # us for IMAGE variables and what direct SQLite reads use for
            # SCALAR_FIELD payloads.
            entry = index.setdefault(
                item_name,
                {
                    "sequence_id": int(row["visid"]),
                    "sequence_name": sequence_name,
                    "visualization_name": _visualization_short_name(sequence_name),
                    "visualization_kind": str(row["visualization_kind"] or ""),
                    "sequence_metadata": _json_object_or_empty(row["sequence_metadata"]),
                    "item_order": int(row["item_order"]),
                    "item_type": str(row["item_type"] or ""),
                    "item_uuid": str(row["item_uuid"] or ""),
                    "item_metadata": _json_object_or_empty(row["item_metadata"]),
                    "item_dataset_name": item_name,
                    "item_file_format": str(row["item_fileformat"] or ""),
                    "scalar_field_metadata": _json_object_or_empty(row["scalar_field_metadata"]),
                    "variables": [],
                },
            )

            variable_name = str(row["variable_name"] or "").strip()
            if variable_name:
                # variable_name is the simulation variable used by the
                # visualization; source_dataset names the BP/output dataset it
                # came from. role explains how the variable was used.
                entry["variables"].append(
                    {
                        "name": variable_name,
                        "role": str(row["role"] or "variable"),
                        "source_dataset": str(row["source_dataset"] or ""),
                    }
                )

        for entry in index.values():
            variables = _normalize_visualization_variables(entry.get("variables", []))
            entry["variables"] = variables
            entry["display_variables"] = _display_visualization_variables(variables)

        return index
    except sqlite3.Error as e:
        print(f"[warn] could not read visualization API metadata: {e}")
        return {}
    finally:
        con.close()


def _load_unified_representation_index(
    campaign_path: str,
) -> Dict[str, Dict[str, Any]]:
    """Load image and scalar-field chunks from the activity variable graph."""

    path = Path(campaign_path).expanduser()
    if not path.exists():
        return {}

    try:
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(f"[warn] could not open ACA SQLite metadata for unified variables: {e}")
        return {}

    try:
        available_tables = _sqlite_table_names(con)
        if not _UNIFIED_VARIABLE_TABLES.issubset(available_tables):
            return {}

        rows = con.execute(
            """
            select
                derived.variableid as derived_variable_id,
                derived.name as derived_variable_name,
                definition.name as derived_definition_name,
                derived_dataset.name as derived_dataset_name,
                chunk.chunkid as chunk_id,
                chunk.chunk_index as chunk_index,
                payload.name as payload_name,
                payload.uuid as payload_uuid,
                payload.fileformat as payload_fileformat,
                output.role as output_role,
                activity.uuid as activity_uuid,
                kind.name as action_name,
                spec.metadata as action_spec_metadata,
                input.inputid as input_id,
                input.role as source_role,
                source.name as source_variable_name,
                source_dataset.name as source_dataset_name,
                mapping.mappingid as mapping_id,
                mapping.output_start as mapping_output_start,
                mapping.count as mapping_count,
                mapping.encoding as mapping_encoding,
                mapping.source_start as mapping_source_start,
                mapping.stride as mapping_stride,
                mapping.explicit_steps as mapping_explicit_steps
            from activity_output as output
            join activity as activity on activity.activityid = output.activityid
            join activity_kind as kind on kind.kindid = activity.kindid
            join logical_variable as derived on derived.variableid = output.variableid
            join variable_definition as definition on definition.definitionid = derived.definitionid
            join dataset as derived_dataset on derived_dataset.rowid = derived.datasetid
            join variable_chunk as chunk on chunk.variableid = derived.variableid
            join dataset as payload on payload.rowid = chunk.payload_datasetid
            left join action_spec as spec on spec.specid = activity.specid
            left join activity_input as input on input.activityid = activity.activityid
            left join logical_variable as source on source.variableid = input.variableid
            left join dataset as source_dataset
                on source_dataset.rowid = source.datasetid
            left join activity_input_step_mapping as mapping
                on mapping.inputid = input.inputid
               and mapping.output_variableid = derived.variableid
               and chunk.chunk_index >= mapping.output_start
               and chunk.chunk_index < mapping.output_start + mapping.count
            where kind.name = 'visualization'
              and derived_dataset.deltime = 0
              and payload.deltime = 0
            order by derived.variableid, chunk.chunk_index, input.inputid
            """
        )

        chunks: Dict[tuple[int, int], Dict[str, Any]] = {}
        for row in rows:
            derived_id = int(row["derived_variable_id"])
            chunk_id = int(row["chunk_id"])
            key = (derived_id, chunk_id)
            chunk_index = int(row["chunk_index"])
            metadata = _json_object_or_empty(row["action_spec_metadata"])
            representation_kind = str(
                metadata.get("representation_kind", "")
                or metadata.get("item_type", "")
                or metadata.get("payload_type", "")
                or ""
            ).strip().lower()
            metadata_kind = str(metadata.get("kind", "") or "").strip().lower()
            payload_fileformat = str(row["payload_fileformat"] or "").strip()
            if payload_fileformat.upper() == "IMAGE":
                item_type = "IMAGE"
                representation_kind = "image"
            elif representation_kind in {
                "scalar_field",
                "scalar-field",
                "scalarfield",
                SCALAR_FIELD_ITEM_TYPE.lower(),
            } or metadata_kind == SCALAR_FIELD_VARIABLE_TYPE.lower():
                item_type = SCALAR_FIELD_ITEM_TYPE
                representation_kind = "scalar_field"
            else:
                continue

            visualization_name = str(metadata.get("visualization_name", "") or "").strip()
            if not visualization_name:
                visualization_name = str(row["derived_variable_name"] or "").strip("/").rsplit("/", 1)[-1]
            source_role = str(row["source_role"] or "").strip()
            source_step = _activity_source_step(row, chunk_index)

            entry = chunks.setdefault(
                key,
                {
                    "sequence_id": derived_id,
                    "sequence_name": (
                        f"{str(row['derived_dataset_name'] or '').strip('/')}"
                        f"/{str(row['derived_variable_name'] or '').strip('/')}"
                    ),
                    "visualization_name": visualization_name,
                    "visualization_kind": str(
                        metadata.get("visualization_kind", "") or representation_kind
                    ),
                    "sequence_metadata": metadata,
                    "item_order": chunk_index,
                    "item_type": item_type,
                    "item_uuid": str(row["payload_uuid"] or ""),
                    "item_metadata": {
                        "activity_uuid": str(row["activity_uuid"] or ""),
                        "output_role": str(row["output_role"] or ""),
                        "source_steps": {},
                    },
                    "item_dataset_name": str(row["payload_name"] or "").strip("/"),
                    "item_file_format": payload_fileformat,
                    "scalar_field_metadata": (
                        metadata if item_type == SCALAR_FIELD_ITEM_TYPE else {}
                    ),
                    "variables": [],
                    "association_source": "unified-variable",
                },
            )

            source_variable = str(row["source_variable_name"] or "").strip()
            if source_variable:
                if source_role:
                    entry["item_metadata"]["source_steps"][source_role] = source_step
                entry["item_metadata"].setdefault("source_step", source_step)
                variable_spec = {
                    "name": source_variable,
                    "role": source_role or "source",
                    "source_dataset": str(row["source_dataset_name"] or ""),
                }
                if variable_spec not in entry["variables"]:
                    entry["variables"].append(variable_spec)

        index: Dict[str, Dict[str, Any]] = {}
        for entry in chunks.values():
            variables = _normalize_visualization_variables(entry.get("variables", []))
            entry["variables"] = variables
            entry["display_variables"] = _display_visualization_variables(variables)
            item_name = str(entry.get("item_dataset_name", "") or "").strip("/")
            if item_name:
                index[item_name] = entry
        return index
    except sqlite3.Error as e:
        print(f"[warn] could not read unified variable metadata: {e}")
        return {}
    finally:
        con.close()


def _normalize_activity_inputs(inputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for spec in inputs:
        name = str(spec.get("name", "") or "").strip()
        if not name:
            continue
        source_dataset = str(spec.get("source_dataset", "") or "").strip()
        key = (name, source_dataset)
        entry = grouped.setdefault(
            key,
            {
                "name": name,
                "source_dataset": source_dataset,
                "definition": str(spec.get("definition", "") or ""),
                "roles": [],
            },
        )
        role = str(spec.get("role", "") or "source").strip().lower()
        if role and role not in entry["roles"]:
            entry["roles"].append(role)

    normalized = list(grouped.values())
    for entry in normalized:
        entry["roles"].sort(key=_role_sort_key)
    normalized.sort(
        key=lambda entry: (
            min((_role_sort_key(role)[0] for role in entry.get("roles", [])), default=50),
            str(entry.get("name", "")),
            str(entry.get("source_dataset", "")),
        )
    )
    return normalized


def _prov_reference(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("$", "")
    return str(value or "").strip()


def _prov_qname(value: Any) -> str:
    text = _prov_reference(value)
    if ":" in text:
        return text.rsplit(":", 1)[-1]
    return text


def _prov_type_values(attrs: Dict[str, Any]) -> List[Any]:
    raw = attrs.get("prov:type")
    if isinstance(raw, list):
        return raw
    if raw is None:
        return []
    return [raw]


def _prov_has_type(attrs: Dict[str, Any], name: str) -> bool:
    target = str(name or "").casefold()
    return any(_prov_qname(value).casefold() == target for value in _prov_type_values(attrs))


def _prov_activity_kind(attrs: Dict[str, Any]) -> str:
    if _prov_has_type(attrs, "QuantityOfInterest"):
        return "quantity_of_interest"
    if _prov_has_type(attrs, "Visualization"):
        return "visualization"
    for value in _prov_type_values(attrs):
        name = _prov_qname(value)
        if name:
            return name
    return ""


def _prov_action_metadata(
    entities: Dict[str, Any],
    usages: Dict[str, Any],
    activity_id: str,
) -> Dict[str, Any]:
    for usage in usages.values():
        if _prov_reference(usage.get("prov:activity")) != activity_id:
            continue
        if _prov_qname(usage.get("prov:role")).casefold() != "action_specification":
            continue
        plan = entities.get(_prov_reference(usage.get("prov:entity")), {})
        if not isinstance(plan, dict):
            continue
        return _json_object_or_empty(plan.get("prov:value", ""))
    return {}


def _prov_activity_operation(metadata: Dict[str, Any]) -> str:
    return str(
        metadata.get("operation", "")
        or metadata.get("visualization_type", "")
        or metadata.get("representation_kind", "")
        or metadata.get("kind", "")
        or ""
    ).strip()


def _prov_activity_uuid(activity_id: str) -> str:
    text = _prov_reference(activity_id)
    if "activity_" in text:
        return text.rsplit("activity_", 1)[-1]
    return text


def _load_prov_json_activity_provenance_index(
    con: sqlite3.Connection,
) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Load compact activity provenance from ACA PROV-JSON documents."""

    if "provenance_document" not in _sqlite_table_names(con):
        return {}

    rows = con.execute(
        """
        select content
        from provenance_document
        where format = 'prov-json' and active = 1
        order by name
        """
    ).fetchall()

    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        try:
            document = json.loads(str(row["content"] or ""))
        except Exception:
            continue
        if not isinstance(document, dict):
            continue

        entities = document.get("entity", {})
        activities = document.get("activity", {})
        usages = document.get("used", {})
        derivations = document.get("wasDerivedFrom", {})
        if not all(
            isinstance(value, dict)
            for value in (entities, activities, usages, derivations)
        ):
            continue

        for derivation in derivations.values():
            if not isinstance(derivation, dict):
                continue
            output_id = _prov_reference(derivation.get("prov:generatedEntity"))
            input_id = _prov_reference(derivation.get("prov:usedEntity"))
            activity_id = _prov_reference(derivation.get("prov:activity"))
            output = entities.get(output_id, {})
            source = entities.get(input_id, {})
            activity = activities.get(activity_id, {})
            if not all(isinstance(value, dict) for value in (output, source, activity)):
                continue
            if not _prov_has_type(output, "LogicalVariable"):
                continue

            output_dataset = str(output.get("hpc:datasetName", "") or "").strip("/")
            output_variable = str(output.get("hpc:variable", "") or "").strip("/")
            if not output_dataset or not output_variable:
                continue

            metadata = _prov_action_metadata(entities, usages, activity_id)
            key = (output_dataset, output_variable)
            entry = grouped.setdefault(
                key,
                {
                    "activity_uuid": _prov_activity_uuid(activity_id),
                    "activity_kind": _prov_activity_kind(activity),
                    "activity_operation": _prov_activity_operation(metadata),
                    "activity_metadata": metadata,
                    "output_role": "",
                    "output_definition": str(
                        output.get("hpc:variableDefinition", "") or ""
                    ),
                    "inputs": [],
                },
            )

            source_variable = str(source.get("hpc:variable", "") or "").strip()
            if not source_variable:
                continue
            usage = usages.get(_prov_reference(derivation.get("prov:usage")), {})
            input_spec = {
                "name": source_variable,
                "definition": str(source.get("hpc:variableDefinition", "") or ""),
                "role": (
                    _prov_qname(usage.get("prov:role"))
                    if isinstance(usage, dict)
                    else "source"
                ),
                "source_dataset": str(source.get("hpc:datasetName", "") or ""),
            }
            if input_spec not in entry["inputs"]:
                entry["inputs"].append(input_spec)

    for entry in grouped.values():
        entry["inputs"] = _normalize_activity_inputs(entry.get("inputs", []))
    return grouped


def _load_activity_provenance_index(campaign_path: str) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Load compact activity provenance keyed by output dataset and variable."""

    path = Path(campaign_path).expanduser()
    if not path.exists():
        return {}

    try:
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(f"[warn] could not open ACA SQLite metadata for activities: {e}")
        return {}

    try:
        available_tables = _sqlite_table_names(con)
        required = {
            "action_spec",
            "activity",
            "activity_input",
            "activity_kind",
            "activity_output",
            "dataset",
            "logical_variable",
            "variable_definition",
        }
        if not required.issubset(available_tables):
            return _load_prov_json_activity_provenance_index(con)

        rows = con.execute(
            """
            select
                derived_dataset.name as output_dataset_name,
                derived.name as output_variable_name,
                derived_definition.name as output_definition_name,
                output.role as output_role,
                activity.uuid as activity_uuid,
                kind.name as activity_kind,
                spec.metadata as action_spec_metadata,
                input.inputid as input_id,
                input.role as input_role,
                source.name as input_variable_name,
                source_definition.name as input_definition_name,
                source_dataset.name as input_dataset_name
            from activity_output as output
            join activity as activity on activity.activityid = output.activityid
            join activity_kind as kind on kind.kindid = activity.kindid
            join logical_variable as derived on derived.variableid = output.variableid
            join variable_definition as derived_definition
                on derived_definition.definitionid = derived.definitionid
            join dataset as derived_dataset on derived_dataset.rowid = derived.datasetid
            left join action_spec as spec on spec.specid = activity.specid
            left join activity_input as input on input.activityid = activity.activityid
            left join logical_variable as source on source.variableid = input.variableid
            left join variable_definition as source_definition
                on source_definition.definitionid = source.definitionid
            left join dataset as source_dataset on source_dataset.rowid = source.datasetid
            order by derived_dataset.name, derived.name, input.inputid
            """
        )

        grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
        for row in rows:
            output_dataset = str(row["output_dataset_name"] or "").strip("/")
            output_variable = str(row["output_variable_name"] or "").strip("/")
            if not output_dataset or not output_variable:
                continue
            key = (output_dataset, output_variable)
            metadata = _json_object_or_empty(row["action_spec_metadata"])
            operation = str(
                metadata.get("operation", "")
                or metadata.get("visualization_type", "")
                or metadata.get("representation_kind", "")
                or metadata.get("kind", "")
                or ""
            ).strip()
            entry = grouped.setdefault(
                key,
                {
                    "activity_uuid": str(row["activity_uuid"] or ""),
                    "activity_kind": str(row["activity_kind"] or ""),
                    "activity_operation": operation,
                    "activity_metadata": metadata,
                    "output_role": str(row["output_role"] or ""),
                    "output_definition": str(row["output_definition_name"] or ""),
                    "inputs": [],
                },
            )
            source_variable = str(row["input_variable_name"] or "").strip()
            if not source_variable:
                continue
            input_spec = {
                "name": source_variable,
                "definition": str(row["input_definition_name"] or ""),
                "role": str(row["input_role"] or "source"),
                "source_dataset": str(row["input_dataset_name"] or ""),
            }
            if input_spec not in entry["inputs"]:
                entry["inputs"].append(input_spec)

        for entry in grouped.values():
            entry["inputs"] = _normalize_activity_inputs(entry.get("inputs", []))
        return grouped or _load_prov_json_activity_provenance_index(con)
    except sqlite3.Error as e:
        print(f"[warn] could not read activity provenance metadata: {e}")
        return {}
    finally:
        con.close()


def _lookup_visualization_api_image(
    varpath: str,
    visualization_api_index: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    # ADIOS may expose image datasets with an added size suffix such as
    # /480x480. Try both the exact path and normalized candidates.
    for candidate in _image_path_candidates(varpath):
        entry = visualization_api_index.get(candidate)
        if entry is not None:
            return entry
    return None


def _to_float(value: Any) -> Optional[float]:
    """
    Best-effort conversion to float.
    Handles ADIOS metadata values that may be strings.
    Returns None if conversion fails.
    """
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        try:
            return float(str(value).strip())
        except Exception:
            return None


def extract_file_var(input: str) -> tuple[str, str, str, str, str]:
    parts = input.split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid file variable format: {input}")
    producer = parts[0]
    casename = parts[1]
    varname = parts[-1]
    filename = parts[-2]
    varpath = "/".join(parts[0:-1])

    bp_idx = next(
        (i for i, part in enumerate(parts) if _ADIOS_DATASET_SEGMENT_RE.search(part)),
        -1,
    )
    if bp_idx >= 0:
        filename = parts[bp_idx]
        if bp_idx - 1 >= 0:
            casename = parts[bp_idx - 1]
        if bp_idx + 1 < len(parts):
            varname = "/".join(parts[bp_idx + 1 :])
            varpath = "/".join(parts[: bp_idx + 1])

    return (varname, filename, varpath, producer, casename)


def extract_file_var_img(input: str) -> tuple[str, str, str, str, str]:
    parts = input.split("/")
    if len(parts) < 4:
        raise ValueError(f"Invalid image variable format: {input}")

    producer, casename, filename, varname, _ = _parse_image_path_components(parts)
    varpath = input
    return (varname, filename, varpath, producer, casename)


def get_visualization_name(input: str) -> str:
    parts = input.split("/")
    _, _, _, _, visualization_name = _parse_image_path_components(parts)
    return visualization_name


def _parse_image_path_components(parts: list[str]) -> tuple[str, str, str, str, str]:
    """
    Parse campaign image logical paths by anchoring on the .bp/.bpN segment.

    Expected robust layout:
      <producer>/<optional-casename>/.../<file.bpN>/<var>/images/<vis>/<image>.png[/<size>]
    """
    producer = parts[0] if parts else ""
    casename = parts[1] if len(parts) > 1 else ""
    filename = parts[2] if len(parts) > 2 else ""
    varname = parts[3] if len(parts) > 3 else ""
    visualization_name = ""

    bp_idx = next(
        (i for i, part in enumerate(parts) if _ADIOS_DATASET_SEGMENT_RE.search(part)),
        -1,
    )
    if bp_idx >= 0:
        filename = parts[bp_idx]
        if bp_idx - 1 >= 0:
            casename = parts[bp_idx - 1]
        if bp_idx + 1 < len(parts):
            varname = parts[bp_idx + 1]

        if "images" in parts[bp_idx + 1 :]:
            rel_idx = parts[bp_idx + 1 :].index("images")
            images_idx = bp_idx + 1 + rel_idx
            if images_idx + 1 < len(parts):
                visualization_name = parts[images_idx + 1]
        elif bp_idx + 2 < len(parts):
            candidate = parts[bp_idx + 2]
            if not candidate.lower().endswith(".png") and not re.fullmatch(r"\d+x\d+", candidate):
                visualization_name = candidate

    return producer, casename, filename, varname, visualization_name


def _source_dataset_from_path(varpath: str) -> str:
    """
    Return the logical source dataset path for an ADIOS variable/image path.

    New visualization API entries carry this explicitly. This fallback keeps
    legacy and raw-variable documents queryable through the same field.
    """
    parts = str(varpath or "").strip("/").split("/")
    if not parts or parts == [""]:
        return ""

    bp_idx = next(
        (i for i, part in enumerate(parts) if _ADIOS_DATASET_SEGMENT_RE.search(part)),
        -1,
    )
    if bp_idx >= 0:
        return "/".join(parts[: bp_idx + 1])

    if len(parts) > 1:
        return "/".join(parts[:-1])
    return str(varpath or "").strip("/")


# Match ".../image.000450.png/..." and capture 000450
_FRAME_RE = re.compile(r"(?:^|/)(?:image)\.(\d+)\.png(?:/|$)")


def extract_frame_index_from_varpath(varpath: str) -> Optional[int]:
    if not varpath:
        return None
    m = _FRAME_RE.search(varpath)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _extract_min_max_from_varinfo(varinfo: Any) -> tuple[Optional[float], Optional[float]]:
    """
    ADIOS available_variables() returns a dict of metadata values.
    Typically 'Min'/'Max' appear as strings.
    We normalize those into numeric min/max fields for DB querying.
    """
    if not isinstance(varinfo, dict):
        return (None, None)

    # Primary: top-level keys from ADIOS variable info
    raw_min = varinfo.get("Min", None)
    raw_max = varinfo.get("Max", None)

    # Some pipelines might store these under different capitalization.
    if raw_min is None:
        raw_min = varinfo.get("min", None)
    if raw_max is None:
        raw_max = varinfo.get("max", None)

    fmin = _to_float(raw_min)
    fmax = _to_float(raw_max)
    return (fmin, fmax)


def parse_campaign(
    campaign_path: str,
    collection,
    image_association_schema_path: Optional[str] = None,
    campaign_schema_path: Optional[str] = None,
):
    print("reading: ", campaign_path)
    schema_file, _schema_text = _load_image_association_schema_text(image_association_schema_path)
    image_assoc_schema = None
    if schema_file:
        print("image association schema:", schema_file)
        image_assoc_schema = _load_image_association_schema(schema_file, _schema_text or "")
        print(
            "image association mode:",
            image_assoc_schema.get("mode"),
            "on_unmatched:",
            image_assoc_schema.get("on_unmatched"),
            "rules:",
            len(image_assoc_schema.get("rules", [])),
            "name_map_exact:",
            len(image_assoc_schema.get("physical_to_logical_exact", {})),
            "name_map_regex:",
            len(image_assoc_schema.get("physical_to_logical_regex", [])),
        )
    var_stats = {}
    image_assoc_matched = 0
    image_assoc_unmatched = 0
    visualization_api_matched = 0
    scalar_field_visualization_count = 0
    skipped_non_visual_data = 0
    # Load explicit visualization metadata once from SQLite, then use it while
    # walking ADIOS variables. Prefer the newer activity-backed representation
    # graph when present, but keep accepting provenance-branch campaigns that
    # still describe rendered output through visualization_* tables.
    legacy_visualization_api_index = _load_visualization_api_index(campaign_path)
    unified_representation_index = _load_unified_representation_index(campaign_path)
    visualization_api_index = unified_representation_index or legacy_visualization_api_index
    activity_provenance_index = _load_activity_provenance_index(campaign_path)
    visualization_metadata_source = (
        "activity-backed"
        if unified_representation_index
        else "provenance visualization"
        if legacy_visualization_api_index
        else ""
    )
    if unified_representation_index:
        print(
            "activity-backed variable representation chunks:",
            len(unified_representation_index),
        )
    elif legacy_visualization_api_index:
        print(
            "provenance visualization metadata items:",
            len(legacy_visualization_api_index),
        )
    if activity_provenance_index:
        print("activity provenance outputs:", len(activity_provenance_index))

    dataset_rows = _load_campaign_dataset_rows(campaign_path)
    dataset_names = [row["name"] for row in dataset_rows if row.get("name")]
    campaign_timeseries = _load_campaign_timeseries(campaign_path)
    campaign_schema = _load_campaign_schema(
        campaign_path,
        dataset_names,
        campaign_timeseries,
        campaign_schema_path=campaign_schema_path,
    )
    if campaign_schema:
        print(
            "campaign schema:",
            campaign_schema.get("schema_name", ""),
            "groups:",
            len(campaign_schema.get("file_groups", {}) or {}),
        )

    with FileReader(campaign_path) as fr:
        vars_dict = fr.available_variables()
        attrs_dict = fr.available_attributes()
        schema_context = _build_schema_time_context(campaign_schema, fr, vars_dict)

        for varname, varinfo in vars_dict.items():
            if any(
                varname == schema_name or varname.startswith(schema_name + "/")
                for schema_name in _CAMPAIGN_SCHEMA_DATASET_NAMES
            ):
                continue

            type_key = varname + "/__dataset_type__"
            loc_key = varname + "/__dataset_location__"

            var_type = "variable"
            var_location = "local"
            if type_key in attrs_dict:
                var_type = _to_simple_string(attrs_dict[type_key]["Value"])
            if loc_key in attrs_dict:
                var_location = _to_simple_string(attrs_dict[loc_key]["Value"])
            var_type = str(var_type or "variable").strip().lower()

            if var_type == "variable":
                var, file, varpath, producer, casename = extract_file_var(varname)
                source_dataset = varpath
            elif var_type == "image":
                var, file, varpath, producer, casename = extract_file_var_img(varname)
                source_dataset = _source_dataset_from_path(varpath)
            else:
                skipped_non_visual_data += 1
                continue

            physical_var = str(var or "")
            var = _map_physical_to_logical_name(physical_var, image_assoc_schema)
            metadata = varinfo

            #print('Var: ', var, 'varpath: ', varpath)
            ## check if it's a statistical variable (e.g. ends with "_stats") and if so, include min/max in the document for easier querying
            if var_type == 'variable' and '_stats' in varpath :
                data = []
                n = var.rfind('_')
                baseVar, statType = var[:n], var[n+1:]
                print('Stat variable detected: ', var, 'varpath: ', varpath, baseVar, statType)
                data = fr.read(varname)
                if baseVar not in var_stats :
                    var_stats[baseVar] = []
                var_stats[baseVar].append((producer, source_dataset, statType, data[0], physical_var))
                continue

            if var_type == "image":
                visualization_name = get_visualization_name(varname)
                association_rule_id = ""
                association_source = "legacy"
                visualization_api_entry = _lookup_visualization_api_image(varpath, visualization_api_index)
                visualization_variables: List[Dict[str, Any]] = []
                # Default legacy association: the image belongs to the variable
                # parsed from its path. The visualization API can replace this
                # with one or more explicit source variables and roles.
                image_variable_records = [
                    {
                        "physical_var": physical_var,
                        "logical_var": var,
                        "variable_id": physical_var,
                        "roles": [],
                        "source_dataset": source_dataset,
                    }
                ]

                if visualization_api_entry is not None:
                    visualization_api_matched += 1
                    # Prefer API metadata over path-derived names. This is what
                    # lets a heatmap/contour/streamline image be attached to the
                    # actual simulation variable instead of the image dataset.
                    visualization_name = str(
                        visualization_api_entry.get("visualization_name", "") or visualization_name
                    )
                    visualization_variables = list(visualization_api_entry.get("variables", []))
                    display_variables = list(visualization_api_entry.get("display_variables", []))
                    if display_variables:
                        # Insert one viewer document per displayed source
                        # variable. Multi-variable visualizations therefore show
                        # up under each meaningful variable in the UI.
                        image_variable_records = []
                        for api_var in display_variables:
                            api_physical_var = str(api_var.get("name", "") or "").strip()
                            if not api_physical_var:
                                continue
                            image_variable_records.append(
                                {
                                    "physical_var": api_physical_var,
                                    "logical_var": _map_physical_to_logical_name(
                                        api_physical_var,
                                        image_assoc_schema,
                                    ),
                                    "variable_id": api_physical_var,
                                    "roles": list(api_var.get("roles", [])),
                                    "source_dataset": str(api_var.get("source_dataset", "") or ""),
                                }
                            )
                    association_source = str(
                        visualization_api_entry.get(
                            "association_source",
                            "visualization-api",
                        )
                        or "visualization-api"
                    )

                if image_assoc_schema is not None:
                    assoc = _match_image_association(varpath, image_assoc_schema)
                    if assoc:
                        image_assoc_matched += 1
                        mapped_var = str(assoc.get("variable_name", "") or "").strip()
                        mapped_vis = str(assoc.get("visualization_name", "") or "").strip()

                        if mapped_var:
                            physical_var = mapped_var
                            var = _map_physical_to_logical_name(mapped_var, image_assoc_schema)
                            image_variable_records = [
                                {
                                    "physical_var": physical_var,
                                    "logical_var": var,
                                    "variable_id": physical_var,
                                    "roles": [],
                                    "source_dataset": source_dataset,
                                }
                            ]
                        if mapped_vis:
                            visualization_name = mapped_vis
                        association_rule_id = str(assoc.get("rule_id", "") or "")
                        association_source = "schema"
                    elif visualization_api_entry is None:
                        image_assoc_unmatched += 1
                        action = str(image_assoc_schema.get("on_unmatched", "warn"))
                        msg = (
                            f"image association schema did not match path: {varpath!r} "
                            f"(fallback to legacy path parser)"
                        )
                        if action == "error":
                            raise ValueError(msg)
                        if action == "warn":
                            print("[warn]", msg)
                        association_source = "legacy-unmatched"

                if not image_variable_records:
                    image_variable_records = [
                        {
                            "physical_var": physical_var,
                            "logical_var": var,
                            "variable_id": physical_var,
                            "roles": [],
                            "source_dataset": source_dataset,
                        }
                    ]

                # frame_index from ".../image.000450.png/..."
                frame_index = extract_frame_index_from_varpath(varpath)
                if frame_index is None:
                    # fallback: try to locate the "image.*.png" segment (avoid 480x480)
                    parts = varpath.split("/")
                    candidate = next((p for p in parts if p.startswith("image.") and p.endswith(".png")), "")
                    if candidate:
                        digits = re.findall(r"(\d+)", candidate)
                        frame_index = int(digits[-1]) if digits else None
                frame_index_value = int(frame_index) if frame_index is not None else None
                item_order_value = None
                if visualization_api_entry is not None:
                    try:
                        item_order_value = int(visualization_api_entry.get("item_order", 0) or 0)
                    except Exception:
                        item_order_value = None
                    if frame_index_value is None and item_order_value is not None:
                        frame_index_value = item_order_value
                    filtered_records = [
                        record
                        for record in image_variable_records
                        if _visualization_record_matches_frame(
                            schema_context,
                            str(record.get("source_dataset", "") or source_dataset),
                            frame_index_value,
                            item_order_value,
                        )
                    ]
                    if filtered_records:
                        image_variable_records = filtered_records

                base_document = {
                    "campaign_path": campaign_path,
                    "file": file,
                    "visualization_name": visualization_name,
                    "variable_path": varpath,
                    "variable_type": var_type,
                    "producer": producer,
                    "casename": casename,
                    "variable_location": var_location,
                    "metadata": metadata,
                    "movie_cache": 1,
                    "frame_index": frame_index_value if frame_index_value is not None else 0,
                    "image_storage": "aca",
                    "association_source": association_source,
                    "association_rule_id": association_rule_id,
                }

                if visualization_api_entry is not None:
                    # Preserve the raw API metadata so downstream UI or
                    # debugging code can inspect the original sequence/item
                    # relationship without reopening the ACA SQLite database.
                    base_document.update(
                        {
                            "visualization_sequence_name": str(
                                visualization_api_entry.get("sequence_name", "") or ""
                            ),
                            "visualization_kind": str(
                                visualization_api_entry.get("visualization_kind", "") or ""
                            ),
                            "visualization_variables": visualization_variables,
                            "visualization_item_order": int(
                                visualization_api_entry.get("item_order", 0) or 0
                            ),
                            "visualization_item_uuid": str(
                                visualization_api_entry.get("item_uuid", "") or ""
                            ),
                            "visualization_sequence_metadata": visualization_api_entry.get(
                                "sequence_metadata",
                                {},
                            ),
                            "visualization_item_metadata": visualization_api_entry.get(
                                "item_metadata",
                                {},
                            ),
                        }
                    )

                for record in image_variable_records:
                    record_source_dataset = str(record.get("source_dataset", "") or source_dataset)
                    document = dict(base_document)
                    # These fields are the normalized viewer-facing association:
                    # which source variable this image represents, which source
                    # dataset it came from, and which visualization roles it had.
                    document.update(
                        {
                            "variable_id": record.get("variable_id")
                            or record["physical_var"],
                            "variable_name": record["logical_var"],
                            "variable_name_physical": record["physical_var"],
                            "source_dataset": record_source_dataset,
                            "visualization_roles": record["roles"],
                            "visualization_source_dataset": record_source_dataset,
                        }
                    )
                    document.update(
                        _schema_metadata_for_variable(
                            schema_context,
                            record_source_dataset or source_dataset,
                            str(record.get("variable_id") or record["physical_var"]),
                            frame_index=frame_index_value,
                            include_time_values=False,
                        )
                    )
                    collection.insert_one(document)
                continue
            else:
                # NEW: normalize min/max into top-level numeric fields for querying
                fmin, fmax = _extract_min_max_from_varinfo(varinfo)

                document = {
                    "campaign_path": campaign_path,
                    "file": file,
                    "variable_id": physical_var,
                    "variable_name": var,
                    "variable_name_physical": physical_var,
                    "source_dataset": source_dataset,
                    "variable_path": varpath,
                    "variable_type": var_type,
                    "producer": producer,
                    "casename": casename,
                    "variable_location": var_location,
                    "metadata": metadata,
                    # These fields enable queries like: min > 1.0, max <= 10
                    # They will be absent/None if not available.
                    "min": fmin,
                    "max": fmax,
                }
                activity_provenance = activity_provenance_index.get(
                    (str(source_dataset or "").strip("/"), physical_var.strip("/"))
                )
                if activity_provenance:
                    document["activity_provenance"] = activity_provenance
                document.update(
                    _schema_metadata_for_variable(
                        schema_context,
                        source_dataset or file,
                        physical_var,
                        include_time_values=True,
                    )
                )

            collection.insert_one(document)

    for visualization_api_entry in visualization_api_index.values():
        item_type = str(visualization_api_entry.get("item_type", "") or "").strip().upper()
        if item_type != SCALAR_FIELD_ITEM_TYPE:
            continue

        item_name = str(visualization_api_entry.get("item_dataset_name", "") or "").strip("/")
        if not item_name:
            continue

        visualization_name = str(visualization_api_entry.get("visualization_name", "") or "")
        scalar_metadata = dict(visualization_api_entry.get("scalar_field_metadata", {}) or {})
        item_metadata = dict(visualization_api_entry.get("item_metadata", {}) or {})

        display_variables = list(visualization_api_entry.get("display_variables", []))
        scalar_variable_records: List[Dict[str, Any]] = []
        if display_variables:
            for api_var in display_variables:
                api_physical_var = str(api_var.get("name", "") or "").strip()
                if not api_physical_var:
                    continue
                scalar_variable_records.append(
                    {
                        "physical_var": api_physical_var,
                        "logical_var": _map_physical_to_logical_name(
                            api_physical_var,
                            image_assoc_schema,
                        ),
                        "variable_id": api_physical_var,
                        "roles": list(api_var.get("roles", [])),
                        "source_dataset": str(api_var.get("source_dataset", "") or ""),
                    }
                )

        if not scalar_variable_records:
            fallback_var = visualization_name or item_name
            scalar_variable_records = [
                {
                    "physical_var": fallback_var,
                    "logical_var": _map_physical_to_logical_name(fallback_var, image_assoc_schema),
                    "variable_id": fallback_var,
                    "roles": [],
                    "source_dataset": "",
                }
            ]

        fmin = _to_float(scalar_metadata.get("min", None))
        fmax = _to_float(scalar_metadata.get("max", None))

        base_document = {
            "campaign_path": campaign_path,
            "file": "",
            "visualization_name": visualization_name,
            "variable_path": item_name,
            "variable_type": SCALAR_FIELD_VARIABLE_TYPE,
            "payload_type": SCALAR_FIELD_ITEM_TYPE,
            "producer": "",
            "casename": "",
            "variable_location": "local",
            "metadata": scalar_metadata,
            "scalar_field_metadata": scalar_metadata,
            "movie_cache": 1,
            "frame_index": int(visualization_api_entry.get("item_order", 0) or 0),
            "image_storage": "aca",
            "association_source": str(
                visualization_api_entry.get(
                    "association_source",
                    "visualization-api",
                )
                or "visualization-api"
            ),
            "association_rule_id": "",
            "visualization_sequence_name": str(visualization_api_entry.get("sequence_name", "") or ""),
            "visualization_kind": str(visualization_api_entry.get("visualization_kind", "") or ""),
            "visualization_variables": list(visualization_api_entry.get("variables", [])),
            "visualization_item_order": int(visualization_api_entry.get("item_order", 0) or 0),
            "visualization_item_uuid": str(visualization_api_entry.get("item_uuid", "") or ""),
            "visualization_item_type": item_type,
            "visualization_sequence_metadata": visualization_api_entry.get("sequence_metadata", {}),
            "visualization_item_metadata": item_metadata,
            "min": fmin,
            "max": fmax,
        }

        for record in scalar_variable_records:
            record_source_dataset = str(record.get("source_dataset", "") or "")
            document = dict(base_document)
            document.update(
                {
                    "variable_id": record.get("variable_id") or record["physical_var"],
                    "variable_name": record["logical_var"],
                    "variable_name_physical": record["physical_var"],
                    "source_dataset": record_source_dataset,
                    "visualization_roles": record["roles"],
                    "visualization_source_dataset": record_source_dataset,
                }
            )
            document.update(
                _schema_metadata_for_variable(
                    schema_context,
                    record_source_dataset,
                    str(record.get("variable_id") or record["physical_var"]),
                    frame_index=int(visualization_api_entry.get("item_order", 0) or 0),
                    include_time_values=False,
                )
            )
            collection.insert_one(document)
            scalar_field_visualization_count += 1

    print('Add statistics')
    for v in var_stats.items() :
        vname, stats = v
        logical_vname = _map_physical_to_logical_name(vname, image_assoc_schema)
        for stat in stats :
            producer, source_dataset, statType, data, output_variable = stat
            document = {"campaign_path": campaign_path,
                        "variable_id": vname,
                        "variable_name": logical_vname,
                        "variable_name_physical": vname,
                        "source_dataset": source_dataset,
                        "variable_type": 'statistic',
                        "producer": producer,
                        "statistic_type": statType,
                        "data": data.tolist()}
            activity_provenance = activity_provenance_index.get(
                (str(source_dataset or "").strip("/"), str(output_variable or "").strip("/"))
            )
            if activity_provenance:
                document["activity_provenance"] = activity_provenance
            collection.insert_one(document)

    if image_assoc_schema is not None:
        print(
            "image association summary:",
            f"matched={image_assoc_matched}",
            f"unmatched={image_assoc_unmatched}",
            f"mode={image_assoc_schema.get('mode')}",
            f"on_unmatched={image_assoc_schema.get('on_unmatched')}",
        )
    if visualization_api_index:
        print(
            f"{visualization_metadata_source} representation summary:",
            f"matched={visualization_api_matched}",
            f"available={len(visualization_api_index)}",
        )
    if scalar_field_visualization_count:
        print("scalar field visualization associations:", scalar_field_visualization_count)
    if skipped_non_visual_data:
        print("Skipped non-visual datasets:", skipped_non_visual_data)

    print(collection.distinct("campaign_path"))
    print(collection.count_documents({}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign", help="Path to .aca campaign file")
    ap.add_argument("--clear", action="store_true", help="Clear collection before ingest")
    ap.add_argument(
        "--image-association-schema",
        default=None,
        help="Optional path to image association schema text/YAML file.",
    )
    ap.add_argument(
        "--campaign-schema",
        default=None,
        help="Optional path to campaign schema YAML; overrides embedded schema.yaml.",
    )
    args = ap.parse_args()

    if args.clear:
        clear_collection(args.campaign)

    collection = get_collection(args.campaign)
    parse_campaign(
        args.campaign,
        collection,
        image_association_schema_path=args.image_association_schema,
        campaign_schema_path=args.campaign_schema,
    )

    coll = get_collection(args.campaign)
    print("Inserted docs:", coll.count_documents({"campaign_path": args.campaign}))
    print("Distinct variable_name:", len(coll.distinct("variable_name")))


if __name__ == "__main__":
    main()
