"""Validated viewer-action contracts produced by natural-language interfaces."""

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Union


MAX_ACTIONS = 1
MAX_CONDITIONS = 32
MAX_CONDITION_VALUES = 100
MAX_CONDITION_TEXT_LENGTH = 1024
VIEWER_ACTION_SCHEMA_VERSION = 1

TEXT_FIELDS = {
    "variable_id",
    "variable_name",
    "variable_type",
    "source_dataset",
    "producer",
    "casename",
    "file",
}
NUMERIC_FIELDS = {"minimum", "maximum"}
CONDITION_FIELDS = TEXT_FIELDS | NUMERIC_FIELDS
CONDITION_OPERATORS = {
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
}


class ViewerActionValidationError(ValueError):
    """Raised when a proposed viewer action is outside the supported schema."""


@dataclass(frozen=True)
class CatalogCondition:
    field: str
    operator: str
    value: Any


@dataclass(frozen=True)
class SourceRank:
    enabled: bool = False
    variable_id: str = ""
    field: str = ""
    direction: str = ""
    limit: int = 1
    include_ties: bool = True


@dataclass(frozen=True)
class CatalogQueryAction:
    action_type: str
    select: str
    result_variable_id: str
    conditions: Tuple[CatalogCondition, ...] = ()
    source_conditions: Tuple[CatalogCondition, ...] = ()
    rank: SourceRank = field(default_factory=SourceRank)


@dataclass(frozen=True)
class VisualizationAddAction:
    action_type: str
    variable_id: str
    target: str = "active_cell"


ViewerAction = Union[CatalogQueryAction, VisualizationAddAction]


@dataclass(frozen=True)
class ViewerActionProposal:
    status: str
    actions: Tuple[ViewerAction, ...]
    explanation: str
    assumptions: Tuple[str, ...] = ()
    clarification: str = ""
    version: int = VIEWER_ACTION_SCHEMA_VERSION


CONDITION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "field": {
            "type": "string",
            "enum": sorted(CONDITION_FIELDS),
        },
        "operator": {
            "type": "string",
            "enum": sorted(CONDITION_OPERATORS),
        },
        "value": {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
                {
                    "type": "array",
                    "maxItems": MAX_CONDITION_VALUES,
                    "items": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "number"},
                        ]
                    },
                },
            ]
        },
    },
    "required": ["field", "operator", "value"],
}


CATALOG_QUERY_ACTION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ["catalog.query"]},
        "arguments": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "select": {
                    "type": "string",
                    "enum": ["variables", "sources"],
                },
                "result_variable_id": {"type": "string"},
                "conditions": {
                    "type": "array",
                    "maxItems": MAX_CONDITIONS,
                    "items": CONDITION_JSON_SCHEMA,
                },
                "source_conditions": {
                    "type": "array",
                    "maxItems": MAX_CONDITIONS,
                    "items": CONDITION_JSON_SCHEMA,
                },
                "rank": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "variable_id": {"type": "string"},
                        "field": {
                            "type": "string",
                            "enum": ["", "minimum", "maximum"],
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["", "ascending", "descending"],
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1,
                        },
                        "include_ties": {"type": "boolean"},
                    },
                    "required": [
                        "enabled",
                        "variable_id",
                        "field",
                        "direction",
                        "limit",
                        "include_ties",
                    ],
                },
            },
            "required": [
                "select",
                "result_variable_id",
                "conditions",
                "source_conditions",
                "rank",
            ],
        },
    },
    "required": ["type", "arguments"],
}


VISUALIZATION_ADD_ACTION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ["visualization.add"]},
        "arguments": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "variable_id": {"type": "string"},
                "target": {
                    "type": "string",
                    "enum": ["active_cell"],
                },
            },
            "required": ["variable_id", "target"],
        },
    },
    "required": ["type", "arguments"],
}


