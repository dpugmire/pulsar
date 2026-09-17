"""Visualization, plot, scalar-field, and plugin controller behavior."""

import asyncio
from typing import Any, Dict, List, Optional

from config import MAX_MOVIE_FRAMES, MOVIE_FPS
from db import (
    GENERATED_SCALAR_PLOT_VIS,
    SCALAR_FIELD_CONTOUR_LEVEL_MODES,
    SCALAR_FIELD_COLORMAP_CSS_GRADIENTS,
    SCALAR_FIELD_COLORMAPS,
    SCALAR_FIELD_DEFAULT_CONTOUR_COUNT,
    SCALAR_FIELD_MAX_CONTOUR_LEVELS,
    SCALAR_FIELD_RENDER_MODES,
    SCALAR_FIELD_VARIABLE_TYPE,
)
from plugin_runtime import (
    build_plugin_meta,
    is_plugin_visualization,
    plugin_id_from_visualization,
    plugin_scope,
    plugin_options_schema,
    render_plugin_tile,
    render_source_plugin_tile,
    supported_source_plugins,
    supported_plugin_visualizations,
    normalize_plugin_options,
)
from query_parser import and_filter
from seurat.models import plot as plot_model
from seurat.models.plugin_options import plugin_option_rows, plugin_options_from_rows
from seurat.models.grid import (
    assign_cell,
    empty_grid_cell,
    empty_grid_cell_like,
    preserve_grid_geometry,
)
from seurat.models.source_selection import (
    source_fields_from_row,
    source_filter_from_row,
)
from seurat.models.timeline import (
    selection_axis_descriptor,
    selection_axis_index_for_value,
    selection_axis_key,
    selection_axis_values,
)
from seurat.plot_options_assistant import (
    PlotOptionsTranslationRequest,
    PlotOptionsTranslationResult,
    plot1d_options_patch_from_dict,
    plot1d_options_patch_to_dict,
    scalar_field_options_patch_from_dict,
    scalar_field_options_patch_to_dict,
)
from seurat.query_assistant import MAX_ASSISTANT_REQUEST_LENGTH, QueryAssistantError
from state_init import fmt


