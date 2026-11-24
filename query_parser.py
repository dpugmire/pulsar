import ast
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from pulsar.models.query import (
    Compare, Junction, Negate, QueryPlan, query_document, query_from_filter,
    query_matches, legacy_filter,
)


MAX_QUERY_LENGTH = 4096
MAX_QUERY_AST_NODES = 256
MAX_QUERY_DEPTH = 32
MAX_QUERY_PREDICATES = 64
MAX_QUERY_LIST_VALUES = 100
MAX_QUERY_STRING_LENGTH = 1024

FIELD_ALIASES = {
    "id": "variable_id",
    "var": "variable_name",
    "type": "variable_type",
    "dataset": "source_dataset",
    "source": "source_dataset",
    "min": "min",
    "max": "max",
}

ALLOWED_FIELDS = {
    "variable_name",
    "variable_id",
    "variable_type",
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
    "frame_index",
    "min",
    "max",
}

TEXT_FIELDS = {
    "variable_name",
    "variable_id",
    "variable_type",
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
}

NUMERIC_FIELDS = {
    "frame_index",
    "min",
    "max",
}


class QueryValidationError(ValueError):
    """Raised when query text is outside Pulsar's supported language."""


def _field_name(name: str) -> str:
    mapped = FIELD_ALIASES.get(name, name)
    if mapped not in ALLOWED_FIELDS:
        raise QueryValidationError(f"Unknown/unsupported field: {name}")
    return mapped


def _const(node: ast.AST):
    if isinstance(node, ast.Constant):
        value = node.value
        if value is not None and not isinstance(value, (str, int, float)):
            raise QueryValidationError(
                f"Unsupported constant type: {type(value).__name__}"
            )
        if isinstance(value, str) and len(value) > MAX_QUERY_STRING_LENGTH:
            raise QueryValidationError(
                f"String values are limited to {MAX_QUERY_STRING_LENGTH} characters"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise QueryValidationError("Numeric values must be finite")
        return value

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _const(node.operand)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise QueryValidationError(
                "Unary +/- is only allowed on numeric constants"
            )
        return +v if isinstance(node.op, ast.UAdd) else -v

    if isinstance(node, (ast.List, ast.Tuple)):
        if len(node.elts) > MAX_QUERY_LIST_VALUES:
            raise QueryValidationError(
                f"Membership lists are limited to {MAX_QUERY_LIST_VALUES} values"
            )
        return [_const(elt) for elt in node.elts]

    raise QueryValidationError(
        f"Only constants/lists are allowed, got: {type(node).__name__}"
    )


def _validate_field_value(field: str, value: Any) -> None:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, (list, tuple)):
            raise QueryValidationError("Membership values must be scalar constants")
        if item is None:
            continue
        if field in TEXT_FIELDS:
            if not isinstance(item, str):
                raise QueryValidationError(f"{field} requires a text value")
            continue
        if field in NUMERIC_FIELDS:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise QueryValidationError(f"{field} requires a numeric value")
            if isinstance(item, float) and not math.isfinite(item):
                raise QueryValidationError(f"{field} requires a finite value")


def _parse_query(expr: str) -> ast.Expression:
    text = (expr or "").strip()
    if len(text) > MAX_QUERY_LENGTH:
        raise QueryValidationError(
            f"Queries are limited to {MAX_QUERY_LENGTH} characters"
        )
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        location = f" at column {e.offset}" if e.offset else ""
        raise QueryValidationError(f"Invalid query syntax{location}: {e.msg}") from e

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_QUERY_AST_NODES:
        raise QueryValidationError(
            f"Query is too complex ({len(nodes)} syntax nodes; "
            f"maximum {MAX_QUERY_AST_NODES})"
        )

    max_depth = 0
    stack = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        max_depth = max(max_depth, depth)
        if max_depth > MAX_QUERY_DEPTH:
            raise QueryValidationError(
                f"Query nesting exceeds the maximum depth of {MAX_QUERY_DEPTH}"
            )
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))

    predicate_count = sum(
        isinstance(node, ast.Compare)
        or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"contains", "source"}
        )
        for node in nodes
    )
    if predicate_count > MAX_QUERY_PREDICATES:
        raise QueryValidationError(
            f"Queries are limited to {MAX_QUERY_PREDICATES} predicates"
        )
    return tree