VIEWER_ACTION_PROPOSAL_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "version": {
            "type": "integer",
            "enum": [VIEWER_ACTION_SCHEMA_VERSION],
        },
        "status": {
            "type": "string",
            "enum": ["proposal", "needs_clarification"],
        },
        "actions": {
            "type": "array",
            "maxItems": MAX_ACTIONS,
            "items": {
                "oneOf": [
                    CATALOG_QUERY_ACTION_JSON_SCHEMA,
                    VISUALIZATION_ADD_ACTION_JSON_SCHEMA,
                ]
            },
        },
        "explanation": {"type": "string"},
        "assumptions": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string"},
        },
        "clarification": {"type": "string"},
    },
    "required": [
        "version",
        "status",
        "actions",
        "explanation",
        "assumptions",
        "clarification",
    ],
}


def _exact_keys(value: Dict[str, Any], expected: set, field: str) -> None:
    extra = set(value) - expected
    missing = expected - set(value)
    if extra:
        raise ViewerActionValidationError(
            f"{field} contains unsupported fields: {', '.join(sorted(extra))}"
        )
    if missing:
        raise ViewerActionValidationError(
            f"{field} is missing fields: {', '.join(sorted(missing))}"
        )


def _text(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ViewerActionValidationError(f"{field} must be text")
    result = value.strip()
    if not allow_empty and not result:
        raise ViewerActionValidationError(f"{field} must not be empty")
    if len(result) > MAX_CONDITION_TEXT_LENGTH:
        raise ViewerActionValidationError(f"{field} is too long")
    return result


def _condition_value(field: str, operator: str, value: Any) -> Any:
    if operator in {"in", "not_in"}:
        if not isinstance(value, list) or not value:
            raise ViewerActionValidationError(
                f"{operator} requires a non-empty value list"
            )
        if len(value) > MAX_CONDITION_VALUES:
            raise ViewerActionValidationError("Condition value list is too large")
        values = value
    else:
        if isinstance(value, list):
            raise ViewerActionValidationError(
                f"{operator} requires one scalar value"
            )
        values = [value]

    normalized = []
    for item in values:
        if field in TEXT_FIELDS:
            normalized.append(_text(item, f"{field} value", allow_empty=False))
        else:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ViewerActionValidationError(
                    f"{field} requires a numeric value"
                )
            number = float(item)
            if not math.isfinite(number):
                raise ViewerActionValidationError(
                    f"{field} requires a finite value"
                )
            normalized.append(item)

    if operator == "contains" and field not in TEXT_FIELDS:
        raise ViewerActionValidationError("contains is only valid for text fields")
    if operator in {"gt", "gte", "lt", "lte"} and field not in NUMERIC_FIELDS:
        raise ViewerActionValidationError(
            f"{operator} is only valid for numeric fields"
        )
    return normalized if isinstance(value, list) else normalized[0]


def parse_catalog_condition(payload: Any) -> CatalogCondition:
    if not isinstance(payload, dict):
        raise ViewerActionValidationError("Catalog condition must be an object")
    _exact_keys(payload, {"field", "operator", "value"}, "Catalog condition")
    field = _text(payload["field"], "Condition field", allow_empty=False)
    operator = _text(
        payload["operator"], "Condition operator", allow_empty=False
    )
    if field not in CONDITION_FIELDS:
        raise ViewerActionValidationError(f"Unsupported condition field: {field}")
    if operator not in CONDITION_OPERATORS:
        raise ViewerActionValidationError(
            f"Unsupported condition operator: {operator}"
        )
    return CatalogCondition(
        field=field,
        operator=operator,
        value=_condition_value(field, operator, payload["value"]),
    )


def _parse_conditions(payload: Any, field: str) -> Tuple[CatalogCondition, ...]:
    if not isinstance(payload, list):
        raise ViewerActionValidationError(f"{field} must be a list")
    if len(payload) > MAX_CONDITIONS:
        raise ViewerActionValidationError(f"{field} contains too many conditions")
    return tuple(parse_catalog_condition(item) for item in payload)


def parse_source_rank(payload: Any) -> SourceRank:
    if not isinstance(payload, dict):
        raise ViewerActionValidationError("Rank must be an object")
    expected = {
        "enabled",
        "variable_id",
        "field",
        "direction",
        "limit",
        "include_ties",
    }
    _exact_keys(payload, expected, "Rank")
    enabled = payload["enabled"]
    include_ties = payload["include_ties"]
    limit = payload["limit"]
    if not isinstance(enabled, bool) or not isinstance(include_ties, bool):
        raise ViewerActionValidationError("Rank flags must be Boolean")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit != 1:
        raise ViewerActionValidationError("Phase 1 ranking supports limit 1")
    variable_id = _text(payload["variable_id"], "Rank variable_id")
    field = _text(payload["field"], "Rank field")
    direction = _text(payload["direction"], "Rank direction")
    if enabled:
        if field not in NUMERIC_FIELDS:
            raise ViewerActionValidationError(
                "Enabled rank field must be minimum or maximum"
            )
        if direction not in {"ascending", "descending"}:
            raise ViewerActionValidationError(
                "Enabled rank direction must be ascending or descending"
            )
        if not include_ties:
            raise ViewerActionValidationError(
                "Phase 1 ranking always includes tied sources"
            )
    elif variable_id or field or direction:
        raise ViewerActionValidationError(
            "Disabled rank must leave variable_id, field, and direction empty"
        )
    return SourceRank(
        enabled=enabled,
        variable_id=variable_id,
        field=field,
        direction=direction,
        limit=limit,
        include_ties=include_ties,
    )


def parse_catalog_query_action(payload: Any) -> CatalogQueryAction:
    if not isinstance(payload, dict):
        raise ViewerActionValidationError("Viewer action must be an object")
    _exact_keys(payload, {"type", "arguments"}, "Viewer action")
    action_type = _text(payload["type"], "Action type", allow_empty=False)
    if action_type != "catalog.query":
        raise ViewerActionValidationError(f"Unsupported action type: {action_type}")
    arguments = payload["arguments"]
    if not isinstance(arguments, dict):
        raise ViewerActionValidationError("Action arguments must be an object")
    expected = {
        "select",
        "result_variable_id",
        "conditions",
        "source_conditions",
        "rank",
    }
    _exact_keys(arguments, expected, "Catalog query arguments")
    select = _text(arguments["select"], "Catalog selection", allow_empty=False)
    if select not in {"variables", "sources"}:
        raise ViewerActionValidationError(f"Unsupported catalog selection: {select}")
    action = CatalogQueryAction(
        action_type=action_type,
        select=select,
        result_variable_id=_text(
            arguments["result_variable_id"], "Result variable_id"
        ),
        conditions=_parse_conditions(arguments["conditions"], "Conditions"),
        source_conditions=_parse_conditions(
            arguments["source_conditions"], "Source conditions"
        ),
        rank=parse_source_rank(arguments["rank"]),
    )
    if (
        not action.result_variable_id
        and not action.conditions
        and not action.source_conditions
        and not action.rank.enabled
    ):
        raise ViewerActionValidationError("Catalog query action is empty")
    return action


def parse_visualization_add_action(payload: Any) -> VisualizationAddAction:
    if not isinstance(payload, dict):
        raise ViewerActionValidationError("Viewer action must be an object")
    _exact_keys(payload, {"type", "arguments"}, "Viewer action")
    action_type = _text(payload["type"], "Action type", allow_empty=False)
    if action_type != "visualization.add":
        raise ViewerActionValidationError(f"Unsupported action type: {action_type}")
    arguments = payload["arguments"]
    if not isinstance(arguments, dict):
        raise ViewerActionValidationError("Action arguments must be an object")
    _exact_keys(
        arguments,
        {"variable_id", "target"},
        "Visualization add arguments",
    )
    variable_id = _text(
        arguments["variable_id"],
        "Visualization variable_id",
        allow_empty=False,
    )
    target = _text(
        arguments["target"],
        "Visualization target",
        allow_empty=False,
    )
    if target != "active_cell":
        raise ViewerActionValidationError(
            f"Unsupported visualization target: {target}"
        )
    return VisualizationAddAction(
        action_type=action_type,
        variable_id=variable_id,
        target=target,
    )


def parse_viewer_action(payload: Any) -> ViewerAction:
    if not isinstance(payload, dict):
        raise ViewerActionValidationError("Viewer action must be an object")
    action_type = payload.get("type")
    if action_type == "catalog.query":
        return parse_catalog_query_action(payload)
    if action_type == "visualization.add":
        return parse_visualization_add_action(payload)
    raise ViewerActionValidationError(f"Unsupported action type: {action_type}")


def catalog_action_to_dict(action: CatalogQueryAction) -> Dict[str, Any]:
    def condition_dict(condition: CatalogCondition) -> Dict[str, Any]:
        value = condition.value
        if isinstance(value, tuple):
            value = list(value)
        return {
            "field": condition.field,
            "operator": condition.operator,
            "value": value,
        }

    return {
        "type": action.action_type,
        "arguments": {
            "select": action.select,
            "result_variable_id": action.result_variable_id,
            "conditions": [
                condition_dict(condition) for condition in action.conditions
            ],
            "source_conditions": [
                condition_dict(condition) for condition in action.source_conditions
            ],
            "rank": {
                "enabled": action.rank.enabled,
                "variable_id": action.rank.variable_id,
                "field": action.rank.field,
                "direction": action.rank.direction,
                "limit": action.rank.limit,
                "include_ties": action.rank.include_ties,
            },
        },
    }


def visualization_action_to_dict(
    action: VisualizationAddAction,
) -> Dict[str, Any]:
    return {
        "type": action.action_type,
        "arguments": {
            "variable_id": action.variable_id,
            "target": action.target,
        },
    }


def viewer_action_plan_to_dict(
    actions: Tuple[ViewerAction, ...],
    *,
    version: int = VIEWER_ACTION_SCHEMA_VERSION,
) -> Dict[str, Any]:
    if version != VIEWER_ACTION_SCHEMA_VERSION:
        raise ViewerActionValidationError(
            f"Unsupported viewer action schema version: {version}"
        )
    serialized = []
    for action in actions:
        if isinstance(action, CatalogQueryAction):
            serialized.append(catalog_action_to_dict(action))
        elif isinstance(action, VisualizationAddAction):
            serialized.append(visualization_action_to_dict(action))
        else:
            raise ViewerActionValidationError(
                f"Unsupported viewer action object: {type(action).__name__}"
            )
    return {"version": version, "actions": serialized}


def _query_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_query_value(item) for item in value) + "]"
    return repr(value)


