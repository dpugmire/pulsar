"""Storage-independent predicates, serialization, and two-valued evaluation.

Missing fields and explicit nulls both evaluate as None. Comparisons return
booleans, including under negation; SQL adapters must preserve this contract.
Legacy collection filters are accepted only as a migration input.
"""

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Tuple, Union


@dataclass(frozen=True)
class Compare:
    field: str
    operator: str
    value: Any

    def __post_init__(self):
        if not isinstance(self.field, str) or not self.field:
            raise ValueError("Query field must be nonempty text")
        if not isinstance(self.operator, str) or self.operator not in _OPERATORS:
            raise ValueError("Unsupported query operator")
        values = self.value if self.operator in {"in", "nin"} else (self.value,)
        if not isinstance(values, tuple):
            raise ValueError("Membership values must be a tuple")
        for value in values:
            if value is not None and not isinstance(value, (str, int, float)):
                raise ValueError("Query values must be scalar constants")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Query values must be finite")
        if self.operator in {"gt", "gte", "lt", "lte"} and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError("Ordered comparisons require a finite number")
        if self.operator == "regex" and not isinstance(self.value, str):
            raise ValueError("Regex requires text")


@dataclass(frozen=True)
class Junction:
    operator: str
    terms: Tuple["Predicate", ...]


@dataclass(frozen=True)
class Negate:
    term: "Predicate"


Predicate = Union[Compare, Junction, Negate]


@dataclass(frozen=True)
class QueryPlan:
    predicate: Predicate
    sources: Tuple[Predicate, ...]


_OPERATORS = {"eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "regex", "exists"}


def query_document(node: Predicate) -> dict:
    """Encode a typed predicate as a versioned, JSON-safe backend request."""
    if isinstance(node, Compare):
        body = {"op": "compare", "field": node.field, "operator": node.operator,
                "value": list(node.value) if isinstance(node.value, tuple) else node.value}
    elif isinstance(node, Negate):
        body = {"op": "not", "term": query_document(node.term)}
    elif isinstance(node, Junction):
        if node.operator == "and" and not node.terms:
            return {}
        body = {"op": node.operator, "terms": [query_document(term) for term in node.terms]}
    else:
        raise ValueError("Unsupported predicate")
    return {"query_version": 1, **body}


def query_from_filter(document: Mapping | None) -> Predicate:
    """Decode a query document or adapt a legacy collection filter.

    Unknown operators and malformed groups fail closed rather than silently
    dropping restrictions. This also supports mixed filters during migration.
    """
    if document is None:
        return Junction("and", ())
    if not isinstance(document, Mapping):
        raise ValueError("Query must be an object")
    if "query_version" in document:
        if document["query_version"] != 1:
            raise ValueError("Unsupported query version")
        op = document.get("op")
        if not isinstance(op, str):
            raise ValueError("Query operation must be text")
        if op == "compare":
            if set(document) != {"query_version", "op", "field", "operator", "value"}:
                raise ValueError("Invalid comparison document")
            field, operator, value = document["field"], document["operator"], document["value"]
            if not isinstance(field, str) or not field or not isinstance(operator, str) or operator not in _OPERATORS:
                raise ValueError("Invalid query field or operator")
            if operator in {"in", "nin"}:
                if not isinstance(value, (list, tuple)):
                    raise ValueError("Membership requires a list")
                value = tuple(value)
            elif isinstance(value, (dict, list, tuple)):
                raise ValueError("Comparison requires a scalar")
            return Compare(field, operator, value)
        if op == "not" and set(document) == {"query_version", "op", "term"}:
            return Negate(query_from_filter(document["term"]))
        if op in {"and", "or"} and set(document) == {"query_version", "op", "terms"}:
            terms = document["terms"]
            if isinstance(terms, (list, tuple)):
                return Junction(op, tuple(query_from_filter(term) for term in terms))
        raise ValueError("Invalid query document")
    terms = []
    for field, condition in document.items():
        if not isinstance(field, str):
            raise ValueError("Query field must be text")
        if field in {"$and", "$or", "$nor"}:
            if not isinstance(condition, (list, tuple)):
                raise ValueError("Boolean query groups require lists")
            group = Junction("and" if field == "$and" else "or",
                             tuple(query_from_filter(term) for term in condition))
            terms.append(Negate(group) if field == "$nor" else group)
        elif field.startswith("$"):
            raise ValueError(f"Unsupported filter operator: {field}")
        elif isinstance(condition, dict):
            for key, value in condition.items():
                if not isinstance(key, str):
                    raise ValueError("Query operator must be text")
                operator = key.removeprefix("$")
                if key != "$" + operator or not isinstance(operator, str) or operator not in _OPERATORS:
                    raise ValueError(f"Unsupported filter operator: {key}")
                if operator in {"in", "nin"}:
                    if not isinstance(value, (list, tuple)):
                        raise ValueError("Membership requires a list")
                    value = tuple(value)
                terms.append(Compare(field, operator, value))
        else:
            terms.append(Compare(field, "eq", condition))
    return terms[0] if len(terms) == 1 else Junction("and", tuple(terms))


def legacy_filter(node: Predicate) -> dict:
    """Adapt predicates at the remaining local collection-policy boundary."""
    if isinstance(node, Compare):
        value = list(node.value) if isinstance(node.value, tuple) else node.value
        return {node.field: value if node.operator == "eq" else {"$" + node.operator: value}}
    if isinstance(node, Negate):
        return {"$nor": [legacy_filter(node.term)]}
    if not node.terms and node.operator == "and":
        return {}
    return {"$" + node.operator: [legacy_filter(term) for term in node.terms]}


def regex_matches(pattern, value):
    """Shared legacy regex behavior; public contains() escapes literal text."""
    if not isinstance(value, str) or len(str(pattern)) > 2048:
        return False
    try:
        return re.search(str(pattern), value) is not None
    except re.error:
        return False


def query_matches(node: Predicate, values: Mapping) -> bool:
    if isinstance(node, Junction):
        matches = (query_matches(term, values) for term in node.terms)
        return all(matches) if node.operator == "and" else any(matches)
    if isinstance(node, Negate):
        return not query_matches(node.term, values)
    value = values.get(node.field)
    expected, operator = node.value, node.operator
    if operator == "eq":
        return value == expected
    if operator == "ne":
        return value != expected
    if operator in {"in", "nin"}:
        matched = value in expected
        return matched if operator == "in" else not matched
    if operator == "exists":
        return (value is not None) == bool(expected)
    if operator == "regex":
        return regex_matches(expected, value)
    if value is None or expected is None:
        return False
    try:
        if operator == "gt":
            return value > expected
        if operator == "gte":
            return value >= expected
        if operator == "lt":
            return value < expected
        if operator == "lte":
            return value <= expected
    except TypeError:
        return False
    raise ValueError(f"Unsupported query operator: {operator}")