def _compile_query_node(node: ast.AST):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "source":
        raise QueryValidationError(
            "source(...) is only supported as a top-level 'and' clause"
        )

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "contains":
        if len(node.args) != 2 or node.keywords:
            raise QueryValidationError(
                "contains(...) takes exactly a field name and a search string"
            )
        field_node, search_node = node.args
        if not isinstance(field_node, ast.Name):
            raise QueryValidationError(
                "contains(...) first argument must be a field name"
            )
        field = _field_name(field_node.id)
        if field not in TEXT_FIELDS:
            raise QueryValidationError(
                f"contains(...) is only supported for text fields, not {field}"
            )
        search_text = _const(search_node)
        if not isinstance(search_text, str) or not search_text:
            raise QueryValidationError(
                "contains(...) search value must be a non-empty string"
            )
        return Compare(field, "regex", re.escape(search_text))

    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else "or"
        return Junction(op, tuple(_compile_query_node(v) for v in node.values))

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return Negate(_compile_query_node(node.operand))

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise QueryValidationError("Chained comparisons are not supported")

        left = node.left
        op = node.ops[0]
        right = node.comparators[0]

        if not isinstance(left, ast.Name):
            raise QueryValidationError("Left side must be a field name")

        field = _field_name(left.id)

        if isinstance(op, ast.Eq):
            if isinstance(right, (ast.List, ast.Tuple)):
                raise QueryValidationError(
                    "Use 'in' rather than comparing a field to a list"
                )
            value = _const(right)
            _validate_field_value(field, value)
            return Compare(field, "eq", value)
        if isinstance(op, ast.NotEq):
            if isinstance(right, (ast.List, ast.Tuple)):
                raise QueryValidationError(
                    "Use 'not in' rather than comparing a field to a list"
                )
            value = _const(right)
            _validate_field_value(field, value)
            return Compare(field, "ne", value)
        if isinstance(op, ast.In):
            if not isinstance(right, (ast.List, ast.Tuple)):
                raise QueryValidationError(
                    "The right side of 'in' must be a list or tuple"
                )
            value = _const(right)
            _validate_field_value(field, value)
            return Compare(field, "in", tuple(value))
        if isinstance(op, ast.NotIn):
            if not isinstance(right, (ast.List, ast.Tuple)):
                raise QueryValidationError(
                    "The right side of 'not in' must be a list or tuple"
                )
            value = _const(right)
            _validate_field_value(field, value)
            return Compare(field, "nin", tuple(value))

        ordered_operators = {
            ast.Gt: "gt",
            ast.GtE: "gte",
            ast.Lt: "lt",
            ast.LtE: "lte",
        }
        for operator_type, filter_operator in ordered_operators.items():
            if isinstance(op, operator_type):
                if field not in NUMERIC_FIELDS:
                    raise QueryValidationError(
                        f"Ordered comparisons are not supported for {field}"
                    )
                value = _const(right)
                _validate_field_value(field, value)
                if value is None or isinstance(value, list):
                    raise QueryValidationError("Ordered comparisons require a finite number")
                return Compare(field, filter_operator, value)

        raise QueryValidationError(f"Unsupported operator: {type(op).__name__}")

    if isinstance(node, ast.Name):
        field = _field_name(node.id)
        return Compare(field, "ne", None)

    raise QueryValidationError(f"Unsupported expression: {type(node).__name__}")


def _is_source_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "source"


def _has_source_call(node: ast.AST) -> bool:
    return any(_is_source_call(child) for child in ast.walk(node))


def _top_level_and_terms(node: ast.AST) -> List[ast.AST]:
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        terms: List[ast.AST] = []
        for value in node.values:
            terms.extend(_top_level_and_terms(value))
        return terms
    return [node]


def parse_query(expr: str) -> QueryPlan:
    """Parse text into storage-independent predicates and intersected source clauses."""
    expr = (expr or "").strip()
    if not expr:
        return QueryPlan(Junction("and", ()), ())
    tree = _parse_query(expr)
    predicates, sources = [], []
    for term in _top_level_and_terms(tree.body):
        if _is_source_call(term):
            if len(term.args) != 1 or term.keywords:
                raise QueryValidationError("source(...) takes exactly one query expression")
            if _has_source_call(term.args[0]):
                raise QueryValidationError("Nested source(...) clauses are not supported")
            sources.append(_compile_query_node(term.args[0]))
        else:
            if _has_source_call(term):
                raise QueryValidationError("source(...) is only supported as a top-level 'and' clause")
            predicates.append(_compile_query_node(term))
    predicate = predicates[0] if len(predicates) == 1 else Junction("and", tuple(predicates))
    return QueryPlan(predicate, tuple(sources))


def parse_query_filters(expr: str):
    """JSON-safe query documents for Trame and backend requests."""
    plan = parse_query(expr)
    return query_document(plan.predicate), [query_document(item) for item in plan.sources]


def python_query_to_mongo(expr: str) -> Dict[str, Any]:
    """Compatibility export for callers that still require collection filters."""
    plan = parse_query(expr)
    if plan.sources:
        raise QueryValidationError("source(...) is only supported as a top-level 'and' clause")
    return legacy_filter(plan.predicate)


def python_query_to_filters(expr: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Compatibility export; new controllers use parse_query_filters."""
    plan = parse_query(expr)
    return legacy_filter(plan.predicate), [legacy_filter(item) for item in plan.sources]


def and_filter(base: Dict[str, Any], extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not extra:
        return base
    if (base or {}).get("query_version") or extra.get("query_version"):
        return query_document(Junction("and", (query_from_filter(base), query_from_filter(extra))))
    return {"$and": [base, extra]}


def mongo_filter_matches(filter_doc: Dict[str, Any], values: Dict[str, Any]) -> bool:
    """Compatibility export using the shared two-valued query evaluator."""
    return query_matches(query_from_filter(filter_doc), values)
