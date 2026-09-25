"""Local ACA/SQLite implementation of Seurat backend capabilities."""

import hashlib
import json
import math
from typing import Any, Dict, List

from .contracts import (
    BackendStatus,
    NavigationNode,
    NavigationRequest,
    NavigationResource,
    QueryExecutionError,
    RepresentationSummary,
    SourceDescriptor,
    SourceLookupRequest,
    SourceRestrictionRequest,
    SourceRestrictionResult,
    SourceSummary,
    SourceSummaryRequest,
)


class LocalCampaignBackend:
    """Adapt the existing ``CampaignDb`` to backend-neutral contracts."""

    def __init__(self, campaign_db):
        self._campaign_db = campaign_db

    def get_status(self) -> BackendStatus:
        return BackendStatus(
            ok=bool(getattr(self._campaign_db, "ok", False)),
            error=str(getattr(self._campaign_db, "last_error", "") or ""),
        )

    def _raise_if_unavailable(self, operation: str) -> None:
        status = self.get_status()
        if not status.ok:
            detail = status.error or "backend unavailable"
            raise QueryExecutionError(f"{operation} failed: {detail}")

    def get_navigation(self, request: NavigationRequest) -> List[NavigationNode]:
        view = str(request.get("view", "variables") or "variables")
        query = request.get("query") or None
        only_visualized = bool(request.get("only_visualized", False))
        if view == "variables":
            groups = self._campaign_db.grouped_variable_names(
                extra_filter=query,
                only_visualized=only_visualized,
            )
            self._raise_if_unavailable("Catalog query")
            return self._variable_navigation(groups)
        if view == "files":
            groups = self._campaign_db.grouped_variables_by_source_dataset(
                extra_filter=query,
                only_visualized=only_visualized,
            )
            self._raise_if_unavailable("Catalog query")
            return self._file_navigation(groups)
        raise ValueError(f"Unsupported navigation view: {view}")

    def get_source_summary(self, request: SourceSummaryRequest) -> SourceSummary:
        variable_id = str(request.get("variable_id", "") or "")
        query = request.get("query") or None
        raw = self._campaign_db.variable_min_max_summary(
            variable_id,
            extra_filter=query,
        )
        self._raise_if_unavailable("Source query")
        result: SourceSummary = {
            "variable_id": str(raw.get("variable", "") or variable_id),
            "num_sources": int(raw.get("num_sources", 0) or 0),
            "global_min": self._optional_float(raw.get("global_min")),
            "global_max": self._optional_float(raw.get("global_max")),
            "mean_min": self._optional_float(raw.get("mean_min")),
            "mean_max": self._optional_float(raw.get("mean_max")),
            "median_min": self._optional_float(raw.get("median_min")),
            "median_max": self._optional_float(raw.get("median_max")),
            "sources": [
                self._source_descriptor(source, variable_id)
                for source in raw.get("sources", []) or []
                if isinstance(source, dict)
            ],
        }
        source_representation = raw.get("source_representation", {})
        if isinstance(source_representation, dict) and source_representation:
            result["source_representation"] = self._representation_summary(
                source_representation
            )
        derived_representations = [
            self._representation_summary(representation)
            for representation in raw.get("derived_representations", []) or []
            if isinstance(representation, dict)
        ]
        if derived_representations:
            result["derived_representations"] = derived_representations
        return result

    @classmethod
    def _representation_summary(
        cls,
        raw: Dict[str, Any],
    ) -> RepresentationSummary:
        return {
            "id": str(raw.get("id", "") or ""),
            "label": str(raw.get("label", "") or ""),
            "kind": str(raw.get("kind", "") or ""),
            "data_model": str(raw.get("data_model", "") or ""),
            "source_data_model": str(raw.get("source_data_model", "") or ""),
            "shape": str(raw.get("shape", "") or ""),
            "axes": str(raw.get("axes", "") or ""),
            "num_frames": int(raw.get("num_frames", 0) or 0),
            "num_sources": int(raw.get("num_sources", 0) or 0),
            "global_min": cls._optional_float(raw.get("global_min")),
            "global_max": cls._optional_float(raw.get("global_max")),
            "mean_min": cls._optional_float(raw.get("mean_min")),
            "mean_max": cls._optional_float(raw.get("mean_max")),
            "median_min": cls._optional_float(raw.get("median_min")),
            "median_max": cls._optional_float(raw.get("median_max")),
        }

    def find_source(
        self, request: SourceLookupRequest
    ) -> SourceDescriptor | None:
        variable_id = str(request.get("variable_id", "") or "")
        visualization_name = str(request.get("visualization_name", "") or "")
        if not variable_id or not visualization_name:
            return None
        source = self._campaign_db.source_for_visualization(
            variable_id,
            visualization_name,
            extra_filter=request.get("query") or None,
        )
        self._raise_if_unavailable("Source lookup")
        return (
            self._source_descriptor(source, variable_id)
            if isinstance(source, dict) and source
            else None
        )

    def resolve_source_restriction(
        self, request: SourceRestrictionRequest
    ) -> SourceRestrictionResult:
        raw = self._campaign_db.source_restriction_summary(
            list(request.get("queries", []) or [])
        )
        self._raise_if_unavailable("Source restriction query")
        return {
            "query": dict(raw.get("filter", {}) or {}),
            "count": int(raw.get("count", 0) or 0),
        }

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except Exception:
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    @classmethod
    def _source_id(cls, source: Dict[str, Any]) -> str:
        source_collection_id = str(source.get("source_collection_id", "") or "")
        schema_file_group = str(source.get("schema_file_group", "") or "")
        schema_mode = str(source.get("schema_mode", "") or "")
        source_dataset = str(source.get("source_dataset", "") or "")
        if source_collection_id:
            identity = {
                "kind": "source_collection",
                "schema_name": str(source.get("schema_name", "") or ""),
                "source_collection_id": source_collection_id,
            }
        elif schema_file_group and schema_mode == "file_per_timestep":
            identity = {
                "kind": "schema_file_group",
                "schema_file_group": schema_file_group,
                "schema_mode": schema_mode,
            }
        elif source_dataset:
            identity = {
                "kind": "source_dataset",
                "source_dataset": source_dataset,
            }
        else:
            identity = {
                "kind": "legacy_source",
                "producer": str(source.get("producer", "") or ""),
                "casename": str(source.get("casename", "") or ""),
                "file": str(source.get("file", "") or ""),
            }
        encoded = json.dumps(
            identity,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"local-source:v1:{hashlib.sha256(encoded).hexdigest()}"

    @classmethod
    def _source_descriptor(
        cls, source: Dict[str, Any], variable_id: str
    ) -> SourceDescriptor:
        source_dataset = str(source.get("source_dataset", "") or "")
        schema_file_group = str(source.get("schema_file_group", "") or "")
        producer = str(source.get("producer", "") or "")
        casename = str(source.get("casename", "") or "")
        file_name = str(source.get("file", "") or "")
        label = str(source.get("source_label", "") or "")
        if not label:
            label = schema_file_group or source_dataset or "/".join(
                part for part in (producer, casename, file_name) if part
            )
        return {
            "id": cls._source_id(source),
            "label": label,
            "variable_id": str(source.get("variable_id", "") or variable_id),
            "variable_name": str(source.get("variable_name", "") or ""),
            "variable_type": str(source.get("variable_type", "variable") or "variable"),
            "variable_path": str(source.get("variable_path", "") or ""),
            "source_dataset": source_dataset,
            "source_collection_id": str(
                source.get("source_collection_id", "") or ""
            ),
            "source_collection_label": str(
                source.get("source_collection_label", "") or ""
            ),
            "source_collection_mode": str(
                source.get("source_collection_mode", "") or ""
            ),
            "source_collection_axis": str(
                source.get("source_collection_axis", "") or ""
            ),
            "source_collection_member_count": int(
                source.get("source_collection_member_count", 0) or 0
            ),
            "source_collection_total_length": int(
                source.get("source_collection_total_length", 0) or 0
            ),
            "source_datasets": [
                str(item) for item in source.get("source_datasets", []) or []
            ],
            "files": [str(item) for item in source.get("files", []) or []],
            "producer": producer,
            "casename": casename,
            "file": file_name,
            "schema_name": str(source.get("schema_name", "") or ""),
            "schema_file_group": schema_file_group,
            "schema_role": str(source.get("schema_role", "") or ""),
            "schema_mode": str(source.get("schema_mode", "") or ""),
            "num_timesteps": int(source.get("num_timesteps", 1) or 1),
            "visualization_name": str(source.get("visualization_name", "") or ""),
            "visualization_kind": str(source.get("visualization_kind", "") or ""),
            "visualization_source_dataset": str(
                source.get("visualization_source_dataset", "") or ""
            ),
            "visualization_variables": list(
                source.get("visualization_variables", []) or []
            ),
            "visualization_roles": [
                str(item) for item in source.get("visualization_roles", []) or []
            ],
            "visualization_sequence_metadata": dict(
                source.get("visualization_sequence_metadata", {}) or {}
            ),
            "visualization_item_metadata": dict(
                source.get("visualization_item_metadata", {}) or {}
            ),
            "activity_provenance": dict(
                source.get("activity_provenance", {}) or {}
            ),
            "association_source": str(source.get("association_source", "") or ""),
            "campaign_path": str(source.get("campaign_path", "") or ""),
            "variable_location": str(source.get("variable_location", "") or ""),
            "frame_index": cls._optional_int(source.get("frame_index")),
            "minimum": cls._optional_float(source.get("min")),
            "maximum": cls._optional_float(source.get("max")),
        }

    @staticmethod
    def _variable_navigation(groups: List[Dict[str, Any]]) -> List[NavigationNode]:
        navigation: List[NavigationNode] = []
        for group in groups:
            group_label = str(group.get("name", "") or "")
            children: List[NavigationNode] = []
            for variable in group.get("variables", []) or []:
                variable_id = str(variable.get("id", "") or "")
                if not variable_id:
                    continue
                label = str(
                    variable.get("label", "")
                    or variable.get("name", "")
                    or variable_id
                )
                resource: NavigationResource = {
                    "variable_id": variable_id,
                    "name": str(variable.get("name", "") or ""),
                    "label": label,
                    "path": str(variable.get("path", "") or ""),
                    "source_dataset": str(
                        variable.get("source_dataset", "") or ""
                    ),
                }
                children.append(
                    {
                        "id": f"variable:{variable_id}",
                        "kind": "variable",
                        "label": label,
                        "resource": resource,
                        "children": [],
                        "has_children": False,
                        "count": None,
                    }
                )

            if not children:
                continue
            navigation.append(
                {
                    "id": f"variable-group:{group_label}",
                    "kind": "variable-group",
                    "label": group_label,
                    "resource": None,
                    "children": children,
                    "has_children": True,
                    "count": len(children),
                }
            )
        return navigation

    @staticmethod
    def _file_navigation(groups: List[Dict[str, Any]]) -> List[NavigationNode]:
        navigation: List[NavigationNode] = []
        for group in groups:
            source_label = str(group.get("name", "") or "")
            source_dataset = str(group.get("source_dataset", "") or "")
            file_count = int(group.get("file_count", 0) or 0)
            children: List[NavigationNode] = []
            for variable in group.get("variables", []) or []:
                variable_id = str(variable.get("id", "") or "")
                if not variable_id:
                    continue
                label = str(
                    variable.get("label", "")
                    or variable.get("name", "")
                    or variable_id
                )
                variable_source = str(
                    variable.get("source_dataset", "") or source_dataset
                )
                resource: NavigationResource = {
                    "variable_id": variable_id,
                    "name": str(variable.get("name", "") or ""),
                    "label": label,
                    "path": str(variable.get("path", "") or ""),
                    "source_dataset": variable_source,
                }
                children.append(
                    {
                        "id": f"file-variable:{source_label}:{variable_id}",
                        "kind": "variable",
                        "label": label,
                        "resource": resource,
                        "children": [],
                        "has_children": False,
                        "count": None,
                    }
                )

            if not children:
                continue
            group_resource: NavigationResource = {
                "source_dataset": source_dataset,
            }
            if file_count > 1:
                group_resource["file_count"] = file_count
            navigation.append(
                {
                    "id": f"file:{source_label}",
                    "kind": "file",
                    "label": source_label,
                    "resource": group_resource,
                    "children": children,
                    "has_children": True,
                    "count": len(children),
                }
            )
        return navigation
