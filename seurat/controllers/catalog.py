"""Catalog, query, and variable-selection controller behavior."""

import json
from typing import Any, Dict, List, Optional

from application import NavigationNode
from config import MAX_MOVIE_FRAMES, MOVIE_FPS
from query_parser import and_filter, python_query_to_filters
from seurat.models.source_selection import (
    normalize_source_keys,
    source_fields_from_row,
    source_filter_from_row,
)
from seurat.state import clear_right_panes
from state_init import fmt


def _variable_groups_from_navigation(
    nodes: List[NavigationNode],
) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    for node in nodes:
        variables: List[Dict[str, str]] = []
        for child in node.get("children", []) or []:
            if child.get("kind") != "variable":
                continue
            resource = child.get("resource") or {}
            variable_id = str(resource.get("variable_id", "") or "")
            if not variable_id:
                continue
            variables.append(
                {
                    "id": variable_id,
                    "name": str(resource.get("name", "") or ""),
                    "label": str(
                        resource.get("label", "")
                        or child.get("label", "")
                        or variable_id
                    ),
                    "path": str(resource.get("path", "") or ""),
                    "source_dataset": str(resource.get("source_dataset", "") or ""),
                }
            )
        if variables:
            group: Dict[str, Any] = {
                "name": str(node.get("label", "") or ""),
                "variables": variables,
            }
            resource = node.get("resource") or {}
            file_count = int(resource.get("file_count", 0) or 0)
            if file_count > 1:
                group["file_count"] = file_count
            groups.append(group)
    return groups


def _filter_variable_groups(
    groups: List[Dict[str, Any]],
    search_text: Any,
) -> List[Dict[str, Any]]:
    """Filter catalog groups locally without changing the canonical catalog."""

    needle = str(search_text or "").strip().casefold()
    if not needle:
        return list(groups or [])

    filtered: List[Dict[str, Any]] = []
    variable_fields = (
        "id",
        "name",
        "label",
        "path",
        "source_dataset",
    )
    for raw_group in groups or []:
        if not isinstance(raw_group, dict):
            continue
        group = dict(raw_group)
        variables = [
            variable
            for variable in (raw_group.get("variables", []) or [])
            if isinstance(variable, dict)
        ]
        group_matches = needle in str(
            raw_group.get("name", "") or ""
        ).casefold()
        if group_matches:
            matches = variables
        else:
            matches = [
                variable
                for variable in variables
                if any(
                    needle in str(variable.get(field, "") or "").casefold()
                    for field in variable_fields
                )
            ]
        if matches:
            group["variables"] = matches
            filtered.append(group)
    return filtered


def _display_representation_summary(raw: Any) -> Dict[str, Any]:
    representation = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        "id": str(representation.get("id", "") or ""),
        "label": str(representation.get("label", "") or ""),
        "kind": str(representation.get("kind", "") or ""),
        "data_model": str(representation.get("data_model", "") or ""),
        "source_data_model": str(
            representation.get("source_data_model", "") or ""
        ),
        "shape": str(representation.get("shape", "") or ""),
        "axes": str(representation.get("axes", "") or ""),
        "num_frames": int(representation.get("num_frames", 0) or 0),
        "num_sources": int(representation.get("num_sources", 0) or 0),
        "global_min": fmt(representation.get("global_min", None)),
        "global_max": fmt(representation.get("global_max", None)),
        "mean_min": fmt(representation.get("mean_min", None)),
        "mean_max": fmt(representation.get("mean_max", None)),
        "median_min": fmt(representation.get("median_min", None)),
        "median_max": fmt(representation.get("median_max", None)),
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(item.get(key, ""))
        if value:
            return value
    return ""


def _source_label_for_provenance(row: Dict[str, Any]) -> str:
    label = _first_text(
        row,
        "sourceName",
        "source_label",
        "schema_file_group",
        "source_dataset",
    )
    if label:
        return label
    return "/".join(
        part
        for part in (
            _text(row.get("producer", "")),
            _text(row.get("casename", "")),
            _text(row.get("file", "")),
        )
        if part
    )


