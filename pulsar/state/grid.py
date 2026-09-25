"""State owned by the visualization grid and synchronized timeline."""

from pulsar.models.grid import DEFAULT_GRID_LAYOUT_MODE, empty_grid_cell
from pulsar.models import canvas_layout


GRID_ROWS = 3
GRID_COLS = 3
GRID_CELL_SIZE = 300
GRID_HEADER_HEIGHT = 32
GRID_FIT_MIN_CELL_SIZE = 180


def _initial_grid_cell():
    cell = empty_grid_cell()
    # These render-only values are populated when a scalar-field tile is built.
    cell.pop("scalar_field_colorbar_min")
    cell.pop("scalar_field_colorbar_max")
    return cell


def defaults():
    return {
        "gridRows": GRID_ROWS,
        "gridCols": GRID_COLS,
        "gridMinRows": 1,
        "gridMinCols": 1,
        "gridMaxRows": 8,
        "gridMaxCols": 8,
        "gridLayoutMode": DEFAULT_GRID_LAYOUT_MODE,
        "canvasCols": canvas_layout.CANVAS_COLUMNS,
        "canvasRowHeight": canvas_layout.CANVAS_ROW_HEIGHT,
        "canvasSnapToGrid": True,
        "canvasNudgeOthers": True,
        "canvasShowGrid": False,
        "canvasZoom": canvas_layout.CANVAS_ZOOM_DEFAULT,
        "canvasFitToView": False,
        "canvasDefaultTileWidth": canvas_layout.CANVAS_DEFAULT_DROP_WIDTH,
        "canvasDwellMs": canvas_layout.CANVAS_DWELL_MS,
        "canvasSnapDeadZone": canvas_layout.CANVAS_SNAP_DEAD_ZONE,
        "canvasTransitionMs": canvas_layout.CANVAS_TRANSITION_MS,
        "canvasLayoutRevision": 0,
        "canvasLayoutError": "",
        "gridSizingMode": "static",
        "gridCellSize": GRID_CELL_SIZE,
        "gridMinCellSize": 80,
        "gridMaxCellSize": 5000,
        "gridFitMinCellSize": GRID_FIT_MIN_CELL_SIZE,
        "gridMaxFitMinCellSize": 5000,
        "gridColumnSizes": [GRID_CELL_SIZE for _ in range(GRID_COLS)],
        "gridRowSizes": [
            GRID_CELL_SIZE + GRID_HEADER_HEIGHT for _ in range(GRID_ROWS)
        ],
        "gridColumnWeights": [1.0 for _ in range(GRID_COLS)],
        "gridRowWeights": [1.0 for _ in range(GRID_ROWS)],
        "gridColumnTemplate": " ".join(
            f"{GRID_CELL_SIZE}px" for _ in range(GRID_COLS)
        ),
        "gridRowTemplate": " ".join(
            f"{GRID_CELL_SIZE + GRID_HEADER_HEIGHT}px" for _ in range(GRID_ROWS)
        ),
        "gridFitColumnTemplate": " ".join(
            f"minmax({GRID_FIT_MIN_CELL_SIZE}px, 1fr)" for _ in range(GRID_COLS)
        ),
        "gridFitRowTemplate": " ".join(
            f"minmax({GRID_FIT_MIN_CELL_SIZE + GRID_HEADER_HEIGHT}px, 1fr)"
            for _ in range(GRID_ROWS)
        ),
        "gridCells": [
            _initial_grid_cell() for _ in range(GRID_ROWS * GRID_COLS)
        ],
        "activeGridCell": -1,
        "selectedGridCellIndices": [],
        "selectedGridCellMap": {},
        "timelineDriverCell": -1,
        "resetViewRequest": {},
        "resetViewRequestNonce": 0,
    }
