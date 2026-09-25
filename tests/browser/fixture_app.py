"""Deterministic Trame application used by the browser tests."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from pulsar import module as pulsar_module  # noqa: E402
from pulsar.controllers.catalog import (  # noqa: E402
    _apply_provenance_expansion,
    _apply_provenance_graph_expansion,
    _filter_variable_groups,
    _provenance_detail_node_ids,
    _provenance_graph_detail_node_ids,
)
from pulsar.history import WorkspaceMutationCoordinator  # noqa: E402
from pulsar.models import canvas_layout  # noqa: E402
from pulsar.models.grid import (  # noqa: E402
    cell_has_content,
    empty_grid_cell,
    normalize_grid_cells,
)
from pulsar.models.workspace_layout import (  # noqa: E402
    active_pane_and_tab,
    add_workspace_tab as add_workspace_tab_model,
    apply_grid_snapshot,
    close_workspace_pane as close_workspace_pane_model,
    close_workspace_tab as close_workspace_tab_model,
    grid_snapshot,
    initial_workspace_layout,
    move_workspace_grid_cell as move_workspace_grid_cell_model,
    move_workspace_tab as move_workspace_tab_model,
    move_workspace_tab_to_pane as move_workspace_tab_to_pane_model,
    normalized_workspace_root,
    normalized_tab_title,
    pane_and_tab,
    reorder_workspace_tab as reorder_workspace_tab_model,
    resize_workspace_split as resize_workspace_split_model,
    split_workspace as split_workspace_model,
    split_workspace_tab as split_workspace_tab_model,
    workspace_geometry,
)
from pulsar.state import init_state  # noqa: E402
from trame.app import get_server  # noqa: E402
from ui import build_ui  # noqa: E402


class FixtureDb:
    ok = True
    last_error = ""


def _image_source(color):
    return (
        "data:image/svg+xml;charset=utf-8,"
        f"%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64'%3E"
        f"%3Crect width='64' height='64' fill='{color.replace('#', '%23')}'/%3E"
        "%3C/svg%3E"
    )


def _plot_cell(mode):
    physical = mode in {"physical", "mixed"}
    x_values = [0.0, 0.25, 1.0] if physical else list(range(80))
    y_values = (
        [10.0, 20.0, 30.0]
        if physical
        else [10.0 + (20.0 * index / 79.0) for index in range(80)]
    )
    cell = empty_grid_cell()
    cell.update(
        {
            "variable_id": "internal_energy",
            "variable_name": "internal_energy",
            "display_title": "internal_energy",
            "media_type": "plot1d",
            "status": "ok",
            "plot": {
                "x_label": "time" if physical else "step",
                "y_label": "internal_energy",
                "x_min": x_values[0],
                "x_max": x_values[-1],
                "y_min": 8.0,
                "y_max": 32.0,
                "data_x_min": x_values[0],
                "data_x_max": x_values[-1],
                "data_y_min": 10.0,
                "data_y_max": 30.0,
                "series": [
                    {
                        "x": x_values,
                        "y": y_values,
                        "source_label": "fixture",
                        "source_key": "fixture",
                        "color": "#1565c0",
                    }
                ],
            },
        }
    )
    return cell


def _image_sequence_cell(mode):
    physical = mode == "physical"
    mixed = mode == "mixed"
    frame_count = 3 if physical or mixed else 35
    colors = ("#c62828", "#2e7d32", "#1565c0")
    sources = [
        _image_source(colors[index % len(colors)]) for index in range(frame_count)
    ]
    cell = empty_grid_cell()
    cell.update(
        {
            "variable_id": "current_z",
            "variable_name": "current_z",
            "display_title": "current_z",
            "media_type": "image_sequence",
            "status": "ok",
            "src": sources[0],
            "fps": 2,
            "frame_count": len(sources),
            "frame_indices": list(range(frame_count)),
            "frame_sources": sources,
            "time_values": (
                [0.0, 0.25, 1.0]
                if physical or mixed
                else list(range(frame_count))
            ),
            "time_mode": "physical_time" if physical else "timestep",
        }
    )
    return cell


def _multi_axis_cells():
    shot_key = "lasernet:laser_runs:shot"
    trace_time_key = "lasernet:laser_runs:trace_time"
    shot_values = [15.0, 16.0, 17.0]

    scalar = _plot_cell("physical")
    scalar.update(
        {
            "variable_id": "laser_energy",
            "variable_name": "laser_energy",
            "display_title": "laser_energy",
            "plot_axis_key": shot_key,
            "selection_axis": {
                "id": "shot",
                "key": shot_key,
                "kind": "shot",
                "label": "Shot number",
                "values": shot_values,
                "index": 0,
                "value": shot_values[0],
            },
        }
    )
    scalar["plot"].update(
        {
            "x_label": "Shot number",
            "x_axis_key": shot_key,
            "series": [
                {
                    "x": shot_values,
                    "y": [2.5, 3.0, 3.75],
                    "source_label": "fixture",
                    "source_key": "fixture",
                    "color": "#1565c0",
                }
            ],
        }
    )

    waveform = _plot_cell("physical")
    waveform.update(
        {
            "variable_id": "photodiode_signal",
            "variable_name": "photodiode_signal",
            "display_title": "photodiode_signal",
            "visualization_name": "generated_timeseries",
            "selected_visualization": "generated_timeseries",
            "plot_axis_key": trace_time_key,
            "selection_axis": {
                "id": "shot",
                "key": shot_key,
                "kind": "shot",
                "label": "Shot number",
                "values": shot_values,
                "index": 0,
                "value": shot_values[0],
            },
        }
    )
    waveform["plot"].update(
        {
            "x_label": "Time within shot (s)",
            "x_axis_key": trace_time_key,
            "series": [
                {
                    "x": [0.0, 0.5, 1.0],
                    "y": [10.0, 12.0, 11.0],
                    "source_label": "fixture",
                    "source_key": "fixture",
                    "color": "#7b1fa2",
                }
            ],
        }
    )

    incompatible = _plot_cell("physical")
    incompatible.update(
        {
            "variable_id": "pulse_profile",
            "variable_name": "pulse_profile",
            "display_title": "pulse_profile",
            "plot_axis_key": trace_time_key,
            "selection_axis": {
                "id": "trace_time",
                "key": trace_time_key,
                "kind": "within_shot_time",
                "label": "Time within shot",
                "unit": "s",
                "values": [0.0, 0.5, 1.0],
                "index": 0,
                "value": 0.0,
            },
        }
    )
    incompatible["plot"].update(
        {
            "x_label": "Time within shot (s)",
            "x_axis_key": trace_time_key,
        }
    )
    return [scalar, waveform, incompatible]


def _scalar_field_cell(background):
    is_white = background == "white"
    background_color = "#ffffff" if is_white else "#000000"
    foreground_color = "#111111" if is_white else "#ffffff"
    cell = empty_grid_cell()
    cell.update(
        {
            "variable_id": f"field_{background}",
            "variable_name": f"field_{background}",
            "display_title": f"field_{background}",
            "variable_type": "scalarField",
            "payload_type": "SCALAR_FIELD",
            "visualization_item_type": "SCALAR_FIELD",
            "media_type": "image",
            "status": "ok",
            "src": _image_source(background_color),
            "scalar_field_settings": {
                "background": background,
                "background_color": background_color,
                "foreground_color": foreground_color,
                "show_axes": True,
                "show_colorbar": True,
                "colorbar_gradient": "linear-gradient(to top, #440154, #fde725)",
            },
            "scalar_field_axes": {
                "x": {
                    "label": "R",
                    "start": 0.2,
                    "end": 4.6,
                    "ticks": [
                        {"position": 0, "value": 0.2, "label": "0.2"},
                        {"position": 50, "value": 2.4, "label": "2.4"},
                        {"position": 100, "value": 4.6, "label": "4.6"},
                    ],
                },
                "y": {
                    "label": "Z",
                    "start": -2.5,
                    "end": 2.5,
                    "ticks": [
                        {"position": 0, "value": -2.5, "label": "-2.5"},
                        {"position": 50, "value": 0.0, "label": "0"},
                        {"position": 100, "value": 2.5, "label": "2.5"},
                    ],
                },
            },
            "scalar_field_colorbar_min": "-1",
            "scalar_field_colorbar_max": "1",
        }
    )
    return cell


def build_fixture_server(mode):
    server = get_server(f"pulsar-browser-{mode}", client_type="vue3")
    server.enable_module(pulsar_module)
    init_state(server.state, FixtureDb())

    state = server.state
    state.variableGroups = [
        {
            "name": "0D",
            "variables": [
                {
                    "id": "internal_energy",
                    "name": "internal_energy",
                    "label": "internal_energy",
                    "path": "fixture/scalars.bp/internal_energy",
                }
            ],
        },
        {
            "name": "2D",
            "variables": [
                {
                    "id": "current_z",
                    "name": "current_z",
                    "label": "current_z",
                    "path": "fixture/images/current_z",
                }
            ],
        },
    ]
    state.filteredVariableGroups = []
    state.variableNames = ["internal_energy", "current_z"]
    state.variableLabelsById = {
        "internal_energy": "internal_energy",
        "current_z": "current_z",
    }
    state.detailsSelectedVar = "internal_energy"
    state.detailsSelectedVarId = "internal_energy"
    state.detailsNumSources = 2
    state.sourceRowsAll = [
        {
            "_key": "source-128",
            "variable_id": "internal_energy",
            "source_dataset": "run-128/output.bp",
            "sourceName": "run-128/output.bp",
            "min": "1",
            "max": "9",
            "min_value": 1.0,
            "max_value": 9.0,
        },
        {
            "_key": "source-64",
            "variable_id": "internal_energy",
            "source_dataset": "run-64/output.bp",
            "sourceName": "run-64/output.bp",
            "min": "2",
            "max": "4",
            "min_value": 2.0,
            "max_value": 4.0,
        },
    ]
    state.sourceRows = list(state.sourceRowsAll)
    state.selectedSourceKeys = ["source-128"]
    state.selectedSourceLabel = "run-128/output.bp"
    state.detailsProvenanceKind = "visualization"
    state.detailsProvenanceChain = (
        "velocity_streamlines --> visualization: streamlines --> vx + vy + pressure --> hll_128/output.bp"
    )
    state.detailsProvenanceCompact = (
        "velocity_streamlines = streamlines(vx + vy + pressure) : hll_128/output.bp"
    )
    state.detailsProvenanceExpanded = {}
    provenance_nodes = [
        {
            "id": "visualization",
            "kind": "visualization",
            "label": "velocity_streamlines",
            "display_label": "Velocity streamlines",
            "secondary_label": "velocity_streamlines",
            "shape": "box",
            "details": [
                {"label": "Visualization", "value": "velocity_streamlines"},
                {"label": "Kind", "value": "streamlines"},
            ],
        },
        {
            "id": "activity",
            "kind": "activity",
            "label": "visualization: streamlines",
            "display_label": "Streamlines",
            "secondary_label": "visualization: streamlines",
            "shape": "box",
            "details": [
                {"label": "Kind", "value": "visualization"},
                {"label": "Operation", "value": "streamlines"},
                {
                    "label": "Inputs",
                    "kind": "input_table",
                    "value": "vx, vy, pressure",
                    "rows": [
                        {"variable": "vx", "role": "streamline-x"},
                        {"variable": "vy", "role": "streamline-y"},
                        {"variable": "pressure", "role": "color-by"},
                    ],
                },
            ],
        },
        {
            "id": "inputs",
            "kind": "variables",
            "label": "Inputs",
            "shape": "group",
            "items": [
                {
                    "id": "input-0",
                    "kind": "variable",
                    "label": "vx",
                    "shape": "box",
                    "details": [
                        {"label": "Variable", "value": "vx"},
                    ],
                },
                {
                    "id": "input-1",
                    "kind": "variable",
                    "label": "vy",
                    "shape": "box",
                    "details": [
                        {"label": "Variable", "value": "vy"},
                    ],
                },
                {
                    "id": "input-2",
                    "kind": "variable",
                    "label": "pressure",
                    "shape": "box",
                    "details": [
                        {"label": "Variable", "value": "pressure"},
                    ],
                },
            ],
            "details": [
                {
                    "label": "Inputs",
                    "value": (
                        "vx (hll_128/output.bp), vy (hll_128/output.bp), "
                        "pressure (hll_128/output.bp)"
                    ),
                },
            ],
        },
        {
            "id": "source",
            "kind": "source",
            "label": "hll_128/output.bp",
            "shape": "cylinder",
            "details": [
                {"label": "Dataset", "value": "hll_128/output.bp"},
            ],
        },
    ]
    state.detailsProvenanceNodes = _apply_provenance_expansion(
        provenance_nodes,
        state.detailsProvenanceExpanded,
    )
    plan_node = {
        "id": "visualization-activity-plan",
        "kind": "plan",
        "label": "MHD visualization workflow",
        "shape": "box",
        "details": [
            {"label": "Workflow", "value": "render_visualizations"},
            {
                "label": "Implementation",
                "value": "plans/render_adios_visualizations_to_campaign.py",
            },
        ],
    }
    agent_node = {
        "id": "visualization-activity-agent",
        "kind": "agent",
        "label": "Matplotlib",
        "shape": "box",
        "details": [
            {"label": "Type", "value": "SoftwareAgent"},
            {"label": "Version", "value": "3.10.0"},
        ],
    }
    state.detailsProvenanceGraph = _apply_provenance_graph_expansion(
        [
            {"id": "node-visualization", "type": "node", "node": provenance_nodes[0]},
            {"id": "arrow-1", "type": "arrow", "relation": ""},
            {
                "id": "plan-group-visualization-activity",
                "type": "plan_group",
                "plan": plan_node,
                "selected_action": {
                    "id": "visualization-activity-selected-action",
                    "node": provenance_nodes[1],
                    "agent": agent_node,
                    "selected": True,
                },
            },
            {
                "id": "branches-input",
                "type": "branches",
                "relation": "uses",
                "branches": [
                    {
                        "id": item["id"],
                        "input": item,
                    }
                    for item in provenance_nodes[2]["items"]
                ],
                "shared_source": provenance_nodes[3],
            },
        ],
        state.detailsProvenanceExpanded,
    )
    state.queryAssistantAvailable = True
    state.queryAssistantProvider = "Deterministic browser fixture"
    state.variableGroupCollapsed = {"0D": False, "2D": False}
    state.variableGroupCollapsedByView = {
        "variables": dict(state.variableGroupCollapsed),
        "files": {},
    }
    state.gridRows = 1
    state.gridCols = 3
    state.gridLayoutMode = "uniform"
    state.gridColumnSizes = [280, 280, 280]
    state.gridRowSizes = [352]
    state.gridColumnWeights = [1.0, 1.0, 1.0]
    state.gridRowWeights = [1.0]
    state.gridColumnTemplate = "280px 280px 280px"
    state.gridRowTemplate = "352px"
    state.gridFitColumnTemplate = " ".join(
        "minmax(180px, 1fr)" for _ in range(state.gridCols)
    )
    state.gridFitRowTemplate = "minmax(212px, 1fr)"
    if mode == "multi-axis":
        state.gridCells = _multi_axis_cells()
    elif mode in {"scalar", "scalar-settings"}:
        state.gridCells = [
            _scalar_field_cell("black"),
            _scalar_field_cell("white"),
            empty_grid_cell(),
        ]
    else:
        state.gridCells = [
            _plot_cell(mode),
            _image_sequence_cell(mode),
            empty_grid_cell(),
        ]
    if mode in {"freeform-column-seam", "freeform-row-seam"}:
        row_tiles = [dict(state.gridCells[0]), dict(state.gridCells[1])]
        row_tiles[0].update(
            {
                "tile_id": "tile-1",
                "tile_type": "plot",
                "canvas_x": 0 if mode == "freeform-column-seam" else 10,
                "canvas_y": 0 if mode == "freeform-column-seam" else 8,
                "canvas_w": 10,
                "canvas_h": 8,
            }
        )
        row_tiles[1].update(
            {
                "tile_id": "tile-2",
                "tile_type": "plot",
                "canvas_x": 10,
                "canvas_y": 0,
                "canvas_w": 10,
                "canvas_h": 8,
            }
        )
        state.gridLayoutMode = "freeform"
        state.gridCells = row_tiles
    if mode == "freeform-resize":
        resize_tile = dict(state.gridCells[0])
        resize_tile.update(
            {
                "tile_id": "tile-1",
                "tile_type": "plot",
                "canvas_x": 6,
                "canvas_y": 4,
                "canvas_w": 8,
                "canvas_h": 8,
            }
        )
        state.gridLayoutMode = "freeform"
        state.gridCells = [resize_tile]
    state.workspaceLayout = initial_workspace_layout(grid_snapshot(state))
    state.workspacePanes = deepcopy(state.workspaceLayout["panes"])
    state.workspacePaneFrames, splitters = workspace_geometry(state.workspaceLayout)
    state.workspaceSplitters = list(splitters)

    if mode == "scalar-settings":
        state.showScalarFieldSettingsModal = True
        state.scalarFieldSettingsCellIndex = 0
        state.scalarFieldSettingsTitle = "field_black"
        state.scalarFieldSettingsShowHeatmap = True
        state.scalarFieldSettingsShowContours = False
        state.scalarFieldSettingsColormap = "viridis"
        state.scalarFieldSettingsBackground = "black"
        state.scalarFieldSettingsRangeAuto = True
        state.scalarFieldSettingsShowColorbar = True
        state.scalarFieldSettingsShowAxes = True
        state.scalarFieldSettingsContourLevelMode = "range"
        state.scalarFieldSettingsContourValues = "-1, 0, 1"
        state.scalarFieldSettingsContourMin = "-1"
        state.scalarFieldSettingsContourMax = "1"
        state.scalarFieldSettingsContourCount = 5
        state.scalarFieldSettingsContourColor = "#ffffff"

    def toggle_variable_group(group_name):
        collapsed = dict(state.variableGroupCollapsed or {})
        collapsed[str(group_name)] = not bool(collapsed.get(str(group_name), False))
        state.variableGroupCollapsed = collapsed

    def publish_workspace_layout(layout):
        layout = deepcopy(layout)
        root = normalized_workspace_root(layout)
        layout["root"] = root
        layout["split_direction"] = (
            root.get("direction", "none") if root.get("kind") == "split" else "none"
        )
        layout["split_ratio"] = (
            float(root.get("ratio", 0.5)) if root.get("kind") == "split" else 0.5
        )
        pane_frames, splitters = workspace_geometry(layout)
        state.workspaceLayout = deepcopy(layout)
        state.workspacePanes = deepcopy(layout["panes"])
        state.workspacePaneFrames = deepcopy(pane_frames)
        state.workspaceSplitters = deepcopy(list(splitters))
        state.workspaceSplitDirection = layout["split_direction"]
        state.workspaceSplitRatio = layout["split_ratio"]
        state.workspaceActivePaneId = layout["active_pane_id"]
        state.workspaceActiveTabId = layout["active_tab_id"]

    def stash_active_workspace_grid():
        layout = deepcopy(state.workspaceLayout)
        _pane, tab = active_pane_and_tab(layout)
        if tab is not None:
            tab["grid"] = grid_snapshot(state)
        publish_workspace_layout(layout)
        return layout

    def activate_workspace_tab(pane_id, tab_id):
        layout = stash_active_workspace_grid()
        pane, tab = pane_and_tab(layout, pane_id, tab_id)
        if pane is None or tab is None:
            return
        pane["active_tab_id"] = tab["id"]
        layout["active_pane_id"] = pane["id"]
        layout["active_tab_id"] = tab["id"]
        publish_workspace_layout(layout)
        apply_grid_snapshot(state, tab["grid"])

    def add_workspace_tab(pane_id=""):
        layout = stash_active_workspace_grid()
        layout, tab_id = add_workspace_tab_model(
            layout,
            pane_id or layout["active_pane_id"],
            grid_snapshot(state),
        )
        publish_workspace_layout(layout)
        pane, tab = pane_and_tab(layout, layout["active_pane_id"], tab_id)
        if pane is not None and tab is not None:
            apply_grid_snapshot(state, tab["grid"])

    def rename_workspace_tab(pane_id, tab_id, title):
        if title is None:
            return
        layout = stash_active_workspace_grid()
        _pane, tab = pane_and_tab(layout, pane_id, tab_id)
        if tab is not None:
            tab["title"] = normalized_tab_title(title, tab["title"])
        publish_workspace_layout(layout)

    def load_active_workspace_grid(layout):
        publish_workspace_layout(layout)
        _pane, tab = active_pane_and_tab(layout)
        if tab is not None:
            apply_grid_snapshot(state, tab["grid"])

    def close_workspace_tab(pane_id, tab_id, confirmed=True):
        if confirmed:
            load_active_workspace_grid(
                close_workspace_tab_model(
                    stash_active_workspace_grid(), pane_id, tab_id
                )
            )

    def split_workspace_pane(direction="horizontal", pane_id=""):
        layout, _pane_id = split_workspace_model(
            stash_active_workspace_grid(),
            direction,
            grid_snapshot(state),
            pane_id=pane_id or state.workspaceActivePaneId,
        )
        load_active_workspace_grid(layout)

    def split_workspace_tab(
        source_pane_id,
        tab_id,
        target_pane_id,
        direction,
    ):
        layout, _pane_id = split_workspace_tab_model(
            stash_active_workspace_grid(),
            direction,
            grid_snapshot(state),
            source_pane_id,
            tab_id,
            target_pane_id,
        )
        load_active_workspace_grid(layout)

    def close_workspace_pane(pane_id, confirmed=True):
        if confirmed:
            load_active_workspace_grid(
                close_workspace_pane_model(stash_active_workspace_grid(), pane_id)
            )

    def move_workspace_tab(
        pane_id,
        tab_id,
        destination_pane_id="",
        insertion_index=None,
    ):
        layout = stash_active_workspace_grid()
        if destination_pane_id:
            layout = move_workspace_tab_to_pane_model(
                layout,
                pane_id,
                tab_id,
                destination_pane_id,
                insertion_index,
            )
        else:
            layout = move_workspace_tab_model(layout, pane_id, tab_id)
        load_active_workspace_grid(layout)

    def reorder_workspace_tab(pane_id, tab_id, insertion_index):
        layout = reorder_workspace_tab_model(
            stash_active_workspace_grid(), pane_id, tab_id, insertion_index
        )
        publish_workspace_layout(layout)

    def move_workspace_grid_cell(
        source_pane_id,
        source_tab_id,
        source_index,
        destination_pane_id,
        destination_tab_id,
        destination_index,
    ):
        load_active_workspace_grid(
            move_workspace_grid_cell_model(
                stash_active_workspace_grid(),
                source_pane_id,
                source_tab_id,
                source_index,
                destination_pane_id,
                destination_tab_id,
                destination_index,
            )
        )

    def move_workspace_canvas_tile(
        source_pane_id,
        source_tab_id,
        source_index,
        destination_pane_id,
        destination_tab_id,
        geometry_payload,
    ):
        layout = stash_active_workspace_grid()
        _source_pane, source_tab = pane_and_tab(
            layout, source_pane_id, source_tab_id
        )
        destination_pane, destination_tab = pane_and_tab(
            layout, destination_pane_id, destination_tab_id
        )
        if source_tab is None or destination_tab is None:
            return
        source_cells = list(source_tab["grid"].get("cells", []) or [])
        index = int(source_index)
        if not 0 <= index < len(source_cells):
            return
        cell = dict(source_cells.pop(index))
        geometry = json.loads(geometry_payload)
        cell.update(
            {
                "canvas_x": geometry["x"],
                "canvas_y": geometry["y"],
                "canvas_w": geometry["w"],
                "canvas_h": geometry["h"],
            }
        )
        source_tab["grid"]["cells"] = source_cells
        destination_cells = list(destination_tab["grid"].get("cells", []) or [])
        destination_cells.append(cell)
        destination_tab["grid"]["cells"] = destination_cells
        destination_tab["grid"]["active_cell"] = len(destination_cells) - 1
        destination_pane["active_tab_id"] = destination_tab_id
        layout["active_pane_id"] = destination_pane_id
        layout["active_tab_id"] = destination_tab_id
        load_active_workspace_grid(layout)

    def resize_workspace_split(split_id, ratio):
        publish_workspace_layout(
            resize_workspace_split_model(
                stash_active_workspace_grid(), split_id, ratio
            )
        )

    @state.change("variableSearchText")
    def filter_variable_groups(variableSearchText, **_):
        search_text = str(variableSearchText or "").strip()
        state.filteredVariableGroups = (
            _filter_variable_groups(state.variableGroups, search_text)
            if search_text
            else []
        )

    def set_active_grid_cell(cell_index, _ignored=0, _extend_selection=0):
        state.activeGridCell = int(cell_index)

    def set_active_axis_selection(axis_index):
        cells = [dict(cell) for cell in state.gridCells]
        driver_index = int(state.timelineDriverCell)
        if not 0 <= driver_index < len(cells):
            driver_index = int(state.activeGridCell)
        if not 0 <= driver_index < len(cells):
            driver_index = next(
                (
                    index
                    for index, cell in enumerate(cells)
                    if (cell.get("selection_axis", {}) or {}).get("values")
                ),
                -1,
            )
        if driver_index < 0:
            return
        driver_axis = dict(cells[driver_index].get("selection_axis", {}) or {})
        driver_values = list(driver_axis.get("values", []) or [])
        if not driver_values:
            return
        selected_index = max(0, min(int(axis_index), len(driver_values) - 1))
        selected_value = driver_values[selected_index]
        driver_key = str(driver_axis.get("key", "") or "")
        for cell in cells:
            axis = dict(cell.get("selection_axis", {}) or {})
            if not axis:
                cell["axis_sync_status"] = "static"
                continue
            if str(axis.get("key", "") or "") != driver_key:
                cell["axis_sync_status"] = "incompatible"
                continue
            values = list(axis.get("values", []) or [])
            if selected_value not in values:
                cell["axis_sync_status"] = "unavailable"
                continue
            target_index = values.index(selected_value)
            axis.update({"index": target_index, "value": selected_value})
            cell["selection_axis"] = axis
            cell["axis_sync_status"] = "synchronized"
            if cell.get("variable_id") == "photodiode_signal":
                plot = deepcopy(cell["plot"])
                series = deepcopy(plot["series"])
                series[0]["y"] = [
                    10.0 + target_index,
                    12.0 + target_index,
                    11.0 + target_index,
                ]
                plot["series"] = series
                cell["plot"] = plot
        state.gridCells = cells

    def assign_var_to_grid_cell(variable_id, cell_index):
        index = int(cell_index)
        cells = [dict(cell) for cell in state.gridCells]
        assigned = empty_grid_cell()
        assigned.update(
            {
                "variable_id": str(variable_id),
                "variable_name": str(variable_id),
                "display_title": str(variable_id),
                "status": "ok",
            }
        )
        cells[index] = assigned
        state.gridCells = cells

    def move_grid_cell(from_cell_index, to_cell_index):
        source_index = int(from_cell_index)
        target_index = int(to_cell_index)
        cells = [dict(cell) for cell in state.gridCells]
        cells[target_index] = cells[source_index]
        cells[source_index] = empty_grid_cell()
        state.gridCells = cells

    def set_grid_layout_size(rows, cols):
        rows = int(rows)
        cols = int(cols)
        cells = [dict(cell) for cell in state.gridCells]
        while len(cells) < rows * cols:
            cells.append(empty_grid_cell())
        state.gridRows = rows
        state.gridCols = cols
        state.gridCells = cells[: rows * cols]
        state.gridColumnSizes = [280 for _ in range(cols)]
        state.gridRowSizes = [352 for _ in range(rows)]
        state.gridColumnWeights = [1.0 for _ in range(cols)]
        state.gridRowWeights = [1.0 for _ in range(rows)]
        state.gridColumnTemplate = " ".join("280px" for _ in range(cols))
        state.gridRowTemplate = " ".join("352px" for _ in range(rows))
        state.gridFitColumnTemplate = " ".join(
            "minmax(180px, 1fr)" for _ in range(cols)
        )
        state.gridFitRowTemplate = " ".join("minmax(212px, 1fr)" for _ in range(rows))

    def set_grid_layout_mode(layout_mode):
        requested = str(layout_mode or "uniform")
        previous = str(state.gridLayoutMode or "uniform")
        if requested == previous:
            return
        if requested == "freeform":
            compact = []
            for index, raw_cell in enumerate(state.gridCells):
                if not cell_has_content(raw_cell):
                    continue
                cell = dict(raw_cell)
                cell.update(
                    {
                        "tile_id": f"tile-{len(compact) + 1}",
                        "tile_type": canvas_layout.tile_type_for_cell(cell),
                        "canvas_x": (len(compact) * 10) % 20,
                        "canvas_y": (len(compact) // 2) * 8,
                        "canvas_w": 10,
                        "canvas_h": 8,
                    }
                )
                compact.append(cell)
            state.gridLayoutMode = "freeform"
            state.gridCells = normalize_grid_cells(
                compact,
                state.gridRows,
                state.gridCols,
                "freeform",
            )
        else:
            cells = [dict(cell) for cell in state.gridCells if cell_has_content(cell)]
            while len(cells) < state.gridRows * state.gridCols:
                cells.append(empty_grid_cell())
            state.gridLayoutMode = requested if requested == "spanning" else "uniform"
            state.gridCells = normalize_grid_cells(
                cells,
                state.gridRows,
                state.gridCols,
                state.gridLayoutMode,
            )
        state.activeGridCell = -1
        state.selectedGridCellIndices = []
        state.selectedGridCellMap = {}
        state.canvasLayoutRevision += 1

    def set_canvas_snap_to_grid(value=True):
        state.canvasSnapToGrid = bool(value)

    def set_canvas_nudge_others(value=True):
        state.canvasNudgeOthers = bool(value)

    def set_canvas_show_grid(value=True):
        state.canvasShowGrid = bool(value)

    def adjust_canvas_zoom(delta=0):
        state.canvasZoom = canvas_layout.normalize_zoom(
            state.canvasZoom + float(delta or 0)
        )
        state.canvasFitToView = False
        state.canvasLayoutRevision += 1

    def adjust_canvas_default_tile_width(delta=0):
        state.canvasDefaultTileWidth = canvas_layout.normalize_drop_width(
            state.canvasDefaultTileWidth + int(delta or 0)
        )

    def set_canvas_fit_to_view(value=True):
        state.canvasFitToView = bool(value)
        state.canvasLayoutRevision += 1

    def sync_canvas_fit_zoom(value, *_args):
        if state.canvasFitToView:
            state.canvasZoom = canvas_layout.normalize_zoom(value)

    def set_canvas_columns(value=canvas_layout.CANVAS_COLUMNS):
        previous = canvas_layout.normalize_columns(state.canvasCols)
        columns = canvas_layout.normalize_columns(value)
        if previous == columns:
            return
        geometries = [
            canvas_layout.geometry_from_cell(
                cell,
                fallback_id=f"tile-{index + 1}",
                fallback_index=index,
                snap=bool(state.canvasSnapToGrid),
                columns=previous,
            )
            for index, cell in enumerate(state.gridCells)
        ]
        scaled = canvas_layout.scale_layout_columns(
            geometries,
            previous,
            columns,
            snap=bool(state.canvasSnapToGrid),
        )
        by_id = {item["tile_id"]: item for item in scaled}
        state.canvasCols = columns
        state.gridCells = [
            canvas_layout.geometry_to_cell(cell, by_id[cell["tile_id"]])
            for cell in state.gridCells
        ]
        state.canvasLayoutRevision += 1

    def commit_canvas_layout(layout_payload, active_tile_id="", *_args):
        proposed = json.loads(layout_payload)
        by_id = {str(item["tile_id"]): item for item in proposed}
        cells = []
        for cell in state.gridCells:
            updated = dict(cell)
            geometry = by_id[updated["tile_id"]]
            updated.update(
                {
                    "canvas_x": geometry["x"],
                    "canvas_y": geometry["y"],
                    "canvas_w": geometry["w"],
                    "canvas_h": geometry["h"],
                }
            )
            cells.append(updated)
        state.gridCells = cells
        state.activeGridCell = next(
            (
                index
                for index, cell in enumerate(cells)
                if cell["tile_id"] == active_tile_id
            ),
            -1,
        )
        state.canvasLayoutRevision += 1

    def add_var_to_canvas(
        variable_id,
        geometry_payload,
        _pane_id="",
        _tab_id="",
        layout_payload="",
    ):
        if layout_payload:
            commit_canvas_layout(layout_payload)
        geometry = json.loads(geometry_payload)
        cell = empty_grid_cell()
        cell.update(
            {
                "variable_id": str(variable_id),
                "variable_name": str(variable_id),
                "display_title": str(variable_id),
                "status": "ok",
                "tile_id": f"tile-{len(state.gridCells) + 1}",
                "tile_type": "plot",
                "canvas_x": geometry["x"],
                "canvas_y": geometry["y"],
                "canvas_w": geometry["w"],
                "canvas_h": geometry["h"],
            }
        )
        state.gridCells = [*state.gridCells, cell]
        state.canvasLayoutRevision += 1

    def _numeric_values(values, count, fallback):
        if isinstance(values, str):
            values = values.split(",")
        parsed = []
        for value in values or []:
            try:
                parsed.append(float(value))
            except (TypeError, ValueError):
                parsed.append(float(fallback))
        return (parsed + [float(fallback)] * count)[:count]

    def set_grid_track_sizes(axis, sizes):
        axis = str(axis)
        if axis == "column":
            state.gridColumnSizes = _numeric_values(sizes, state.gridCols, 280)
            state.gridColumnTemplate = " ".join(
                f"{round(value)}px" for value in state.gridColumnSizes
            )
        elif axis == "row":
            state.gridRowSizes = _numeric_values(sizes, state.gridRows, 352)
            state.gridRowTemplate = " ".join(
                f"{round(value)}px" for value in state.gridRowSizes
            )
        state.gridSizingMode = "static"

    def set_grid_sizing_mode(mode):
        state.gridSizingMode = "fit" if str(mode or "") == "fit" else "static"

    def set_grid_track_weights(axis, weights):
        axis = str(axis)
        if axis == "column":
            state.gridColumnWeights = _numeric_values(weights, state.gridCols, 1)
            state.gridFitColumnTemplate = " ".join(
                f"minmax(180px, {value:g}fr)"
                for value in state.gridColumnWeights
            )
        elif axis == "row":
            state.gridRowWeights = _numeric_values(weights, state.gridRows, 1)
            state.gridFitRowTemplate = " ".join(
                f"minmax(212px, {value:g}fr)" for value in state.gridRowWeights
            )
        state.gridSizingMode = "fit"

    def commit_grid_track_resize(resize_payload):
        payload = json.loads(str(resize_payload or "{}"))
        changes = payload.get("changes", [])
        applied_axes = set()
        for change in changes[:2]:
            axis = str(change.get("axis", "") or "").strip().lower()
            if axis not in {"column", "row"} or axis in applied_axes:
                continue
            kind = str(change.get("kind", "") or "").strip().lower()
            if kind == "sizes":
                set_grid_track_sizes(axis, change.get("values", []))
            elif kind == "weights":
                set_grid_track_weights(axis, change.get("values", []))
            else:
                continue
            applied_axes.add(axis)

    def show_cell_context_menu(cell_index, x, y):
        index = int(cell_index)
        cell = state.gridCells[index]
        state.contextMenuKind = "cell"
        state.contextMenuItem = str(cell.get("variable_name", "") or "")
        state.contextMenuItemLabel = state.contextMenuItem or f"Cell {index + 1}"
        state.contextMenuCellIndex = index
        state.contextMenuCellHasVariable = bool(state.contextMenuItem)
        state.contextMenuX = int(float(x))
        state.contextMenuY = int(float(y))
        state.contextMenuVisible = True

    def show_item_context_menu(item, x, y):
        state.contextMenuKind = "item"
        state.contextMenuItem = str(item)
        state.contextMenuItemLabel = str(item)
        state.contextMenuX = int(float(x))
        state.contextMenuY = int(float(y))
        state.contextMenuVisible = True

    def hide_context_menu_trigger():
        state.contextMenuVisible = False

    def show_tab_context_menu(pane_id, tab_id, x, y):
        _pane, tab = pane_and_tab(state.workspaceLayout, pane_id, tab_id)
        if tab is None:
            return
        state.contextMenuKind = "tab"
        state.contextMenuItemLabel = tab["title"]
        state.contextMenuTabPaneId = pane_id
        state.contextMenuTabId = tab_id
        state.contextMenuTabCanClose = sum(
            len(pane["tabs"]) for pane in state.workspaceLayout["panes"]
        ) > 1
        state.contextMenuX = int(float(x))
        state.contextMenuY = int(float(y))
        state.contextMenuVisible = True

    def context_menu_tab_rename(title):
        rename_workspace_tab(
            state.contextMenuTabPaneId,
            state.contextMenuTabId,
            title,
        )
        state.contextMenuVisible = False

    def context_menu_tab_close(confirmed=True):
        if confirmed and state.contextMenuTabCanClose:
            close_workspace_tab(
                state.contextMenuTabPaneId,
                state.contextMenuTabId,
            )
        state.contextMenuVisible = False

    saved_grid_sizing = None

    def apply_live_grid_sizing(sizing):
        if not isinstance(sizing, dict):
            return
        mode = str(sizing.get("mode", "") or "")
        state.gridColumnSizes = _numeric_values(
            sizing.get("column_sizes"),
            state.gridCols,
            280,
        )
        state.gridRowSizes = _numeric_values(
            sizing.get("row_sizes"),
            state.gridRows,
            352,
        )
        state.gridColumnWeights = _numeric_values(
            sizing.get("column_weights"),
            state.gridCols,
            1,
        )
        state.gridRowWeights = _numeric_values(
            sizing.get("row_weights"),
            state.gridRows,
            1,
        )
        state.gridSizingMode = "fit" if mode == "fit" else "static"
        state.gridColumnTemplate = " ".join(
            f"{round(value)}px" for value in state.gridColumnSizes
        )
        state.gridRowTemplate = " ".join(
            f"{round(value)}px" for value in state.gridRowSizes
        )
        state.gridFitColumnTemplate = " ".join(
            f"minmax(180px, {value:g}fr)"
            for value in state.gridColumnWeights
        )
        state.gridFitRowTemplate = " ".join(
            f"minmax(212px, {value:g}fr)" for value in state.gridRowWeights
        )

    def save_workspace_state(live_grid_sizing=None):
        nonlocal saved_grid_sizing
        apply_live_grid_sizing(live_grid_sizing)
        saved_grid_sizing = {
            "mode": state.gridSizingMode,
            "column_sizes": list(state.gridColumnSizes),
            "row_sizes": list(state.gridRowSizes),
            "column_weights": list(state.gridColumnWeights),
            "row_weights": list(state.gridRowWeights),
        }
        if not state.workspaceStatePath:
            state.workspaceStatePath = f"/tmp/browser-{mode}.json"
        state.workspaceStateStatus = f"Saved: {state.workspaceStatePath}"

    def save_workspace_state_as(live_grid_sizing=None):
        save_workspace_state(live_grid_sizing)

    def load_workspace_state():
        if saved_grid_sizing:
            apply_live_grid_sizing(saved_grid_sizing)
        if not state.workspaceStatePath:
            state.workspaceStatePath = f"/tmp/browser-{mode}.json"
        state.workspaceStateStatus = f"Loaded: {state.workspaceStatePath}"

    def toggle_scalar_field_background():
        state.scalarFieldSettingsBackground = (
            "black"
            if state.scalarFieldSettingsBackground == "white"
            else "white"
        )

    def update_scalar_field_contour_color(color):
        state.scalarFieldSettingsContourColor = str(color or "#ffffff")

    def reset_query_assistant_proposal():
        state.queryAssistantProposalText = ""
        state.queryAssistantProposalSummary = ""
        state.queryAssistantActionPlan = {}
        state.queryAssistantExplanation = ""
        state.queryAssistantStatus = ""
        state.queryAssistantError = ""
        state.queryAssistantTargetCellIndex = -1
        state.queryAssistantVisualizationName = ""

    def open_query_assistant():
        previous_target = state.queryAssistantTarget
        reset_query_assistant_proposal()
        state.queryAssistantTarget = "catalog"
        if previous_target != "catalog":
            state.queryAssistantRequestText = ""
        state.showQueryAssistant = True

    def open_source_query_assistant():
        reset_query_assistant_proposal()
        state.queryAssistantTarget = "source_filter"
        state.queryAssistantRequestText = state.sourceFilterDraftText
        state.showQueryAssistant = True

    def open_visualization_assistant():
        previous_target = state.queryAssistantTarget
        reset_query_assistant_proposal()
        state.queryAssistantTarget = "visualization"
        if previous_target != "visualization":
            state.queryAssistantRequestText = ""
        state.showQueryAssistant = True

    def close_query_assistant():
        state.showQueryAssistant = False

    def translate_query_request():
        if state.queryAssistantTarget == "source_filter":
            state.queryAssistantProposalText = (
                'max > 5.0 and contains(source_dataset, "128")'
            )
            state.queryAssistantProposalSummary = (
                "Select sources for internal_energy with 2 conditions."
            )
            state.queryAssistantStatus = "Valid · 1 source row"
            state.queryAssistantVariableCount = 1
            state.queryAssistantSourceCount = 1
        elif state.queryAssistantTarget == "visualization":
            variable_id = (
                "current_z"
                if "current" in state.queryAssistantRequestText.lower()
                else "internal_energy"
            )
            state.queryAssistantProposalText = ""
            state.queryAssistantVisualizationName = "viewer default"
            state.queryAssistantTargetCellIndex = state.activeGridCell
            state.queryAssistantProposalSummary = (
                f"Add {variable_id} to grid cell {state.activeGridCell + 1} "
                "using viewer default."
            )
            state.queryAssistantStatus = (
                f"Valid · {variable_id} · grid cell {state.activeGridCell + 1}"
            )
            state.queryAssistantVariableCount = 1
            state.queryAssistantSourceCount = 0
        else:
            state.queryAssistantProposalText = "var == 'internal_energy'"
            state.queryAssistantProposalSummary = (
                "Select variables for internal_energy."
            )
            state.queryAssistantStatus = "Valid · 1 variable"
            state.queryAssistantVariableCount = 1
            state.queryAssistantSourceCount = 0
        if state.queryAssistantTarget == "visualization":
            state.queryAssistantActionPlan = {
                "version": 1,
                "actions": [
                    {
                        "type": "visualization.add",
                        "arguments": {
                            "variable_id": variable_id,
                            "target": "active_cell",
                        },
                    }
                ],
            }
        else:
            state.queryAssistantActionPlan = {
                "version": 1,
                "actions": [
                    {
                        "type": "catalog.query",
                        "arguments": {
                            "select": "variables",
                            "result_variable_id": "internal_energy",
                        },
                    }
                ],
            }
        state.queryAssistantExplanation = (
            f"Add {variable_id} to the active grid cell."
            if state.queryAssistantTarget == "visualization"
            else "Select the exact internal_energy variable."
        )

    def validate_query_proposal():
        if state.queryAssistantTarget == "source_filter":
            state.queryAssistantStatus = "Valid · 1 source row"
        elif state.queryAssistantTarget == "catalog":
            state.queryAssistantStatus = "Valid · 1 variable"

    def apply_query_proposal():
        if state.queryAssistantTarget == "source_filter":
            state.sourceFilterDraftText = state.queryAssistantProposalText
            state.sourceFilterText = state.queryAssistantProposalText
            state.sourceRows = [dict(state.sourceRowsAll[0])]
        elif state.queryAssistantTarget == "visualization":
            action = state.queryAssistantActionPlan["actions"][0]
            assign_var_to_grid_cell(
                action["arguments"]["variable_id"],
                state.queryAssistantTargetCellIndex,
            )
        else:
            state.queryText = state.queryAssistantProposalText
        state.showQueryAssistant = False

    def toggle_sources():
        state.sourceDialogTitle = "Sources: internal_energy"
        state.showSourcesModal = not bool(state.showSourcesModal)

    def open_provenance_dialog():
        if state.detailsProvenanceChain:
            state.showProvenanceModal = True

    def close_provenance_dialog():
        state.showProvenanceModal = False

    def toggle_provenance_node_details(node_id):
        target = str(node_id or "")
        nodes = [
            dict(node)
            for node in (state.detailsProvenanceNodes or [])
            if isinstance(node, dict)
        ]
        graph = [
            dict(segment)
            for segment in (state.detailsProvenanceGraph or [])
            if isinstance(segment, dict)
        ]
        detail_node_ids = _provenance_detail_node_ids(
            nodes
        ) | _provenance_graph_detail_node_ids(graph)
        if target not in detail_node_ids:
            return
        expanded = dict(state.detailsProvenanceExpanded or {})
        expanded[target] = not bool(expanded.get(target, False))
        state.detailsProvenanceExpanded = expanded
        state.detailsProvenanceNodes = _apply_provenance_expansion(nodes, expanded)
        state.detailsProvenanceGraph = _apply_provenance_graph_expansion(
            graph,
            expanded,
        )

    def capture_fixture_history():
        layout = deepcopy(state.workspaceLayout)
        _pane, tab = active_pane_and_tab(layout)
        if tab is not None:
            tab["grid"] = grid_snapshot(state)
        return {"workspace": layout}

    def restore_fixture_history(snapshot):
        current_pane_id = str(state.workspaceActivePaneId or "")
        current_tab_id = str(state.workspaceActiveTabId or "")
        layout = deepcopy(snapshot["workspace"])
        focused_pane, focused_tab = pane_and_tab(
            layout, current_pane_id, current_tab_id
        )
        if focused_pane is not None and focused_tab is not None:
            focused_pane["active_tab_id"] = current_tab_id
            layout["active_pane_id"] = current_pane_id
            layout["active_tab_id"] = current_tab_id
        load_active_workspace_grid(layout)
        state.canvasLayoutRevision = int(state.canvasLayoutRevision or 0) + 1

    fixture_history = WorkspaceMutationCoordinator(
        state,
        capture_fixture_history,
        restore_fixture_history,
    )

    def history_edit(label, callback):
        def wrapped(*args, **kwargs):
            with fixture_history.transaction(label):
                return callback(*args, **kwargs)

        return wrapped

    server.controller.add("toggle_variable_group")(toggle_variable_group)
    server.controller.add("activate_workspace_tab")(activate_workspace_tab)
    server.controller.add("add_workspace_tab")(
        history_edit("Add tab", add_workspace_tab)
    )
    server.controller.add("rename_workspace_tab")(
        history_edit("Rename tab", rename_workspace_tab)
    )
    server.controller.add("close_workspace_tab")(
        history_edit("Close tab", close_workspace_tab)
    )
    server.controller.add("context_menu_tab_rename")(context_menu_tab_rename)
    server.controller.add("context_menu_tab_close")(context_menu_tab_close)
    server.controller.add("split_workspace_pane")(
        history_edit("Split pane", split_workspace_pane)
    )
    server.controller.add("close_workspace_pane")(
        history_edit("Close pane", close_workspace_pane)
    )
    server.controller.add("move_workspace_tab")(
        history_edit("Move tab", move_workspace_tab)
    )
    server.controller.add("set_active_grid_cell")(set_active_grid_cell)
    server.controller.add("set_active_axis_selection")(set_active_axis_selection)
    server.controller.add("set_grid_layout_mode")(
        history_edit("Change layout mode", set_grid_layout_mode)
    )
    server.controller.add("set_canvas_snap_to_grid")(set_canvas_snap_to_grid)
    server.controller.add("set_canvas_nudge_others")(set_canvas_nudge_others)
    server.controller.add("set_canvas_show_grid")(set_canvas_show_grid)
    server.controller.add("adjust_canvas_zoom")(adjust_canvas_zoom)
    server.controller.add("adjust_canvas_default_tile_width")(
        adjust_canvas_default_tile_width
    )
    server.controller.add("set_canvas_fit_to_view")(set_canvas_fit_to_view)
    server.controller.add("set_canvas_columns")(
        history_edit("Change canvas columns", set_canvas_columns)
    )
    server.controller.add("set_grid_layout_size")(
        history_edit("Resize grid", set_grid_layout_size)
    )
    server.controller.add("set_grid_sizing_mode")(
        history_edit("Change grid sizing mode", set_grid_sizing_mode)
    )
    server.controller.add("undo_workspace")(fixture_history.undo)
    server.controller.add("redo_workspace")(fixture_history.redo)
    server.controller.trigger("commit_canvas_layout_trigger")(
        history_edit("Move or resize plot", commit_canvas_layout)
    )
    server.controller.trigger("add_var_to_canvas_trigger")(
        history_edit("Add plot", add_var_to_canvas)
    )
    server.controller.trigger("undo_workspace_trigger")(fixture_history.undo)
    server.controller.trigger("redo_workspace_trigger")(fixture_history.redo)
    server.controller.trigger("sync_canvas_fit_zoom_trigger")(
        sync_canvas_fit_zoom
    )
    server.controller.trigger("assign_var_to_grid_cell_trigger")(
        assign_var_to_grid_cell
    )
    server.controller.trigger("move_grid_cell_trigger")(move_grid_cell)
    server.controller.trigger("move_workspace_grid_cell_trigger")(
        history_edit("Move plot between panes", move_workspace_grid_cell)
    )
    server.controller.trigger("move_workspace_canvas_tile_trigger")(
        history_edit("Move plot between panes", move_workspace_canvas_tile)
    )
    server.controller.trigger("move_workspace_tab_trigger")(
        history_edit("Move tab", move_workspace_tab)
    )
    server.controller.trigger("reorder_workspace_tab_trigger")(
        history_edit("Reorder tab", reorder_workspace_tab)
    )
    server.controller.trigger("resize_workspace_split_trigger")(
        history_edit("Resize pane", resize_workspace_split)
    )
    server.controller.trigger("split_workspace_tab_trigger")(
        history_edit("Split tab", split_workspace_tab)
    )
    server.controller.trigger("set_grid_track_sizes_trigger")(
        history_edit("Resize grid track", set_grid_track_sizes)
    )
    server.controller.trigger("set_grid_track_weights_trigger")(
        history_edit("Resize grid track", set_grid_track_weights)
    )
    server.controller.trigger("commit_grid_track_resize_trigger")(
        history_edit("Resize grid track", commit_grid_track_resize)
    )
    server.controller.trigger("show_item_context_menu")(show_item_context_menu)
    server.controller.trigger("show_cell_context_menu")(show_cell_context_menu)
    server.controller.trigger("show_tab_context_menu")(show_tab_context_menu)
    server.controller.trigger("hide_context_menu_trigger")(hide_context_menu_trigger)
    server.controller.add("save_workspace_state")(save_workspace_state)
    server.controller.add("save_workspace_state_as")(save_workspace_state_as)
    server.controller.add("load_workspace_state")(load_workspace_state)
    server.controller.add("toggle_scalar_field_background")(
        toggle_scalar_field_background
    )
    server.controller.add("update_scalar_field_contour_color")(
        update_scalar_field_contour_color
    )
    server.controller.add("toggle_sources")(toggle_sources)
    server.controller.add("open_provenance_dialog")(open_provenance_dialog)
    server.controller.add("close_provenance_dialog")(close_provenance_dialog)
    server.controller.add("toggle_provenance_node_details")(
        toggle_provenance_node_details
    )
    server.controller.add("open_query_assistant")(open_query_assistant)
    server.controller.add("open_source_query_assistant")(
        open_source_query_assistant
    )
    server.controller.add("open_visualization_assistant")(
        open_visualization_assistant
    )
    server.controller.add("close_query_assistant")(close_query_assistant)
    server.controller.add("translate_query_request")(translate_query_request)
    server.controller.add("validate_query_proposal")(validate_query_proposal)
    server.controller.add("apply_query_proposal")(apply_query_proposal)
    build_ui(server, campaign_name=f"browser-{mode}.aca")
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--mode",
        choices=(
            "step",
            "physical",
            "mixed",
            "multi-axis",
            "scalar",
            "scalar-settings",
            "freeform-column-seam",
            "freeform-resize",
            "freeform-row-seam",
        ),
        default="step",
    )
    args = parser.parse_args()

    server = build_fixture_server(args.mode)
    server.start(
        port=args.port,
        host="127.0.0.1",
        open_browser=False,
        show_connection_info=False,
        timeout=0,
    )


if __name__ == "__main__":
    main()
