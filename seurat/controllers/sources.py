"""Source discovery, filtering, selection, and dialog controller behavior."""

import math
from typing import Any, Dict, List, Optional, Tuple

from db import (
    GENERATED_SCALAR_PLOT_VIS,
)
from plugin_runtime import (
    is_plugin_visualization,
    plot1d_payload,
)
from query_parser import and_filter, mongo_filter_matches, python_query_to_filters
from seurat.learning.context import stable_fingerprint
from seurat.models import source_selection as source_selection_model
from seurat.models.grid import (
    assign_cell,
)
from seurat.models.source_selection import (
    normalize_source_keys,
    select_single_source,
    select_visible_sources,
    selected_source_label,
    source_fields_from_row,
    source_filter_from_row,
    source_key_for_fields,
    toggle_source_selection,
)
from state_init import fmt


class SourcesControllerMixin:
    ACTION_BINDINGS = (
        ("sort_sources", "sort_sources"),
        ("toggle_sources", "toggle_sources"),
        ("cancel_source_dialog", "cancel_source_dialog"),
        ("apply_source_dialog", "apply_source_dialog"),
        ("clear_source_filter", "clear_source_filter"),
        ("apply_source_dialog_filter", "apply_source_dialog_filter"),
        ("toggle_add_source", "toggle_add_source"),
        ("select_all_sources", "select_all_sources"),
        ("clear_all_sources", "clear_all_sources"),
        ("select_source", "select_source"),
        ("source_dialog_select", "source_dialog_select"),
        ("toggle_source_visibility", "toggle_source_visibility"),
        ("toggle_movie_details", "toggle_movie_details"),
        ("pick_tile_visualization", "pick_tile_visualization"),
    )
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = ()
    HISTORY_ACTIONS = {
        "apply_source_dialog": "Change plot sources",
        "select_source": "Change plot source",
        "toggle_source_visibility": "Change plot source",
    }
    HISTORY_TRIGGERS = {}

    def all_source_rows(self) -> List[Dict[str, Any]]:
        return list(self.state.sourceRowsAll or self.state.sourceRows or [])

    def source_row_keys(self, rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        source_rows = self.all_source_rows() if rows is None else rows
        return source_selection_model.source_row_keys(source_rows)

    def visible_source_row_keys(self) -> List[str]:
        return self.source_row_keys(list(self.state.sourceRows or []))

    def update_selected_source_label(self):
        self.state.selectedSourceLabel = selected_source_label(
            self.all_source_rows(),
            list(self.state.sourceRows or []),
            self.state.selectedSourceKeys or [],
        )

    def select_source_key(self, key: str):
        self.state.selectedSourceKeys = select_single_source(
            key, self.source_row_keys()
        )
        self.update_selected_source_label()

    def select_first_source(self):
        keys = self.visible_source_row_keys()
        self.select_source_key(keys[0] if keys else "")

    def source_row_for_key(self, key: str) -> Dict[str, str]:
        k = str(key or "")
        if not k:
            return {}
        return next(
            (r for r in self.all_source_rows() if str(r.get("_key", "")) == k), {}
        )

    def source_keys_from_cell(self, cell: Dict[str, Any]) -> List[str]:
        keys = normalize_source_keys(cell.get("_source_keys", []))
        key = str(cell.get("_source_key", "") or "").strip()
        if key and key not in keys:
            keys.insert(0, key)
        return keys

    def source_rows_for_keys(self, keys: List[str]) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for key in normalize_source_keys(keys):
            row = self.source_row_for_key(key)
            if row:
                rows.append(row)
        return rows

    def source_fields_list_from_cell(
        self, cell: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        raw_items = cell.get("_source_fields_list", [])
        fields_list: List[Dict[str, Any]] = []
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if isinstance(raw_item, dict):
                    fields = {
                        "source_id": str(raw_item.get("source_id", "") or ""),
                        "_source_key": str(raw_item.get("_source_key", "") or ""),
                        "source_dataset": str(raw_item.get("source_dataset", "") or ""),
                        "source_collection_id": str(
                            raw_item.get("source_collection_id", "") or ""
                        ),
                        "schema_file_group": str(
                            raw_item.get("schema_file_group", "") or ""
                        ),
                        "schema_mode": str(raw_item.get("schema_mode", "") or ""),
                        "producer": str(raw_item.get("producer", "") or ""),
                        "casename": str(raw_item.get("casename", "") or ""),
                        "file": str(raw_item.get("file", "") or ""),
                    }
                    if any(fields.values()):
                        fields_list.append(fields)

        if not fields_list:
            for row in self.source_rows_for_keys(self.source_keys_from_cell(cell)):
                fields = source_fields_from_row(row)
                if fields:
                    fields_list.append(fields)

        if not fields_list:
            fields = {
                "source_id": str(cell.get("source_id", "") or ""),
                "_source_key": str(cell.get("_source_key", "") or ""),
                "source_dataset": str(cell.get("source_dataset", "") or ""),
                "source_collection_id": str(
                    cell.get("source_collection_id", "") or ""
                ),
                "schema_file_group": str(cell.get("schema_file_group", "") or ""),
                "schema_mode": str(cell.get("schema_mode", "") or ""),
                "producer": str(cell.get("producer", "") or ""),
                "casename": str(cell.get("casename", "") or ""),
                "file": str(cell.get("file", "") or ""),
            }
            if any(fields.values()):
                fields_list.append(fields)
        return fields_list

    def source_filter_from_cell(self, cell: Dict[str, Any]) -> Dict[str, str]:
        source_collection_id = str(cell.get("source_collection_id", "") or "")
        if source_collection_id:
            filt = {"source_collection_id": source_collection_id}
            variable_id = str(cell.get("variable_id", "") or "")
            if variable_id:
                filt["variable_id"] = variable_id
            return filt

        schema_file_group = str(cell.get("schema_file_group", "") or "")
        schema_mode = str(cell.get("schema_mode", "") or "")
        if schema_file_group and schema_mode == "file_per_timestep":
            filt = {"schema_file_group": schema_file_group, "schema_mode": schema_mode}
            variable_id = str(cell.get("variable_id", "") or "")
            if variable_id:
                filt["variable_id"] = variable_id
            return filt

        source_dataset = str(cell.get("source_dataset", "") or "")
        if source_dataset:
            filt = {"source_dataset": source_dataset}
            variable_id = str(cell.get("variable_id", "") or "")
            if variable_id:
                filt["variable_id"] = variable_id
            return filt

        producer = str(cell.get("producer", "") or "")
        casename = str(cell.get("casename", "") or "")
        file_name = str(cell.get("file", "") or "")
        if producer or casename or file_name:
            filt = {"producer": producer, "casename": casename}
            if file_name:
                filt["file"] = file_name
            return filt
        return {}

    def source_row_for_cell(self, cell: Dict[str, Any]) -> Dict[str, str]:
        key = str(cell.get("_source_key", "") or "")
        if key:
            row = self.source_row_for_key(key)
            if row:
                return row

        source_dataset = str(cell.get("source_dataset", "") or "")
        schema_file_group = str(cell.get("schema_file_group", "") or "")
        schema_mode = str(cell.get("schema_mode", "") or "")
        producer = str(cell.get("producer", "") or "")
        casename = str(cell.get("casename", "") or "")
        file_name = str(cell.get("file", "") or "")
        for row in self.all_source_rows():
            if (
                schema_file_group
                and schema_mode
                and str(row.get("schema_file_group", "") or "") == schema_file_group
                and str(row.get("schema_mode", "") or "") == schema_mode
            ):
                return row
            if (
                source_dataset
                and str(row.get("source_dataset", "") or "") == source_dataset
            ):
                return row
            if (
                (producer or casename or file_name)
                and str(row.get("producer", "") or "") == producer
                and str(row.get("casename", "") or "") == casename
                and str(row.get("file", "") or "") == file_name
            ):
                return row
        return {}

    def visualization_names_for_source_filter(
        self, variable_id: str, source_filter: Dict[str, Any]
    ) -> List[str]:
        qf = self.active_query_filter()
        active_filter = (
            and_filter(qf, source_filter)
            if qf and source_filter
            else (qf or source_filter or None)
        )
        return self.visualization_names_with_plugins(
            variable_id, source_filter=source_filter, extra_filter=active_filter
        )

    def plugin_source_variables_cache_key(
        self, source_fields: Dict[str, Any]
    ) -> Tuple[str, str, str, str, str, str]:
        fields = dict(source_fields or {})
        return tuple(
            str(fields.get(key, "") or "")
            for key in (
                "source_dataset",
                "schema_file_group",
                "schema_mode",
                "producer",
                "casename",
                "file",
            )
        )

    def plugin_source_variables(
        self, candidate: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        source_fields = dict((candidate or {}).get("source_fields", {}) or {})
        cache_key = self.plugin_source_variables_cache_key(source_fields)
        if cache_key in self.plugin_source_variables_cache:
            return list(self.plugin_source_variables_cache[cache_key])

        query: Dict[str, Any] = {"variable_type": "variable"}
        source_dataset = str(source_fields.get("source_dataset", "") or "")
        schema_file_group = str(source_fields.get("schema_file_group", "") or "")
        schema_mode = str(source_fields.get("schema_mode", "") or "")
        if schema_file_group and schema_mode == "file_per_timestep":
            query["schema_file_group"] = schema_file_group
            query["schema_mode"] = schema_mode
        elif source_dataset:
            query["source_dataset"] = source_dataset
        else:
            for key in ("producer", "casename", "file"):
                value = str(source_fields.get(key, "") or "")
                if value:
                    query[key] = value

        proj = {
            "_id": 0,
            "variable_id": 1,
            "variable_name": 1,
            "variable_path": 1,
            "source_dataset": 1,
            "metadata": 1,
        }
        variables: List[Dict[str, Any]] = []
        try:
            for doc in self.db.collection.find(query, proj):
                variable_id = str(doc.get("variable_id", "") or "")
                variable_name = str(doc.get("variable_name", "") or variable_id)
                variable_path = str(doc.get("variable_path", "") or "")
                if not variable_id and not variable_name and not variable_path:
                    continue
                metadata = doc.get("metadata", {}) or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                variables.append(
                    {
                        "variable_id": variable_id,
                        "variable_name": variable_name,
                        "variable_path": variable_path,
                        "source_dataset": str(doc.get("source_dataset", "") or ""),
                        "metadata": metadata,
                    }
                )
        except Exception:
            variables = []

        self.plugin_source_variables_cache[cache_key] = list(variables)
        return variables

    def source_row_for_visualization_pick(
        self, variable_id: str, visualization_name: str
    ) -> Dict[str, str]:
        var_id = str(variable_id or "").strip()
        vis = str(visualization_name or "").strip()
        if not var_id or not vis:
            return {}
        if is_plugin_visualization(vis):
            return {}
        source = self.application.find_source(
            {
                "variable_id": var_id,
                "visualization_name": vis,
                "query": self.active_query_filter() or {},
            }
        )
        return self.source_row_from_descriptor(source or {}, var_id) if source else {}

    def active_source_filter_for_variable(self, variable_id: str) -> Dict[str, str]:
        if str(self.state.detailsSelectedVarId or "") != str(variable_id or ""):
            return {}

        selected = set(self.state.selectedSourceKeys or [])
        row = next(
            (r for r in self.all_source_rows() if str(r.get("_key", "")) in selected),
            None,
        )
        return source_filter_from_row(row) if row else {}

    def source_name_for_row(self, row: Dict[str, Any]) -> str:
        source_label = str(row.get("source_label", "") or "")
        if source_label:
            return source_label
        schema_file_group = str(row.get("schema_file_group", "") or "")
        if schema_file_group:
            return schema_file_group
        source_dataset = str(row.get("source_dataset", "") or "")
        if source_dataset:
            return source_dataset
        parts = [
            str(row.get("producer", "") or ""),
            str(row.get("casename", "") or ""),
            str(row.get("file", "") or ""),
        ]
        return "/".join(part for part in parts if part)

    def source_row_from_descriptor(
        self, source: Dict[str, Any], variable_id: str
    ) -> Dict[str, Any]:
        row = {
            "source_dataset": str(source.get("source_dataset", "") or ""),
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
            "source_label": str(source.get("label", "") or ""),
            "schema_name": str(source.get("schema_name", "") or ""),
            "schema_file_group": str(source.get("schema_file_group", "") or ""),
            "schema_role": str(source.get("schema_role", "") or ""),
            "schema_mode": str(source.get("schema_mode", "") or ""),
            "num_timesteps": int(source.get("num_timesteps", 1) or 1),
            "files": list(source.get("files", []) or []),
            "source_datasets": list(source.get("source_datasets", []) or []),
            "variable_id": str(source.get("variable_id", "") or variable_id or ""),
            "variable_name": str(source.get("variable_name", "") or ""),
            "variable_type": str(source.get("variable_type", "variable") or "variable"),
            "variable_path": str(source.get("variable_path", "") or ""),
            "producer": str(source.get("producer", "") or ""),
            "casename": str(source.get("casename", "") or ""),
            "file": str(source.get("file", "") or ""),
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
            "frame_index": source.get("frame_index", None),
            "min": fmt(source.get("minimum", None)),
            "max": fmt(source.get("maximum", None)),
            "min_value": source.get("minimum", None),
            "max_value": source.get("maximum", None),
        }
        source_id = str(source.get("id", "") or source_key_for_fields(row))
        row["source_id"] = source_id
        row["_key"] = source_id
        row["sourceName"] = self.source_name_for_row(row)
        return row

    def first_query_source_row_for_variable(
        self, variable_id: str, preferred_vis: str = ""
    ) -> Dict[str, Any]:
        var_id = str(variable_id or "").strip()
        vis = str(preferred_vis or "").strip()
        if not var_id:
            return {}

        if vis and vis != GENERATED_SCALAR_PLOT_VIS:
            row = self.source_row_for_visualization_pick(var_id, vis)
            if row:
                return row

        summary = self.application.get_source_summary(
            {
                "variable_id": var_id,
                "query": self.active_query_filter() or {},
            }
        )
        for source in summary.get("sources", []) or []:
            row = self.source_row_from_descriptor(dict(source or {}), var_id)
            if source_filter_from_row(row):
                return row
        return {}

    def source_filter_number(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() == "n/a":
            return None
        try:
            numeric = float(text)
        except Exception:
            return None
        return numeric if math.isfinite(numeric) else None

    def source_filter_values(self, row: Dict[str, Any]) -> Dict[str, Any]:
        variable_id = str(row.get("variable_id", "") or "")
        variable_name = str(row.get("variable_name", "") or "").strip()
        if not variable_name and variable_id:
            variable_name = variable_id.strip("/").rsplit("/", 1)[-1]
        source_dataset = str(row.get("source_dataset", "") or "")
        return {
            "variable_id": variable_id,
            "variable_name": variable_name,
            "variable_type": str(row.get("variable_type", "") or "variable"),
            "source_dataset": source_dataset,
            "source_collection_id": str(
                row.get("source_collection_id", "") or ""
            ),
            "source_collection_label": str(
                row.get("source_collection_label", "") or ""
            ),
            "source_label": str(row.get("source_label", "") or ""),
            "sourceName": str(row.get("sourceName", "") or ""),
            "schema_name": str(row.get("schema_name", "") or ""),
            "schema_file_group": str(row.get("schema_file_group", "") or ""),
            "schema_role": str(row.get("schema_role", "") or ""),
            "schema_mode": str(row.get("schema_mode", "") or ""),
            "num_timesteps": self.source_filter_number(row.get("num_timesteps", None)),
            "producer": str(row.get("producer", "") or ""),
            "casename": str(row.get("casename", "") or ""),
            "file": str(row.get("file", "") or ""),
            "visualization_name": str(row.get("visualization_name", "") or ""),
            "visualization_kind": str(row.get("visualization_kind", "") or ""),
            "visualization_source_dataset": str(
                row.get("visualization_source_dataset", "") or source_dataset
            ),
            "association_source": str(row.get("association_source", "") or ""),
            "variable_path": str(row.get("variable_path", "") or ""),
            "campaign_path": str(row.get("campaign_path", "") or ""),
            "variable_location": str(row.get("variable_location", "") or ""),
            "frame_index": self.source_filter_number(row.get("frame_index", None)),
            "min": self.source_filter_number(
                row.get("min_value", row.get("min", None))
            ),
            "max": self.source_filter_number(
                row.get("max_value", row.get("max", None))
            ),
        }

    def source_extrema_for_title(
        self,
        variable_id: str,
        source_filter: Dict[str, Any],
        representation_id: str = "",
    ) -> Tuple[Optional[float], Optional[float]]:
        var_id = str(variable_id or "").strip()
        if not var_id or not source_filter:
            return None, None

        qf = self.active_query_filter()
        extra_filter = and_filter(qf, source_filter) if qf else source_filter
        summary = self.application.get_source_summary(
            {"variable_id": var_id, "query": extra_filter or {}}
        )
        derived_id = str(representation_id or "").strip()
        if derived_id:
            derived_representations = [
                representation
                for representation in summary.get(
                    "derived_representations", []
                )
                or []
                if isinstance(representation, dict)
            ]
            representation = next(
                (
                    item
                    for item in derived_representations
                    if str(item.get("id", "") or "") == derived_id
                ),
                None,
            )
            if representation is None and len(derived_representations) == 1:
                representation = derived_representations[0]
            if representation is None:
                return None, None
            return self.valid_title_extrema(
                representation.get("global_min", None),
                representation.get("global_max", None),
            )

        return self.valid_title_extrema(
            summary.get("global_min", None),
            summary.get("global_max", None),
        )

    def source_sort_key(self, row: Dict[str, Any], field: str, selected_keys: set):
        if field == "show":
            key = str(row.get("_key", ""))
            # Ascending puts the active source first.
            return (0 if key in selected_keys else 1, key)

        value = row.get(field, "")
        if field in ("min", "max"):
            numeric = self.source_filter_number(row.get(f"{field}_value", value))
            if numeric is not None:
                return ("__num__", numeric)

        if value is None:
            return ("__str__", "")
        return ("__str__", str(value).lower())

    def sorted_source_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        field = str(self.state.sourceSortField or "")
        if not field:
            return list(rows)
        selected_keys = set(self.state.selectedSourceKeys or [])
        asc = bool(self.state.sourceSortAsc)
        return sorted(
            rows,
            key=lambda row: self.source_sort_key(row, field, selected_keys),
            reverse=(not asc),
        )

    def source_rows_matching_filter(self, expression: str) -> List[Dict[str, Any]]:
        rows = self.all_source_rows()
        expr = str(expression or "").strip()
        if not expr:
            return rows

        row_filter, source_filters = python_query_to_filters(expr)
        source_restriction = {}
        if source_filters:
            source_summary = self.application.resolve_source_restriction(
                {"queries": source_filters}
            )
            source_restriction = dict(source_summary.get("query", {}) or {})

        matched_rows = []
        for row in rows:
            values = self.source_filter_values(row)
            if mongo_filter_matches(
                row_filter, values
            ) and mongo_filter_matches(source_restriction, values):
                matched_rows.append(row)
        return matched_rows

    def apply_source_filter_and_sort(self):
        expr = str(self.state.sourceFilterText or "").strip()
        try:
            rows = self.source_rows_matching_filter(expr)
            self.state.sourceFilterError = ""
        except Exception as e:
            self.state.sourceFilterError = f"{type(e).__name__}: {e}"
            rows = self.all_source_rows()

        self.state.sourceRows = self.sorted_source_rows(rows)
        self.update_selected_source_label()

    def source_fields_to_filter(
        self, variable_id: str, source_fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        cell = dict(source_fields or {})
        cell["variable_id"] = str(variable_id or "")
        return self.source_filter_from_cell(cell)

    def source_filter_for_assignment(
        self,
        variable_id: str,
        source_row: Optional[Dict[str, str]] = None,
        existing_cell: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if source_row:
            return source_filter_from_row(source_row)
        if existing_cell:
            return self.source_filter_from_cell(existing_cell)
        return self.active_source_filter_for_variable(variable_id)

    def source_fields_for_assignment(
        self,
        variable_id: str,
        source_row: Optional[Dict[str, str]] = None,
        candidate: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if source_row:
            return source_fields_from_row(source_row)
        source_fields = dict((candidate or {}).get("source_fields", {}) or {})
        if source_fields:
            return source_fields
        source_filter = self.active_source_filter_for_variable(variable_id)
        return {
            "source_dataset": str(source_filter.get("source_dataset", "") or ""),
            "source_collection_id": str(
                source_filter.get("source_collection_id", "") or ""
            ),
            "schema_file_group": str(source_filter.get("schema_file_group", "") or ""),
            "schema_mode": str(source_filter.get("schema_mode", "") or ""),
            "producer": str(source_filter.get("producer", "") or ""),
            "casename": str(source_filter.get("casename", "") or ""),
            "file": str(source_filter.get("file", "") or ""),
        }

    def set_generated_scalar_plot_sources_cell(
        self,
        cell_index: int,
        variable_id: str,
        source_rows: List[Dict[str, str]],
        sync_selection: bool = True,
    ) -> bool:
        try:
            idx = int(cell_index)
        except Exception:
            return False
        if not self.is_valid_grid_index(idx):
            return False

        rows = [row for row in source_rows if row]
        if not rows:
            return False

        source_fields_list = [source_fields_from_row(row) for row in rows]
        source_filters = [source_filter_from_row(row) for row in rows]
        source_keys = [
            str(fields.get("_source_key", "") or "")
            for fields in source_fields_list
            if str(fields.get("_source_key", "") or "")
        ]
        try:
            tile = self.db.get_generated_scalar_plot_tile_for_sources(
                self.campaign_path,
                variable_id,
                source_filters=source_filters,
                extra_filter=self.active_query_filter(),
            )
        except Exception as e:
            tile = {}
            self.state.scalarPlotStatus = (
                f"Scalar plot generation failed: {type(e).__name__}: {e}"
            )

        cells = self.normalize_grid_cells(self.state.gridCells)
        prior_settings = self.existing_plot_settings(cells[idx], variable_id)
        if tile:
            first_fields = source_fields_list[0]
            tile.update(
                {k: v for k, v in first_fields.items() if v and k != "_source_key"}
            )
            tile["_source_key"] = (
                source_keys[0]
                if source_keys
                else str(first_fields.get("_source_key", "") or "")
            )
            tile["_source_keys"] = source_keys
            tile["_source_fields_list"] = source_fields_list
            self.assign_plot_series_keys(tile, source_keys)
            tile["plot_settings"] = self.normalize_plot_settings(tile, prior_settings)
            tile["visualization_name"] = GENERATED_SCALAR_PLOT_VIS
            tile["selected_visualization"] = GENERATED_SCALAR_PLOT_VIS
            tile["visualization_options"] = [GENERATED_SCALAR_PLOT_VIS]
            assign_cell(cells, idx, tile)
            self.state.scalarPlotStatus = ""
        else:
            assign_cell(
                cells,
                idx,
                self.no_visualization_grid_cell(
                    variable_id,
                    "Could not generate scalar plot for the selected sources",
                ),
            )

        self.state.gridCells = cells
        self.state.activeGridCell = idx
        if sync_selection:
            self.set_details_provenance_context(True)
            self.state.selectedVar = variable_id
            self.state.draggedVar = variable_id
        return bool(tile)

    def generated_scalar_plot_cell_for_source_rows(
        self,
        variable_id: str,
        source_rows: List[Dict[str, Any]],
        existing_cell: Dict[str, Any],
        allow_multi_sources: bool,
    ) -> Dict[str, Any]:
        var_id = str(variable_id or "").strip()
        rows = [self.source_row_for_variable(row, var_id) for row in source_rows if row]
        if not var_id or not rows:
            raise ValueError("No source selected")

        prior_settings = self.existing_plot_settings(existing_cell, var_id)
        if allow_multi_sources and len(rows) > 1:
            source_fields_list = [source_fields_from_row(row) for row in rows]
            source_filters = [source_filter_from_row(row) for row in rows]
            source_keys = [
                str(fields.get("_source_key", "") or "")
                for fields in source_fields_list
                if str(fields.get("_source_key", "") or "")
            ]
            tile = self.db.get_generated_scalar_plot_tile_for_sources(
                self.campaign_path,
                var_id,
                source_filters=source_filters,
                extra_filter=self.active_query_filter(),
            )
            if not tile:
                raise ValueError(
                    "Could not generate scalar plot for the selected sources"
                )

            first_fields = source_fields_list[0]
            tile.update(
                {k: v for k, v in first_fields.items() if v and k != "_source_key"}
            )
            tile["_source_key"] = (
                source_keys[0]
                if source_keys
                else str(first_fields.get("_source_key", "") or "")
            )
            tile["_source_keys"] = source_keys
            tile["_source_fields_list"] = source_fields_list
            self.assign_plot_series_keys(tile, source_keys)
        else:
            source_fields = source_fields_from_row(rows[0])
            source_filter = self.source_fields_to_filter(var_id, source_fields)
            tile = self.db.get_or_create_generated_scalar_plot_tile(
                self.campaign_path,
                var_id,
                source_filter=source_filter or None,
                extra_filter=self.active_query_filter(),
            )
            if not tile:
                raise ValueError("Could not generate scalar plot for this source")

            tile.update({k: v for k, v in source_fields.items() if v})
            source_key = str(source_fields.get("_source_key", "") or "")
            tile["_source_keys"] = [source_key] if source_key else []
            tile["_source_fields_list"] = [source_fields] if source_fields else []
            self.assign_plot_series_keys(tile, [source_key] if source_key else [])

        tile["plot_settings"] = self.normalize_plot_settings(tile, prior_settings)
        tile["visualization_name"] = GENERATED_SCALAR_PLOT_VIS
        tile["selected_visualization"] = GENERATED_SCALAR_PLOT_VIS
        tile["visualization_options"] = [GENERATED_SCALAR_PLOT_VIS]
        return tile

    def plugin_plot1d_cell_for_source_rows(
        self,
        variable_id: str,
        source_rows: List[Dict[str, Any]],
        existing_cell: Dict[str, Any],
    ) -> Dict[str, Any]:
        var_id = str(variable_id or "").strip()
        rows: List[Dict[str, Any]] = []
        for source_row in source_rows:
            if not source_row:
                continue
            row = self.source_row_for_variable(source_row, var_id)
            source_id = str(
                source_row.get("source_id", "")
                or source_row.get("id", "")
                or source_row.get("_key", "")
                or ""
            )
            if source_id:
                row["source_id"] = source_id
                row["_key"] = source_id
            rows.append(row)
        plugin_vis = str(
            existing_cell.get("selected_visualization", "")
            or existing_cell.get("visualization_name", "")
            or ""
        ).strip()
        if not var_id or not rows:
            raise ValueError("No source selected")
        if not is_plugin_visualization(plugin_vis):
            raise ValueError("Cell is not a plugin plot")

        prior_settings = self.existing_plot_settings(existing_cell, var_id)
        plugin_options = dict(existing_cell.get("plugin_options", {}) or {})
        merged_series: List[Dict[str, Any]] = []
        rendered_tiles: List[Dict[str, Any]] = []
        rendered_fields: List[Dict[str, Any]] = []
        rendered_keys: List[str] = []
        x_labels: List[str] = []
        y_labels: List[str] = []

        for source_index, row in enumerate(rows):
            tile = self.build_plugin_grid_cell(
                var_id,
                plugin_vis,
                source_row=row,
                existing_cell=existing_cell,
                plugin_options=plugin_options,
            )
            if str(tile.get("media_type", "") or "") != "plot1d":
                raise ValueError("Selected plugin does not produce a 1D plot")

            plot = dict(tile.get("plot", {}) or {})
            series = self.plot_series(tile)
            if not series:
                continue

            source_fields = source_fields_from_row(row)
            source_key = str(source_fields.get("_source_key", "") or "")
            source_label = (
                self.source_name_for_row(row)
                or source_key
                or f"Source {source_index + 1}"
            )
            for series_index, raw_series in enumerate(series):
                item = dict(raw_series)
                item_label = str(item.get("source_label", "") or "").strip()
                item_key = str(item.get("source_key", "") or "").strip()
                if len(series) == 1:
                    item["source_label"] = source_label
                    item["source_key"] = source_key or item_key
                else:
                    suffix = item_label or f"Series {series_index + 1}"
                    item["source_label"] = f"{source_label}: {suffix}"
                    item["source_key"] = ":".join(
                        part
                        for part in (
                            source_key,
                            item_key or f"series-{series_index + 1}",
                        )
                        if part
                    )
                merged_series.append(item)

            rendered_tiles.append(tile)
            rendered_fields.append(source_fields)
            if source_key:
                rendered_keys.append(source_key)
            x_labels.append(str(plot.get("x_label", "") or ""))
            y_labels.append(str(plot.get("y_label", "") or ""))

        if not rendered_tiles or not merged_series:
            raise ValueError("Could not render the selected sources")

        nonempty_x_labels = {label for label in x_labels if label}
        nonempty_y_labels = {label for label in y_labels if label}
        x_label = x_labels[0] if len(nonempty_x_labels) <= 1 else "x"
        y_label = (
            y_labels[0]
            if len(nonempty_y_labels) <= 1
            else self.variable_label(var_id)
        )

        tile = dict(rendered_tiles[0])
        first_fields = rendered_fields[0]
        tile.update(
            {
                key: value
                for key, value in first_fields.items()
                if value and key != "_source_key"
            }
        )
        tile["_source_key"] = rendered_keys[0] if rendered_keys else ""
        tile["_source_keys"] = rendered_keys
        tile["_source_fields_list"] = rendered_fields
        tile["plot"] = plot1d_payload(
            merged_series,
            x_label=x_label,
            y_label=y_label,
        )
        tile["plot_settings"] = self.normalize_plot_settings(tile, prior_settings)
        tile["source_count"] = len(rendered_tiles)
        tile["note"] = (
            f"plugin: {plugin_vis.removeprefix('plugin:')}; "
            f"{len(rendered_tiles)} sources"
        )
        return tile

    def build_cell_for_source_rows(
        self,
        variable_id: str,
        existing_cell: Dict[str, Any],
        source_rows: List[Dict[str, Any]],
        allow_multi_sources: bool,
    ) -> Dict[str, Any]:
        var_id = str(variable_id or "").strip()
        if not var_id:
            raise ValueError("Cell has no variable")
        if not source_rows:
            raise ValueError("No source selected")

        existing = dict(existing_cell or {})
        if allow_multi_sources and is_plugin_visualization(
            str(
                existing.get("selected_visualization", "")
                or existing.get("visualization_name", "")
                or ""
            )
        ):
            return self.plugin_plot1d_cell_for_source_rows(
                var_id,
                source_rows,
                existing,
            )
        if self.is_generated_plot1d_cell(existing):
            return self.generated_scalar_plot_cell_for_source_rows(
                var_id,
                source_rows,
                existing,
                allow_multi_sources,
            )

        target_row = self.source_row_for_variable(source_rows[0], var_id)
        selected_vis = str(
            existing.get("selected_visualization", "")
            or existing.get("visualization_name", "")
            or ""
        )
        new_cell = self.build_grid_cell_for_variable(
            var_id,
            preferred_vis=selected_vis,
            source_row=target_row,
            existing_cell=existing,
        )
        status = str(new_cell.get("status", "") or "")
        if status == "error":
            note = str(new_cell.get("note", "") or "No visualization for this source")
            raise ValueError(note)
        return new_cell

    def source_dialog_target_indices(self) -> List[int]:
        cells = self.normalize_grid_cells(self.state.gridCells)
        raw_targets = list(self.state.sourceDialogTargetCellIndices or [])
        if not raw_targets:
            try:
                raw_targets = [int(self.state.sourceDialogCellIndex)]
            except Exception:
                raw_targets = []
        return self.normalize_grid_selection(raw_targets, cells)

    def source_dialog_multi_source_allowed(
        self, targets: List[int], cells: List[Dict[str, Any]]
    ) -> bool:
        return bool(targets) and all(
            self.is_multi_source_plot1d_cell(cells[idx]) for idx in targets
        )

    def apply_source_rows_to_targets(
        self,
        target_indices: List[int],
        selected_source_keys: List[str],
        allow_multi_sources: bool,
    ) -> Tuple[int, List[str]]:
        source_rows = self.source_rows_for_keys(selected_source_keys)
        if not source_rows:
            return 0, ["No sources selected"]

        cells = self.normalize_grid_cells(self.state.gridCells)
        targets = self.normalize_grid_selection(target_indices, cells)
        if not targets:
            return 0, ["No plot cells selected"]

        updated = list(cells)
        failures: List[str] = []
        applied = 0
        for idx in targets:
            existing = dict(updated[idx] or {})
            var_id = str(
                existing.get("variable_id", "")
                or existing.get("variable_name", "")
                or ""
            ).strip()
            if not var_id:
                failures.append(f"Cell {idx + 1}: no variable")
                continue
            try:
                new_cell = self.build_cell_for_source_rows(
                    var_id,
                    existing,
                    source_rows,
                    allow_multi_sources
                    and self.is_multi_source_plot1d_cell(existing),
                )
            except Exception as e:
                failures.append(f"Cell {idx + 1}: {e}")
                continue
            assign_cell(updated, idx, new_cell)
            applied += 1

        if applied:
            self.state.gridCells = self.normalize_grid_cells(updated)
            anchor = targets[0]
            self.state.activeGridCell = anchor
            self.publish_grid_selection(
                self.normalize_grid_selection(targets, list(self.state.gridCells or []))
            )
        return applied, failures

    def open_source_dialog_for_cell(
        self, cell_index: int, prefer_multi: bool = False
    ) -> None:
        if not self.is_valid_grid_index(cell_index):
            return
        cells = self.normalize_grid_cells(self.state.gridCells)
        targets = self.source_dialog_targets_for_anchor(cell_index, cells)
        if not targets:
            return

        cell = dict(cells[cell_index] or {})
        var = str(
            cell.get("variable_id", "") or cell.get("variable_name", "") or ""
        ).strip()
        if not var:
            return
        selected_visualization = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        )

        multi_allowed = self.source_dialog_multi_source_allowed(targets, cells)
        source_keys = self.source_keys_from_cell(cell)
        preferred_key = (
            source_keys[0] if source_keys else str(cell.get("_source_key", "") or "")
        )

        self.state.activeGridCell = cell_index
        self.publish_grid_selection(targets)
        self.state.sourceDialogTargetCellIndices = targets
        self.state.sourceDialogCellIndex = cell_index
        self.state.sourceDialogMode = (
            "add" if (prefer_multi or len(targets) > 1) and multi_allowed else "single"
        )
        if len(targets) > 1:
            self.state.sourceDialogTitle = f"Sources: {self.variable_label(var)} - applying to {len(targets)} cells"
        else:
            self.state.sourceDialogTitle = f"{'Add Source' if str(self.state.sourceDialogMode or '') == 'add' else 'Sources'}: {self.variable_label(var)}"
        self.state.sourceDialogStatus = ""
        self.state.sourceDialogStatusIsError = False
        self.set_details_provenance_context(True)
        self.state.selectedVar = var
        self.state.draggedVar = var

        if str(self.state.sourceDialogMode or "") == "add":
            self.update_selected_var_panels(
                var,
                preferred_source_keys=source_keys,
                include_visualization_provenance=True,
                preferred_visualization=selected_visualization,
            )
        else:
            self.update_selected_var_panels(
                var,
                preferred_source_key=preferred_key,
                include_visualization_provenance=True,
                preferred_visualization=selected_visualization,
            )
        self.state.sourceDialogInitialSelectedSourceKeys = normalize_source_keys(
            self.state.selectedSourceKeys or source_keys
        )
        self.state.showSourcesModal = True

    def open_source_dialog_for_details(self) -> None:
        var = str(
            self.state.detailsSelectedVarId or self.state.selectedVar or ""
        ).strip()
        if not var:
            return

        self.state.sourceDialogTargetCellIndices = []
        self.state.sourceDialogCellIndex = -1
        self.state.sourceDialogMode = "single"
        self.state.sourceDialogTitle = f"Sources: {self.variable_label(var)}"
        self.state.sourceDialogStatus = ""
        self.state.sourceDialogStatusIsError = False
        self.set_details_provenance_context(False)
        self.state.selectedVar = var
        self.state.draggedVar = var
        self.state.sourceDialogInitialSelectedSourceKeys = normalize_source_keys(
            self.state.selectedSourceKeys or []
        )
        self.state.showSourcesModal = True

    def sort_sources(self, field: str, toggle: bool = True, **_):
        if not field:
            return

        if self.state.sourceSortField == field:
            if toggle:
                self.state.sourceSortAsc = not bool(self.state.sourceSortAsc)
        else:
            self.state.sourceSortField = field
            self.state.sourceSortAsc = True

        self.state.sourceRows = self.sorted_source_rows(
            list(self.state.sourceRows or [])
        )

    def toggle_sources(self, **_):
        if bool(self.state.showSourcesModal):
            self.state.showSourcesModal = False
            return

        try:
            idx = int(self.state.activeGridCell)
        except Exception:
            idx = -1

        if self.is_valid_grid_index(idx):
            self.open_source_dialog_for_cell(idx, prefer_multi=True)
        if not bool(self.state.showSourcesModal):
            self.open_source_dialog_for_details()

    def cancel_source_dialog(self, **_):
        valid_keys = self.source_row_keys()
        restored = [
            key
            for key in normalize_source_keys(
                self.state.sourceDialogInitialSelectedSourceKeys or []
            )
            if key in valid_keys
        ]
        self.state.selectedSourceKeys = restored
        self.update_selected_source_label()
        self.state.sourceDialogStatus = ""
        self.state.sourceDialogStatusIsError = False
        self.state.showSourcesModal = False

    def apply_source_dialog(self, **_):
        mode = str(self.state.sourceDialogMode or "single")
        valid_keys = self.source_row_keys()
        selected = [
            key
            for key in normalize_source_keys(self.state.selectedSourceKeys or [])
            if key in valid_keys
        ]
        targets = self.source_dialog_target_indices()
        cells = self.normalize_grid_cells(self.state.gridCells)
        allow_multi_sources = mode == "add" and self.source_dialog_multi_source_allowed(
            targets, cells
        )
        if not allow_multi_sources:
            selected = selected[:1]

        if not targets:
            if not selected:
                self.state.sourceDialogStatus = "Select a source."
                self.state.sourceDialogStatusIsError = True
                return

            var = str(
                self.state.detailsSelectedVarId or self.state.selectedVar or ""
            ).strip()
            if not var:
                self.state.sourceDialogStatus = "Select a variable first."
                self.state.sourceDialogStatusIsError = True
                return

            self.update_selected_var_panels(var, preferred_source_key=selected[0])
            self.state.sourceDialogInitialSelectedSourceKeys = selected
            self.state.sourceDialogStatus = ""
            self.state.sourceDialogStatusIsError = False
            self.state.showSourcesModal = False
            return

        applied, failures = self.apply_source_rows_to_targets(
            targets,
            selected,
            allow_multi_sources,
        )
        if applied:
            try:
                anchor = int(self.state.activeGridCell)
            except Exception:
                anchor = -1
            refreshed_var = ""
            cells = self.normalize_grid_cells(self.state.gridCells)
            preferred_visualization = ""
            if self.is_valid_grid_index(anchor):
                refreshed_var = str(
                    cells[anchor].get("variable_id", "")
                    or cells[anchor].get("variable_name", "")
                    or ""
                ).strip()
                preferred_visualization = str(
                    cells[anchor].get("selected_visualization", "")
                    or cells[anchor].get("visualization_name", "")
                    or ""
                )
            if refreshed_var:
                if allow_multi_sources:
                    self.update_selected_var_panels(
                        refreshed_var,
                        preferred_source_keys=selected,
                        include_visualization_provenance=True,
                        preferred_visualization=preferred_visualization,
                    )
                else:
                    self.update_selected_var_panels(
                        refreshed_var,
                        preferred_source_key=selected[0] if selected else "",
                        include_visualization_provenance=True,
                        preferred_visualization=preferred_visualization,
                    )

        self.state.sourceDialogInitialSelectedSourceKeys = selected
        if failures:
            prefix = (
                f"Applied to {applied} cell{'s' if applied != 1 else ''}; "
                if applied
                else ""
            )
            self.state.sourceDialogStatus = (
                prefix + "Failed: " + "; ".join(failures[:4])
            )
            if len(failures) > 4:
                self.state.sourceDialogStatus += f"; {len(failures) - 4} more"
            self.state.sourceDialogStatusIsError = True
            return

        self.state.sourceDialogStatus = (
            f"Applied to {applied} cell{'s' if applied != 1 else ''}."
        )
        self.state.sourceDialogStatusIsError = False
        self.state.showSourcesModal = False

    def clear_source_filter(self, **_):
        self.select_first_source()
        self.update_selected_var_panels(
            self.state.selectedVar,
            include_visualization_provenance=(
                self.details_provenance_includes_visualization()
            ),
        )

    def apply_source_dialog_filter(self, **_):
        self.state.sourceFilterText = str(
            self.state.sourceFilterDraftText or ""
        ).strip()
        self.state.sourceFilterError = ""
        self.apply_source_filter_and_sort()
        if self.state.sourceFilterError or not self.state.sourceFilterText:
            return
        row_filter, source_filters = python_query_to_filters(
            self.state.sourceFilterText
        )
        self.record_query_applied(
            origin="source_filter",
            target="source_filter",
            action_plan={
                "action": "source_filter",
                "row_filter": row_filter,
                "source_filters": source_filters,
                "variable_id": str(self.state.detailsSelectedVarId or ""),
            },
        )

    def sync_add_source_selection_to_cell(
        self, var_id: str, idx: int, selected: List[str]
    ) -> None:
        if not var_id or not self.is_valid_grid_index(idx):
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell_var = str(
            cells[idx].get("variable_id", "")
            or cells[idx].get("variable_name", "")
            or ""
        ).strip()
        selected_vis = str(
            cells[idx].get("selected_visualization", "")
            or cells[idx].get("visualization_name", "")
            or ""
        )
        visualization_name = str(
            cells[idx].get("visualization_name", "") or selected_vis
        )
        if cell_var != var_id or (
            selected_vis != GENERATED_SCALAR_PLOT_VIS
            and visualization_name != GENERATED_SCALAR_PLOT_VIS
        ):
            return

        rows = self.source_rows_for_keys(selected)
        if rows:
            self.set_generated_scalar_plot_sources_cell(
                idx,
                var_id,
                rows,
                sync_selection=False,
            )
            self.update_selected_var_panels(
                var_id,
                preferred_source_keys=selected,
                include_visualization_provenance=True,
                preferred_visualization=selected_vis or visualization_name,
            )

    def toggle_add_source(self, key: str, **_):
        k = str(key or "").strip()
        if not k:
            return

        valid_keys = self.source_row_keys()
        if k not in valid_keys:
            return

        self.state.sourceDialogMode = "add"
        self.state.selectedSourceKeys = toggle_source_selection(
            self.state.selectedSourceKeys or [],
            k,
            valid_keys,
        )
        self.update_selected_source_label()

    def select_all_sources(self, **_):
        visible_keys = self.visible_source_row_keys()
        if not visible_keys:
            return

        valid_keys = self.source_row_keys()
        self.state.sourceDialogMode = "add"
        self.state.selectedSourceKeys = select_visible_sources(
            self.state.selectedSourceKeys or [],
            visible_keys,
            valid_keys,
        )
        self.update_selected_source_label()

    def clear_all_sources(self, **_):
        self.state.sourceDialogMode = "add"
        self.state.selectedSourceKeys = []
        self.update_selected_source_label()

    def commit_single_source_selection(self, key: str, idx: int = -1) -> None:
        row = self.source_row_for_key(key)
        self.state.sourceDialogMode = "single"
        self.select_source_key(key)

        var_id = str(
            self.state.detailsSelectedVarId or self.state.selectedVar or ""
        ).strip()
        if not self.is_valid_grid_index(idx):
            try:
                idx = int(self.state.sourceDialogCellIndex)
            except Exception:
                idx = -1
        if not self.is_valid_grid_index(idx):
            try:
                idx = int(self.state.activeGridCell)
            except Exception:
                idx = -1

        selected_vis = ""
        if row and var_id and self.is_valid_grid_index(idx):
            cells = self.normalize_grid_cells(self.state.gridCells)
            cell_var = str(
                cells[idx].get("variable_id", "")
                or cells[idx].get("variable_name", "")
                or ""
            ).strip()
            if cell_var == var_id:
                selected_vis = str(cells[idx].get("selected_visualization", "") or "")
                visualization_name = str(
                    cells[idx].get("visualization_name", "") or selected_vis
                )
                if (
                    visualization_name == GENERATED_SCALAR_PLOT_VIS
                    or selected_vis == GENERATED_SCALAR_PLOT_VIS
                ):
                    self.set_generated_scalar_plot_cell(
                        idx,
                        var_id,
                        source_fields=source_fields_from_row(row),
                        sync_selection=False,
                    )
                else:
                    assign_cell(
                        cells,
                        idx,
                        self.build_grid_cell_for_variable(
                            var_id,
                            preferred_vis=selected_vis,
                            source_row=row,
                        ),
                    )
                    self.state.gridCells = self.normalize_grid_cells(cells)

        self.update_selected_var_panels(
            var_id,
            preferred_source_key=str(key or ""),
            include_visualization_provenance=(
                self.details_provenance_includes_visualization()
            ),
            preferred_visualization=selected_vis,
        )

    def select_source(self, key: str, **_):
        self.commit_single_source_selection(key)
        self.state.showSourcesModal = True

    def source_dialog_select(self, key: str, **_):
        if str(self.state.sourceDialogMode or "single") == "add":
            self.toggle_add_source(key)
        else:
            self.state.sourceDialogMode = "single"
            self.select_source_key(key)

    def toggle_source_visibility(self, key: str, **_):
        self.select_source(key)

    def toggle_movie_details(self, key: str, **_):
        k = str(key or "")
        current = bool((self.state.movieDetailsOpen or {}).get(k, False))
        self.state.movieDetailsOpen = {
            **(self.state.movieDetailsOpen or {}),
            k: (not current),
        }

    def pick_tile_visualization(self, source_key: str, value=None, **_):
        key = str(source_key or "")
        if not key:
            return

        picked = value
        if isinstance(picked, dict):
            picked = picked.get("value", "")
        picked = str(picked or "")

        by_source = dict(self.state.tileVisualizationBySource or {})
        previous = str(by_source.get(key, "") or "")
        by_source[key] = picked
        self.state.tileVisualizationBySource = by_source

        if self.state.selectedVar:
            self.update_selected_var_panels(
                self.state.selectedVar,
                include_visualization_provenance=(
                    self.details_provenance_includes_visualization()
                ),
                preferred_visualization=picked,
            )
        if picked and picked != previous:
            self.record_interaction(
                "visualization.changed",
                source="source_preview_menu",
                payload={
                    "variable_id": str(self.state.selectedVar or ""),
                    "source_id": stable_fingerprint(key, "source"),
                    "previous_visualization": previous,
                    "selected_visualization": picked,
                    "query_id": self._interaction_query_id,
                    "context": "source_preview",
                },
            )