def _dict_value(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_value(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _short_variable_name(value: Any) -> str:
    name = _text(value).strip("/")
    if "/" in name:
        return name.rsplit("/", 1)[-1]
    return name


def _input_roles(item: Dict[str, Any]) -> List[str]:
    roles = item.get("roles", [])
    if isinstance(roles, list):
        return [_text(role).lower() for role in roles if _text(role)]
    role = _text(item.get("role", "")).lower()
    return [role] if role else []


def _display_input_role(role: str) -> str:
    normalized = _text(role).lower().replace("-", "_")
    if not normalized:
        return ""
    if normalized in {"streamline_0", "streamline_x"}:
        return "streamline-x"
    if normalized in {"streamline_1", "streamline_y"}:
        return "streamline-y"
    if normalized in {"streamline_2", "streamline_z"}:
        return "streamline-z"
    if normalized in {"color", "color_by"}:
        return "color-by"
    if normalized in {"contour", "contour_by"}:
        return "contour-by"
    return normalized.replace("_", "-")


def _input_role_labels(item: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    seen = set()
    for role in _input_roles(item):
        label = _display_input_role(role)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            labels.append(label)
    return labels


def _role_priority(role: str) -> tuple[int, int]:
    normalized = _text(role).lower().replace("-", "_")
    if normalized.startswith("streamline_"):
        suffix = normalized.rsplit("_", 1)[-1]
        try:
            return (0, int(suffix))
        except Exception:
            return (0, 0)
    if normalized in {"streamline", "streamline_by"}:
        return (0, 0)
    if normalized in {"color", "color_by"}:
        return (20, 0)
    if normalized in {"contour", "contour_by"}:
        return (30, 0)
    if normalized.startswith("y_axis"):
        return (40, 0)
    if normalized in {"primary", "variable", "source"}:
        return (50, 0)
    if normalized in {"x_axis"}:
        return (90, 0)
    return (60, 0)


def _skip_input(roles: List[str]) -> bool:
    normalized = {_text(role).lower().replace("-", "_") for role in roles}
    return bool(normalized) and normalized <= {"x_axis"}


def _provenance_input_items(raw_inputs: Any) -> List[Dict[str, Any]]:
    inputs = _list_value(raw_inputs)
    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(inputs):
        if isinstance(raw, str):
            raw = {"name": raw, "roles": ["source"]}
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        roles = _input_roles(item)
        if _skip_input(roles):
            continue
        name = _short_variable_name(
            _first_text(
                item,
                "_display_name",
                "label",
                "name",
                "variable_name",
                "variable_id",
                "definition",
            )
        )
        if not name:
            continue
        priority = min((_role_priority(role) for role in roles), default=(60, index))
        source_label = _first_text(
            item,
            "_source_label",
            "source_label",
            "source_dataset",
            "dataset",
            "datasetName",
        )
        item["_display_name"] = name
        item["_source_label"] = source_label
        item["_priority"] = priority
        item["_index"] = index
        items.append(item)

    items.sort(
        key=lambda item: (
            item.get("_priority", (60, 0)),
            int(item.get("_index", 0) or 0),
            str(item.get("_display_name", "")),
        )
    )
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        name = str(item.get("_display_name", "") or "")
        source_label = str(item.get("_source_label", "") or "")
        key = (name.casefold(), source_label.casefold())
        if key in seen:
            continue
        seen.add(key)
        item["_display_name"] = name
        item["_source_label"] = source_label
        normalized.append(item)
    return normalized


def _provenance_input_names(raw_inputs: Any) -> List[str]:
    names: List[str] = []
    seen = set()
    for item in _provenance_input_items(raw_inputs):
        name = str(item.get("_display_name", "") or "")
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _activity_label(kind: Any, operation: Any = "") -> str:
    raw_kind = _text(kind)
    kind_norm = raw_kind.lower()
    op = _text(operation)
    if kind_norm == "quantity_of_interest":
        label = "statistics" if op == "descriptive_statistics" else "derived"
    elif kind_norm:
        label = raw_kind
    else:
        label = "activity"

    if op and op.casefold() != label.casefold():
        return f"{label}: {op}"
    return label


def _visualization_operation(tile: Dict[str, Any], row: Dict[str, Any]) -> str:
    visualization_provenance = _dict_value(
        tile.get("visualization_activity_provenance")
        or row.get("visualization_activity_provenance")
    )
    provenance_operation = _first_text(
        visualization_provenance,
        "activity_operation",
    )
    if provenance_operation:
        return provenance_operation
    sequence_metadata = _dict_value(
        tile.get("visualization_sequence_metadata")
        or row.get("visualization_sequence_metadata")
    )
    item_metadata = _dict_value(
        tile.get("visualization_item_metadata")
        or row.get("visualization_item_metadata")
    )
    for item in (sequence_metadata, item_metadata, tile, row):
        value = _first_text(
            item,
            "visualization_type",
            "operation",
            "visualization_kind",
            "representation_kind",
            "payload_type",
            "visualization_item_type",
            "kind",
        )
        if value:
            return value
    return ""


def _chain(*parts: Any) -> str:
    return " --> ".join(_text(part) for part in parts if _text(part))


def _detail_rows(*pairs: tuple[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for label, value in pairs:
        if isinstance(value, (list, tuple)):
            value = ", ".join(_text(item) for item in value if _text(item))
        text = _text(value)
        if text:
            rows.append({"label": str(label), "value": text})
    return rows


def _compact_source_label(value: Any) -> str:
    text = _text(value).strip("/")
    if not text:
        return ""
    parts = [part for part in text.split("/") if part]
    if len(parts) >= 2 and parts[-1].endswith(".bp"):
        return "/".join(parts[-2:])
    return text


def _input_display_name(item: Dict[str, Any]) -> str:
    return str(item.get("_display_name", "") or "")


def _input_source_label(item: Dict[str, Any]) -> str:
    return str(item.get("_source_label", "") or "")


def _input_effective_source_label(
    item: Dict[str, Any],
    fallback_source: str = "",
) -> str:
    return _input_source_label(item) or _text(fallback_source)


def _source_labels_from_inputs(
    input_items: List[Dict[str, Any]],
    fallback: str = "",
) -> List[str]:
    labels: List[str] = []
    seen = set()
    for item in input_items:
        label = _input_source_label(item)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            labels.append(label)
    if labels:
        return labels
    fallback_label = _text(fallback)
    return [fallback_label] if fallback_label else []


def _compact_input_expression(
    input_items: List[Dict[str, Any]],
    source_labels: List[str],
) -> str:
    if not input_items:
        return "..."

    source_tags = {
        label.casefold(): f"S{index + 1}"
        for index, label in enumerate(source_labels)
    }
    use_tags = len(source_labels) > 1
    visible = input_items if len(input_items) <= 3 else input_items[:2]
    terms: List[str] = []
    for item in visible:
        name = _input_display_name(item)
        if not name:
            continue
        if use_tags:
            tag = source_tags.get(_input_source_label(item).casefold(), "?")
            name = f"{name}[{tag}]"
        terms.append(name)

    if len(input_items) > len(visible):
        terms.append("...")
    return " + ".join(terms) if terms else "..."


def _compact_source_suffix(source_labels: List[str]) -> str:
    if not source_labels:
        return ""
    if len(source_labels) == 1:
        return _compact_source_label(source_labels[0])
    if len(source_labels) <= 3:
        return " : ".join(
            f"S{index + 1}={_compact_source_label(label)}"
            for index, label in enumerate(source_labels)
        )
    return f"{len(source_labels)} sources"


def _compact_activity_breadcrumb(
    output_label: str,
    operation: str,
    input_items: List[Dict[str, Any]],
    fallback_source: str,
) -> str:
    output = _text(output_label)
    op = _text(operation) or "activity"
    source_labels = _source_labels_from_inputs(input_items, fallback_source)
    expression = f"{output} = {op}({_compact_input_expression(input_items, source_labels)})"
    source_suffix = _compact_source_suffix(source_labels)
    if source_suffix:
        return f"{expression} : {source_suffix}"
    return expression


def _compact_visualization_breadcrumb(
    visualization_label: str,
    operation: str,
    input_label: str,
    input_items: List[Dict[str, Any]],
    fallback_source: str,
    derived_operation: str = "",
    derived_input_items: Optional[List[Dict[str, Any]]] = None,
    derived_fallback_source: str = "",
) -> str:
    visualization = _text(visualization_label)
    op = _text(operation) or "visualization"
    if derived_input_items is not None:
        source_labels = _source_labels_from_inputs(
            derived_input_items,
            derived_fallback_source,
        )
        derived_expr = (
            f"{_text(input_label)} = "
            f"{_text(derived_operation) or 'activity'}("
            f"{_compact_input_expression(derived_input_items, source_labels)})"
        )
    else:
        source_labels = _source_labels_from_inputs(input_items, fallback_source)
        derived_expr = _compact_input_expression(input_items, source_labels)

    expression = f"{visualization} = {op}({derived_expr})"
    source_suffix = _compact_source_suffix(source_labels)
    if source_suffix:
        return f"{expression} : {source_suffix}"
    return expression


def _input_details(
    item: Dict[str, Any],
    fallback_source: str = "",
) -> List[Dict[str, str]]:
    return _detail_rows(
        ("Variable", _input_display_name(item)),
        ("Definition", item.get("definition", "")),
    )


def _input_summary(
    input_items: List[Dict[str, Any]],
    include_sources: bool = False,
    fallback_source: str = "",
) -> str:
    values: List[str] = []
    for item in input_items:
        name = _input_display_name(item)
        if not name:
            continue
        source = _input_effective_source_label(item, fallback_source)
        if include_sources and source:
            name = f"{name} ({source})"
        values.append(name)
    return ", ".join(values)


def _input_role_binding_summary(
    input_items: List[Dict[str, Any]],
    include_sources: bool = False,
    fallback_source: str = "",
) -> str:
    values: List[str] = []
    for item in input_items:
        roles = _input_role_labels(item)
        name = _input_display_name(item)
        if not roles or not name:
            continue
        source = _input_effective_source_label(item, fallback_source)
        if include_sources and source:
            name = f"{name} ({source})"
        values.append(f"{' + '.join(roles)}: {name}")
    return ", ".join(values)


def _source_details(
    label: str,
    input_items: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    if not input_items:
        return _detail_rows(("Dataset", label))
    source_labels = _source_labels_from_inputs(input_items, label)
    if len(source_labels) <= 1:
        return _detail_rows(("Dataset", source_labels[0] if source_labels else label))
    return _detail_rows(
        ("Sources", len(source_labels)),
        *(
            (f"S{index + 1}", source_label)
            for index, source_label in enumerate(source_labels)
        ),
    )


def _activity_metadata(activity_provenance: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _dict_value(activity_provenance.get("activity_metadata", {}))
    if metadata:
        return metadata
    return _dict_value(activity_provenance.get("metadata", {}))


def _input_table_detail(input_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, str]] = []
    for item in input_items:
        name = _input_display_name(item)
        if not name:
            continue
        rows.append(
            {
                "variable": name,
                "role": ", ".join(_input_role_labels(item)),
            }
        )
    if not rows:
        return []
    return [
        {
            "label": "Inputs",
            "kind": "input_table",
            "value": ", ".join(row["variable"] for row in rows),
            "rows": rows,
        }
    ]


def _activity_details(
    activity_provenance: Dict[str, Any],
    activity_label: str,
    output_label: str,
    output_source: str,
    input_items: List[Dict[str, Any]],
    input_source: str = "",
) -> List[Dict[str, Any]]:
    metadata = _activity_metadata(activity_provenance)
    details: List[Dict[str, Any]] = _detail_rows(
        ("Kind", _activity_label(activity_provenance.get("activity_kind", ""))),
        ("Operation", activity_provenance.get("activity_operation", activity_label)),
        ("Output", output_label),
        ("Output source", output_source),
    )
    details.extend(_input_table_detail(input_items))
    details.extend(
        _detail_rows(
            ("Script", metadata.get("script_dataset", "")),
            ("Method", metadata.get("discretization", "")),
        )
    )
    return details


def _provenance_detail_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(", ", ": "),
            )
        except (TypeError, ValueError):
            pass
    return _text(value)


def _workflow_plan_node(
    activity_provenance: Dict[str, Any],
    node_prefix: str,
) -> Optional[Dict[str, Any]]:
    plan = _dict_value(activity_provenance.get("workflow_plan", {}))
    if not plan:
        return None
    plan_details = _dict_value(plan.get("details", {}))
    label = _first_text(plan, "label") or _first_text(
        plan_details,
        "workflow",
    )
    details = _detail_rows(
        ("Workflow", plan_details.get("workflow", "")),
        ("Implementation", plan_details.get("implementation_dataset", "")),
        ("Location", plan.get("location", "")),
        (
            "Selection",
            _provenance_detail_value(plan_details.get("selection", "")),
        ),
        (
            "Parameters",
            _provenance_detail_value(plan_details.get("parameters", "")),
        ),
        (
            "Output policy",
            _provenance_detail_value(plan_details.get("output_policy", "")),
        ),
    )
    return _provenance_node(
        f"{node_prefix}-plan",
        "plan",
        label or "Workflow plan",
        "box",
        details=details,
    )


def _activity_agent_node(
    activity_provenance: Dict[str, Any],
    node_prefix: str,
) -> Optional[Dict[str, Any]]:
    agent = _dict_value(activity_provenance.get("activity_agent", {}))
    if not agent:
        return None
    label = _first_text(agent, "label") or "Agent"
    return _provenance_node(
        f"{node_prefix}-agent",
        "agent",
        label,
        "box",
        details=_detail_rows(
            ("Type", agent.get("type", "")),
            ("Version", agent.get("version", "")),
        ),
    )


def _visualization_details(
    visualization_label: str,
    operation: str,
    input_items: List[Dict[str, Any]],
    input_source: str = "",
    activity_provenance: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = _detail_rows(
        ("Kind", "visualization"),
        ("Operation", operation),
        ("Output", visualization_label),
    )
    details.extend(_input_table_detail(input_items))
    metadata = _activity_metadata(dict(activity_provenance or {}))
    details.extend(
        _detail_rows(
            ("Steps", _provenance_detail_value(metadata.get("steps", ""))),
            (
                "Rendering",
                _provenance_detail_value(metadata.get("rendering_parameters", "")),
            ),
        )
    )
    return details


def _provenance_node(
    node_id: str,
    kind: str,
    label: Any,
    shape: str,
    items: Optional[List[Dict[str, Any]]] = None,
    details: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    node_kind = str(kind or "")
    node_label = _text(label)
    node = {
        "id": str(node_id or ""),
        "kind": node_kind,
        "label": node_label,
        "shape": str(shape or ""),
    }
    if node_kind == "activity" and node_label:
        operation = node_label.split(":", 1)[-1].strip()
        display_label = operation.replace("_", " ").replace("-", " ").capitalize()
        if display_label and display_label != node_label:
            node["display_label"] = display_label
            node["secondary_label"] = node_label
    elif node_kind == "visualization" and "_" in node_label:
        display_label = node_label.replace("_", " ").capitalize()
        node["display_label"] = display_label
        node["secondary_label"] = node_label
    if items:
        node["items"] = items
    if details:
        node["details"] = details
        node["expanded"] = False
    return node


def _apply_node_expansion(
    raw_node: Dict[str, Any],
    expanded_by_id: Dict[str, bool],
) -> Dict[str, Any]:
    node = dict(raw_node)
    node_id = str(node.get("id", "") or "")
    if node.get("details"):
        node["expanded"] = bool(expanded_by_id.get(node_id, False))
    else:
        node.pop("expanded", None)
    if node.get("items"):
        node["items"] = [
            _apply_node_expansion(dict(item), expanded_by_id)
            for item in node.get("items", [])
            if isinstance(item, dict)
        ]
    return node


def _apply_provenance_expansion(
    nodes: List[Dict[str, Any]],
    expanded_by_id: Dict[str, Any],
) -> List[Dict[str, Any]]:
    expanded = {
        str(node_id): bool(value)
        for node_id, value in (expanded_by_id or {}).items()
    }
    updated: List[Dict[str, Any]] = []
    for raw_node in nodes or []:
        if not isinstance(raw_node, dict):
            continue
        updated.append(_apply_node_expansion(raw_node, expanded))
    return updated


def _apply_provenance_graph_expansion(
    graph: List[Dict[str, Any]],
    expanded_by_id: Dict[str, Any],
) -> List[Dict[str, Any]]:
    expanded = {
        str(node_id): bool(value)
        for node_id, value in (expanded_by_id or {}).items()
    }
    updated: List[Dict[str, Any]] = []
    for raw_segment in graph or []:
        if not isinstance(raw_segment, dict):
            continue
        segment = dict(raw_segment)
        if segment.get("type") == "node" and isinstance(segment.get("node"), dict):
            segment["node"] = _apply_node_expansion(segment["node"], expanded)
        elif segment.get("type") == "entity_source":
            for key in ("entity", "source"):
                if isinstance(segment.get(key), dict):
                    segment[key] = _apply_node_expansion(
                        segment[key],
                        expanded,
                    )
        elif segment.get("type") == "activity_context":
            if isinstance(segment.get("node"), dict):
                segment["node"] = _apply_node_expansion(
                    segment["node"],
                    expanded,
                )
            contexts: List[Dict[str, Any]] = []
            for raw_context in segment.get("contexts", []) or []:
                if not isinstance(raw_context, dict):
                    continue
                context = dict(raw_context)
                if isinstance(context.get("node"), dict):
                    context["node"] = _apply_node_expansion(
                        context["node"],
                        expanded,
                    )
                contexts.append(context)
            segment["contexts"] = contexts
        elif segment.get("type") == "plan_group":
            if isinstance(segment.get("plan"), dict):
                segment["plan"] = _apply_node_expansion(
                    segment["plan"],
                    expanded,
                )
            raw_action = segment.get("selected_action")
            if isinstance(raw_action, dict):
                action = dict(raw_action)
                if isinstance(action.get("node"), dict):
                    action["node"] = _apply_node_expansion(
                        action["node"],
                        expanded,
                    )
                if isinstance(action.get("agent"), dict):
                    action["agent"] = _apply_node_expansion(
                        action["agent"],
                        expanded,
                    )
                segment["selected_action"] = action
        elif segment.get("type") == "branches":
            branches: List[Dict[str, Any]] = []
            for raw_branch in segment.get("branches", []) or []:
                if not isinstance(raw_branch, dict):
                    continue
                branch = dict(raw_branch)
                if isinstance(branch.get("input"), dict):
                    branch["input"] = _apply_node_expansion(
                        branch["input"],
                        expanded,
                    )
                if isinstance(branch.get("source"), dict):
                    branch["source"] = _apply_node_expansion(
                        branch["source"],
                        expanded,
                    )
                branches.append(branch)
            segment["branches"] = branches
            if isinstance(segment.get("shared_source"), dict):
                segment["shared_source"] = _apply_node_expansion(
                    segment["shared_source"],
                    expanded,
                )
        updated.append(segment)
    return updated


def _provenance_detail_node_ids(nodes: List[Dict[str, Any]]) -> set[str]:
    node_ids: set[str] = set()
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "") or "")
        if node_id and node.get("details"):
            node_ids.add(node_id)
        node_ids.update(_provenance_detail_node_ids(node.get("items", []) or []))
    return node_ids


def _provenance_graph_detail_node_ids(graph: List[Dict[str, Any]]) -> set[str]:
    node_ids: set[str] = set()
    for segment in graph or []:
        if not isinstance(segment, dict):
            continue
        if segment.get("type") == "node":
            node = segment.get("node")
            if isinstance(node, dict):
                node_ids.update(_provenance_detail_node_ids([node]))
        elif segment.get("type") == "entity_source":
            for key in ("entity", "source"):
                node = segment.get(key)
                if isinstance(node, dict):
                    node_ids.update(_provenance_detail_node_ids([node]))
        elif segment.get("type") == "activity_context":
            node = segment.get("node")
            if isinstance(node, dict):
                node_ids.update(_provenance_detail_node_ids([node]))
            for context in segment.get("contexts", []) or []:
                if not isinstance(context, dict):
                    continue
                node = context.get("node")
                if isinstance(node, dict):
                    node_ids.update(_provenance_detail_node_ids([node]))
        elif segment.get("type") == "plan_group":
            plan = segment.get("plan")
            if isinstance(plan, dict):
                node_ids.update(_provenance_detail_node_ids([plan]))
            action = segment.get("selected_action")
            if isinstance(action, dict):
                for key in ("node", "agent"):
                    node = action.get(key)
                    if isinstance(node, dict):
                        node_ids.update(_provenance_detail_node_ids([node]))
        elif segment.get("type") == "branches":
            for branch in segment.get("branches", []) or []:
                if not isinstance(branch, dict):
                    continue
                for key in ("input", "source"):
                    node = branch.get(key)
                    if isinstance(node, dict):
                        node_ids.update(_provenance_detail_node_ids([node]))
            shared_source = segment.get("shared_source")
            if isinstance(shared_source, dict):
                node_ids.update(_provenance_detail_node_ids([shared_source]))
    return node_ids


def _variable_provenance_node(
    node_id: str,
    label: Any,
    details: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return _provenance_node(node_id, "variable", label, "box", details=details)


def _activity_provenance_node(
    label: Any,
    node_id: str = "activity",
    details: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return _provenance_node(node_id, "activity", label, "box", details=details)


def _activity_graph_item(
    activity_node: Dict[str, Any],
    activity_provenance: Dict[str, Any],
    node_prefix: str,
) -> Dict[str, Any]:
    plan_node = _workflow_plan_node(activity_provenance, node_prefix)
    if plan_node:
        return {
            "id": f"plan-group-{node_prefix}",
            "type": "plan_group",
            "plan": plan_node,
            "selected_action": {
                "id": f"{node_prefix}-selected-action",
                "node": activity_node,
                "agent": (
                    _activity_agent_node(activity_provenance, node_prefix) or {}
                ),
            },
        }

    contexts: List[Dict[str, Any]] = []
    agent_node = _activity_agent_node(activity_provenance, node_prefix)
    if agent_node:
        contexts.append(
            {
                "id": f"{node_prefix}-agent-context",
                "relation": "Agent",
                "node": agent_node,
            }
        )
    if not contexts:
        return activity_node
    return {
        "id": f"context-{node_prefix}",
        "type": "activity_context",
        "node": activity_node,
        "contexts": contexts,
    }


def _source_provenance_node(
    label: Any,
    details: Optional[List[Dict[str, Any]]] = None,
    node_id: str = "source",
) -> Dict[str, Any]:
    return _provenance_node(node_id, "source", label, "cylinder", details=details)


def _graph_node_segment(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": f"node-{str(node.get('id', '') or '')}",
        "type": "node",
        "node": node,
    }


def _graph_arrow_segment(index: int, relation: str = "") -> Dict[str, Any]:
    return {
        "id": f"arrow-{index}",
        "type": "arrow",
        "relation": relation,
    }


def _graph_item_kind(item: Dict[str, Any]) -> str:
    item_type = _text(item.get("type", ""))
    if item_type:
        return item_type
    return _text(item.get("kind", ""))


def _graph_relation(
    previous: Dict[str, Any],
    current: Dict[str, Any],
) -> str:
    previous_kind = _graph_item_kind(previous)
    current_kind = _graph_item_kind(current)
    activity_kinds = {"activity", "activity_context", "plan_group"}
    if current_kind in activity_kinds:
        return ""
    if previous_kind in activity_kinds:
        return "uses"
    if current_kind == "source":
        return "stored in"
    return ""


def _provenance_graph_segments(*items: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    index = 0
    raw_items = [item for item in items if item]
    while index < len(raw_items):
        item = raw_items[index]
        following = raw_items[index + 1] if index + 1 < len(raw_items) else {}
        if (
            not item.get("type")
            and item.get("kind") == "variable"
            and not following.get("type")
            and following.get("kind") == "source"
        ):
            normalized.append(
                {
                    "id": f"entity-source-{item.get('id', index)}",
                    "type": "entity_source",
                    "entity": item,
                    "source": following,
                }
            )
            index += 2
            continue
        normalized.append(item)
        index += 1

    segments: List[Dict[str, Any]] = []
    previous: Optional[Dict[str, Any]] = None
    arrow_index = 0
    for item in normalized:
        if item.get("type") == "branches":
            if item.get("branches"):
                branch_segment = dict(item)
                if previous:
                    branch_segment["relation"] = _graph_relation(previous, item)
                segments.append(branch_segment)
            previous = None
            continue
        if previous:
            arrow_index += 1
            segments.append(
                _graph_arrow_segment(
                    arrow_index,
                    _graph_relation(previous, item),
                )
            )
        if item.get("type") in {
            "activity_context",
            "entity_source",
            "plan_group",
        }:
            segments.append(item)
        else:
            segments.append(_graph_node_segment(item))
        previous = item
    return segments


def _input_source_for_graph(item: Dict[str, Any], fallback_source: str) -> str:
    return _input_source_label(item) or _text(fallback_source) or "source"


def _needs_stored_source_edge(source_label: str, upstream_source_label: str) -> bool:
    source = _text(source_label)
    upstream_source = _text(upstream_source_label)
    if not source or source.casefold() == "source":
        return False
    if not upstream_source:
        return False
    return source.casefold() != upstream_source.casefold()


def _input_branch_segment(
    input_items: List[Dict[str, Any]],
    fallback_source: str,
    input_prefix: str = "input",
    source_prefix: str = "source",
) -> Dict[str, Any]:
    branches: List[Dict[str, Any]] = []
    source_labels: List[str] = []
    seen_sources = set()
    for index, item in enumerate(input_items or []):
        name = _input_display_name(item)
        if not name:
            continue
        source_label = _input_source_for_graph(item, fallback_source)
        source_key = source_label.casefold()
        if source_key not in seen_sources:
            seen_sources.add(source_key)
            source_labels.append(source_label)
        branches.append(
            {
                "id": f"{input_prefix}-{index}",
                "input": _variable_provenance_node(
                    f"{input_prefix}-{index}",
                    name,
                    details=_input_details(item, fallback_source),
                ),
                "source": _source_provenance_node(
                    source_label,
                    details=_source_details(source_label, [item]),
                    node_id=f"{source_prefix}-{index}",
                ),
            }
        )

    shared_source = None
    if len(branches) > 1 and len(source_labels) == 1:
        shared_source = _source_provenance_node(
            source_labels[0],
            details=_source_details(source_labels[0], input_items),
            node_id=source_prefix,
        )

    return {
        "id": f"branches-{input_prefix}",
        "type": "branches",
        "branches": branches,
        "shared_source": shared_source,
    }


def _input_provenance_nodes(
    inputs: List[Any],
    fallback_source: str = "",
) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for index, value in enumerate(inputs):
        if isinstance(value, dict):
            name = _input_display_name(value) or _text(value.get("label", ""))
            details = _input_details(value, fallback_source)
            source = _input_effective_source_label(value, fallback_source)
        else:
            name = _text(value)
            details = []
            source = ""
        if not name:
            continue
        specs.append(
            {
                "index": index,
                "name": name,
                "details": details,
                "source": source,
            }
        )

    if not specs:
        return []
    if len(specs) == 1:
        return [
            _variable_provenance_node(
                "input-0",
                specs[0]["name"],
                details=specs[0]["details"],
            )
        ]
    return [
        _provenance_node(
            "inputs",
            "variables",
            "Inputs",
            "group",
            items=[
                _variable_provenance_node(
                    f"input-{spec['index']}",
                    spec["name"],
                    details=spec["details"],
                )
                for spec in specs
            ],
            details=_detail_rows(
                (
                    "Inputs",
                    ", ".join(
                        (
                            f"{spec['name']} ({spec['source']})"
                            if spec["source"]
                            else str(spec["name"])
                        )
                        for spec in specs
                    ),
                )
            ),
        )
    ]


def _activity_input_source_label(
    activity_provenance: Dict[str, Any],
    fallback: str,
) -> str:
    labels: List[str] = []
    seen = set()
    for raw in _list_value(activity_provenance.get("inputs", [])):
        if not isinstance(raw, dict):
            continue
        label = _first_text(
            raw,
            "source_label",
            "source_dataset",
            "dataset",
            "datasetName",
        )
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            labels.append(label)

    if len(labels) == 1:
        return labels[0]
    if len(labels) > 1:
        return " + ".join(labels)
    return fallback


def _details_provenance_summary(
    variable_label: str,
    selected_rows: List[Dict[str, Any]],
    tiles: List[Dict[str, Any]],
    include_visualization: bool = False,
) -> Dict[str, Any]:
    label = _text(variable_label)
    rows = [dict(row or {}) for row in selected_rows or [] if isinstance(row, dict)]
    if not label or not rows:
        return {"kind": "", "chain": "", "compact": "", "nodes": [], "graph": []}

    if len(rows) > 1:
        count = len(rows)
        nodes = [
            _variable_provenance_node(
                "variable",
                label,
                details=_detail_rows(("Variable", label)),
            ),
            _source_provenance_node(
                f"{count} selected sources",
                details=_detail_rows(("Sources", count)),
            ),
        ]
        return {
            "kind": "multiple_sources",
            "chain": f"{label} --> {count} selected sources",
            "compact": f"{label} : {count} selected sources",
            "nodes": nodes,
            "graph": _provenance_graph_segments(*nodes),
        }

    row = rows[0]
    tile = dict(tiles[0] or {}) if tiles else {}
    variable_name = label or _first_text(row, "variable_name", "variable_id")
    source_label = _source_label_for_provenance(row) or "source"
    visualization_name = ""
    if include_visualization:
        visualization_name = _first_text(
            tile,
            "selected_visualization",
            "visualization_name",
        )
        if not visualization_name:
            visualization_name = _first_text(row, "visualization_name")

    if visualization_name:
        visualization_operation = _visualization_operation(tile, row)
        visualization_activity_provenance = _dict_value(
            tile.get("visualization_activity_provenance")
            or row.get("visualization_activity_provenance")
        )
        activity = _activity_label("visualization", visualization_operation)
        input_items = _provenance_input_items(
            tile.get("visualization_variables")
            or row.get("visualization_variables")
            or []
        )
        if not input_items and variable_name:
            input_items = [
                {
                    "_display_name": variable_name,
                    "_source_label": source_label,
                    "roles": ["source"],
                }
            ]
        inputs = _provenance_input_names(input_items)
        activity_provenance = _dict_value(row.get("activity_provenance", {}))
        if activity_provenance and len(inputs) <= 1:
            derived_activity = _activity_label(
                activity_provenance.get("activity_kind", ""),
                activity_provenance.get("activity_operation", ""),
            )
            derived_input_items = _provenance_input_items(
                activity_provenance.get("inputs", [])
            )
            derived_inputs = _provenance_input_names(derived_input_items)
            derived_source_label = _activity_input_source_label(
                activity_provenance,
                source_label,
            )
            input_label = inputs[0] if inputs else variable_name
            visualization_input_source_label = source_label
            if len(input_items) == 1:
                visualization_input_source_label = _input_effective_source_label(
                    input_items[0],
                    source_label,
                )
            derived_operation = str(
                activity_provenance.get("activity_operation", "") or ""
            )
            chain = _chain(
                visualization_name,
                activity,
                input_label,
                derived_activity,
                " + ".join(derived_inputs),
                derived_source_label,
            )
            nodes = [
                _provenance_node(
                    "visualization",
                    "visualization",
                    visualization_name,
                    "box",
                    details=_detail_rows(
                        ("Visualization", visualization_name),
                        ("Kind", visualization_operation),
                    ),
                ),
                _activity_provenance_node(
                    activity,
                    "visualization-activity",
                    details=_visualization_details(
                        visualization_name,
                        visualization_operation,
                        input_items,
                        visualization_input_source_label,
                        visualization_activity_provenance,
                    ),
                ),
                _variable_provenance_node(
                    "visualization-input",
                    input_label,
                    details=_detail_rows(
                        ("Variable", input_label),
                    ),
                ),
                _activity_provenance_node(
                    derived_activity,
                    "derived-activity",
                    details=_activity_details(
                        activity_provenance,
                        derived_activity,
                        input_label,
                        visualization_input_source_label,
                        derived_input_items,
                        derived_source_label,
                    ),
                ),
                *_input_provenance_nodes(
                    derived_input_items,
                    derived_source_label,
                ),
                _source_provenance_node(
                    derived_source_label,
                    details=_source_details(
                        derived_source_label,
                        derived_input_items,
                    ),
                ),
            ]
            stored_source_node = None
            if _needs_stored_source_edge(
                visualization_input_source_label,
                derived_source_label,
            ):
                stored_source_node = _source_provenance_node(
                    visualization_input_source_label,
                    details=_source_details(visualization_input_source_label),
                    node_id="visualization-input-source",
                )
                nodes[3:3] = [stored_source_node]

            graph_main_nodes = [
                nodes[0],
                _activity_graph_item(
                    nodes[1],
                    visualization_activity_provenance,
                    "visualization-activity",
                ),
                nodes[2],
            ]
            derived_activity_index = 3
            if stored_source_node:
                graph_main_nodes.append(nodes[3])
                derived_activity_index = 4
            graph_main_nodes.append(
                _activity_graph_item(
                    nodes[derived_activity_index],
                    activity_provenance,
                    "derived-activity",
                )
            )
            derived_input_branches = _input_branch_segment(
                derived_input_items,
                derived_source_label,
            )
            graph_tail = (
                derived_input_branches
                if derived_input_branches.get("branches")
                else nodes[-1]
            )
            return {
                "kind": "visualization",
                "chain": chain,
                "compact": _compact_visualization_breadcrumb(
                    visualization_name,
                    visualization_operation,
                    input_label,
                    input_items,
                    source_label,
                    derived_operation=derived_operation,
                    derived_input_items=derived_input_items,
                    derived_fallback_source=derived_source_label,
                ),
                "nodes": nodes,
                "graph": _provenance_graph_segments(
                    *graph_main_nodes,
                    graph_tail,
                ),
            }
        input_label = " + ".join(inputs) if inputs else variable_name
        chain = _chain(visualization_name, activity, input_label, source_label)
        nodes = [
            _provenance_node(
                "visualization",
                "visualization",
                visualization_name,
                "box",
                details=_detail_rows(
                    ("Visualization", visualization_name),
                    ("Kind", visualization_operation),
                ),
            ),
            _activity_provenance_node(
                activity,
                details=_visualization_details(
                    visualization_name,
                    visualization_operation,
                    input_items,
                    source_label,
                    visualization_activity_provenance,
                ),
            ),
            *(
                _input_provenance_nodes(input_items, source_label)
                if input_items
                else [_variable_provenance_node("input-0", variable_name)]
            ),
            _source_provenance_node(
                source_label,
                details=_source_details(source_label, input_items),
            ),
        ]
        return {
            "kind": "visualization",
            "chain": chain,
            "compact": _compact_visualization_breadcrumb(
                visualization_name,
                visualization_operation,
                input_label,
                input_items,
                source_label,
            ),
            "nodes": nodes,
            "graph": _provenance_graph_segments(
                nodes[0],
                _activity_graph_item(
                    nodes[1],
                    visualization_activity_provenance,
                    "visualization-activity",
                ),
                _input_branch_segment(input_items, source_label),
            ),
        }

    activity_provenance = _dict_value(row.get("activity_provenance", {}))
    if activity_provenance:
        activity = _activity_label(
            activity_provenance.get("activity_kind", ""),
                activity_provenance.get("activity_operation", ""),
            )
        input_items = _provenance_input_items(activity_provenance.get("inputs", []))
        inputs = _provenance_input_names(input_items)
        activity_source_label = _activity_input_source_label(
            activity_provenance,
            source_label,
        )
        if inputs:
            chain = _chain(
                variable_name,
                activity,
                " + ".join(inputs),
                activity_source_label,
            )
        else:
            chain = _chain(variable_name, activity, activity_source_label)
        nodes = [
            _variable_provenance_node(
                "variable",
                variable_name,
                details=_detail_rows(
                    ("Variable", variable_name),
                    (
                        "Definition",
                        activity_provenance.get("output_definition", ""),
                    ),
                ),
            ),
            _activity_provenance_node(
                activity,
                details=_activity_details(
                    activity_provenance,
                    activity,
                    variable_name,
                    source_label,
                    input_items,
                    activity_source_label,
                ),
            ),
            *_input_provenance_nodes(input_items, activity_source_label),
            _source_provenance_node(
                activity_source_label,
                details=_source_details(activity_source_label, input_items),
            ),
        ]
        input_branches = _input_branch_segment(input_items, activity_source_label)
        graph_tail = input_branches if input_branches.get("branches") else nodes[-1]
        return {
            "kind": "activity",
            "chain": chain,
            "compact": _compact_activity_breadcrumb(
                variable_name,
                str(activity_provenance.get("activity_operation", "") or ""),
                input_items,
                activity_source_label,
            ),
            "nodes": nodes,
            "graph": _provenance_graph_segments(
                nodes[0],
                _activity_graph_item(
                    nodes[1],
                    activity_provenance,
                    "activity",
                ),
                graph_tail,
            ),
        }

    chain = _chain(variable_name, source_label)
    kind = "variable"
    nodes = [
        _variable_provenance_node(
            "variable",
            variable_name,
            details=_detail_rows(("Variable", variable_name)),
        ),
        _source_provenance_node(
            source_label,
            details=_source_details(source_label),
        ),
    ]

    return {
        "kind": kind,
        "chain": chain,
        "compact": (
            f"{variable_name} : {_compact_source_label(source_label)}"
            if source_label
            else variable_name
        ),
        "nodes": nodes,
        "graph": _provenance_graph_segments(*nodes),
    }


class CatalogControllerMixin:
    ACTION_BINDINGS = (
        ("pick_var", "pick_var"),
        ("select_var", "select_var"),
        ("set_dragged_var", "set_dragged_var"),
        ("toggle_variable_group", "toggle_variable_group"),
        ("show_query_help", "show_query_help"),
        ("show_source_filter_help", "show_source_filter_help"),
        ("close_help_modal", "close_help_modal"),
        ("open_provenance_dialog", "open_provenance_dialog"),
        ("close_provenance_dialog", "close_provenance_dialog"),
        ("toggle_provenance_node_details", "toggle_provenance_node_details"),
        ("run_query", "run_query"),
        ("clear_query", "clear_query"),
    )
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = (
        (("showOnlyVisualizedVars",), "on_show_only_visualized_vars"),
        (("variablePaneView",), "on_variable_pane_view"),
        (("variableSearchText",), "on_variable_search_text"),
        (("selectedVar",), "on_selected_var"),
    )

    def active_query_filter(self) -> Optional[Dict[str, Any]]:
        query_filter = self.state.queryFilter or None
        source_restriction = self.state.querySourceRestrictionFilter or None
        if query_filter and source_restriction:
            return and_filter(query_filter, source_restriction)
        return query_filter or source_restriction or None

    @staticmethod
    def combined_query_filter(
        query_filter: Dict[str, Any],
        source_restriction: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if query_filter and source_restriction:
            return and_filter(query_filter, source_restriction)
        return query_filter or source_restriction or None

    def variable_pane_view(self) -> str:
        view = str(getattr(self.state, "variablePaneView", "variables") or "variables")
        return "files" if view == "files" else "variables"

    def refresh_variable_list(self):
        view = self.variable_pane_view()
        navigation = self.application.get_navigation(
            {
                "view": view,
                "query": self.active_query_filter() or {},
                "only_visualized": bool(self.state.showOnlyVisualizedVars),
                "parent_id": None,
            }
        )
        grouped = _variable_groups_from_navigation(navigation)
        self.state.variableGroups = grouped
        self.update_variable_search_results()
        variables = [
            variable
            for group in grouped
            for variable in (group.get("variables") or [])
            if isinstance(variable, dict)
        ]
        self.state.variableNames = list(
            dict.fromkeys(
                str(v.get("id", "") or "")
                for v in variables
                if str(v.get("id", "") or "")
            )
        )
        self.state.variableLabelsById = {
            str(v.get("id", "") or ""): str(
                v.get("label", "") or v.get("name", "") or v.get("id", "") or ""
            )
            for v in variables
            if str(v.get("id", "") or "")
        }
        collapsed_by_view = dict(
            getattr(self.state, "variableGroupCollapsedByView", {}) or {}
        )
        existing_collapsed = dict(collapsed_by_view.get(view, {}) or {})
        valid_group_names = {str(g.get("name", "")) for g in grouped}
        self.state.variableGroupCollapsed = {
            name: bool(existing_collapsed.get(name, True))
            for name in valid_group_names
            if name
        }
        collapsed_by_view[view] = dict(self.state.variableGroupCollapsed)
        self.state.variableGroupCollapsedByView = collapsed_by_view
        backend_status = self.application.get_backend_status()
        self.state.dbOk = backend_status.ok
        self.state.dbStatus = (
            "Connected"
            if backend_status.ok
            else f"DB error: {backend_status.error}"
        )

    def update_variable_search_results(self) -> None:
        search_text = str(
            getattr(self.state, "variableSearchText", "") or ""
        ).strip()
        self.state.filteredVariableGroups = (
            _filter_variable_groups(
                list(self.state.variableGroups or []),
                search_text,
            )
            if search_text
            else []
        )

    def show_help(self, title: str) -> None:
        self.state.helpModalTitle = title
        if str(title or "") in {"Query Help", "Source Filter Help"}:
            scope_note = (
                "Query applies globally to the variable list, source lists, grid cells, and generated plots."
                if str(title or "") == "Query Help"
                else "Source Filter applies only to source rows that already passed the active Query."
            )
            self.state.helpModalText = f"""Use Python-like expressions to filter variables and sources.

{scope_note}

Basic fields:
  var                 variable name, e.g. 'U', 'V', 'valid'
  id                  variable id
  type                variable type, e.g. 'variable', 'image', 'scalarField'
  source or dataset   source dataset path
  producer            run/producer name
  casename            case name
  file                file name
  visualization_name  visualization name
  min, max            variable/source min and max values
  frame_index         visualization frame index

Operators:
  ==  !=  >  >=  <  <=
  in, not in
  and, or, not

Functions:
  contains(field, 'text')   substring match on a text field
                            literal and case-sensitive

Examples:
  var == 'U'
  var in ['U', 'V']
  var == 'U' and min > 0.32
  contains(producer, 'F0.03968')
  contains(source, 'output.bp')
  visualization_name == 'U_heatmap_yz'
  producer == 'Du0.0979_Dv0.0526_F0.01634_k0.0502'

Source restrictions:
  Use source(...) to restrict to runs/sources that match another query.

  source(var == 'valid' and min == 1)

In Query, this keeps only sources/runs where valid == 1 while still allowing you to select U, V, and other variables.
In Source Filter, this keeps only visible source rows from those sources/runs.

Multiple source(...) clauses are intersected:

  source(var == 'valid' and min == 1) and source(var == 'U' and min > 0.32)

This keeps sources/runs where valid == 1 and U.min > 0.32.

Notes:
  var == 'valid' and min == 1 filters directly to the valid variable rows.
  source(var == 'valid' and min == 1) filters sources/runs for all variables.
  source(...) is supported as a top-level clause combined with and.
"""
        else:
            self.state.helpModalText = "TODO"
        self.state.showHelpModal = True

    def refresh_after_variable_catalog_change(self):
        self.refresh_variable_list()
        if self.state.selectedVar and self.state.selectedVar not in (
            self.state.variableNames or []
        ):
            self.state.selectedVar = ""
            clear_right_panes(self.state)
        else:
            self.update_selected_var_panels(
                self.state.selectedVar,
                include_visualization_provenance=(
                    self.details_provenance_includes_visualization()
                ),
            )
        self.refresh_grid_cells()

    def update_selected_var_panels(
        self,
        variable_id: str,
        preferred_source_key: str = "",
        preferred_source_keys: Optional[List[str]] = None,
        include_visualization_provenance: bool = False,
        preferred_visualization: str = "",
    ):
        var_id = str(variable_id or "").strip()
        if not var_id:
            clear_right_panes(self.state)
            return

        label = self.variable_label(var_id)
        previous_var = self.state.detailsSelectedVarId
        previous_tile_map = (
            dict(self.state.tileVisualizationBySource or {})
            if previous_var == var_id
            else {}
        )
        qf = self.active_query_filter()
        preferred_vis = str(preferred_visualization or "").strip()
        summary = self.application.get_source_summary(
            {"variable_id": var_id, "query": qf or {}}
        )

        backend_status = self.application.get_backend_status()
        self.state.dbOk = backend_status.ok
        self.state.dbStatus = (
            f'Connected • Selected variable: "{label}" • QueryView: {self.state.queryViewLabel}'
            if backend_status.ok
            else f'DB error • "{label}" • {backend_status.error}'
        )

        self.state.detailsSelectedVar = label
        self.state.detailsSelectedVarId = var_id
        self.state.detailsNumSources = int(summary.get("num_sources", 0))

        self.state.detailsGlobalMin = fmt(summary.get("global_min", None))
        self.state.detailsGlobalMax = fmt(summary.get("global_max", None))
        self.state.detailsMeanMin = fmt(summary.get("mean_min", None))
        self.state.detailsMeanMax = fmt(summary.get("mean_max", None))
        self.state.detailsMedianMin = fmt(summary.get("median_min", None))
        self.state.detailsMedianMax = fmt(summary.get("median_max", None))
        self.state.detailsSourceRepresentation = _display_representation_summary(
            summary.get("source_representation", {})
        )
        self.state.detailsDerivedRepresentations = [
            _display_representation_summary(representation)
            for representation in summary.get("derived_representations", []) or []
            if isinstance(representation, dict)
        ]

        rows = summary.get("sources", []) or []
        source_rows_all: List[Dict[str, Any]] = []
        for r in rows:
            source_rows_all.append(
                self.source_row_from_descriptor(dict(r or {}), var_id)
            )

        self.state.sourceRowsAll = source_rows_all
        self.apply_source_filter_and_sort()

        all_keys = self.source_row_keys()
        allow_multi_sources = str(self.state.sourceDialogMode or "single") == "add"
        preferred_keys = [
            key
            for key in normalize_source_keys(preferred_source_keys or [])
            if key in all_keys
        ]
        preferred_key = str(preferred_source_key or "")
        if preferred_keys:
            self.state.selectedSourceKeys = (
                preferred_keys if allow_multi_sources else preferred_keys[:1]
            )
        elif preferred_key and preferred_key in all_keys:
            self.state.selectedSourceKeys = [preferred_key]
        elif previous_var != var_id:
            self.state.selectedSourceKeys = [all_keys[0]] if all_keys else []
        else:
            selected = set(self.state.selectedSourceKeys or [])
            selected_keys = [k for k in all_keys if k in selected]
            if allow_multi_sources:
                self.state.selectedSourceKeys = selected_keys or (
                    [all_keys[0]] if all_keys else []
                )
            else:
                self.state.selectedSourceKeys = selected_keys[:1] or (
                    [all_keys[0]] if all_keys else []
                )
        self.update_selected_source_label()

        selected_rows: List[Dict[str, Any]] = []
        try:
            if all_keys and not self.state.selectedSourceKeys:
                self.state.movieTiles = []
                self.state.movieDetailsOpen = {}
                self.state.tileVisualizationBySource = {}
                self.state.movieStatus = "No sources selected"
                self.update_details_provenance(
                    label,
                    selected_rows,
                    [],
                    include_visualization=include_visualization_provenance,
                )
                return

            selected_rows = self.source_rows_for_keys(
                normalize_source_keys(self.state.selectedSourceKeys or [])
            )

            tiles: List[Dict[str, Any]] = []
            new_tile_map: Dict[str, str] = {}

            for row in selected_rows:
                source_key = str(row.get("_key", ""))
                source_filter = source_filter_from_row(row)
                source_query = and_filter(qf, source_filter) if qf else source_filter

                vis_names = self.db.distinct_visualization_names_for_variable(
                    var_id,
                    extra_filter=source_query,
                )
                selected_vis = self.choose_visualization_default(
                    vis_names, preferred_vis or previous_tile_map.get(source_key, "")
                )
                if selected_vis:
                    new_tile_map[source_key] = selected_vis

                tile: Dict[str, Any] = {
                    "variable_id": var_id,
                    "variable_name": label,
                    "visualization_name": selected_vis,
                    "source_dataset": row.get("source_dataset", ""),
                    "producer": row.get("producer", ""),
                    "casename": row.get("casename", ""),
                    "file": row.get("file", ""),
                    "src": "",
                    "media_type": "video",
                    "fps": 0,
                    "frame_count": 0,
                    "frame_indices": [],
                    "frame_sources": [],
                    "time_values": [],
                    "time_mode": "timestep",
                    "status": "no-visualizations",
                    "note": "No visualization types for this source",
                }

                if selected_vis:
                    movie_query = and_filter(
                        source_query, {"visualization_name": selected_vis}
                    )
                    one = self.db.get_first_movie_tiles_for_variable(
                        var_id,
                        extra_filter=movie_query,
                        limit=1,
                        limit_frames=MAX_MOVIE_FRAMES,
                        fps=MOVIE_FPS,
                    )
                    if one:
                        tile = one[0]
                        tile.update(
                            {k: v for k, v in source_fields_from_row(row).items() if v}
                        )
                    else:
                        tile["status"] = "no-frames"
                        tile["note"] = f'No movie for "{selected_vis}"'

                tile["_source_key"] = source_key
                tile["variable_id"] = var_id
                tile["variable_name"] = label
                tile["visualization_options"] = vis_names
                tile["selected_visualization"] = selected_vis
                tiles.append(tile)

            self.state.tileVisualizationBySource = new_tile_map
            self.state.movieTiles = tiles
            self.state.movieDetailsOpen = {}
            self.state.movieStatus = ""
            if self.state.movieTiles:
                with_media = sum(1 for t in self.state.movieTiles if t.get("src"))
                self.state.movieStatus = (
                    f"{with_media}/{len(self.state.movieTiles)} sources with media"
                )
            self.update_details_provenance(
                label,
                selected_rows,
                tiles,
                include_visualization=include_visualization_provenance,
            )
        except Exception as e:
            self.state.movieTiles = []
            self.state.movieDetailsOpen = {}
            self.state.tileVisualizationBySource = {}
            self.state.movieStatus = (
                f"Movie query/build failed: {type(e).__name__}: {e}"
            )
            self.update_details_provenance(
                label,
                selected_rows,
                [],
                include_visualization=include_visualization_provenance,
            )

    def update_details_provenance(
        self,
        variable_label: str,
        selected_rows: List[Dict[str, Any]],
        tiles: List[Dict[str, Any]],
        include_visualization: bool = False,
    ) -> None:
        self.state.detailsProvenanceContext = (
            "visualization" if include_visualization else "variable"
        )
        provenance = _details_provenance_summary(
            variable_label,
            selected_rows,
            tiles,
            include_visualization=include_visualization,
        )
        self.state.detailsProvenanceKind = str(provenance.get("kind", "") or "")
        self.state.detailsProvenanceChain = str(provenance.get("chain", "") or "")
        self.state.detailsProvenanceCompact = str(
            provenance.get("compact", "") or ""
        )
        self.state.detailsProvenanceExpanded = {}
        self.state.detailsProvenanceNodes = _apply_provenance_expansion(
            list(provenance.get("nodes", []) or []),
            self.state.detailsProvenanceExpanded,
        )
        self.state.detailsProvenanceGraph = _apply_provenance_graph_expansion(
            list(provenance.get("graph", []) or []),
            self.state.detailsProvenanceExpanded,
        )

    def details_provenance_includes_visualization(self) -> bool:
        return (
            str(getattr(self.state, "detailsProvenanceContext", "") or "variable")
            == "visualization"
        )

    def set_details_provenance_context(
        self, include_visualization: bool = False
    ) -> None:
        self.state.detailsProvenanceContext = (
            "visualization" if include_visualization else "variable"
        )

    def pick_var(self, var_name: str, **_):
        picked = str(var_name or "")
        self.set_details_provenance_context(False)
        if str(self.state.selectedVar or "") == picked:
            self.state.selectedVar = ""
            self.state.draggedVar = ""
        else:
            self.state.selectedVar = picked
            self.state.draggedVar = picked

    def select_var(self, var_name: str, button=0, **_):
        try:
            if int(button) == 2:
                return
        except Exception:
            pass

        picked = str(var_name or "")
        if not picked:
            return
        self.set_details_provenance_context(False)
        self.state.selectedVar = picked
        self.state.draggedVar = picked

    def set_dragged_var(self, var_name: str, **_):
        self.state.draggedVar = str(var_name or "")

    def open_provenance_dialog(self, **_):
        if self.state.detailsProvenanceChain:
            self.state.showProvenanceModal = True

    def close_provenance_dialog(self, **_):
        self.state.showProvenanceModal = False

    def toggle_provenance_node_details(self, node_id: str, **_):
        target = str(node_id or "")
        if not target:
            return

        nodes = [
            dict(node)
            for node in (getattr(self.state, "detailsProvenanceNodes", []) or [])
            if isinstance(node, dict)
        ]
        graph = [
            dict(segment)
            for segment in (getattr(self.state, "detailsProvenanceGraph", []) or [])
            if isinstance(segment, dict)
        ]
        detail_node_ids = _provenance_detail_node_ids(
            nodes
        ) | _provenance_graph_detail_node_ids(graph)
        if target not in detail_node_ids:
            return

        expanded = dict(getattr(self.state, "detailsProvenanceExpanded", {}) or {})
        expanded[target] = not bool(expanded.get(target, False))
        self.state.detailsProvenanceExpanded = expanded
        self.state.detailsProvenanceNodes = _apply_provenance_expansion(
            nodes,
            expanded,
        )
        self.state.detailsProvenanceGraph = _apply_provenance_graph_expansion(
            graph,
            expanded,
        )

    def toggle_variable_group(self, group_name: str, **_):
        name = str(group_name or "").strip()
        if not name:
            return
        collapsed = dict(self.state.variableGroupCollapsed or {})
        collapsed[name] = not bool(collapsed.get(name, False))
        self.state.variableGroupCollapsed = collapsed
        collapsed_by_view = dict(
            getattr(self.state, "variableGroupCollapsedByView", {}) or {}
        )
        collapsed_by_view[self.variable_pane_view()] = dict(collapsed)
        self.state.variableGroupCollapsedByView = collapsed_by_view

    def show_query_help(self, **_):
        self.show_help("Query Help")

    def show_source_filter_help(self, **_):
        self.show_help("Source Filter Help")

    def close_help_modal(self, **_):
        self.state.showHelpModal = False

    def update_query_state(self) -> bool:
        q = (self.state.queryText or "").strip()

        if not q:
            self.state.queryFilter = {}
            self.state.querySourceFilters = []
            self.state.querySourceRestrictionFilter = {}
            self.state.querySourceRestrictionCount = 0
            self.state.queryError = ""
            self.state.queryStatus = "Query cleared"
            self.state.queryViewLabel = "ALL"
            return True

        try:
            evaluation = self.evaluate_query_text(q)
            self.state.queryFilter = evaluation["query_filter"]
            self.state.querySourceFilters = evaluation["source_filters"]
            self.state.querySourceRestrictionFilter = evaluation[
                "source_restriction"
            ]
            self.state.querySourceRestrictionCount = evaluation["source_count"]
            self.state.queryError = ""
            self.state.queryStatus = (
                f"Query OK · {evaluation['source_count']} source "
                f"run{'s' if evaluation['source_count'] != 1 else ''}"
                if evaluation["source_filters"]
                else "Query OK"
            )
            self.state.queryViewLabel = q
        except Exception as e:
            self.state.queryError = f"{type(e).__name__}: {e}"
            self.state.queryStatus = "Query ERROR · active query unchanged"
            return False

        return True

    def evaluate_query_text(self, query_text: str) -> Dict[str, Any]:
        q = str(query_text or "").strip()
        if not q:
            return {
                "query_filter": {},
                "source_filters": [],
                "source_restriction": {},
                "source_count": 0,
                "variable_count": 0,
            }

        query_filter, source_filters = python_query_to_filters(q)
        source_restriction: Dict[str, Any] = {}
        source_count = 0
        if source_filters:
            source_summary = self.application.resolve_source_restriction(
                {"queries": source_filters}
            )
            source_restriction = dict(source_summary.get("query", {}) or {})
            source_count = int(source_summary.get("count", 0) or 0)

        active_filter = self.combined_query_filter(
            query_filter,
            source_restriction,
        )
        navigation = self.application.get_navigation(
            {
                "view": self.variable_pane_view(),
                "query": active_filter or {},
                "only_visualized": bool(self.state.showOnlyVisualizedVars),
                "parent_id": None,
            }
        )
        variable_ids = {
            str((child.get("resource") or {}).get("variable_id", "") or "")
            for node in navigation
            for child in (node.get("children", []) or [])
            if child.get("kind") == "variable"
        }
        variable_ids.discard("")
        return {
            "query_filter": query_filter,
            "source_filters": source_filters,
            "source_restriction": source_restriction,
            "source_count": source_count,
            "variable_count": len(variable_ids),
        }

    def run_query(self, **_):
        if self.update_query_state():
            pending_plan = getattr(
                self, "_interaction_pending_query_action_plan", None
            )
            pending_origin = str(
                getattr(self, "_interaction_pending_query_origin", "manual")
                or "manual"
            )
            self.state.activeViewerActionPlan = {}
            self.state.activeNaturalLanguageQuery = ""
            self.refresh_after_variable_catalog_change()
            if str(self.state.queryText or "").strip():
                self.record_query_applied(
                    origin=pending_origin,
                    target="catalog",
                    action_plan=pending_plan,
                )
            return True
        return False

    def clear_query(self, **_):
        previous_query_id = self._interaction_query_id
        had_query = bool(str(self.state.queryText or "").strip())
        self.state.activeViewerActionPlan = {}
        self.state.activeNaturalLanguageQuery = ""
        self.state.queryText = ""
        self.update_query_state()
        self.refresh_after_variable_catalog_change()
        if had_query or previous_query_id:
            self.record_interaction(
                "query.cleared",
                source="query_toolbar",
                payload={"query_id": previous_query_id, "target": "catalog"},
            )
        self._interaction_query_id = ""

    def on_show_only_visualized_vars(self, showOnlyVisualizedVars, **_):
        self.refresh_after_variable_catalog_change()

    def on_variable_pane_view(self, variablePaneView, **_):
        self.refresh_variable_list()

    def on_variable_search_text(self, variableSearchText, **_):
        self.update_variable_search_results()

    def on_selected_var(self, selectedVar, **_):
        if not selectedVar:
            clear_right_panes(self.state)
            backend_status = self.application.get_backend_status()
            self.state.dbOk = backend_status.ok
            self.state.dbStatus = (
                "Connected"
                if backend_status.ok
                else f"DB error: {backend_status.error}"
            )
            return
        self.update_selected_var_panels(
            selectedVar,
            include_visualization_provenance=(
                self.details_provenance_includes_visualization()
            ),
        )
