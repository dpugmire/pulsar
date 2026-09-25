import ast
import math
import re
from typing import Any, Dict, List, Optional, Tuple


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


def _compile_query_node(node: ast.AST) -> Dict[str, Any]:
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
        return {field: {"$regex": re.escape(search_text)}}

    if isinstance(node, ast.BoolOp):
        op = "$and" if isinstance(node.op, ast.And) else "$or"
        parts = [_compile_query_node(v) for v in node.values]
        flat: List[Dict[str, Any]] = []
        for p in parts:
            if isinstance(p, dict) and op in p and len(p) == 1:
                flat.extend(p[op])
            else:
                flat.append(p)
        return {op: flat}

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _compile_query_node(node.operand)
        return {"$nor": [inner]}

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
            return {field: value}
        if isinstance(op, ast.NotEq):
            if isinstance(right, (ast.List, ast.Tuple)):
                raise QueryValidationError(
                    "Use 'not in' rather than comparing a field to a list"
                )
            value = _const(right)
            _validate_field_value(field, value)
            return {field: {"$ne": value}}
        if isinstance(op, ast.In):
            if not isinstance(right, (ast.List, ast.Tuple)):
                raise QueryValidationError(
                    "The right side of 'in' must be a list or tuple"
                )
            value = _const(right)
            _validate_field_value(field, value)
            return {field: {"$in": value}}
        if isinstance(op, ast.NotIn):
            if not isinstance(right, (ast.List, ast.Tuple)):
                raise QueryValidationError(
                    "The right side of 'not in' must be a list or tuple"
                )
            value = _const(right)
            _validate_field_value(field, value)
            return {field: {"$nin": value}}

        ordered_operators = {
            ast.Gt: "$gt",
            ast.GtE: "$gte",
            ast.Lt: "$lt",
            ast.LtE: "$lte",
        }
        for operator_type, filter_operator in ordered_operators.items():
            if isinstance(op, operator_type):
                if field not in NUMERIC_FIELDS:
                    raise QueryValidationError(
                        f"Ordered comparisons are not supported for {field}"
                    )
                value = _const(right)
                _validate_field_value(field, value)
                return {field: {filter_operator: value}}

        raise QueryValidationError(f"Unsupported operator: {type(op).__name__}")

    if isinstance(node, ast.Name):
        field = _field_name(node.id)
        return {field: {"$ne": None}}

    raise QueryValidationError(f"Unsupported expression: {type(node).__name__}")


def _combine_and(filters: List[Dict[str, Any]]) -> Dict[str, Any]:
    nonempty = [f for f in filters if f]
    if not nonempty:
        return {}
    if len(nonempty) == 1:
        return nonempty[0]
    return {"$and": nonempty}


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


def python_query_to_mongo(expr: str) -> Dict[str, Any]:
    expr = (expr or "").strip()
    if not expr:
        return {}

    tree = _parse_query(expr)
    return _compile_query_node(tree.body)


def python_query_to_filters(expr: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    expr = (expr or "").strip()
    if not expr:
        return {}, []

    tree = _parse_query(expr)
    doc_filters: List[Dict[str, Any]] = []
    source_filters: List[Dict[str, Any]] = []

    for term in _top_level_and_terms(tree.body):
        if _is_source_call(term):
            if len(term.args) != 1 or term.keywords:
                raise QueryValidationError(
                    "source(...) takes exactly one query expression"
                )
            if _has_source_call(term.args[0]):
                raise QueryValidationError(
                    "Nested source(...) clauses are not supported"
                )
            source_filters.append(_compile_query_node(term.args[0]))
            continue

        if _has_source_call(term):
            raise QueryValidationError(
                "source(...) is only supported as a top-level 'and' clause"
            )

        doc_filters.append(_compile_query_node(term))

    return _combine_and(doc_filters), source_filters


def and_filter(base: Dict[str, Any], extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not extra:
        return base
    return {"$and": [base, extra]}


def _value_matches(value: Any, condition: Any) -> bool:
    if not isinstance(condition, dict):
        return value == condition

    for op, expected in condition.items():
        if op == "$ne":
            if value == expected:
                return False
            continue

        if op in {"$in", "$nin"}:
            try:
                matched = value in expected
            except TypeError:
                matched = False
            if op == "$in" and not matched:
                return False
            if op == "$nin" and matched:
                return False
            continue

        if op == "$regex":
            if not isinstance(value, str):
                return False
            return re.search(str(expected), value) is not None

        try:
            if op == "$gt" and not (value > expected):
                return False
            if op == "$gte" and not (value >= expected):
                return False
            if op == "$lt" and not (value < expected):
                return False
            if op == "$lte" and not (value <= expected):
                return False
        except TypeError:
            return False

        if op not in {"$gt", "$gte", "$lt", "$lte"}:
            raise ValueError(f"Unsupported filter operator: {op}")

    return True


def mongo_filter_matches(filter_doc: Dict[str, Any], values: Dict[str, Any]) -> bool:
    if not filter_doc:
        return True

    for key, condition in filter_doc.items():
        if key == "$and":
            return all(mongo_filter_matches(part, values) for part in condition)
        if key == "$or":
            return any(mongo_filter_matches(part, values) for part in condition)
        if key == "$nor":
            return not any(mongo_filter_matches(part, values) for part in condition)
        if key.startswith("$"):
            raise ValueError(f"Unsupported filter operator: {key}")

        if not _value_matches(values.get(key), condition):
            return False

    return True