class VisualizationControllerMixin:
    ACTION_BINDINGS = (
        ("set_active_axis_selection", "set_active_axis_selection"),
        ("cancel_scalar_plot_generation", "cancel_scalar_plot_generation"),
        ("confirm_scalar_plot_generation", "confirm_scalar_plot_generation"),
        ("cancel_plot_settings", "cancel_plot_settings"),
        ("open_plot_settings_plugin_options", "open_plot_settings_plugin_options"),
        ("cancel_plugin_options", "cancel_plugin_options"),
        ("reset_plugin_options", "reset_plugin_options"),
        ("update_plugin_option_value", "update_plugin_option_value"),
        ("apply_plugin_options", "apply_plugin_options"),
        ("cancel_scalar_field_settings", "cancel_scalar_field_settings"),
        ("reset_scalar_field_settings", "reset_scalar_field_settings"),
        ("apply_scalar_field_settings", "apply_scalar_field_settings"),
        ("toggle_scalar_field_background", "toggle_scalar_field_background"),
        ("update_scalar_field_contour_color", "update_scalar_field_contour_color"),
        (
            "open_scalar_field_options_assistant",
            "open_scalar_field_options_assistant",
        ),
        (
            "cancel_scalar_field_options_assistant",
            "cancel_scalar_field_options_assistant",
        ),
        (
            "translate_scalar_field_options_request",
            "translate_scalar_field_options_request",
        ),
        (
            "apply_scalar_field_options_patch",
            "apply_scalar_field_options_patch",
        ),
        ("reset_plot_settings", "reset_plot_settings"),
        ("update_plot_background_color", "update_plot_background_color"),
        ("update_plot_grid_color", "update_plot_grid_color"),
        ("update_plot_cursor_color", "update_plot_cursor_color"),
        ("update_plot_series_color", "update_plot_series_color"),
        ("update_plot_series_line_style", "update_plot_series_line_style"),
        ("apply_plot_settings", "apply_plot_settings"),
    )
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = ()
    HISTORY_ACTIONS = {
        "confirm_scalar_plot_generation": "Generate scalar plot",
        "apply_plugin_options": "Change plugin settings",
        "apply_scalar_field_settings": "Change scalar field settings",
        "apply_scalar_field_options_patch": "Change scalar field settings",
        "apply_plot_settings": "Change plot settings",
    }
    HISTORY_TRIGGERS = {}

    assign_plot_series_keys = staticmethod(plot_model.assign_plot_series_keys)
    axis_has_positive_data = staticmethod(plot_model.axis_has_positive_data)
    clean_line_style = staticmethod(plot_model.clean_line_style)
    clean_plot_color = staticmethod(plot_model.clean_plot_color)
    existing_plot_settings = staticmethod(plot_model.existing_plot_settings)
    finite_float = staticmethod(plot_model.finite_float)
    normalize_plot_settings = staticmethod(plot_model.normalize_plot_settings)
    plot_series = staticmethod(plot_model.plot_series)
    plot_series_rows_for_tile = staticmethod(plot_model.plot_series_rows_for_tile)
    plugin_option_rows = staticmethod(plugin_option_rows)
    plugin_options_from_rows = staticmethod(plugin_options_from_rows)
    settings_value_text = staticmethod(plot_model.settings_value_text)
    to_bool = staticmethod(plot_model.to_bool)
    valid_title_extrema = staticmethod(plot_model.valid_extrema)

    def merge_visualization_names(
        self, base_names: List[str], plugin_names: List[str]
    ) -> List[str]:
        out: List[str] = []
        for raw_name in list(base_names or []) + list(plugin_names or []):
            name = str(raw_name or "").strip()
            if name and name not in out:
                out.append(name)
        return out

    def active_selection_axis_cell_index(
        self,
        cells: List[Dict[str, Any]],
    ) -> int:
        try:
            driver = int(self.state.timelineDriverCell)
        except Exception:
            driver = -1
        if 0 <= driver < len(cells) and selection_axis_values(cells[driver]):
            return driver
        try:
            active = int(self.state.activeGridCell)
        except Exception:
            active = -1
        if 0 <= active < len(cells) and selection_axis_values(cells[active]):
            return active
        return next(
            (
                index
                for index, cell in enumerate(cells)
                if selection_axis_values(cell)
            ),
            -1,
        )

    def regenerate_axis_selected_plot(
        self,
        cell: Dict[str, Any],
        selection_index: int,
    ) -> Dict[str, Any]:
        variable_id = str(
            cell.get("variable_id", "") or cell.get("variable_name", "") or ""
        ).strip()
        source_fields_list = self.source_fields_list_from_cell(cell)
        source_keys = self.source_keys_from_cell(cell)
        if len(source_fields_list) > 1:
            source_filters = [
                self.source_fields_to_filter(variable_id, fields)
                for fields in source_fields_list
            ]
            tile = self.db.get_generated_scalar_plot_tile_for_sources(
                self.campaign_path,
                variable_id,
                source_filters=source_filters,
                extra_filter=self.active_query_filter(),
                selection_index=selection_index,
            )
        else:
            source_fields = source_fields_list[0] if source_fields_list else {}
            tile = self.db.get_or_create_generated_scalar_plot_tile(
                self.campaign_path,
                variable_id,
                source_filter=self.source_fields_to_filter(
                    variable_id,
                    source_fields,
                )
                or None,
                extra_filter=self.active_query_filter(),
                selection_index=selection_index,
            )
        if not tile:
            raise ValueError("Could not regenerate axis-selected plot")

        if source_fields_list:
            tile.update(
                {
                    key: value
                    for key, value in source_fields_list[0].items()
                    if value and key != "_source_key"
                }
            )
        tile["_source_key"] = source_keys[0] if source_keys else ""
        tile["_source_keys"] = source_keys
        tile["_source_fields_list"] = source_fields_list
        self.assign_plot_series_keys(tile, source_keys)
        tile["plot_settings"] = self.normalize_plot_settings(
            tile,
            self.existing_plot_settings(cell, variable_id),
        )
        return preserve_grid_geometry(tile, cell)

    def set_active_axis_selection(self, axis_index: int, **_):
        try:
            requested_index = int(axis_index)
        except Exception:
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        driver_index = self.active_selection_axis_cell_index(cells)
        if driver_index < 0:
            return
        driver = cells[driver_index]
        driver_values = selection_axis_values(driver)
        driver_key = selection_axis_key(driver)
        if not driver_values or not driver_key:
            return
        requested_index = max(0, min(requested_index, len(driver_values) - 1))
        selected_value = driver_values[requested_index]

        updated: List[Dict[str, Any]] = []
        for raw_cell in cells:
            cell = dict(raw_cell or {})
            cell_key = selection_axis_key(cell)
            if not cell_key:
                cell["axis_sync_status"] = "static"
                updated.append(cell)
                continue
            if cell_key != driver_key:
                cell["axis_sync_status"] = "incompatible"
                updated.append(cell)
                continue

            target_index = selection_axis_index_for_value(cell, selected_value)
            if target_index is None:
                cell["axis_sync_status"] = "unavailable"
                updated.append(cell)
                continue

            axis = selection_axis_descriptor(cell)
            axis["index"] = target_index
            axis["value"] = selected_value
            cell["selection_axis"] = axis
            cell["axis_sync_status"] = "synchronized"

            is_axis_selected_generated_plot = (
                str(cell.get("visualization_name", "") or "")
                == GENERATED_SCALAR_PLOT_VIS
                and str(cell.get("media_type", "") or "") == "plot1d"
                and str(cell.get("plot_axis_key", "") or "") != driver_key
            )
            if is_axis_selected_generated_plot:
                try:
                    cell = self.regenerate_axis_selected_plot(cell, target_index)
                    cell["axis_sync_status"] = "synchronized"
                except Exception as e:
                    cell["axis_sync_status"] = "error"
                    cell["note"] = f"Axis synchronization failed: {type(e).__name__}: {e}"
            elif (
                is_plugin_visualization(
                    str(cell.get("visualization_name", "") or "")
                )
                and str(cell.get("plot_axis_key", "") or "") != driver_key
            ):
                cell["axis_sync_status"] = "unsupported"
            updated.append(cell)

        self.state.gridCells = self.normalize_grid_cells(updated)

    def plugin_candidate(
        self,
        variable_id: str,
        source_filter: Optional[Dict[str, Any]] = None,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            candidate = self.db.scalar_plot_candidate(
                variable_id,
                source_filter=source_filter or None,
                extra_filter=extra_filter,
            )
            if candidate:
                candidate["source_variables"] = self.plugin_source_variables(candidate)
            return candidate
        except Exception:
            return {}

    def source_plugin_context_for_cell(self, cell: Dict[str, Any]) -> Dict[str, Any]:
        source_fields_items = self.source_fields_list_from_cell(cell)
        source_fields = dict(source_fields_items[0] if source_fields_items else {})
        if not source_fields:
            source_fields = {
                "_source_key": str(cell.get("_source_key", "") or ""),
                "source_dataset": str(cell.get("source_dataset", "") or ""),
                "schema_file_group": str(cell.get("schema_file_group", "") or ""),
                "schema_mode": str(cell.get("schema_mode", "") or ""),
                "producer": str(cell.get("producer", "") or ""),
                "casename": str(cell.get("casename", "") or ""),
                "file": str(cell.get("file", "") or ""),
            }

        source_variables = (
            self.plugin_source_variables({"source_fields": source_fields})
            if source_fields
            else []
        )
        metadata = cell.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "variable_id": str(cell.get("variable_id", "") or ""),
            "variable_name": str(
                cell.get("variable_name", "") or cell.get("variable_id", "") or ""
            ),
            "variable_path": str(cell.get("variable_path", "") or ""),
            "source_dataset": str(
                source_fields.get("source_dataset", "")
                or cell.get("source_dataset", "")
                or ""
            ),
            "source_fields": source_fields,
            "source_variables": source_variables,
            "metadata": dict(metadata),
            "ndims": None,
            "steps_count": 1,
            "shape": [],
            "min": cell.get("min", None),
            "max": cell.get("max", None),
        }

    def source_plugin_menu_entries_for_cell(
        self, cell: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        try:
            meta = self.source_plugin_context_for_cell(cell)
            plugins = supported_source_plugins(meta)
        except Exception:
            plugins = []
        return [
            {
                "plugin_id": info.plugin_id,
                "label": info.label,
                "visualization_name": f"plugin:{info.plugin_id}",
            }
            for info in plugins
        ]

    def build_source_plugin_grid_cell(
        self,
        plugin_id: str,
        existing_cell: Dict[str, Any],
        plugin_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plugin = str(plugin_id or "").strip()
        if not plugin:
            raise ValueError("Missing plugin")
        existing = dict(existing_cell or {})
        meta = self.source_plugin_context_for_cell(existing)
        schema = plugin_options_schema(plugin, meta)
        raw_options = (
            plugin_options
            if plugin_options is not None
            else dict(existing.get("plugin_options", {}) or {})
        )
        options = normalize_plugin_options(schema, raw_options)
        tile = render_source_plugin_tile(
            self.campaign_path, plugin, meta, options=options
        )

        source_fields = dict(meta.get("source_fields", {}) or {})
        tile.update({k: v for k, v in source_fields.items() if v})
        source_key = str(source_fields.get("_source_key", "") or "")
        tile["_source_keys"] = [source_key] if source_key else []
        tile["_source_fields_list"] = [source_fields] if source_fields else []
        tile["variable_id"] = str(
            existing.get("variable_id", "") or meta.get("variable_id", "") or ""
        )
        tile["variable_name"] = str(
            existing.get("variable_name", "")
            or meta.get("variable_name", "")
            or tile.get("display_title", "")
            or plugin
        )
        tile["plugin_options_schema"] = schema
        tile["plugin_options"] = options
        tile["plugin_scope"] = "source"
        return tile

    def plugin_visualization_names_for_variable(
        self,
        variable_id: str,
        source_filter: Optional[Dict[str, Any]] = None,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        candidate = self.plugin_candidate(
            variable_id, source_filter=source_filter, extra_filter=extra_filter
        )
        if not candidate:
            return []
        return supported_plugin_visualizations(build_plugin_meta(candidate))

    def visualization_names_with_plugins(
        self,
        variable_id: str,
        source_filter: Optional[Dict[str, Any]] = None,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        base_names = self.db.distinct_visualization_names_for_variable(
            variable_id, extra_filter=extra_filter
        )
        plugin_names = self.plugin_visualization_names_for_variable(
            variable_id,
            source_filter=source_filter,
            extra_filter=extra_filter,
        )
        return self.merge_visualization_names(base_names, plugin_names)

    def update_2d_display_title(
        self, cell: Dict[str, Any], variable_id: str, label: str
    ) -> None:
        media_type = str(cell.get("media_type", "") or "")
        if media_type not in {"image", "image_sequence", "video"}:
            cell["display_title"] = str(label or "")
            cell["scalar_field_colorbar_min"] = ""
            cell["scalar_field_colorbar_max"] = ""
            return

        title_min: Optional[float] = None
        title_max: Optional[float] = None
        if self.is_scalar_field_cell(cell):
            representation_id = str(
                cell.get("selected_visualization", "")
                or cell.get("visualization_name", "")
                or ""
            )
            fmin, fmax = self.source_extrema_for_title(
                variable_id,
                self.source_filter_from_cell(cell),
                representation_id=representation_id,
            )
            if fmin is None or fmax is None:
                fmin, fmax = self.valid_title_extrema(
                    cell.get("min", None), cell.get("max", None)
                )
            title_min, title_max = fmin, fmax
        else:
            fmin, fmax = self.valid_title_extrema(
                cell.get("min", None), cell.get("max", None)
            )
            if fmin is None or fmax is None:
                fmin, fmax = self.source_extrema_for_title(
                    variable_id,
                    self.source_filter_from_cell(cell),
                )

        if fmin is None or fmax is None:
            cell["display_title"] = str(label or "")
        else:
            cell["display_title"] = f"{label} [{fmt(fmin)}, {fmt(fmax)}]"

        cell["scalar_field_colorbar_min"] = ""
        cell["scalar_field_colorbar_max"] = ""
        if self.is_scalar_field_cell(cell):
            settings = self.normalize_scalar_field_settings(
                cell.get("scalar_field_settings", {})
            )
            if not bool(settings.get("range_auto", True)):
                bar_min = self.finite_float(settings.get("min", None))
                bar_max = self.finite_float(settings.get("max", None))
            else:
                bar_min, bar_max = title_min, title_max
            if bar_min is not None and bar_max is not None:
                cell["scalar_field_colorbar_min"] = fmt(bar_min)
                cell["scalar_field_colorbar_max"] = fmt(bar_max)

    def is_generated_plot1d_cell(self, cell: Dict[str, Any]) -> bool:
        if str(cell.get("media_type", "") or "") != "plot1d":
            return False
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        ).strip()
        visualization_name = str(
            cell.get("visualization_name", "") or selected_vis
        ).strip()
        return (
            selected_vis == GENERATED_SCALAR_PLOT_VIS
            or visualization_name == GENERATED_SCALAR_PLOT_VIS
        )

    def is_multi_source_plot1d_cell(self, cell: Dict[str, Any]) -> bool:
        if self.is_generated_plot1d_cell(cell):
            return True
        if str(cell.get("media_type", "") or "") != "plot1d":
            return False
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        ).strip()
        if not is_plugin_visualization(selected_vis):
            return False
        plugin_id = plugin_id_from_visualization(selected_vis)
        return bool(plugin_id) and plugin_scope(plugin_id) == "variable"

    def scalar_colormap(self, value: Any) -> str:
        name = str(value or "viridis").strip().lower()
        return name if name in SCALAR_FIELD_COLORMAPS else "viridis"

    def scalar_colormap_gradient(self, value: Any) -> str:
        name = self.scalar_colormap(value)
        return SCALAR_FIELD_COLORMAP_CSS_GRADIENTS.get(
            name,
            SCALAR_FIELD_COLORMAP_CSS_GRADIENTS.get("viridis", ""),
        )

    @staticmethod
    def scalar_field_background(value: Any) -> str:
        return "white" if str(value or "").strip().lower() == "white" else "black"

    @staticmethod
    def scalar_field_render_mode(value: Any) -> str:
        mode = str(value or "colormap").strip().lower()
        return mode if mode in SCALAR_FIELD_RENDER_MODES else "colormap"

    @staticmethod
    def scalar_field_contour_level_mode(value: Any) -> str:
        mode = str(value or "range").strip().lower()
        return mode if mode in SCALAR_FIELD_CONTOUR_LEVEL_MODES else "range"

    def parse_scalar_field_contour_values(self, value: Any) -> List[float]:
        if isinstance(value, (list, tuple)):
            tokens = list(value)
        else:
            text = str(value or "").replace(",", " ").replace(";", " ")
            tokens = text.split()

        values: List[float] = []
        for token in tokens:
            parsed = self.finite_float(token)
            if parsed is None:
                raise ValueError(f'Invalid contour value: "{token}"')
            values.append(float(parsed))

        values = sorted(set(values))
        if not values:
            raise ValueError("Enter at least one contour value.")
        if len(values) > SCALAR_FIELD_MAX_CONTOUR_LEVELS:
            raise ValueError(
                "Contour values are limited to "
                f"{SCALAR_FIELD_MAX_CONTOUR_LEVELS} levels."
            )
        return values

    def normalize_scalar_field_settings(
        self, raw_settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        raw = dict(raw_settings or {})
        background = self.scalar_field_background(raw.get("background", "black"))
        render_mode = self.scalar_field_render_mode(
            raw.get("render_mode", "colormap")
        )
        range_mode = str(raw.get("range_mode", "") or "").strip().lower()
        range_auto = raw.get("range_auto", None)
        if range_auto is None:
            range_auto = range_mode != "manual"
        range_auto = self.to_bool(range_auto, True)
        min_value = self.finite_float(raw.get("min", None))
        max_value = self.finite_float(raw.get("max", None))
        if (
            range_auto
            or min_value is None
            or max_value is None
            or min_value >= max_value
        ):
            min_value = None
            max_value = None
            range_auto = True

        raw_contours = raw.get("contours", {})
        contours = raw_contours if isinstance(raw_contours, dict) else {}
        contour_level_mode = self.scalar_field_contour_level_mode(
            contours.get("level_mode", "range")
        )
        contour_values: List[float] = []
        raw_contour_values = contours.get("values", [])
        if isinstance(raw_contour_values, (list, tuple)):
            for value in raw_contour_values:
                parsed = self.finite_float(value)
                if parsed is not None:
                    contour_values.append(float(parsed))
        contour_values = sorted(set(contour_values))[
            :SCALAR_FIELD_MAX_CONTOUR_LEVELS
        ]
        contour_min = self.finite_float(contours.get("min", None))
        contour_max = self.finite_float(contours.get("max", None))
        if (
            contour_min is None
            or contour_max is None
            or contour_min >= contour_max
        ):
            contour_min = None
            contour_max = None
        try:
            contour_count = int(
                contours.get("count", SCALAR_FIELD_DEFAULT_CONTOUR_COUNT)
            )
        except (TypeError, ValueError):
            contour_count = SCALAR_FIELD_DEFAULT_CONTOUR_COUNT
        if not 2 <= contour_count <= SCALAR_FIELD_MAX_CONTOUR_LEVELS:
            contour_count = SCALAR_FIELD_DEFAULT_CONTOUR_COUNT
        contour_color = self.clean_plot_color(
            contours.get("color", "#ffffff"),
            "#ffffff",
        )

        return {
            "render_mode": render_mode,
            "colormap": self.scalar_colormap(raw.get("colormap", "viridis")),
            "colorbar_gradient": self.scalar_colormap_gradient(
                raw.get("colormap", "viridis")
            ),
            "background": background,
            "background_color": "#ffffff" if background == "white" else "#000000",
            "foreground_color": "#111111" if background == "white" else "#ffffff",
            "range_auto": range_auto,
            "range_mode": "auto" if range_auto else "manual",
            "min": min_value,
            "max": max_value,
            "show_colorbar": self.to_bool(raw.get("show_colorbar", False), False),
            "show_axes": self.to_bool(raw.get("show_axes", False), False),
            "contours": {
                "level_mode": contour_level_mode,
                "values": contour_values,
                "min": contour_min,
                "max": contour_max,
                "count": contour_count,
                "color": contour_color,
            },
        }

    def is_scalar_field_cell(self, cell: Dict[str, Any]) -> bool:
        variable_type = str(cell.get("variable_type", "") or "").strip()
        payload_type = str(cell.get("payload_type", "") or "").strip().upper()
        item_type = str(cell.get("visualization_item_type", "") or "").strip().upper()
        return (
            variable_type == SCALAR_FIELD_VARIABLE_TYPE
            or payload_type == "SCALAR_FIELD"
            or item_type == "SCALAR_FIELD"
        )

    def existing_scalar_field_settings(
        self, existing_cell: Optional[Dict[str, Any]], variable_id: str
    ) -> Dict[str, Any]:
        if not isinstance(existing_cell, dict):
            return self.normalize_scalar_field_settings()
        existing_var = str(
            existing_cell.get("variable_id", "")
            or existing_cell.get("variable_name", "")
            or ""
        )
        if existing_var != str(variable_id or ""):
            return self.normalize_scalar_field_settings()
        return self.normalize_scalar_field_settings(
            existing_cell.get("scalar_field_settings", {})
        )

    def load_scalar_field_settings_dialog(self, idx: int, reset: bool = False) -> None:
        cells = self.normalize_grid_cells(self.state.gridCells)
        if not self.is_valid_grid_index(idx):
            return
        cell = dict(cells[idx] or {})
        if not self.is_scalar_field_cell(cell):
            return

        raw_settings = (
            {} if reset else dict(cell.get("scalar_field_settings", {}) or {})
        )
        settings = self.normalize_scalar_field_settings(raw_settings)
        self.state.scalarFieldSettingsCellIndex = idx
        self.state.scalarFieldSettingsTitle = str(
            cell.get("variable_name", "") or f"Cell {idx + 1}"
        )
        self.state.scalarFieldSettingsStatus = ""
        self.state.scalarFieldSettingsStatusIsError = False
        self.state.scalarFieldSettingsColormap = str(
            settings.get("colormap", "viridis") or "viridis"
        )
        render_mode = self.scalar_field_render_mode(
            settings.get("render_mode", "colormap")
        )
        self.state.scalarFieldSettingsShowHeatmap = render_mode in {
            "colormap",
            "both",
        }
        self.state.scalarFieldSettingsShowContours = render_mode in {
            "contours",
            "both",
        }
        self.state.scalarFieldSettingsBackground = str(
            settings.get("background", "black") or "black"
        )
        self.state.scalarFieldSettingsRangeAuto = bool(settings.get("range_auto", True))
        self.state.scalarFieldSettingsMin = self.settings_value_text(
            settings.get("min", None)
        )
        self.state.scalarFieldSettingsMax = self.settings_value_text(
            settings.get("max", None)
        )
        self.state.scalarFieldSettingsShowColorbar = bool(
            settings.get("show_colorbar", False)
        )
        self.state.scalarFieldSettingsShowAxes = bool(settings.get("show_axes", False))
        contours = dict(settings.get("contours", {}) or {})
        self.state.scalarFieldSettingsContourLevelMode = str(
            contours.get("level_mode", "range") or "range"
        )
        self.state.scalarFieldSettingsContourValues = ", ".join(
            self.settings_value_text(value)
            for value in contours.get("values", [])
        )
        contour_min = contours.get("min", None)
        contour_max = contours.get("max", None)
        if contour_min is None:
            contour_min = self.finite_float(
                cell.get("scalar_field_colorbar_min", None)
            )
        if contour_max is None:
            contour_max = self.finite_float(
                cell.get("scalar_field_colorbar_max", None)
            )
        self.state.scalarFieldSettingsContourMin = self.settings_value_text(
            contour_min
        )
        self.state.scalarFieldSettingsContourMax = self.settings_value_text(
            contour_max
        )
        self.state.scalarFieldSettingsContourCount = int(
            contours.get("count", SCALAR_FIELD_DEFAULT_CONTOUR_COUNT)
        )
        self.state.scalarFieldSettingsContourColor = str(
            contours.get("color", "#ffffff") or "#ffffff"
        )
        self.state.showScalarFieldSettingsModal = True

    def reset_scalar_field_options_assistant_proposal(self) -> None:
        self.state.scalarFieldAssistantStatus = ""
        self.state.scalarFieldAssistantError = ""
        self.state.scalarFieldAssistantProposalSummary = ""
        self.state.scalarFieldAssistantClarification = ""
        self.state.scalarFieldAssistantPatch = {}

    def open_scalar_field_options_assistant(self, idx: int, **_) -> bool:
        if not self.plot_options_translator:
            return False
        try:
            cell_index = int(idx)
        except (TypeError, ValueError):
            cell_index = -1
        cells = self.normalize_grid_cells(self.state.gridCells)
        if not self.is_valid_grid_index(cell_index):
            return False
        cell = dict(cells[cell_index] or {})
        if not self.is_scalar_field_cell(cell) and str(
            cell.get("media_type", "") or ""
        ) != "plot1d":
            return False

        self._invalidate_scalar_field_assistant_request()
        self.reset_scalar_field_options_assistant_proposal()
        self.state.scalarFieldAssistantCellIndex = cell_index
        self.state.scalarFieldAssistantTitle = str(
            cell.get("variable_name", "") or f"Cell {cell_index + 1}"
        )
        self.state.scalarFieldAssistantRequestText = ""
        self.state.scalarFieldAssistantBusy = False
        self.state.showScalarFieldAssistantModal = True
        self.state.activeGridCell = cell_index
        return True

    def cancel_scalar_field_options_assistant(self, **_) -> None:
        self._invalidate_scalar_field_assistant_request()
        self.state.scalarFieldAssistantBusy = False
        self.state.showScalarFieldAssistantModal = False
        self.state.scalarFieldAssistantCellIndex = -1
        self.reset_scalar_field_options_assistant_proposal()

    def _invalidate_scalar_field_assistant_request(self) -> int:
        request_id = int(
            getattr(self, "_scalar_field_assistant_request_id", 0) or 0
        ) + 1
        self._scalar_field_assistant_request_id = request_id
        return request_id

    def _flush_scalar_field_assistant_state(self) -> None:
        flush = getattr(self.state, "flush", None)
        if callable(flush):
            flush()

    def scalar_field_options_translation_request(
        self, request_text: str
    ) -> PlotOptionsTranslationRequest:
        try:
            idx = int(self.state.scalarFieldAssistantCellIndex)
        except (TypeError, ValueError):
            idx = -1
        if not self.is_valid_grid_index(idx):
            raise QueryAssistantError("No scalar-field cell selected.")
        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        is_plot1d = str(cell.get("media_type", "") or "") == "plot1d"
        if not self.is_scalar_field_cell(cell) and not is_plot1d:
            raise QueryAssistantError("Selected cell does not support plot options.")

        if is_plot1d:
            settings = self.normalize_plot_settings(
                cell,
                cell.get("plot_settings", {}),
            )
            plot = dict(cell.get("plot", {}) or {})
            return PlotOptionsTranslationRequest(
                request_text=request_text,
                plot_type="plot1d",
                variable_id=str(
                    cell.get("variable_id", "")
                    or cell.get("variable_name", "")
                    or ""
                ),
                variable_name=str(cell.get("variable_name", "") or ""),
                current_settings=settings,
                x_label=str(plot.get("x_label", "") or ""),
                y_label=str(plot.get("y_label", "") or ""),
                series=tuple(self.plot_series_rows_for_tile(cell, settings)),
            )

        settings = self.normalize_scalar_field_settings(
            cell.get("scalar_field_settings", {})
        )
        return PlotOptionsTranslationRequest(
            request_text=request_text,
            plot_type="scalar_field",
            variable_id=str(
                cell.get("variable_id", "") or cell.get("variable_name", "") or ""
            ),
            variable_name=str(cell.get("variable_name", "") or ""),
            current_settings=settings,
            data_min=self.finite_float(
                cell.get("scalar_field_colorbar_min", cell.get("min", None))
            ),
            data_max=self.finite_float(
                cell.get("scalar_field_colorbar_max", cell.get("max", None))
            ),
        )

    async def translate_scalar_field_options_request(self, **_) -> bool:
        if not self.plot_options_translator:
            self.state.scalarFieldAssistantError = (
                "Plot Options Assistant is not configured."
            )
            return False

        request_text = str(
            self.state.scalarFieldAssistantRequestText or ""
        ).strip()
        if not request_text:
            self.state.scalarFieldAssistantError = "Enter a plot option request."
            return False
        if len(request_text) > MAX_ASSISTANT_REQUEST_LENGTH:
            self.state.scalarFieldAssistantError = (
                f"Requests are limited to {MAX_ASSISTANT_REQUEST_LENGTH} characters."
            )
            return False

        request_id = self._invalidate_scalar_field_assistant_request()
        self.reset_scalar_field_options_assistant_proposal()
        self.state.scalarFieldAssistantBusy = True
        self.state.scalarFieldAssistantStatus = "Translating request..."
        self._flush_scalar_field_assistant_state()

        try:
            translation_request = self.scalar_field_options_translation_request(
                request_text
            )
            timeout_seconds = max(
                1.0,
                float(self.plot_options_translator.timeout_seconds),
            )
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self.plot_options_translator.translate,
                    translation_request,
                ),
                timeout=timeout_seconds + 1.0,
            )
            if not isinstance(result, PlotOptionsTranslationResult):
                raise QueryAssistantError(
                    "Translator returned an invalid option proposal object."
                )
        except asyncio.TimeoutError:
            if request_id == self._scalar_field_assistant_request_id:
                self.state.scalarFieldAssistantError = (
                    "Plot option translation timed out."
                )
                self.state.scalarFieldAssistantStatus = ""
            return False
        except Exception as e:
            if request_id == self._scalar_field_assistant_request_id:
                message = (
                    str(e)
                    if isinstance(e, QueryAssistantError)
                    else f"Plot option translation failed ({type(e).__name__})."
                )
                self.state.scalarFieldAssistantError = message
                self.state.scalarFieldAssistantStatus = ""
            return False
        finally:
            if request_id == self._scalar_field_assistant_request_id:
                self.state.scalarFieldAssistantBusy = False

        if request_id != self._scalar_field_assistant_request_id:
            return False

        self.state.scalarFieldAssistantClarification = result.clarification
        if result.status == "needs_clarification":
            self.state.scalarFieldAssistantStatus = "Clarification needed"
            return False

        if translation_request.plot_type == "plot1d":
            self.state.scalarFieldAssistantPatch = plot1d_options_patch_to_dict(
                result.patch
            )
        else:
            self.state.scalarFieldAssistantPatch = scalar_field_options_patch_to_dict(
                result.patch
            )
        self.state.scalarFieldAssistantProposalSummary = (
            result.summary or "Ready to apply plot option changes."
        )
        self.state.scalarFieldAssistantStatus = "Proposal ready"
        return True

    def scalar_field_settings_with_options_patch(
        self,
        cell: Dict[str, Any],
        patch_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        patch = scalar_field_options_patch_from_dict(patch_payload)
        settings = self.normalize_scalar_field_settings(
            cell.get("scalar_field_settings", {})
        )
        contours = dict(settings.get("contours", {}) or {})
        raw = {
            "render_mode": settings.get("render_mode", "colormap"),
            "colormap": settings.get("colormap", "viridis"),
            "background": settings.get("background", "black"),
            "range_auto": bool(settings.get("range_auto", True)),
            "min": settings.get("min", None),
            "max": settings.get("max", None),
            "show_colorbar": bool(settings.get("show_colorbar", False)),
            "show_axes": bool(settings.get("show_axes", False)),
            "contours": contours,
        }

        if patch.render_mode is not None:
            raw["render_mode"] = patch.render_mode
        if patch.colormap is not None:
            if self.scalar_colormap(patch.colormap) != patch.colormap:
                raise ValueError(f"Unsupported colormap: {patch.colormap}")
            raw["colormap"] = patch.colormap
        if patch.background is not None:
            raw["background"] = patch.background
        if patch.range_auto is not None:
            raw["range_auto"] = patch.range_auto
            if patch.range_auto:
                raw["min"] = None
                raw["max"] = None
        if patch.min is not None or patch.max is not None:
            raw["range_auto"] = False if patch.range_auto is None else patch.range_auto
            if patch.min is not None:
                raw["min"] = patch.min
            if patch.max is not None:
                raw["max"] = patch.max
        if patch.show_colorbar is not None:
            raw["show_colorbar"] = patch.show_colorbar
        if patch.show_axes is not None:
            raw["show_axes"] = patch.show_axes

        contour_patch = patch.contours
        if contour_patch.level_mode is not None:
            contours["level_mode"] = contour_patch.level_mode
        if contour_patch.values is not None:
            contours["level_mode"] = (
                contour_patch.level_mode
                if contour_patch.level_mode is not None
                else "values"
            )
            contours["values"] = list(contour_patch.values)
        if contour_patch.min is not None:
            contours["level_mode"] = (
                contour_patch.level_mode
                if contour_patch.level_mode is not None
                else "range"
            )
            contours["min"] = contour_patch.min
        if contour_patch.max is not None:
            contours["level_mode"] = (
                contour_patch.level_mode
                if contour_patch.level_mode is not None
                else "range"
            )
            contours["max"] = contour_patch.max
        if contour_patch.count is not None:
            contours["level_mode"] = (
                contour_patch.level_mode
                if contour_patch.level_mode is not None
                else "range"
            )
            contours["count"] = contour_patch.count
        if contour_patch.color is not None:
            color = self.clean_plot_color(contour_patch.color, "")
            if not color:
                raise ValueError(f"Invalid contour color: {contour_patch.color}")
            contours["color"] = color

        range_auto = bool(raw.get("range_auto", True))
        min_value = self.finite_float(raw.get("min", None))
        max_value = self.finite_float(raw.get("max", None))
        if not range_auto:
            if min_value is None or max_value is None:
                raise ValueError("Manual range requires min and max values.")
            if min_value >= max_value:
                raise ValueError("Manual range must have min < max.")

        render_mode = self.scalar_field_render_mode(raw.get("render_mode", "colormap"))
        contour_level_mode = self.scalar_field_contour_level_mode(
            contours.get("level_mode", "range")
        )
        if render_mode != "colormap" and contour_level_mode == "values":
            contour_values = list(contours.get("values", []) or [])
            if not contour_values:
                raise ValueError("Enter at least one contour value.")

        return self.normalize_scalar_field_settings(raw)

    def update_scalar_field_cell_settings(
        self,
        idx: int,
        settings: Dict[str, Any],
    ) -> None:
        if not self.is_valid_grid_index(idx):
            raise ValueError("No scalar-field cell selected.")
        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        if not self.is_scalar_field_cell(cell):
            raise ValueError("Selected cell is not a scalar-field visualization.")

        var = str(
            cell.get("variable_id", "") or cell.get("variable_name", "") or ""
        ).strip()
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        ).strip()
        if not var or not selected_vis:
            raise ValueError("Cell is missing a variable or visualization.")

        cell["scalar_field_settings"] = settings
        new_cell = self.build_grid_cell_for_variable(
            var,
            preferred_vis=selected_vis,
            existing_cell=cell,
        )
        assign_cell(cells, idx, new_cell)
        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = idx

    def validated_plot_settings(
        self,
        cell: Dict[str, Any],
        raw_settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw = dict(raw_settings or {})
        x_auto = bool(raw.get("x_auto", True))
        y_auto = bool(raw.get("y_auto", True))
        x_min = self.finite_float(raw.get("x_min", None))
        x_max = self.finite_float(raw.get("x_max", None))
        y_min = self.finite_float(raw.get("y_min", None))
        y_max = self.finite_float(raw.get("y_max", None))
        x_scale = str(raw.get("x_scale", "linear") or "linear").strip().lower()
        y_scale = str(raw.get("y_scale", "linear") or "linear").strip().lower()
        if x_scale not in {"linear", "log"}:
            x_scale = "linear"
        if y_scale not in {"linear", "log"}:
            y_scale = "linear"

        if not x_auto:
            if x_min is None or x_max is None:
                raise ValueError("Manual X range requires min and max values.")
            if x_min >= x_max:
                raise ValueError("Manual X range must have min < max.")
        if not y_auto:
            if y_min is None or y_max is None:
                raise ValueError("Manual Y range requires min and max values.")
            if y_min >= y_max:
                raise ValueError("Manual Y range must have min < max.")

        if x_scale == "log":
            if not self.axis_has_positive_data(cell, "x"):
                raise ValueError("X log scale requires positive X values.")
            if not x_auto and (
                x_min is None or x_max is None or x_min <= 0 or x_max <= 0
            ):
                raise ValueError("Manual X log range must be positive.")
        if y_scale == "log":
            if not self.axis_has_positive_data(cell, "y"):
                raise ValueError("Y log scale requires positive Y values.")
            if not y_auto and (
                y_min is None or y_max is None or y_min <= 0 or y_max <= 0
            ):
                raise ValueError("Manual Y log range must be positive.")

        line_width = self.finite_float(raw.get("line_width", 2.5))
        if line_width is None:
            raise ValueError("Line width must be a number.")
        line_width = max(0.5, min(8.0, line_width))

        return self.normalize_plot_settings(
            cell,
            {
                "x_auto": x_auto,
                "x_min": None if x_auto else x_min,
                "x_max": None if x_auto else x_max,
                "x_scale": x_scale,
                "y_auto": y_auto,
                "y_min": None if y_auto else y_min,
                "y_max": None if y_auto else y_max,
                "y_scale": y_scale,
                "series_colors": dict(raw.get("series_colors", {}) or {}),
                "series_styles": dict(raw.get("series_styles", {}) or {}),
                "line_width": line_width,
                "show_grid": bool(raw.get("show_grid", True)),
                "show_cursor": bool(raw.get("show_cursor", True)),
                "background_color": self.clean_plot_color(
                    raw.get("background_color", ""), "#ffffff"
                ),
                "grid_color": self.clean_plot_color(
                    raw.get("grid_color", ""), "#e8e8e8"
                ),
                "cursor_color": self.clean_plot_color(
                    raw.get("cursor_color", ""), "#111111"
                ),
            },
        )

    def plot1d_settings_with_options_patch(
        self,
        cell: Dict[str, Any],
        patch_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        patch = plot1d_options_patch_from_dict(patch_payload)
        current = self.normalize_plot_settings(cell, cell.get("plot_settings", {}))
        raw = dict(current)
        raw["series_colors"] = dict(current.get("series_colors", {}) or {})
        raw["series_styles"] = {
            key: dict(value or {})
            for key, value in dict(current.get("series_styles", {}) or {}).items()
        }

        if patch.x_auto is not None:
            raw["x_auto"] = patch.x_auto
            if patch.x_auto:
                raw["x_min"] = None
                raw["x_max"] = None
        if patch.x_min is not None or patch.x_max is not None:
            raw["x_auto"] = False if patch.x_auto is None else patch.x_auto
            if patch.x_min is not None:
                raw["x_min"] = patch.x_min
            if patch.x_max is not None:
                raw["x_max"] = patch.x_max
        if patch.x_scale is not None:
            raw["x_scale"] = patch.x_scale
        if patch.y_auto is not None:
            raw["y_auto"] = patch.y_auto
            if patch.y_auto:
                raw["y_min"] = None
                raw["y_max"] = None
        if patch.y_min is not None or patch.y_max is not None:
            raw["y_auto"] = False if patch.y_auto is None else patch.y_auto
            if patch.y_min is not None:
                raw["y_min"] = patch.y_min
            if patch.y_max is not None:
                raw["y_max"] = patch.y_max
        if patch.y_scale is not None:
            raw["y_scale"] = patch.y_scale
        if patch.line_width is not None:
            raw["line_width"] = patch.line_width
        if patch.show_grid is not None:
            raw["show_grid"] = patch.show_grid
        if patch.show_cursor is not None:
            raw["show_cursor"] = patch.show_cursor
        if patch.background_color is not None:
            color = self.clean_plot_color(patch.background_color, "")
            if not color:
                raise ValueError(f"Invalid background color: {patch.background_color}")
            raw["background_color"] = color
        if patch.grid_color is not None:
            color = self.clean_plot_color(patch.grid_color, "")
            if not color:
                raise ValueError(f"Invalid grid color: {patch.grid_color}")
            raw["grid_color"] = color
        if patch.cursor_color is not None:
            color = self.clean_plot_color(patch.cursor_color, "")
            if not color:
                raise ValueError(f"Invalid cursor color: {patch.cursor_color}")
            raw["cursor_color"] = color

        known_keys = {
            str(row.get("key", "") or "")
            for row in self.plot_series_rows_for_tile(cell, current)
        }
        for item in patch.series:
            key = str(item.series_key or "").strip()
            if key not in known_keys:
                raise ValueError(f"Unknown plot series: {key}")
            style = dict(raw["series_styles"].get(key, {}) or {})
            if item.color is not None:
                color = self.clean_plot_color(item.color, "")
                if not color:
                    raise ValueError(f"Invalid series color: {item.color}")
                raw["series_colors"][key] = color
                style["color"] = color
            if item.line_style is not None:
                style["line_style"] = self.clean_line_style(item.line_style)
            raw["series_styles"][key] = style

        return self.validated_plot_settings(cell, raw)

    def update_plot1d_cell_settings(
        self,
        idx: int,
        settings: Dict[str, Any],
    ) -> None:
        if not self.is_valid_grid_index(idx):
            raise ValueError("No plot cell selected.")
        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        if str(cell.get("media_type", "") or "") != "plot1d":
            raise ValueError("Selected cell is not a 1D plot.")
        cell["plot_settings"] = settings
        cells[idx] = cell
        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = idx

    def apply_scalar_field_options_patch(self, **_) -> bool:
        try:
            idx = int(self.state.scalarFieldAssistantCellIndex)
        except (TypeError, ValueError):
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.state.scalarFieldAssistantError = "No scalar-field cell selected."
            return False

        patch_payload = dict(self.state.scalarFieldAssistantPatch or {})
        if not patch_payload:
            self.state.scalarFieldAssistantError = (
                "Translate a plot option request before applying."
            )
            return False

        try:
            cells = self.normalize_grid_cells(self.state.gridCells)
            cell = dict(cells[idx] or {})
            if str(cell.get("media_type", "") or "") == "plot1d":
                settings = self.plot1d_settings_with_options_patch(
                    cell,
                    patch_payload,
                )
                self.update_plot1d_cell_settings(idx, settings)
            else:
                if not self.is_scalar_field_cell(cell):
                    raise ValueError("Selected cell does not support plot options.")
                settings = self.scalar_field_settings_with_options_patch(
                    cell,
                    patch_payload,
                )
                self.update_scalar_field_cell_settings(idx, settings)
        except Exception as e:
            self.state.scalarFieldAssistantError = f"{type(e).__name__}: {e}"
            self.state.scalarFieldAssistantStatus = ""
            return False

        self.state.scalarFieldAssistantError = ""
        self.state.scalarFieldAssistantStatus = "Applied."
        self.state.scalarFieldAssistantPatch = {}
        return True

    def load_plot_settings_dialog(self, idx: int, reset: bool = False) -> None:
        cells = self.normalize_grid_cells(self.state.gridCells)
        if not self.is_valid_grid_index(idx):
            return
        cell = dict(cells[idx] or {})
        if str(cell.get("media_type", "") or "") != "plot1d":
            return

        raw_settings = {} if reset else dict(cell.get("plot_settings", {}) or {})
        settings = self.normalize_plot_settings(cell, raw_settings)
        self.state.plotSettingsCellIndex = idx
        self.state.plotSettingsTitle = str(
            cell.get("variable_name", "") or f"Cell {idx + 1}"
        )
        self.state.plotSettingsStatus = ""
        self.state.plotSettingsCanPluginOptions = is_plugin_visualization(
            str(
                cell.get("selected_visualization", "")
                or cell.get("visualization_name", "")
                or ""
            )
        )
        self.state.plotSettingsXAuto = bool(settings.get("x_auto", True))
        self.state.plotSettingsXMin = self.settings_value_text(
            settings.get("x_min", None)
        )
        self.state.plotSettingsXMax = self.settings_value_text(
            settings.get("x_max", None)
        )
        self.state.plotSettingsXScale = str(
            settings.get("x_scale", "linear") or "linear"
        )
        self.state.plotSettingsYAuto = bool(settings.get("y_auto", True))
        self.state.plotSettingsYMin = self.settings_value_text(
            settings.get("y_min", None)
        )
        self.state.plotSettingsYMax = self.settings_value_text(
            settings.get("y_max", None)
        )
        self.state.plotSettingsYScale = str(
            settings.get("y_scale", "linear") or "linear"
        )
        self.state.plotSettingsLineWidth = float(settings.get("line_width", 2.5) or 2.5)
        self.state.plotSettingsShowGrid = bool(settings.get("show_grid", True))
        self.state.plotSettingsShowCursor = bool(settings.get("show_cursor", True))
        self.state.plotSettingsBackgroundColor = self.clean_plot_color(
            settings.get("background_color", ""), "#ffffff"
        )
        self.state.plotSettingsGridColor = self.clean_plot_color(
            settings.get("grid_color", ""), "#e8e8e8"
        )
        self.state.plotSettingsCursorColor = self.clean_plot_color(
            settings.get("cursor_color", ""), "#111111"
        )
        self.state.plotSettingsSeriesRows = self.plot_series_rows_for_tile(
            cell, settings
        )
        self.state.showPlotSettingsModal = True

    def load_plugin_options_dialog(self, idx: int, reset: bool = False) -> None:
        cells = self.normalize_grid_cells(self.state.gridCells)
        if not self.is_valid_grid_index(idx):
            return
        cell = dict(cells[idx] or {})
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        )
        if not is_plugin_visualization(selected_vis):
            return

        schema = list(cell.get("plugin_options_schema", []) or [])
        options = {} if reset else dict(cell.get("plugin_options", {}) or {})
        options = normalize_plugin_options(schema, options)
        self.state.pluginOptionsCellIndex = idx
        self.state.pluginOptionsTitle = str(
            cell.get("display_title", "")
            or cell.get("variable_name", "")
            or f"Cell {idx + 1}"
        )
        self.state.pluginOptionsStatus = ""
        self.state.pluginOptionsRows = self.plugin_option_rows(schema, options)
        self.state.showPluginOptionsModal = True

    def choose_visualization_default(
        self, vis_names: List[str], preferred_vis: str = ""
    ) -> str:
        preferred = str(preferred_vis or "").strip()
        if preferred and preferred in vis_names:
            return preferred
        if "heatmap" in vis_names:
            return "heatmap"
        return vis_names[0] if vis_names else ""

    def variable_label(self, variable_id: str) -> str:
        item_id = str(variable_id or "").strip()
        labels = dict(self.state.variableLabelsById or {})
        return str(labels.get(item_id, "") or item_id)

    def normalize_scalar_plot_policy(self) -> str:
        policy = str(self.state.scalarPlotPolicy or "always").strip().lower()
        if policy not in {"ask", "always", "never"}:
            policy = "always"
        self.state.scalarPlotPolicy = policy
        return policy

    def clear_pending_scalar_plot(self) -> None:
        self.state.showScalarPlotDialog = False
        self.state.pendingScalarPlotVariableId = ""
        self.state.pendingScalarPlotCellIndex = -1
        self.state.pendingScalarPlotSourceFields = {}
        self.state.pendingScalarPlotSyncSelection = True
        self.state.scalarPlotDialogMessage = ""
        self.state.scalarPlotAlwaysForSession = False

    def build_plugin_grid_cell(
        self,
        variable_id: str,
        plugin_visualization: str,
        source_row: Optional[Dict[str, str]] = None,
        existing_cell: Optional[Dict[str, Any]] = None,
        plugin_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        var_id = str(variable_id or "").strip()
        plugin_vis = str(plugin_visualization or "").strip()
        plugin_id = plugin_id_from_visualization(plugin_vis)
        if not var_id or not plugin_id:
            raise ValueError("Missing plugin visualization")

        if source_row:
            source_filter = source_filter_from_row(source_row)
        elif existing_cell:
            source_filter = self.source_filter_from_cell(existing_cell)
        else:
            source_filter = self.active_source_filter_for_variable(var_id)

        query_filter = self.active_query_filter()
        candidate = self.plugin_candidate(
            var_id,
            source_filter=source_filter or None,
            extra_filter=query_filter,
        )
        if not candidate:
            raise ValueError("No plugin-compatible source for this variable")

        meta = build_plugin_meta(candidate)
        schema = plugin_options_schema(plugin_id, meta)
        raw_options = (
            plugin_options
            if plugin_options is not None
            else dict((existing_cell or {}).get("plugin_options", {}) or {})
        )
        options = normalize_plugin_options(schema, raw_options)
        tile = render_plugin_tile(
            self.campaign_path, plugin_id, candidate, options=options
        )
        label = self.variable_label(var_id)
        source_fields = self.source_fields_for_assignment(
            var_id, source_row=source_row, candidate=candidate
        )
        if existing_cell and not source_fields.get("_source_key"):
            source_fields["_source_key"] = str(
                existing_cell.get("_source_key", "") or ""
            )
        tile.update({k: v for k, v in source_fields.items() if v})
        source_key = str(source_fields.get("_source_key", "") or "")
        tile["_source_keys"] = [source_key] if source_key else []
        tile["_source_fields_list"] = [source_fields] if source_fields else []
        if str(tile.get("media_type", "") or "") == "plot1d":
            self.assign_plot_series_keys(tile, [source_key] if source_key else [])
            tile["plot_settings"] = self.normalize_plot_settings(
                tile, self.existing_plot_settings(existing_cell, var_id)
            )
        active_filter = (
            and_filter(query_filter, source_filter)
            if query_filter and source_filter
            else (query_filter or source_filter or None)
        )
        base_vis = self.db.distinct_visualization_names_for_variable(
            var_id, extra_filter=active_filter
        )
        plugin_vis_names = supported_plugin_visualizations(meta)
        tile["visualization_options"] = self.merge_visualization_names(
            base_vis, plugin_vis_names
        )
        tile["visualization_name"] = plugin_vis
        tile["selected_visualization"] = plugin_vis
        tile["variable_id"] = var_id
        tile["variable_name"] = label
        tile["plugin_options_schema"] = schema
        tile["plugin_options"] = options
        tile.setdefault("src", "")
        return tile

    def build_grid_cell_for_variable(
        self,
        variable_id: str,
        preferred_vis: str = "",
        source_row: Optional[Dict[str, str]] = None,
        existing_cell: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cell = empty_grid_cell()
        var_id = str(variable_id or "").strip()
        if not var_id:
            return cell
        label = self.variable_label(var_id)
        scalar_settings = self.existing_scalar_field_settings(existing_cell, var_id)

        qf = self.active_query_filter()
        source_fields: Dict[str, str] = {}
        if source_row:
            source_fields = source_fields_from_row(source_row)
            source_filter = source_filter_from_row(source_row)
        elif existing_cell:
            source_fields = {
                "_source_key": str(existing_cell.get("_source_key", "") or ""),
                "source_dataset": str(existing_cell.get("source_dataset", "") or ""),
                "source_collection_id": str(
                    existing_cell.get("source_collection_id", "") or ""
                ),
                "schema_file_group": str(
                    existing_cell.get("schema_file_group", "") or ""
                ),
                "schema_mode": str(existing_cell.get("schema_mode", "") or ""),
                "producer": str(existing_cell.get("producer", "") or ""),
                "casename": str(existing_cell.get("casename", "") or ""),
                "file": str(existing_cell.get("file", "") or ""),
            }
            source_filter = self.source_filter_from_cell(existing_cell)
        else:
            source_filter = self.active_source_filter_for_variable(var_id)
        active_filter = (
            and_filter(qf, source_filter)
            if qf and source_filter
            else (qf or source_filter or None)
        )
        vis_names = self.visualization_names_with_plugins(
            var_id,
            source_filter=source_filter,
            extra_filter=active_filter,
        )
        if existing_cell and not source_row and source_filter and not vis_names:
            fallback_row = self.first_query_source_row_for_variable(
                var_id, preferred_vis
            )
            if fallback_row:
                source_fields = source_fields_from_row(fallback_row)
                source_filter = source_filter_from_row(fallback_row)
                active_filter = (
                    and_filter(qf, source_filter)
                    if qf and source_filter
                    else (qf or source_filter or None)
                )
                vis_names = self.visualization_names_with_plugins(
                    var_id,
                    source_filter=source_filter,
                    extra_filter=active_filter,
                )

        selected_vis = self.choose_visualization_default(vis_names, preferred_vis)
        if selected_vis and is_plugin_visualization(selected_vis):
            return self.build_plugin_grid_cell(
                var_id,
                selected_vis,
                source_row=source_row,
                existing_cell=existing_cell,
            )

        source_label = self.source_name_for_row(source_row or {})
        no_visualization_note = (
            f"No visualization for source {source_label}"
            if source_label
            else "No visualization types for this variable"
        )
        cell.update(
            {
                "variable_id": var_id,
                "variable_name": label,
                "visualization_name": selected_vis,
                "selected_visualization": selected_vis,
                "visualization_options": vis_names,
                "status": "no-visualizations",
                "note": no_visualization_note,
            }
        )
        cell.update({k: v for k, v in source_fields.items() if v})

        if selected_vis:
            movie_query = (
                and_filter(active_filter, {"visualization_name": selected_vis})
                if active_filter
                else {"visualization_name": selected_vis}
            )
            one = self.db.get_first_movie_tiles_for_variable(
                var_id,
                extra_filter=movie_query,
                limit=1,
                limit_frames=MAX_MOVIE_FRAMES,
                fps=MOVIE_FPS,
                scalar_field_options=scalar_settings,
            )
            if one:
                cell.update(one[0] or {})
                cell.update({k: v for k, v in source_fields.items() if v})
                if self.is_scalar_field_cell(cell):
                    cell["scalar_field_settings"] = scalar_settings
            else:
                cell["status"] = "no-frames"
                cell["note"] = f'No movie for "{selected_vis}"'

        if not str(cell.get("_source_key", "") or ""):
            row = self.source_row_for_cell(cell)
            if row:
                cell.update(source_fields_from_row(row))

        cell["variable_id"] = var_id
        cell["variable_name"] = label
        cell["visualization_name"] = selected_vis
        cell["selected_visualization"] = selected_vis
        cell["visualization_options"] = vis_names
        if self.is_scalar_field_cell(cell):
            cell["scalar_field_settings"] = scalar_settings
        self.update_2d_display_title(cell, var_id, label)
        return cell

    def no_visualization_grid_cell(self, variable_id: str, note: str) -> Dict[str, Any]:
        cell = empty_grid_cell()
        cell["variable_id"] = variable_id
        cell["variable_name"] = self.variable_label(variable_id)
        cell["status"] = "no-visualizations"
        cell["note"] = note
        return cell

    def set_generated_scalar_plot_cell(
        self,
        cell_index: int,
        variable_id: str,
        source_fields: Optional[Dict[str, Any]] = None,
        sync_selection: bool = True,
    ) -> bool:
        try:
            idx = int(cell_index)
        except Exception:
            return False
        if not self.is_valid_grid_index(idx):
            return False

        source_fields = dict(source_fields or {})
        source_filter = self.source_fields_to_filter(variable_id, source_fields)
        try:
            tile = self.db.get_or_create_generated_scalar_plot_tile(
                self.campaign_path,
                variable_id,
                source_filter=source_filter or None,
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
            tile.update({k: v for k, v in source_fields.items() if v})
            source_key = str(source_fields.get("_source_key", "") or "")
            self.assign_plot_series_keys(tile, [source_key] if source_key else [])
            tile["plot_settings"] = self.normalize_plot_settings(tile, prior_settings)
            tile["visualization_name"] = str(
                tile.get("visualization_name", "") or GENERATED_SCALAR_PLOT_VIS
            )
            tile["selected_visualization"] = str(
                tile.get("selected_visualization", "") or GENERATED_SCALAR_PLOT_VIS
            )
            tile["visualization_options"] = [GENERATED_SCALAR_PLOT_VIS]
            assign_cell(cells, idx, tile)
            self.state.scalarPlotStatus = ""
        else:
            assign_cell(
                cells,
                idx,
                self.no_visualization_grid_cell(
                    variable_id,
                    "Could not generate scalar plot for this source",
                ),
            )

        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = idx
        if sync_selection:
            self.state.selectedVar = variable_id
            self.state.draggedVar = variable_id
        return bool(tile)

    def maybe_handle_generated_scalar_plot(
        self,
        variable_id: str,
        cell_index: int,
        source_row: Optional[Dict[str, str]] = None,
        sync_selection: bool = True,
    ) -> bool:
        source_filter = self.source_filter_for_assignment(
            variable_id, source_row=source_row
        )
        qf = self.active_query_filter()
        active_filter = (
            and_filter(qf, source_filter)
            if qf and source_filter
            else (qf or source_filter or None)
        )
        if self.visualization_names_with_plugins(
            variable_id, source_filter=source_filter, extra_filter=active_filter
        ):
            return False

        candidate = self.db.scalar_plot_candidate(
            variable_id,
            source_filter=source_filter or None,
            extra_filter=qf,
        )
        if not candidate:
            return False

        source_fields = self.source_fields_for_assignment(
            variable_id, source_row=source_row, candidate=candidate
        )
        source_label = str(candidate.get("source_label", "") or "").strip()
        label = self.variable_label(variable_id)
        policy = self.normalize_scalar_plot_policy()
        self.state.activeGridCell = cell_index
        self.set_details_provenance_context(True)
        self.state.selectedVar = variable_id
        self.state.draggedVar = variable_id

        if policy == "never":
            cells = self.normalize_grid_cells(self.state.gridCells)
            note = "No saved visualization; scalar plot generation is disabled"
            assign_cell(
                cells, cell_index, self.no_visualization_grid_cell(variable_id, note)
            )
            self.state.gridCells = self.normalize_grid_cells(cells)
            self.state.scalarPlotStatus = note
            return True

        if policy == "always":
            self.set_generated_scalar_plot_cell(
                cell_index,
                variable_id,
                source_fields=source_fields,
                sync_selection=sync_selection,
            )
            return True

        self.state.pendingScalarPlotVariableId = variable_id
        self.state.pendingScalarPlotCellIndex = cell_index
        self.state.pendingScalarPlotSourceFields = source_fields
        self.state.pendingScalarPlotSyncSelection = bool(sync_selection)
        self.state.scalarPlotDialogMessage = (
            f'"{label}" has no saved visualization'
            + (f" for {source_label}" if source_label else "")
            + ". Generate a scalar plot from the raw campaign data?"
        )
        self.state.scalarPlotAlwaysForSession = False
        self.state.showScalarPlotDialog = True
        self.state.scalarPlotStatus = ""
        return True

    def refresh_grid_cells(self):
        cells = self.normalize_grid_cells(self.state.gridCells)
        updated: List[Dict[str, Any]] = []

        for c in cells:
            var_id = str(
                c.get("variable_id", "") or c.get("variable_name", "") or ""
            ).strip()
            if not var_id:
                updated.append(empty_grid_cell_like(c))
                continue

            if is_plugin_visualization(
                str(
                    c.get("visualization_name", "")
                    or c.get("selected_visualization", "")
                    or ""
                )
            ):
                selected_vis = str(
                    c.get("selected_visualization", "")
                    or c.get("visualization_name", "")
                    or ""
                )
                try:
                    if str(c.get("plugin_scope", "") or "") == "source":
                        tile = self.build_source_plugin_grid_cell(
                            plugin_id_from_visualization(selected_vis),
                            c,
                            plugin_options=dict(
                                c.get("plugin_options", {}) or {}
                            ),
                        )
                    else:
                        tile = self.build_plugin_grid_cell(
                            var_id,
                            selected_vis,
                            existing_cell=c,
                            plugin_options=dict(
                                c.get("plugin_options", {}) or {}
                            ),
                        )
                    updated.append(preserve_grid_geometry(tile, c))
                except Exception as e:
                    err_cell = self.no_visualization_grid_cell(
                        var_id, f"{type(e).__name__}: {e}"
                    )
                    updated.append(preserve_grid_geometry(err_cell, c))
                continue

            if str(c.get("visualization_name", "") or "") == GENERATED_SCALAR_PLOT_VIS:
                source_keys = self.source_keys_from_cell(c)
                source_fields_list = self.source_fields_list_from_cell(c)
                try:
                    if len(source_fields_list) > 1:
                        valid_source_fields_list: List[Dict[str, Any]] = []
                        valid_source_keys: List[str] = []
                        for fields in source_fields_list:
                            source_filter = self.source_fields_to_filter(var_id, fields)
                            if self.db.scalar_plot_candidate(
                                var_id,
                                source_filter=source_filter or None,
                                extra_filter=self.active_query_filter(),
                            ):
                                valid_source_fields_list.append(fields)
                                source_key = str(fields.get("_source_key", "") or "")
                                if source_key:
                                    valid_source_keys.append(source_key)
                        source_fields_list = valid_source_fields_list
                        source_keys = valid_source_keys
                        if not source_fields_list:
                            raise ValueError(
                                "Could not regenerate scalar plot for selected sources"
                            )
                        source_filters = [
                            self.source_fields_to_filter(var_id, fields)
                            for fields in source_fields_list
                        ]
                        tile = self.db.get_generated_scalar_plot_tile_for_sources(
                            self.campaign_path,
                            var_id,
                            source_filters=source_filters,
                            extra_filter=self.active_query_filter(),
                        )
                        if not tile:
                            raise ValueError(
                                "Could not regenerate scalar plot for selected sources"
                            )
                        first_fields = source_fields_list[0]
                        tile.update(
                            {
                                k: v
                                for k, v in first_fields.items()
                                if v and k != "_source_key"
                            }
                        )
                        tile["_source_key"] = (
                            source_keys[0]
                            if source_keys
                            else str(first_fields.get("_source_key", "") or "")
                        )
                        tile["_source_keys"] = source_keys
                        tile["_source_fields_list"] = source_fields_list
                    else:
                        source_fields = (
                            source_fields_list[0] if source_fields_list else {}
                        )
                        tile = self.db.get_or_create_generated_scalar_plot_tile(
                            self.campaign_path,
                            var_id,
                            source_filter=self.source_fields_to_filter(
                                var_id, source_fields
                            )
                            or None,
                            extra_filter=self.active_query_filter(),
                        )
                        if not tile:
                            raise ValueError(
                                "Could not regenerate scalar plot for source"
                            )
                        tile.update({k: v for k, v in source_fields.items() if v})
                    tile["visualization_name"] = GENERATED_SCALAR_PLOT_VIS
                    tile["selected_visualization"] = GENERATED_SCALAR_PLOT_VIS
                    tile["visualization_options"] = [GENERATED_SCALAR_PLOT_VIS]
                    self.assign_plot_series_keys(tile, source_keys)
                    tile["plot_settings"] = self.normalize_plot_settings(
                        tile, self.existing_plot_settings(c, var_id)
                    )
                    updated.append(preserve_grid_geometry(tile, c))
                except Exception as e:
                    fallback_row = self.first_query_source_row_for_variable(
                        var_id, GENERATED_SCALAR_PLOT_VIS
                    )
                    try:
                        if not fallback_row:
                            raise e
                        source_fields = source_fields_from_row(fallback_row)
                        source_key = str(source_fields.get("_source_key", "") or "")
                        tile = self.db.get_or_create_generated_scalar_plot_tile(
                            self.campaign_path,
                            var_id,
                            source_filter=self.source_fields_to_filter(
                                var_id, source_fields
                            )
                            or None,
                            extra_filter=self.active_query_filter(),
                        )
                        if not tile:
                            raise e
                        tile.update({k: v for k, v in source_fields.items() if v})
                        tile["visualization_name"] = GENERATED_SCALAR_PLOT_VIS
                        tile["selected_visualization"] = GENERATED_SCALAR_PLOT_VIS
                        tile["visualization_options"] = [GENERATED_SCALAR_PLOT_VIS]
                        tile["_source_keys"] = [source_key] if source_key else []
                        tile["_source_fields_list"] = (
                            [source_fields] if source_fields else []
                        )
                        self.assign_plot_series_keys(
                            tile, [source_key] if source_key else []
                        )
                        tile["plot_settings"] = self.normalize_plot_settings(
                            tile, self.existing_plot_settings(c, var_id)
                        )
                        updated.append(preserve_grid_geometry(tile, c))
                    except Exception as fallback_e:
                        err_cell = self.no_visualization_grid_cell(
                            var_id, f"{type(fallback_e).__name__}: {fallback_e}"
                        )
                        updated.append(preserve_grid_geometry(err_cell, c))
                continue

            preferred_vis = str(c.get("selected_visualization", "") or "")
            try:
                updated.append(
                    preserve_grid_geometry(
                        self.build_grid_cell_for_variable(
                            var_id, preferred_vis=preferred_vis, existing_cell=c
                        ),
                        c,
                    )
                )
            except Exception as e:
                err_cell = empty_grid_cell()
                err_cell["variable_id"] = var_id
                err_cell["variable_name"] = self.variable_label(var_id)
                err_cell["status"] = "error"
                err_cell["note"] = f"{type(e).__name__}: {e}"
                updated.append(preserve_grid_geometry(err_cell, c))

        self.state.gridCells = self.normalize_grid_cells(updated)

        try:
            idx = int(self.state.activeGridCell)
        except Exception:
            idx = -1
        self.state.activeGridCell = idx if self.is_valid_grid_index(idx) else -1

    def cancel_scalar_plot_generation(self, **_):
        self.clear_pending_scalar_plot()

    def confirm_scalar_plot_generation(self, **_):
        var_id = str(self.state.pendingScalarPlotVariableId or "").strip()
        try:
            idx = int(self.state.pendingScalarPlotCellIndex)
        except Exception:
            idx = -1
        source_fields = dict(self.state.pendingScalarPlotSourceFields or {})
        sync_selection = bool(self.state.pendingScalarPlotSyncSelection)

        if bool(self.state.scalarPlotAlwaysForSession):
            self.state.scalarPlotPolicy = "always"

        self.clear_pending_scalar_plot()
        if not var_id or not self.is_valid_grid_index(idx):
            return

        self.set_generated_scalar_plot_cell(
            idx,
            var_id,
            source_fields=source_fields,
            sync_selection=sync_selection,
        )

    def cancel_plot_settings(self, **_):
        self.state.showPlotSettingsModal = False
        self.state.plotSettingsCellIndex = -1
        self.state.plotSettingsStatus = ""
        self.state.plotSettingsCanPluginOptions = False

    def open_plot_settings_plugin_options(self, **_):
        try:
            idx = int(self.state.plotSettingsCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.state.plotSettingsStatus = "No plot cell selected."
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        )
        if not is_plugin_visualization(selected_vis):
            self.state.plotSettingsStatus = (
                "Selected cell is not a plugin visualization."
            )
            return

        self.state.showPlotSettingsModal = False
        self.load_plugin_options_dialog(idx)

    def cancel_plugin_options(self, **_):
        self.state.showPluginOptionsModal = False
        self.state.pluginOptionsCellIndex = -1
        self.state.pluginOptionsStatus = ""
        self.state.pluginOptionsRows = []

    def reset_plugin_options(self, **_):
        try:
            idx = int(self.state.pluginOptionsCellIndex)
        except Exception:
            idx = -1
        if self.is_valid_grid_index(idx):
            self.load_plugin_options_dialog(idx, reset=True)

    def update_plugin_option_value(self, key: str, value: Any, **_):
        target_key = str(key or "").strip()
        if not target_key:
            return
        rows = []
        for raw_row in self.state.pluginOptionsRows or []:
            row = dict(raw_row or {})
            if str(row.get("key", "") or "") == target_key:
                if str(row.get("type", "") or "") == "bool":
                    row["value"] = bool(value)
                else:
                    row["value"] = str(value or "")
            rows.append(row)
        self.state.pluginOptionsRows = rows

    def apply_plugin_options(self, **_):
        try:
            idx = int(self.state.pluginOptionsCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.state.pluginOptionsStatus = "No plugin cell selected."
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        )
        if not is_plugin_visualization(selected_vis):
            self.state.pluginOptionsStatus = (
                "Selected cell is not a plugin visualization."
            )
            return

        var_id = str(
            cell.get("variable_id", "") or cell.get("variable_name", "") or ""
        ).strip()
        if not var_id:
            self.state.pluginOptionsStatus = "Selected cell has no variable."
            return

        options = self.plugin_options_from_rows(
            list(self.state.pluginOptionsRows or [])
        )
        try:
            plugin_id = plugin_id_from_visualization(selected_vis)
            if plugin_scope(plugin_id) == "source":
                new_cell = self.build_source_plugin_grid_cell(
                    plugin_id, cell, plugin_options=options
                )
            else:
                new_cell = self.build_plugin_grid_cell(
                    var_id,
                    selected_vis,
                    existing_cell=cell,
                    plugin_options=options,
                )
            assign_cell(cells, idx, new_cell)
        except Exception as e:
            self.state.pluginOptionsStatus = f"{type(e).__name__}: {e}"
            return

        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = idx
        self.state.pluginOptionsStatus = ""
        self.state.showPluginOptionsModal = False

    def cancel_scalar_field_settings(self, **_):
        self.state.showScalarFieldSettingsModal = False
        self.state.scalarFieldSettingsCellIndex = -1
        self.state.scalarFieldSettingsStatus = ""
        self.state.scalarFieldSettingsStatusIsError = False

    def reset_scalar_field_settings(self, **_):
        try:
            idx = int(self.state.scalarFieldSettingsCellIndex)
        except Exception:
            idx = -1
        if self.is_valid_grid_index(idx):
            self.load_scalar_field_settings_dialog(idx, reset=True)

    def toggle_scalar_field_background(self, **_):
        background = self.scalar_field_background(
            self.state.scalarFieldSettingsBackground
        )
        self.state.scalarFieldSettingsBackground = (
            "black" if background == "white" else "white"
        )

    def update_scalar_field_contour_color(self, color: Any, **_):
        self.state.scalarFieldSettingsContourColor = self.clean_plot_color(
            color,
            str(
                self.state.scalarFieldSettingsContourColor
                or "#ffffff"
            ),
        )

    def apply_scalar_field_settings(self, **_):
        try:
            idx = int(self.state.scalarFieldSettingsCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.state.scalarFieldSettingsStatus = "No scalar-field cell selected."
            self.state.scalarFieldSettingsStatusIsError = True
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        if not self.is_scalar_field_cell(cell):
            self.state.scalarFieldSettingsStatus = (
                "Selected cell is not a scalar-field visualization."
            )
            self.state.scalarFieldSettingsStatusIsError = True
            return

        colormap = self.scalar_colormap(self.state.scalarFieldSettingsColormap)
        show_heatmap = bool(self.state.scalarFieldSettingsShowHeatmap)
        show_contours = bool(self.state.scalarFieldSettingsShowContours)
        if not show_heatmap and not show_contours:
            self.state.scalarFieldSettingsStatus = (
                "Select Heatmap, Contour, or both."
            )
            self.state.scalarFieldSettingsStatusIsError = True
            return
        render_mode = (
            "both"
            if show_heatmap and show_contours
            else ("colormap" if show_heatmap else "contours")
        )
        background = self.scalar_field_background(
            self.state.scalarFieldSettingsBackground
        )
        range_auto = bool(self.state.scalarFieldSettingsRangeAuto)
        show_colorbar = bool(self.state.scalarFieldSettingsShowColorbar)
        show_axes = bool(self.state.scalarFieldSettingsShowAxes)
        min_value = self.finite_float(self.state.scalarFieldSettingsMin)
        max_value = self.finite_float(self.state.scalarFieldSettingsMax)
        if show_heatmap and not range_auto:
            if min_value is None or max_value is None:
                self.state.scalarFieldSettingsStatus = (
                    "Manual range requires min and max values."
                )
                self.state.scalarFieldSettingsStatusIsError = True
                return
            if min_value >= max_value:
                self.state.scalarFieldSettingsStatus = (
                    "Manual range must have min < max."
                )
                self.state.scalarFieldSettingsStatusIsError = True
                return

        contour_level_mode = self.scalar_field_contour_level_mode(
            self.state.scalarFieldSettingsContourLevelMode
        )
        existing_contours = dict(
            self.normalize_scalar_field_settings(
                cell.get("scalar_field_settings", {})
            ).get("contours", {})
        )
        contour_values_text = str(
            self.state.scalarFieldSettingsContourValues or ""
        ).strip()
        try:
            contour_values = (
                self.parse_scalar_field_contour_values(contour_values_text)
                if contour_values_text
                else list(existing_contours.get("values", []) or [])
            )
        except ValueError as e:
            if render_mode != "colormap" and contour_level_mode == "values":
                self.state.scalarFieldSettingsStatus = str(e)
                self.state.scalarFieldSettingsStatusIsError = True
                return
            contour_values = list(existing_contours.get("values", []) or [])

        contour_min = self.finite_float(self.state.scalarFieldSettingsContourMin)
        contour_max = self.finite_float(self.state.scalarFieldSettingsContourMax)
        contour_color = self.clean_plot_color(
            self.state.scalarFieldSettingsContourColor,
            "#ffffff",
        )
        try:
            contour_count = int(self.state.scalarFieldSettingsContourCount)
        except (TypeError, ValueError):
            contour_count = 0

        contours_active = render_mode != "colormap"
        if contours_active and contour_level_mode == "values" and not contour_values:
            self.state.scalarFieldSettingsStatus = (
                "Enter at least one contour value."
            )
            self.state.scalarFieldSettingsStatusIsError = True
            return
        if contours_active and contour_level_mode == "range":
            if contour_min is None or contour_max is None:
                self.state.scalarFieldSettingsStatus = (
                    "Contour range requires min and max values."
                )
                self.state.scalarFieldSettingsStatusIsError = True
                return
            if contour_min >= contour_max:
                self.state.scalarFieldSettingsStatus = (
                    "Contour range must have min < max."
                )
                self.state.scalarFieldSettingsStatusIsError = True
                return
            if not 2 <= contour_count <= SCALAR_FIELD_MAX_CONTOUR_LEVELS:
                self.state.scalarFieldSettingsStatus = (
                    "Contour count must be between 2 and "
                    f"{SCALAR_FIELD_MAX_CONTOUR_LEVELS}."
                )
                self.state.scalarFieldSettingsStatusIsError = True
                return
        elif not 2 <= contour_count <= SCALAR_FIELD_MAX_CONTOUR_LEVELS:
            contour_count = int(
                existing_contours.get(
                    "count", SCALAR_FIELD_DEFAULT_CONTOUR_COUNT
                )
            )

        settings = self.normalize_scalar_field_settings(
            {
                "render_mode": render_mode,
                "colormap": colormap,
                "background": background,
                "range_auto": range_auto,
                "min": None if range_auto else min_value,
                "max": None if range_auto else max_value,
                "show_colorbar": show_colorbar,
                "show_axes": show_axes,
                "contours": {
                    "level_mode": contour_level_mode,
                    "values": contour_values,
                    "min": contour_min,
                    "max": contour_max,
                    "count": contour_count,
                    "color": contour_color,
                },
            }
        )
        try:
            self.update_scalar_field_cell_settings(idx, settings)
        except Exception as e:
            self.state.scalarFieldSettingsStatus = f"{type(e).__name__}: {e}"
            self.state.scalarFieldSettingsStatusIsError = True
            return

        self.state.scalarFieldSettingsStatus = "Applied."
        self.state.scalarFieldSettingsStatusIsError = False

    def reset_plot_settings(self, **_):
        try:
            idx = int(self.state.plotSettingsCellIndex)
        except Exception:
            idx = -1
        if self.is_valid_grid_index(idx):
            self.load_plot_settings_dialog(idx, reset=True)

    def update_plot_background_color(self, color: str, **_):
        self.state.plotSettingsBackgroundColor = self.clean_plot_color(
            color,
            str(self.state.plotSettingsBackgroundColor or "#ffffff"),
        )

    def update_plot_grid_color(self, color: str, **_):
        self.state.plotSettingsGridColor = self.clean_plot_color(
            color,
            str(self.state.plotSettingsGridColor or "#e8e8e8"),
        )

    def update_plot_cursor_color(self, color: str, **_):
        self.state.plotSettingsCursorColor = self.clean_plot_color(
            color,
            str(self.state.plotSettingsCursorColor or "#111111"),
        )

    def update_plot_series_color(self, key: str, color: str, **_):
        target_key = str(key or "")
        rows = []
        for raw_row in self.state.plotSettingsSeriesRows or []:
            row = dict(raw_row or {})
            if str(row.get("key", "") or "") == target_key:
                row["color"] = self.clean_plot_color(
                    color, str(row.get("color", "") or "#1565c0")
                )
            rows.append(row)
        self.state.plotSettingsSeriesRows = rows

    def update_plot_series_line_style(self, key: str, line_style: str, **_):
        target_key = str(key or "")
        rows = []
        for raw_row in self.state.plotSettingsSeriesRows or []:
            row = dict(raw_row or {})
            if str(row.get("key", "") or "") == target_key:
                row["line_style"] = self.clean_line_style(line_style)
            rows.append(row)
        self.state.plotSettingsSeriesRows = rows

    def apply_plot_settings(self, **_):
        try:
            idx = int(self.state.plotSettingsCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.state.plotSettingsStatus = "No plot cell selected."
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        if str(cell.get("media_type", "") or "") != "plot1d":
            self.state.plotSettingsStatus = "Selected cell is not a 1D plot."
            return

        x_auto = bool(self.state.plotSettingsXAuto)
        y_auto = bool(self.state.plotSettingsYAuto)
        x_min = self.finite_float(self.state.plotSettingsXMin)
        x_max = self.finite_float(self.state.plotSettingsXMax)
        y_min = self.finite_float(self.state.plotSettingsYMin)
        y_max = self.finite_float(self.state.plotSettingsYMax)
        x_scale = str(self.state.plotSettingsXScale or "linear").strip().lower()
        y_scale = str(self.state.plotSettingsYScale or "linear").strip().lower()
        if x_scale not in {"linear", "log"}:
            x_scale = "linear"
        if y_scale not in {"linear", "log"}:
            y_scale = "linear"

        if not x_auto:
            if x_min is None or x_max is None:
                self.state.plotSettingsStatus = (
                    "Manual X range requires min and max values."
                )
                return
            if x_min >= x_max:
                self.state.plotSettingsStatus = "Manual X range must have min < max."
                return
        if not y_auto:
            if y_min is None or y_max is None:
                self.state.plotSettingsStatus = (
                    "Manual Y range requires min and max values."
                )
                return
            if y_min >= y_max:
                self.state.plotSettingsStatus = "Manual Y range must have min < max."
                return

        if x_scale == "log":
            if not self.axis_has_positive_data(cell, "x"):
                self.state.plotSettingsStatus = (
                    "X log scale requires positive X values."
                )
                return
            if not x_auto and (
                x_min is None or x_max is None or x_min <= 0 or x_max <= 0
            ):
                self.state.plotSettingsStatus = "Manual X log range must be positive."
                return
        if y_scale == "log":
            if not self.axis_has_positive_data(cell, "y"):
                self.state.plotSettingsStatus = (
                    "Y log scale requires positive Y values."
                )
                return
            if not y_auto and (
                y_min is None or y_max is None or y_min <= 0 or y_max <= 0
            ):
                self.state.plotSettingsStatus = "Manual Y log range must be positive."
                return

        line_width = self.finite_float(self.state.plotSettingsLineWidth)
        if line_width is None:
            self.state.plotSettingsStatus = "Line width must be a number."
            return
        line_width = max(0.5, min(8.0, line_width))
        background_color = self.clean_plot_color(
            self.state.plotSettingsBackgroundColor, "#ffffff"
        )
        grid_color = self.clean_plot_color(self.state.plotSettingsGridColor, "#e8e8e8")
        cursor_color = self.clean_plot_color(
            self.state.plotSettingsCursorColor, "#111111"
        )

        series_colors: Dict[str, str] = {}
        series_styles: Dict[str, Dict[str, str]] = {}
        current_settings = self.normalize_plot_settings(
            cell, cell.get("plot_settings", {})
        )
        current_colors = current_settings.get("series_colors", {})
        current_colors = current_colors if isinstance(current_colors, dict) else {}
        current_styles = current_settings.get("series_styles", {})
        current_styles = current_styles if isinstance(current_styles, dict) else {}
        for row in self.state.plotSettingsSeriesRows or []:
            item = dict(row or {})
            key = str(item.get("key", "") or "")
            if not key:
                continue
            current_style = current_styles.get(key, {})
            current_style = current_style if isinstance(current_style, dict) else {}
            color = self.clean_plot_color(
                item.get("color", ""),
                str(
                    current_style.get("color", "")
                    or current_colors.get(key, "")
                    or "#1565c0"
                ),
            )
            line_style = self.clean_line_style(
                item.get("line_style", current_style.get("line_style", "solid"))
            )
            series_colors[key] = color
            series_styles[key] = {
                "color": color,
                "line_style": line_style,
            }

        cell["plot_settings"] = self.normalize_plot_settings(
            cell,
            {
                "x_auto": x_auto,
                "x_min": None if x_auto else x_min,
                "x_max": None if x_auto else x_max,
                "x_scale": x_scale,
                "y_auto": y_auto,
                "y_min": None if y_auto else y_min,
                "y_max": None if y_auto else y_max,
                "y_scale": y_scale,
                "series_colors": series_colors,
                "series_styles": series_styles,
                "line_width": line_width,
                "show_grid": bool(self.state.plotSettingsShowGrid),
                "show_cursor": bool(self.state.plotSettingsShowCursor),
                "background_color": background_color,
                "grid_color": grid_color,
                "cursor_color": cursor_color,
            },
        )
        cells[idx] = cell
        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = idx
        self.state.plotSettingsStatus = ""
        self.state.showPlotSettingsModal = False