def compile_catalog_condition(condition: CatalogCondition) -> str:
    field = {"minimum": "min", "maximum": "max"}.get(
        condition.field, condition.field
    )
    if condition.operator == "contains":
        return f"contains({field}, {_query_value(condition.value)})"
    operator = {
        "eq": "==",
        "ne": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "in": "in",
        "not_in": "not in",
    }[condition.operator]
    return f"{field} {operator} {_query_value(condition.value)}"


def _joined_conditions(conditions: Tuple[CatalogCondition, ...]) -> list:
    return [compile_catalog_condition(condition) for condition in conditions]


def compile_catalog_query(
    action: CatalogQueryAction,
    *,
    rank_value: Optional[float] = None,
) -> str:
    """Materialize a validated catalog action through the legacy query path."""

    outer = []
    source_terms = []
    result_term = (
        f"id == {_query_value(action.result_variable_id)}"
        if action.result_variable_id
        else ""
    )

    if action.select == "variables":
        if result_term:
            outer.append(result_term)
        outer.extend(_joined_conditions(action.conditions))
        source_inner = _joined_conditions(action.source_conditions)
        if source_inner:
            source_terms.append(f"source({' and '.join(source_inner)})")
    else:
        source_inner = []
        if result_term:
            source_inner.append(result_term)
        source_inner.extend(_joined_conditions(action.conditions))
        source_inner.extend(_joined_conditions(action.source_conditions))
        rank_is_only_result = (
            action.rank.enabled
            and action.result_variable_id
            and action.result_variable_id == action.rank.variable_id
            and len(source_inner) == 1
        )
        if source_inner and not rank_is_only_result:
            source_terms.append(f"source({' and '.join(source_inner)})")

    if action.rank.enabled:
        if rank_value is None:
            raise ViewerActionValidationError(
                "Ranked catalog query requires a resolved rank value"
            )
        rank_variable_id = action.rank.variable_id or action.result_variable_id
        if not rank_variable_id:
            raise ViewerActionValidationError("Ranked query requires a variable")
        rank_field = "min" if action.rank.field == "minimum" else "max"
        rank_inner = (
            f"id == {_query_value(rank_variable_id)} and "
            f"{rank_field} == {_query_value(rank_value)}"
        )
        source_terms.append(f"source({rank_inner})")

    return " and ".join([*outer, *source_terms])


def compile_source_filter_query(
    action: CatalogQueryAction,
    *,
    rank_value: Optional[float] = None,
) -> str:
    """Materialize an action for rows of the Sources dialog's current variable."""

    if action.select != "sources":
        raise ViewerActionValidationError(
            "Source Filter query requires a source selection"
        )

    terms = _joined_conditions(action.conditions)
    source_conditions = _joined_conditions(action.source_conditions)
    if source_conditions:
        terms.append(f"source({' and '.join(source_conditions)})")

    if action.rank.enabled:
        if rank_value is None:
            raise ViewerActionValidationError(
                "Ranked source filter requires a resolved rank value"
            )
        rank_field = "min" if action.rank.field == "minimum" else "max"
        rank_term = f"{rank_field} == {_query_value(rank_value)}"
        if action.rank.variable_id in {"", action.result_variable_id}:
            terms.append(rank_term)
        else:
            terms.append(
                "source("
                f"id == {_query_value(action.rank.variable_id)} and {rank_term}"
                ")"
            )

    return " and ".join(terms)


def summarize_catalog_query(
    action: CatalogQueryAction,
    *,
    rank_value: Optional[float] = None,
    tie_count: int = 0,
) -> str:
    entity = "sources" if action.select == "sources" else "variables"
    variable_id = action.result_variable_id or action.rank.variable_id
    if action.rank.enabled:
        direction = "largest" if action.rank.direction == "descending" else "smallest"
        summary = (
            f"Select {entity} for {variable_id or 'the selected variable'} with "
            f"the {direction} source {action.rank.field}."
        )
        if rank_value is not None:
            summary += f" Resolved {action.rank.field}: {rank_value:g}."
        if tie_count > 1:
            summary += f" {tie_count} sources are tied."
        return summary

    parts = [f"Select {entity}"]
    if variable_id:
        parts.append(f"for {variable_id}")
    condition_count = len(action.conditions) + len(action.source_conditions)
    if condition_count:
        parts.append(
            f"using {condition_count} metadata condition"
            f"{'s' if condition_count != 1 else ''}"
        )
    return " ".join(parts) + "."


def summarize_visualization_add(
    action: VisualizationAddAction,
    *,
    cell_index: int,
    visualization_name: str,
) -> str:
    visualization = str(visualization_name or "viewer default").strip()
    return (
        f"Add {action.variable_id} to grid cell {cell_index + 1} using "
        f"{visualization}. The active query and current source selection apply."
    )
