"""Characterize Seurat behavior in a mounted Vue client."""

import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image


pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("SEURAT_RUN_BROWSER_TESTS") != "1",
        reason="set SEURAT_RUN_BROWSER_TESTS=1 to run browser tests",
    ),
]


def _open_app(page, seurat_server, mode="step"):
    console_errors = []
    page_errors = []
    response_errors = []
    page.on(
        "console",
        lambda message: (
            console_errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: (
            response_errors.append(
                f"{response.status} {response.request.method} {response.url}"
            )
            if response.status >= 400
            else None
        ),
    )
    page.goto(seurat_server(mode), wait_until="networkidle")
    page.locator("#seurat-variable-column").wait_for(state="visible")
    return console_errors, page_errors, response_errors


def _drag(page, locator, delta_x=0, delta_y=0, release=True, button="left"):
    bounds = locator.bounding_box()
    assert bounds is not None
    start_x = bounds["x"] + bounds["width"] / 2
    start_y = bounds["y"] + bounds["height"] / 2
    page.mouse.move(start_x, start_y)
    page.mouse.down(button=button)
    page.mouse.move(start_x + delta_x, start_y + delta_y, steps=3)
    if release:
        page.mouse.up(button=button)


def _split_workspace_pane_by_drag(page, pane_bar, direction):
    pane_count = page.locator(".seurat-workspace-tab-bar").count()
    pane_id = pane_bar.get_attribute("data-pane-frame-id")
    assert pane_id
    original = pane_bar.locator(".seurat-workspace-tab.is-pane-tab-active")
    original_tab_id = original.get_attribute("data-tab-id")
    assert original_tab_id
    tab_count = pane_bar.locator(".seurat-workspace-tab").count()
    pane_bar.get_by_role("button", name="New tab").click()
    page.wait_for_function(
        f"""() => {{
          const bar = document.querySelector(
            '.seurat-workspace-tab-bar[data-pane-frame-id="{pane_id}"]'
          );
          const active = bar && bar.querySelector(
            '.seurat-workspace-tab.is-pane-tab-active'
          );
          return bar
            && bar.querySelectorAll('.seurat-workspace-tab').length === {tab_count + 1}
            && active
            && active.getAttribute('data-tab-id') !== {original_tab_id!r};
        }}"""
    )
    source = pane_bar.locator(".seurat-workspace-tab.is-pane-tab-active")
    source.wait_for(state="visible")
    moved_tab_id = source.get_attribute("data-tab-id")
    assert moved_tab_id
    source_bounds = source.bounding_box()
    assert source_bounds is not None
    page.mouse.move(
        source_bounds["x"] + source_bounds["width"] / 2,
        source_bounds["y"] + source_bounds["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        source_bounds["x"] + source_bounds["width"] / 2 + 12,
        source_bounds["y"] + source_bounds["height"] / 2,
        steps=3,
    )
    page.wait_for_function(
        "document.querySelector('.v-application')"
        ".classList.contains('is-workspace-tab-dragging')"
    )
    preview = page.locator(
        f'.seurat-workspace-tab-dock-preview[data-tab-dock-pane-id="{pane_id}"]'
    )
    preview_bounds = preview.bounding_box()
    assert preview_bounds is not None
    if direction == "vertical":
        target_x = preview_bounds["x"] + preview_bounds["width"] / 2
        target_y = preview_bounds["y"] + preview_bounds["height"] - 8
    else:
        target_x = preview_bounds["x"] + preview_bounds["width"] - 8
        target_y = preview_bounds["y"] + preview_bounds["height"] * 0.4
    page.mouse.move(
        target_x,
        target_y,
        steps=10,
    )
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-workspace-tab-dock-target.is-tab-dock-active'"
        ").length === 1"
    )
    page.mouse.up()
    page.wait_for_function(
        f"document.querySelectorAll('.seurat-workspace-tab-bar').length === {pane_count + 1}"
    )
    page.locator(
        f'.seurat-workspace-tab[data-pane-id="{pane_id}"]'
        f'[data-tab-id="{original_tab_id}"]'
    ).click()
    page.wait_for_function(
        f"document.querySelector('.seurat-workspace-active-grid')"
        f".getAttribute('data-pane-id') === {pane_id!r}"
    )
    page.locator(
        f'.seurat-workspace-tab[data-tab-id="{moved_tab_id}"]'
    ).click()
    page.wait_for_function(
        f"document.querySelector('.seurat-workspace-active-grid')"
        f".getAttribute('data-tab-id') === {moved_tab_id!r}"
    )


def test_canvas_layout_shared_conformance_fixtures(page, seurat_server):
    _open_app(page, seurat_server)
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "canvas_layout_conformance.json"
    )
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]

    results = page.evaluate(
        """cases => cases.map(testCase => {
            const layout = window.seuratCanvasLayout;
            const args = testCase.arguments;
            if (testCase.operation === 'horizontal_resize_push') {
                return layout.horizontalResizePush(
                    testCase.items, args.priority_id, args.original_right, args.columns
                );
            }
            if (testCase.operation === 'insertion_zone') {
                return layout.insertionZone(
                    testCase.items,
                    args.dragged_id,
                    args.pointer_x,
                    args.pointer_y,
                    { xTolerance: args.x_tolerance, yTolerance: args.y_tolerance }
                );
            }
            if (testCase.operation === 'apply_column_insertion') {
                return layout.applyColumnInsertion(testCase.items, {
                    draggedId: args.dragged_id,
                    seam: args.seam,
                    anchorY: args.anchor_y,
                    moveIds: args.move_ids,
                    width: args.width,
                    height: args.height,
                    mode: args.mode,
                    columns: args.columns,
                });
            }
            throw new Error(`Unknown operation: ${testCase.operation}`);
        })""",
        cases,
    )

    assert results == [test_case["expected"] for test_case in cases]


def test_app_mounts_and_renders_structural_ui(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    assert page.get_by_text("browser-step.aca", exact=True).is_visible()
    assert page.locator('[title="fixture/scalars.bp/internal_energy"]').is_visible()
    assert page.locator('[title="fixture/images/current_z"]').is_visible()
    assert page.locator(".seurat-plot1d svg").is_visible()
    page.locator('[data-seurat-grid-runtime="mounted"]').wait_for(state="attached")
    page.locator('[data-seurat-interaction-runtime="mounted"]').wait_for(
        state="attached"
    )
    page.locator('[data-seurat-canvas-runtime="mounted"]').wait_for(
        state="attached"
    )
    page.locator('[data-seurat-resize-runtime="mounted"]').wait_for(
        state="attached"
    )
    page.locator('[data-seurat-history-runtime="mounted"]').wait_for(
        state="attached"
    )
    assert (
        page.locator(
            '.seurat-content-column[data-seurat-grid-runtime-owner="mounted"]'
        ).count()
        == 1
    )
    assert (
        page.locator(
            '.seurat-content-column[data-seurat-media-runtime-owner="mounted"]'
        ).count()
        == 1
    )
    assert (
        page.locator(
            '.seurat-content-column[data-seurat-plot-runtime-owner="mounted"]'
        ).count()
        == 1
    )
    assert (
        page.locator(
            '.seurat-content-column[data-seurat-timeline-runtime-owner="mounted"]'
        ).count()
        == 1
    )
    assert (
        page.locator(
            '.v-application[data-seurat-canvas-runtime-owner="1"]'
        ).count()
        == 1
    )
    assert (
        page.locator(
            '.v-application[data-seurat-interaction-runtime-owner="mounted"]'
        ).count()
        == 1
    )
    assert (
        page.locator('.v-application[data-seurat-resize-runtime-owner="mounted"]').count()
        == 1
    )
    assert (
        page.locator('.v-application[data-seurat-history-runtime-owner="mounted"]').count()
        == 1
    )
    assert page.evaluate(
        """() => {
            const runtimes = window.seurat && window.seurat.runtimes;
            return Boolean(
                runtimes
                && runtimes.grid === window.seuratGridRuntime
                && runtimes.media === window.seuratMediaRuntime
                && runtimes.plot === window.seuratPlotRuntime
                && runtimes.timeline === window.seuratTimelineRuntime
                && runtimes.canvas === window.seuratCanvasRuntime
                && runtimes.interaction === window.seuratInteractionRuntime
                && runtimes.resize === window.seuratResizeRuntime
                && runtimes.history === window.seuratHistoryRuntime
            );
        }"""
    )

    rendered = page.locator(".seurat-content-column").screenshot()
    image = Image.open(io.BytesIO(rendered)).convert("RGB")
    assert image.width >= 500
    assert image.height >= 300
    assert len(image.getcolors(maxcolors=image.width * image.height) or []) > 8

    assert page_errors == []
    assert console_errors == [], response_errors


def test_provenance_detail_buttons_expand_in_popup(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    page.get_by_role("button", name="Provenance", exact=True).click()
    panel = page.locator("#seurat-provenance-panel")
    panel.wait_for(state="visible")
    dialog = page.locator(".seurat-provenance-dialog")
    dialog.wait_for(state="visible")
    content_styles = panel.locator(".seurat-provenance-dialog-content").evaluate(
        """element => {
            const style = window.getComputedStyle(element);
            return {
                maxHeight: style.maxHeight,
                overflowX: style.overflowX,
                overflowY: style.overflowY,
            };
        }"""
    )
    graph_styles = panel.locator(".seurat-provenance-graph").evaluate(
        """element => {
            const style = window.getComputedStyle(element);
            return {
                overflowX: style.overflowX,
                overflowY: style.overflowY,
            };
        }"""
    )
    assert content_styles["maxHeight"] != "none"
    assert content_styles["overflowY"] in {"auto", "scroll"}
    assert graph_styles["overflowX"] in {"auto", "scroll"}
    assert dialog.locator(".seurat-provenance-node-details").count() == 0
    assert dialog.locator(".seurat-provenance-branch-section").count() == 1
    assert dialog.locator(".seurat-provenance-input-row").get_by_text(
        "vx",
        exact=True,
    ).is_visible()
    assert dialog.locator(".seurat-provenance-input-row").get_by_text(
        "vy",
        exact=True,
    ).is_visible()
    assert dialog.locator(".seurat-provenance-input-row").get_by_text(
        "pressure",
        exact=True,
    ).is_visible()
    assert dialog.locator(".seurat-provenance-shared-source-row").get_by_text(
        "hll_128/output.bp",
        exact=True,
    ).is_visible()

    dialog.locator(".seurat-provenance-detail-btn").first.click()
    page.wait_for_function(
        """() => {
            const dialog = document.querySelector('.seurat-provenance-dialog');
            return Boolean(
                dialog
                && dialog.querySelector('.seurat-provenance-node-details')
                && dialog.querySelector('.seurat-provenance-detail-btn')
                    ?.getAttribute('aria-expanded') === 'true'
            );
        }"""
    )
    assert dialog.locator(".seurat-provenance-detail-row").filter(
        has_text="Visualization"
    ).first.is_visible()
    assert dialog.locator(".seurat-provenance-detail-row").filter(
        has_text="velocity_streamlines"
    ).first.is_visible()

    dialog.locator(".seurat-provenance-detail-btn").first.click()
    page.wait_for_function(
        """() => {
            const dialog = document.querySelector('.seurat-provenance-dialog');
            return Boolean(
                dialog
                && !dialog.querySelector('.seurat-provenance-node-details')
                && dialog.querySelector('.seurat-provenance-detail-btn')
                    ?.getAttribute('aria-expanded') === 'false'
            );
        }"""
    )
    action_node = dialog.locator(".seurat-provenance-node.is-activity").first
    action_node.locator(".seurat-provenance-detail-btn").click()
    page.wait_for_function(
        """() => {
            const action = document.querySelector(
              '.seurat-provenance-node.is-activity'
            );
            return Boolean(
                action
                && action.querySelector('.seurat-provenance-node-details')
                && action.querySelector('.seurat-provenance-input-table')
                && action.textContent.includes('Variable')
                && action.textContent.includes('Role')
                && action.textContent.includes('vx')
                && action.textContent.includes('streamline-x')
                && action.textContent.includes('vy')
                && action.textContent.includes('streamline-y')
                && action.textContent.includes('pressure')
                && action.textContent.includes('color-by')
                && !action.textContent.includes('hll_128/output.bp')
            );
        }"""
    )

    input_node = dialog.locator(
        ".seurat-provenance-input-row .seurat-provenance-node.is-variable"
    ).first
    input_node.locator(".seurat-provenance-detail-btn").click()
    page.wait_for_function(
        """() => {
            const input = document.querySelector(
              '.seurat-provenance-input-row .seurat-provenance-node.is-variable'
            );
            return Boolean(
                input && input.querySelector('.seurat-provenance-node-details')
            );
        }"""
    )
    input_detail_labels = input_node.locator(
        ".seurat-provenance-detail-label"
    ).evaluate_all("labels => labels.map(label => label.textContent.trim())")
    assert input_detail_labels == ["Variable"]

    assert page_errors == []
    assert console_errors == [], response_errors


def test_provenance_popup_drags_and_clamps(page, seurat_server):
    _open_app(page, seurat_server)

    page.get_by_role("button", name="Provenance", exact=True).click()
    panel = page.locator("#seurat-provenance-panel")
    panel.wait_for(state="visible")
    handle = panel.locator(".seurat-floating-panel-drag-handle")
    initial = panel.bounding_box()
    assert initial is not None

    _drag(page, handle, delta_x=50, delta_y=30)
    moved = panel.bounding_box()
    assert moved["x"] == pytest.approx(initial["x"] + 50, abs=2)
    assert moved["y"] == pytest.approx(initial["y"] + 30, abs=2)
    assert not panel.evaluate("panel => panel.classList.contains('is-dragging')")

    _drag(page, handle, delta_x=2000, delta_y=2000)
    clamped = panel.bounding_box()
    assert clamped["x"] + clamped["width"] <= page.viewport_size["width"] - 7
    assert clamped["y"] + clamped["height"] <= page.viewport_size["height"] - 7


def test_workspace_tabs_and_split_panes_preserve_grid_content(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    first_bar.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    assert page.locator(".seurat-workspace-tab").count() == 2

    add_tab = first_bar.get_by_role("button", name="New tab")
    assert add_tab.evaluate(
        """button => {
            const strip = button.parentElement;
            const tabs = strip.querySelectorAll(':scope > .seurat-workspace-tab-shell');
            return strip.classList.contains('seurat-workspace-tabs')
                && strip.lastElementChild === button
                && button.previousElementSibling === tabs[tabs.length - 1];
        }"""
    )
    last_tab_bounds = first_bar.locator(
        ".seurat-workspace-tab-shell"
    ).last.bounding_box()
    add_tab_bounds = add_tab.bounding_box()
    assert last_tab_bounds is not None
    assert add_tab_bounds is not None
    assert abs(
        add_tab_bounds["x"] - (last_tab_bounds["x"] + last_tab_bounds["width"] + 4)
    ) <= 1

    page.get_by_role("tab", name="View 1").click()
    page.locator(".seurat-workspace-active-grid").get_by_text(
        "internal_energy", exact=True
    ).wait_for(state="visible")

    _split_workspace_pane_by_drag(page, first_bar, "horizontal")
    page.get_by_role("tab", name="View 3").wait_for(state="visible")

    assert page.locator(".seurat-workspace-tab-bar").count() == 2
    assert page.locator(".seurat-main-grid").count() == 2
    assert page.locator(".seurat-workspace-grid-preview").count() == 1
    assert page.locator(
        ".seurat-workspace-active-grid.seurat-workspace-slot-second"
    ).count() == 1
    assert page.locator(".seurat-workspace-grid-preview").get_by_text(
        "internal_energy", exact=True
    ).is_visible()

    page.get_by_role("tab", name="View 1").click()
    page.locator(
        ".seurat-workspace-active-grid.seurat-workspace-slot-first"
    ).wait_for(state="visible")
    assert page.locator(".seurat-workspace-grid-preview").count() == 1

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_undo_redo_buttons_and_shortcuts(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)
    undo_button, redo_button = page.locator(".seurat-history-button").all()
    assert undo_button.is_disabled()
    assert redo_button.is_disabled()

    page.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    assert not undo_button.is_disabled()
    assert "Undo Add tab" in undo_button.get_attribute("title")

    undo_button.click()
    page.wait_for_function(
        "document.querySelectorAll('.seurat-workspace-tab').length === 1"
    )
    assert not redo_button.is_disabled()
    assert "Redo Add tab" in redo_button.get_attribute("title")

    page.locator(".seurat-content-column").focus()
    page.keyboard.press("Control+Shift+Z")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    assert page.get_by_role("tab", name="View 1").get_attribute(
        "aria-selected"
    ) == "true"
    page.keyboard.press("Control+Z")
    page.wait_for_function(
        "document.querySelectorAll('.seurat-workspace-tab').length === 1"
    )

    page.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    query_field = page.get_by_placeholder(
        "e.g. var == 'rho' and source_dataset == 'hll_128/output.bp'"
    )
    query_field.fill("density")
    query_field.press("Control+Z")
    assert page.locator(".seurat-workspace-tab").count() == 2

    assert page_errors == []
    assert console_errors == [], response_errors


def test_plot_undo_after_timeline_scrub(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)
    undo_button, redo_button = page.locator(".seurat-history-button").all()

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Freeform", exact=True).click()
    canvas = page.locator(".seurat-freeform-canvas")
    canvas.wait_for(state="visible")
    tiles = canvas.locator(":scope > .seurat-dropcell")
    assert tiles.count() == 2

    page.locator('[data-item="internal_energy"]').drag_to(
        canvas,
        target_position={"x": 540, "y": 340},
    )
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-freeform-canvas > .seurat-dropcell').length === 3"
    )
    assert "Undo Add plot" in undo_button.get_attribute("title")

    slider = page.locator("#seurat-vcr-step-slider")
    slider_bounds = slider.bounding_box()
    assert slider_bounds is not None
    slider.click(
        position={
            "x": slider_bounds["width"] * 0.7,
            "y": slider_bounds["height"] * 0.5,
        }
    )
    assert int(slider.input_value()) > 0

    undo_button.click()
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-freeform-canvas > .seurat-dropcell').length === 2"
    )
    redo_button.click()
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-freeform-canvas > .seurat-dropcell').length === 3"
    )

    slider.focus()
    slider.press("Control+Z")
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-freeform-canvas > .seurat-dropcell').length === 2"
    )

    assert page_errors == []
    assert console_errors == [], response_errors


def test_visualization_drop_on_inactive_pane_moves_and_activates_it(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    pane_one_bar = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    _split_workspace_pane_by_drag(page, pane_one_bar, "horizontal")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Uniform", exact=True).click()
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("tab", name="View 1").click()

    source_grid = page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-1"]'
    )
    source_grid.wait_for(state="visible")
    source = source_grid.locator('.seurat-dropcell[data-cell-index="0"]')
    destination = page.locator(
        '.seurat-workspace-grid-preview[data-pane-frame-id="pane-2"] '
        '.seurat-workspace-preview-cell[data-cell-index="2"]'
    )
    destination.wait_for(state="visible")

    source.drag_to(destination)

    destination_grid = page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-2"]'
    )
    destination_grid.wait_for(state="visible")
    destination_grid.locator(
        '.seurat-dropcell[data-cell-index="2"]'
    ).get_by_text("internal_energy", exact=True).wait_for(state="visible")
    assert page.get_by_role("tab", name="View 2").get_attribute(
        "aria-selected"
    ) == "true"
    assert page.locator(
        '.seurat-workspace-grid-preview[data-pane-frame-id="pane-1"] '
        '.seurat-workspace-preview-cell[data-cell-index="0"]'
    ).get_attribute("data-cell-filled") == "0"
    assert page.locator(
        ".seurat-workspace-grid-preview.is-visualization-drop-target"
    ).count() == 0
    assert page.locator(".seurat-dropcell.seurat-drop-hover").count() == 0

    assert page_errors == []
    assert console_errors == [], response_errors


def test_vertical_split_keeps_inactive_grid_backgrounds_visible(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    _split_workspace_pane_by_drag(page, first_bar, "vertical")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    page.get_by_role("tab", name="View 1").click()
    lower_preview = page.locator(
        ".seurat-workspace-grid-preview.seurat-workspace-slot-second"
    )
    lower_preview.wait_for(state="visible")
    assert lower_preview.locator(".seurat-workspace-preview-cell").evaluate_all(
        "cells => cells.every(cell => getComputedStyle(cell).backgroundColor === 'rgb(255, 255, 255)')"
    )

    page.get_by_role("tab", name="View 2").click()
    upper_preview = page.locator(
        ".seurat-workspace-grid-preview.seurat-workspace-slot-first"
    )
    upper_preview.wait_for(state="visible")
    assert upper_preview.locator(".seurat-plot1d").evaluate(
        "plot => getComputedStyle(plot).backgroundColor === 'rgb(255, 255, 255)'"
    )

    assert page_errors == []
    assert console_errors == [], response_errors


def test_split_pane_slider_updates_inactive_1d_plot(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    _split_workspace_pane_by_drag(page, first_bar, "horizontal")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    preview = page.locator(
        '.seurat-workspace-grid-preview[data-pane-frame-id="pane-1"]'
    )
    cursor = preview.locator(".seurat-plot1d-cursor-line")
    cursor.wait_for(state="attached")
    initial_x = float(cursor.get_attribute("x1"))

    slider = page.locator("#seurat-vcr-step-slider")
    slider_bounds = slider.bounding_box()
    assert slider_bounds is not None
    slider.click(
        position={
            "x": slider_bounds["width"] * 0.8,
            "y": slider_bounds["height"] * 0.5,
        }
    )
    selected_step = int(slider.input_value())
    assert selected_step > 0
    page.wait_for_function(
        "step => document.querySelector('#seurat-vcr-time-value').textContent === 'Step = ' + step",
        arg=selected_step,
    )

    split_x = float(cursor.get_attribute("x1"))
    assert split_x > initial_x

    page.get_by_role("tab", name="View 1").click()
    active_cursor = page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-1"] '
        ".seurat-plot1d-cursor-line"
    )
    active_cursor.wait_for(state="attached")
    page.wait_for_function(
        "step => document.querySelector('#seurat-vcr-time-value').textContent === 'Step = ' + step",
        arg=selected_step,
    )
    active_frame = page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-1"] '
        ".seurat-plot1d svg rect"
    ).first
    frame_x = float(active_frame.get_attribute("x"))
    frame_width = float(active_frame.get_attribute("width"))
    active_cursor_x = float(active_cursor.get_attribute("x1"))
    assert (active_cursor_x - frame_x) / frame_width == pytest.approx(
        selected_step / 79.0, abs=0.01
    )
    assert page_errors == []
    assert console_errors == [], response_errors


def test_split_pane_tab_switch_keeps_2d_image_fitted(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    first_bar.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    page.get_by_role("tab", name="View 1").click()
    page.wait_for_function(
        "document.querySelector('[data-tab-id=\"tab-1\"]')"
        ".classList.contains('is-pane-tab-active')"
    )
    _split_workspace_pane_by_drag(page, first_bar, "horizontal")
    page.get_by_role("tab", name="View 3").wait_for(state="visible")

    preview_image = page.locator(
        '.seurat-workspace-grid-preview[data-pane-frame-id="pane-1"] '
        '.seurat-workspace-preview-media img[data-grid-image-sequence="1"]'
    )
    preview_image.wait_for(state="visible")
    preview_geometry = preview_image.evaluate(
        """image => {
            const imageBounds = image.getBoundingClientRect();
            const parentBounds = image.parentElement.getBoundingClientRect();
            return {
                className: image.className,
                objectFit: getComputedStyle(image).objectFit,
                width: imageBounds.width,
                height: imageBounds.height,
                parentWidth: parentBounds.width,
                parentHeight: parentBounds.height,
            };
        }"""
    )
    assert "seurat-workspace-preview-image" in preview_geometry["className"]
    assert preview_geometry["objectFit"] == "contain"
    assert preview_geometry["width"] == pytest.approx(
        preview_geometry["parentWidth"], abs=1
    )
    assert preview_geometry["height"] == pytest.approx(
        preview_geometry["parentHeight"], abs=1
    )

    page.get_by_role("tab", name="View 2").click()
    page.get_by_role("tab", name="View 1").click()
    active_viewport = page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-1"] '
        ".seurat-panzoom-viewport"
    )
    active_viewport.wait_for(state="visible")
    assert active_viewport.evaluate(
        "viewport => ({ ...viewport.__seuratPanZoomState })"
    ) == pytest.approx({"scale": 1, "tx": 0, "ty": 0})

    page.get_by_role("tab", name="View 3").click()
    preview_image.wait_for(state="visible")
    page.get_by_role("tab", name="View 1").click()
    active_viewport.wait_for(state="visible")
    assert active_viewport.evaluate(
        "viewport => ({ ...viewport.__seuratPanZoomState })"
    ) == pytest.approx({"scale": 1, "tx": 0, "ty": 0})

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_can_create_a_nested_three_pane_layout(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    pane_one = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    _split_workspace_pane_by_drag(page, pane_one, "horizontal")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    page.get_by_role("tab", name="View 1").click()
    page.wait_for_function(
        "document.querySelector('[data-tab-id=\"tab-1\"]')"
        ".classList.contains('is-pane-tab-active')"
    )
    _split_workspace_pane_by_drag(page, pane_one, "vertical")
    page.get_by_role("tab", name="View 3").wait_for(state="visible")

    pane_two = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-2"]'
    )
    pane_three = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-3"]'
    )
    pane_one_bounds = pane_one.bounding_box()
    pane_two_bounds = pane_two.bounding_box()
    pane_three_bounds = pane_three.bounding_box()
    assert pane_one_bounds is not None
    assert pane_two_bounds is not None
    assert pane_three_bounds is not None

    assert page.locator(".seurat-workspace-tab-bar").count() == 3
    assert page.locator(".seurat-workspace-splitter").count() == 2
    assert page.locator(".seurat-main-grid").count() == 3
    assert pane_two_bounds["x"] > pane_one_bounds["x"] + pane_one_bounds["width"] - 2
    assert pane_three_bounds["x"] == pytest.approx(pane_one_bounds["x"], abs=2)
    assert pane_three_bounds["y"] > pane_one_bounds["y"]
    assert pane_three_bounds["width"] == pytest.approx(
        pane_one_bounds["width"], abs=2
    )

    root_splitter = page.locator(
        '.seurat-workspace-splitter[data-split-id="split-1"]'
    )
    _drag(page, root_splitter, delta_x=-60, release=False)
    assert page.locator(
        ".seurat-workspace-tab-dock-preview.is-split-resize-first"
    ).count() == 2
    assert page.locator(
        ".seurat-workspace-tab-dock-preview.is-split-resize-second"
    ).count() == 1
    assert "% / " in root_splitter.locator(
        ".seurat-workspace-split-readout"
    ).text_content()
    page.mouse.up()
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-workspace-tab-dock-preview.is-split-resize-first, "
        ".seurat-workspace-tab-dock-preview.is-split-resize-second'"
        ").length === 0"
    )

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_splitter_resizes_and_resets_panes(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    pane_one = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    _split_workspace_pane_by_drag(page, pane_one, "horizontal")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    splitter = page.locator(
        '.seurat-workspace-splitter[data-split-id="split-1"]'
    )
    splitter.wait_for(state="visible")
    initial_width = pane_one.bounding_box()["width"]

    _drag(page, splitter, delta_x=120, release=False)
    assert "is-resizing" in (splitter.get_attribute("class") or "")
    readout = splitter.locator(".seurat-workspace-split-readout")
    assert readout.is_visible()
    assert "% / " in readout.text_content()
    assert page.locator(
        ".seurat-workspace-tab-dock-preview.is-split-resize-first"
    ).count() == 1
    assert page.locator(
        ".seurat-workspace-tab-dock-preview.is-split-resize-second"
    ).count() == 1
    live_width = pane_one.bounding_box()["width"]
    live_ratio = splitter.get_attribute("data-split-ratio")
    live_pane_width = pane_one.evaluate(
        "element => element.style.getPropertyValue('--pane-width')"
    )
    assert live_width > initial_width + 80, (
        live_ratio,
        live_pane_width,
        readout.text_content(),
    )
    page.mouse.up()
    page.wait_for_function(
        "Number(document.querySelector('[data-split-id=\"split-1\"]')"
        ".getAttribute('data-split-ratio')) > 0.55"
    )
    resized_width = pane_one.bounding_box()["width"]
    assert resized_width > initial_width + 80
    assert splitter.get_attribute("aria-valuenow") == str(
        round(float(splitter.get_attribute("data-split-ratio")) * 100)
    )
    page.wait_for_function(
        "getComputedStyle(document.querySelector("
        "'.seurat-workspace-split-readout')).opacity === '0'"
    )
    assert readout.text_content() == ""
    assert page.locator(
        ".seurat-workspace-tab-dock-preview.is-split-resize-first, "
        ".seurat-workspace-tab-dock-preview.is-split-resize-second"
    ).count() == 0

    splitter.dblclick()
    page.wait_for_function(
        "Math.abs(Number(document.querySelector('[data-split-id=\"split-1\"]')"
        ".getAttribute('data-split-ratio')) - 0.5) < 0.001"
    )
    assert pane_one.bounding_box()["width"] == pytest.approx(initial_width, abs=3)

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_tabs_preserve_independent_grid_track_sizes(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    first_bar.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Uniform", exact=True).click()
    page.get_by_role("button", name="Settings", exact=True).click()

    grid = page.locator(".seurat-workspace-active-grid")
    original_sizes = grid.get_attribute("data-grid-column-sizes")
    handle = grid.locator(
        '.seurat-dropcell[data-cell-index="0"] '
        '.seurat-grid-col-resize-handle[data-resize-edge="right"]'
    )
    _drag(page, handle, delta_x=45)
    page.wait_for_function(
        "Number(document.querySelector('.seurat-workspace-active-grid')"
        ".getAttribute('data-grid-column-sizes').split(',')[0]) > 320"
    )
    resized_sizes = grid.get_attribute("data-grid-column-sizes")
    assert resized_sizes != original_sizes

    page.get_by_role("tab", name="View 1").click()
    page.wait_for_function(
        "document.querySelector('.seurat-workspace-active-grid')"
        ".getAttribute('data-grid-column-sizes') === "
        f"{original_sizes!r}"
    )
    assert grid.get_attribute("data-grid-column-sizes") == original_sizes

    page.get_by_role("tab", name="View 2").click()
    page.wait_for_function(
        "document.querySelector('.seurat-workspace-active-grid')"
        ".getAttribute('data-grid-column-sizes') === "
        f"{resized_sizes!r}"
    )
    assert grid.get_attribute("data-grid-column-sizes") == resized_sizes

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_tabs_drag_to_reorder_with_insertion_feedback(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    add_tab = first_bar.get_by_role("button", name="New tab")
    add_tab.click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    add_tab.click()
    page.get_by_role("tab", name="View 3").wait_for(state="visible")

    source = page.get_by_role("tab", name="View 1")
    destination = page.get_by_role("tab", name="View 3")
    source_bounds = source.bounding_box()
    destination_bounds = destination.bounding_box()
    assert source_bounds is not None
    assert destination_bounds is not None

    page.mouse.move(
        source_bounds["x"] + source_bounds["width"] / 2,
        source_bounds["y"] + source_bounds["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        destination_bounds["x"] + destination_bounds["width"] * 0.8,
        destination_bounds["y"] + destination_bounds["height"] / 2,
        steps=8,
    )
    page.wait_for_function(
        "document.querySelectorAll('.seurat-workspace-tab-shell.is-tab-drop-after').length === 1"
    )
    assert source.get_attribute("aria-grabbed") == "true"
    page.mouse.up()

    page.wait_for_function(
        """() => Array.from(document.querySelectorAll('.seurat-workspace-tab'))
            .map(tab => tab.textContent.trim()).join(',') === 'View 2,View 3,View 1'"""
    )
    assert page.locator(".seurat-workspace-tab-shell.is-tab-dragging").count() == 0
    assert page.locator(
        ".seurat-workspace-tab-shell.is-tab-drop-before, "
        ".seurat-workspace-tab-shell.is-tab-drop-after"
    ).count() == 0
    assert page.get_by_role("tab", name="View 3").get_attribute(
        "aria-selected"
    ) == "true"

    page.get_by_role("tab", name="View 1").click()
    page.locator(".seurat-workspace-active-grid").get_by_text(
        "internal_energy", exact=True
    ).wait_for(state="visible")

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_tabs_drag_between_panes_at_the_drop_position(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    pane_one = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    pane_one.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    _split_workspace_pane_by_drag(page, pane_one, "horizontal")
    page.get_by_role("tab", name="View 3").wait_for(state="visible")
    page.wait_for_function(
        """() => {
            const first = document.querySelector(
              '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
            );
            const second = document.querySelector(
              '.seurat-workspace-tab-bar[data-pane-frame-id="pane-2"]'
            );
            if (!first || !second) return false;
            const firstBounds = first.getBoundingClientRect();
            const secondBounds = second.getBoundingClientRect();
            return secondBounds.left >= firstBounds.right - 2;
        }"""
    )

    source = page.get_by_role("tab", name="View 1")
    destination = page.get_by_role("tab", name="View 3")
    source_bounds = source.bounding_box()
    destination_bounds = destination.bounding_box()
    assert source_bounds is not None
    assert destination_bounds is not None

    source.drag_to(
        destination,
        target_position={
            "x": destination_bounds["width"] * 0.2,
            "y": destination_bounds["height"] / 2,
        },
    )

    page.wait_for_function(
        """() => {
            const paneOne = document.querySelector(
              '.seurat-workspace-tabs[data-pane-id="pane-1"]'
            );
            const paneTwo = document.querySelector(
              '.seurat-workspace-tabs[data-pane-id="pane-2"]'
            );
            const titles = element => Array.from(
              element.querySelectorAll('.seurat-workspace-tab')
            ).map(tab => tab.textContent.trim()).join(',');
            return paneOne && paneTwo
              && titles(paneOne) === 'View 2'
              && titles(paneTwo) === 'View 1,View 3';
        }"""
    )
    assert page.get_by_role("tab", name="View 1").get_attribute(
        "aria-selected"
    ) == "true"
    page.locator(".seurat-workspace-active-grid").get_by_text(
        "internal_energy", exact=True
    ).wait_for(state="visible")
    assert page.locator(".seurat-workspace-tabs.is-tab-drop-target").count() == 0
    assert page.locator(
        ".seurat-workspace-tab-shell.is-tab-drop-before, "
        ".seurat-workspace-tab-shell.is-tab-drop-after"
    ).count() == 0

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_tab_drag_to_right_edge_creates_split_and_undoes_once(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    first_bar.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    source = page.get_by_role("tab", name="View 1")
    source_bounds = source.bounding_box()
    target_bounds = first_bar.bounding_box()
    assert source_bounds is not None
    assert target_bounds is not None

    page.mouse.move(
        source_bounds["x"] + source_bounds["width"] / 2,
        source_bounds["y"] + source_bounds["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        source_bounds["x"] + source_bounds["width"] / 2 + 12,
        source_bounds["y"] + source_bounds["height"] / 2,
        steps=3,
    )
    page.wait_for_function(
        "document.querySelector('.v-application')"
        ".classList.contains('is-workspace-tab-dragging')"
    )
    dock_preview = page.locator(
        '.seurat-workspace-tab-dock-preview[data-tab-dock-pane-id="pane-1"]'
    )
    right_target = dock_preview.locator(
        '.seurat-workspace-tab-dock-target[data-tab-dock-direction="horizontal"]'
    )
    bottom_target = dock_preview.locator(
        '.seurat-workspace-tab-dock-target[data-tab-dock-direction="vertical"]'
    )
    preview_bounds = dock_preview.bounding_box()
    right_bounds = right_target.bounding_box()
    bottom_bounds = bottom_target.bounding_box()
    assert preview_bounds is not None
    assert right_bounds is not None
    assert bottom_bounds is not None
    assert right_bounds["width"] == pytest.approx(
        preview_bounds["width"] * 0.15, abs=2
    )
    assert bottom_bounds["height"] == pytest.approx(
        preview_bounds["height"] * 0.15, abs=2
    )
    page.mouse.move(
        target_bounds["x"] + target_bounds["width"] - 12,
        source_bounds["y"] + source_bounds["height"] / 2,
        steps=10,
    )
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-workspace-tab-dock-target.is-tab-dock-active.is-tab-dock-right'"
        ").length === 1"
    )
    page.mouse.up()

    page.get_by_role("tab", name="View 1").wait_for(state="visible")
    page.wait_for_function(
        "document.querySelectorAll('.seurat-workspace-tab-bar').length === 2"
    )
    assert page.locator(
        '.seurat-workspace-tabs[data-pane-id="pane-1"] .seurat-workspace-tab'
    ).all_text_contents() == ["View 2"]
    assert page.locator(
        '.seurat-workspace-tabs[data-pane-id="pane-2"] .seurat-workspace-tab'
    ).all_text_contents() == ["View 1"]
    assert page.get_by_role("tab", name="View 1").get_attribute(
        "aria-selected"
    ) == "true"
    assert page.locator(
        ".seurat-workspace-tab-dock-target.is-tab-dock-active"
    ).count() == 0
    assert page.locator(
        '.seurat-workspace-splitter[data-split-direction="horizontal"]'
    ).count() == 1

    undo_button = page.locator(".seurat-history-button").first
    assert "Undo Split tab" in undo_button.get_attribute("title")
    undo_button.click()
    page.wait_for_function(
        "document.querySelectorAll('.seurat-workspace-tab-bar').length === 1"
    )
    assert page.locator(".seurat-workspace-tab").all_text_contents() == [
        "View 1",
        "View 2",
    ]

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_only_tab_drag_to_bottom_leaves_empty_source_tab(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    source = page.get_by_role("tab", name="View 1")
    target = page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-1"]'
    )
    source_bounds = source.bounding_box()
    target_bounds = target.bounding_box()
    assert source_bounds is not None
    assert target_bounds is not None

    page.mouse.move(
        source_bounds["x"] + source_bounds["width"] / 2,
        source_bounds["y"] + source_bounds["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        target_bounds["x"] + target_bounds["width"] / 2,
        target_bounds["y"] + target_bounds["height"] - 12,
        steps=10,
    )
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-workspace-tab-dock-target.is-tab-dock-active.is-tab-dock-bottom'"
        ").length === 1"
    )
    page.mouse.up()

    page.wait_for_function(
        "document.querySelectorAll('.seurat-workspace-tab-bar').length === 2"
    )
    assert page.locator(
        '.seurat-workspace-tabs[data-pane-id="pane-1"] .seurat-workspace-tab'
    ).all_text_contents() == ["View 2"]
    assert page.locator(
        '.seurat-workspace-tabs[data-pane-id="pane-2"] .seurat-workspace-tab'
    ).all_text_contents() == ["View 1"]
    assert page.locator(
        '.seurat-workspace-splitter[data-split-direction="vertical"]'
    ).count() == 1
    page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-2"]'
    ).get_by_text("internal_energy", exact=True).wait_for(state="visible")
    empty_preview = page.locator(
        '.seurat-workspace-grid-preview[data-pane-frame-id="pane-1"]'
    )
    assert empty_preview.locator(".seurat-dropcell").count() == 0

    assert page_errors == []
    assert console_errors == [], response_errors


def test_tab_context_menu_renames_and_closes_with_icons(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    first_bar.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    page.get_by_role("tab", name="View 1").click(button="right")
    menu = page.locator("#seurat-context-menu")
    menu.get_by_text("View 1", exact=True).wait_for(state="visible")
    assert menu.locator(".mdi-pencil-outline").count() == 1
    assert menu.locator(".mdi-close").count() == 1

    page.once("dialog", lambda dialog: dialog.accept("Overview"))
    menu.get_by_text("Rename…", exact=True).click()
    page.get_by_role("tab", name="Overview").wait_for(state="visible")

    page.get_by_role("tab", name="Overview").click(button="right")
    menu.get_by_text("Close", exact=True).wait_for(state="visible")
    page.once("dialog", lambda dialog: dialog.accept())
    menu.get_by_text("Close", exact=True).click()
    page.get_by_role("tab", name="Overview").wait_for(state="detached")
    assert page.locator(".seurat-workspace-tab").count() == 1

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_tab_close_button_is_visible_for_active_and_hovered_tabs(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    first_bar.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    active_close = first_bar.get_by_role("button", name="Close View 2")
    inactive_tab = page.get_by_role("tab", name="View 1")
    inactive_shell = inactive_tab.locator("xpath=..")
    inactive_close = inactive_shell.get_by_role("button", name="Close View 1")

    assert active_close.evaluate("button => getComputedStyle(button).opacity") == "1"
    assert inactive_close.evaluate("button => getComputedStyle(button).opacity") == "0"
    inactive_shell.hover()
    page.wait_for_function(
        "getComputedStyle(document.querySelector('[aria-label=\"Close View 1\"]')).opacity === '1'"
    )

    page.once("dialog", lambda dialog: dialog.accept())
    inactive_close.click()
    inactive_tab.wait_for(state="detached")
    assert page.locator(".seurat-workspace-tab").count() == 1
    assert first_bar.locator(".seurat-workspace-tab-close").count() == 0

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_tab_strip_marks_hidden_tabs_at_each_scroll_edge(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    add_tab = first_bar.get_by_role("button", name="New tab")
    for expected_count in range(2, 19):
        add_tab.click()
        page.wait_for_function(
            "expected => document.querySelectorAll('.seurat-workspace-tab').length === expected",
            arg=expected_count,
        )

    viewport = first_bar.locator(".seurat-workspace-tabs-viewport")
    tabs = viewport.locator(".seurat-workspace-tabs")
    active_tab = page.get_by_role("tab", name="View 18")
    page.wait_for_function(
        "document.querySelector('.seurat-workspace-tabs').scrollLeft > 0"
    )
    assert active_tab.evaluate(
        """tab => {
            const strip = tab.closest('.seurat-workspace-tabs');
            const tabBounds = tab.getBoundingClientRect();
            const stripBounds = strip.getBoundingClientRect();
            return tabBounds.left >= stripBounds.left
                && tabBounds.right <= stripBounds.right + 1;
        }"""
    )
    assert add_tab.evaluate(
        """button => {
            const stripBounds = button.parentElement.getBoundingClientRect();
            const buttonBounds = button.getBoundingClientRect();
            return buttonBounds.left >= stripBounds.left
                && buttonBounds.right <= stripBounds.right + 1;
        }"""
    )

    tabs.evaluate("element => { element.scrollLeft = 0; }")
    page.wait_for_function(
        "document.querySelector('.seurat-workspace-tabs-viewport').classList.contains('has-overflow-right')"
    )
    assert viewport.evaluate("element => element.classList.contains('has-overflow-left')") is False

    tabs.evaluate("element => { element.scrollLeft = element.scrollWidth; }")
    page.wait_for_function(
        "document.querySelector('.seurat-workspace-tabs-viewport').classList.contains('has-overflow-left')"
    )
    assert viewport.evaluate("element => element.classList.contains('has-overflow-right')") is False

    assert page_errors == []
    assert console_errors == [], response_errors


def test_query_assistant_reviews_before_applying(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    page.get_by_role("button", name="Ask").click()
    page.get_by_text("Query Assistant", exact=True).wait_for(state="visible")
    page.get_by_label("Request").fill("Show internal energy")
    page.get_by_role("button", name="Translate").click()

    proposal = page.get_by_label("Resolved Advanced Query")
    proposal.wait_for(state="visible")
    assert proposal.input_value() == "var == 'internal_energy'"
    assert page.get_by_text(
        "Select variables for internal_energy.", exact=True
    ).is_visible()
    assert page.get_by_text("Valid · 1 variable", exact=True).is_visible()

    page.get_by_role("button", name="Apply").click()
    page.get_by_text("Query Assistant", exact=True).wait_for(state="hidden")
    assert page.locator(
        'input[placeholder^="e.g. var =="]'
    ).input_value() == "var == 'internal_energy'"

    assert page_errors == []
    assert console_errors == [], response_errors


def test_query_assistant_panel_drags(page, seurat_server):
    _open_app(page, seurat_server)

    page.get_by_role("button", name="Ask").click()
    panel = page.locator("#seurat-query-assistant-panel")
    panel.wait_for(state="visible")
    handle = panel.locator(".seurat-floating-panel-drag-handle")
    initial = panel.bounding_box()
    assert initial is not None

    _drag(page, handle, delta_x=48, delta_y=32)
    moved = panel.bounding_box()
    assert moved["x"] == pytest.approx(initial["x"] + 48, abs=2)
    assert moved["y"] == pytest.approx(initial["y"] + 32, abs=2)
    assert not panel.evaluate("panel => panel.classList.contains('is-dragging')")


def test_visualization_assistant_reviews_before_adding_to_grid(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    target_cell = page.locator('.seurat-dropcell[data-cell-index="2"]')
    target_cell.click()
    page.wait_for_function(
        "document.querySelector('.seurat-dropcell[data-cell-index=\"2\"]')"
        ".getAttribute('data-cell-active') === '1'"
    )
    assert target_cell.get_by_text("current_z", exact=True).count() == 0

    page.get_by_role("button", name="Visualize").click()
    page.get_by_text("Visualization Assistant", exact=True).wait_for(
        state="visible"
    )
    page.get_by_label("Request").fill("Show current_z in the selected cell")
    page.get_by_role("button", name="Translate").click()

    page.get_by_text(
        "Valid · current_z · grid cell 3", exact=True
    ).wait_for(state="visible")
    assert target_cell.get_by_text("current_z", exact=True).count() == 0

    page.get_by_role("button", name="Add to Grid").click()
    page.get_by_text("Visualization Assistant", exact=True).wait_for(
        state="hidden"
    )
    target_cell.get_by_text("current_z", exact=True).wait_for(state="visible")

    assert page_errors == []
    assert console_errors == [], response_errors


def test_source_filter_uses_query_assistant_without_changing_global_query(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    global_query = page.locator('input[placeholder^="e.g. var =="]')
    initial_global_query = global_query.input_value()
    page.get_by_role("button", name="SOURCES(2)").click()
    page.get_by_text("Sources: internal_energy", exact=True).wait_for(
        state="visible"
    )
    source_request = page.get_by_placeholder(
        "Natural language + Ask, or Advanced Query + Filter"
    )
    source_request.fill(
        'max > 5.0 and source dataset name contains "128"'
    )
    page.get_by_title("Interpret as natural language").click()

    page.get_by_text("Source Filter Assistant", exact=True).wait_for(
        state="visible"
    )
    assert page.get_by_label("Request").input_value() == (
        'max > 5.0 and source dataset name contains "128"'
    )
    page.get_by_role("button", name="Translate").click()
    page.get_by_text("Valid · 1 source row", exact=True).wait_for(
        state="visible"
    )

    assert global_query.input_value() == initial_global_query
    page.get_by_role("button", name="Apply to Source Filter").click()

    page.get_by_text("Source Filter Assistant", exact=True).wait_for(
        state="hidden"
    )
    assert source_request.input_value() == (
        'max > 5.0 and contains(source_dataset, "128")'
    )
    assert page.get_by_text("run-128/output.bp", exact=True).count() >= 1
    assert page.get_by_text("run-64/output.bp", exact=True).count() == 0
    assert global_query.input_value() == initial_global_query

    assert page_errors == []
    assert console_errors == [], response_errors


def test_scalar_field_axes_and_backgrounds_use_automatic_contrast(
    page,
    seurat_server,
):
    console_errors, page_errors, response_errors = _open_app(
        page,
        seurat_server,
        mode="scalar",
    )

    black_view = page.locator(
        '.seurat-dropcell[data-cell-index="0"] .seurat-scalar-field-view'
    )
    white_view = page.locator(
        '.seurat-dropcell[data-cell-index="1"] .seurat-scalar-field-view'
    )

    for view in (black_view, white_view):
        assert view.locator('[data-scalar-axis="x"]').is_visible()
        assert view.locator('[data-scalar-axis="y"]').is_visible()
        assert view.locator(".seurat-scalar-field-x-tick").count() == 3
        assert view.locator(".seurat-scalar-field-y-tick").count() == 3
        assert view.locator(".seurat-scalar-field-x-label").text_content() == "R"
        assert view.locator(".seurat-scalar-field-y-label").text_content() == "Z"

    assert black_view.evaluate(
        "view => getComputedStyle(view).backgroundColor"
    ) == "rgb(0, 0, 0)"
    assert black_view.locator(".seurat-scalar-field-x-tick").first.evaluate(
        "tick => getComputedStyle(tick).color"
    ) == "rgb(255, 255, 255)"
    assert black_view.locator(".seurat-scalar-field-x-axis").evaluate(
        "axis => getComputedStyle(axis).borderTopColor"
    ) == "rgb(255, 255, 255)"

    assert white_view.evaluate(
        "view => getComputedStyle(view).backgroundColor"
    ) == "rgb(255, 255, 255)"
    assert white_view.locator(".seurat-scalar-field-x-tick").first.evaluate(
        "tick => getComputedStyle(tick).color"
    ) == "rgb(17, 17, 17)"
    assert white_view.locator(".seurat-scalar-field-x-axis").evaluate(
        "axis => getComputedStyle(axis).borderTopColor"
    ) == "rgb(17, 17, 17)"

    black_viewport = black_view.locator(".seurat-panzoom-viewport")
    page.wait_for_function(
        """() => Boolean(
            document.querySelector(
                '.seurat-dropcell[data-cell-index="0"] .seurat-panzoom-viewport'
            ).__seuratScalarFieldDataRect
        )"""
    )
    data_rect = black_viewport.evaluate(
        "viewport => ({ ...viewport.__seuratScalarFieldDataRect })"
    )
    x_axis_box = black_view.locator(
        ".seurat-scalar-field-x-axis"
    ).bounding_box()
    y_axis_box = black_view.locator(
        ".seurat-scalar-field-y-axis"
    ).bounding_box()
    assert x_axis_box["width"] == pytest.approx(data_rect["width"], abs=1)
    assert y_axis_box["height"] == pytest.approx(data_rect["height"], abs=1)

    def axis_values(axis):
        return black_view.locator(
            f'.seurat-scalar-field-{axis}-axis'
        ).evaluate(
            """axis => Array.from(axis.querySelectorAll('[data-axis-value]'))
                .map(tick => Number(tick.getAttribute('data-axis-value')))"""
        )

    initial_x = axis_values("x")
    initial_y = axis_values("y")
    viewport_box = black_viewport.bounding_box()
    page.mouse.move(
        viewport_box["x"] + data_rect["left"] + data_rect["width"] / 2,
        viewport_box["y"] + data_rect["top"] + data_rect["height"] / 2,
    )
    page.mouse.wheel(0, -120)
    zoomed_x = axis_values("x")
    zoomed_y = axis_values("y")
    assert zoomed_x[-1] - zoomed_x[0] < initial_x[-1] - initial_x[0]
    assert zoomed_y[-1] - zoomed_y[0] < initial_y[-1] - initial_y[0]

    page.keyboard.down("Shift")
    _drag(page, black_viewport, delta_x=30)
    page.keyboard.up("Shift")
    panned_x = axis_values("x")
    assert panned_x[0] != pytest.approx(zoomed_x[0])

    black_viewport.dblclick()
    assert axis_values("x") == pytest.approx(initial_x)
    assert axis_values("y") == pytest.approx(initial_y)

    assert page_errors == []
    assert console_errors == [], response_errors


def test_scalar_field_contour_controls_follow_render_mode(
    page,
    seurat_server,
):
    console_errors, page_errors, response_errors = _open_app(
        page,
        seurat_server,
        mode="scalar-settings",
    )

    panel = page.locator("#seurat-scalar-field-settings-panel")
    panel.wait_for(state="visible")
    section_titles = panel.locator(".seurat-scalar-field-section-title")
    heatmap = section_titles.nth(0).locator('input[type="checkbox"]')
    contour = section_titles.nth(1).locator('input[type="checkbox"]')
    sections = panel.locator(".seurat-scalar-field-layer-section")
    display_section = panel.locator(".seurat-plot-settings-section").nth(0)
    heatmap_section = sections.nth(0)
    contour_section = panel.locator(".seurat-scalar-field-contour-section")
    background = display_section.locator(
        ".seurat-scalar-field-background-toggle"
    )
    axes = display_section.locator('input[type="checkbox"]')
    colormap_row = heatmap_section.locator(
        ".seurat-scalar-field-compact-row"
    ).nth(0)
    range_row = heatmap_section.locator(
        ".seurat-scalar-field-compact-row"
    ).nth(1)
    colormap = colormap_row.locator(".seurat-scalar-field-colormap")
    colorbar = colormap_row.locator('input[type="checkbox"]')

    assert heatmap.is_checked()
    assert not contour.is_checked()
    assert (
        panel.locator(".seurat-plot-settings-section-title")
        .first.text_content()
        .strip()
        == "Display"
    )
    assert axes.count() == 1
    assert background.evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgb(0, 0, 0)"
    assert not colormap.is_disabled()
    assert not colorbar.is_disabled()
    assert range_row.get_by_text("Range", exact=True).is_visible()
    assert range_row.get_by_text("Auto", exact=True).is_visible()
    assert range_row.get_by_label("Min").is_disabled()
    assert range_row.get_by_label("Max").is_disabled()
    assert contour_section.locator(
        ".seurat-scalar-field-contour-color"
    ).is_disabled()

    background.click()
    page.wait_for_function(
        """() => getComputedStyle(
            document.querySelector('.seurat-scalar-field-background-toggle')
        ).backgroundColor === 'rgb(255, 255, 255)'"""
    )
    background.click()
    page.wait_for_function(
        """() => getComputedStyle(
            document.querySelector('.seurat-scalar-field-background-toggle')
        ).backgroundColor === 'rgb(0, 0, 0)'"""
    )

    contour.check()
    assert contour_section.is_visible()
    assert not colormap.is_disabled()
    assert not colorbar.is_disabled()
    contour_color = contour_section.locator(
        ".seurat-scalar-field-contour-color"
    )
    assert not contour_color.is_disabled()

    heatmap.uncheck()
    assert colormap.is_disabled()
    assert colorbar.is_disabled()

    range_radio = contour_section.get_by_label("Range", exact=True)
    values_radio = contour_section.get_by_label("Values", exact=True)
    assert range_radio.is_checked()
    assert contour_section.get_by_label("Min").input_value() == "-1"
    assert contour_section.get_by_label("Max").input_value() == "1"
    assert contour_section.get_by_label("Number").input_value() == "5"

    values_radio.check()
    values = panel.locator(".seurat-scalar-field-contour-values input")
    values.wait_for(state="visible")
    assert values.input_value() == "-1, 0, 1"

    contour_color.click()
    color_popup = page.locator(".seurat-plot-settings-color-popup").last
    color_popup.wait_for(state="visible")
    color_popup.locator('button[title="#ff0000"]').click()
    page.wait_for_function(
        """() => getComputedStyle(
            document.querySelector('.seurat-scalar-field-contour-color')
        ).backgroundColor === 'rgb(255, 0, 0)'"""
    )

    heatmap.check()
    assert not colormap.is_disabled()
    assert not colorbar.is_disabled()
    assert contour_section.is_visible()

    assert page_errors == []
    assert console_errors == [], response_errors


def test_workspace_commands_are_in_hamburger_drawer(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(
        page,
        seurat_server,
    )

    drawer = page.locator(".v-navigation-drawer")
    assert not drawer.is_visible()
    page.locator(".v-app-bar-nav-icon").click()
    drawer.wait_for(state="visible")
    assert drawer.get_by_text("Save", exact=True).is_visible()
    assert drawer.get_by_text("Save As…", exact=True).is_visible()
    assert drawer.get_by_text("Load…", exact=True).is_visible()
    assert drawer.get_by_text("No state file selected", exact=True).is_visible()

    drawer.get_by_text("Save", exact=True).click()
    drawer.get_by_text("/tmp/browser-step.json", exact=True).wait_for(state="visible")
    drawer.get_by_text(
        "Saved: /tmp/browser-step.json",
        exact=True,
    ).wait_for(state="visible")
    assert console_errors == [], response_errors
    assert page_errors == []


def test_workspace_save_and_load_restore_live_grid_track_sizes(
    page,
    seurat_server,
):
    _open_app(page, seurat_server)

    grid = page.locator(".seurat-main-grid")
    corner = page.locator(
        '.seurat-dropcell[data-cell-index="0"] '
        ".seurat-grid-corner-bottom-right"
    )
    _drag(page, corner, delta_x=55, delta_y=40)
    saved_column_sizes = grid.get_attribute("data-grid-column-sizes")
    saved_row_sizes = grid.get_attribute("data-grid-row-sizes")
    assert saved_column_sizes.startswith("335")
    assert saved_row_sizes.startswith("392")

    page.locator(".v-app-bar-nav-icon").click()
    drawer = page.locator(".v-navigation-drawer")
    drawer.wait_for(state="visible")
    drawer.get_by_text("Save", exact=True).click()
    drawer.get_by_text(
        "Saved: /tmp/browser-step.json",
        exact=True,
    ).wait_for(state="visible")

    page.locator(".v-app-bar-nav-icon").click()
    drawer.wait_for(state="detached")
    _drag(page, corner, delta_x=-35, delta_y=-25)
    assert grid.get_attribute("data-grid-column-sizes") != saved_column_sizes
    assert grid.get_attribute("data-grid-row-sizes") != saved_row_sizes

    page.locator(".v-app-bar-nav-icon").click()
    drawer.wait_for(state="visible")
    drawer.get_by_text("Load…", exact=True).click()
    page.wait_for_function(
        """([columnSizes, rowSizes]) => {
            const grid = document.querySelector('.seurat-main-grid');
            return grid
                && grid.getAttribute('data-grid-column-sizes') === columnSizes
                && grid.getAttribute('data-grid-row-sizes') === rowSizes;
        }""",
        arg=[saved_column_sizes, saved_row_sizes],
    )
    assert grid.evaluate(
        "element => getComputedStyle(element).gridTemplateColumns"
    ).startswith("335px ")
    assert (
        grid.evaluate("element => getComputedStyle(element).gridTemplateRows")
        == "392px"
    )


def test_variable_group_expands_and_collapses(page, seurat_server):
    _open_app(page, seurat_server)

    group = page.get_by_role("button", name="▾0D", exact=True)
    variable = page.locator('[title="fixture/scalars.bp/internal_energy"]')
    assert variable.is_visible()

    group.click()
    variable.wait_for(state="hidden")
    collapsed_group = page.get_by_role("button", name="▸0D", exact=True)
    assert collapsed_group.get_attribute("aria-expanded") == "false"

    collapsed_group.click()
    variable.wait_for(state="visible")
    expanded_group = page.get_by_role("button", name="▾0D", exact=True)
    assert expanded_group.get_attribute("aria-expanded") == "true"


def test_variable_catalog_search_filters_locally_and_preserves_collapse_state(
    page,
    seurat_server,
):
    _open_app(page, seurat_server)

    search = page.locator(".seurat-variable-search input")
    zero_d_group = page.get_by_role("button", name="▾0D", exact=True)
    internal_energy = page.locator('[data-item="internal_energy"]')
    current_z = page.locator('[data-item="current_z"]')

    zero_d_group.click()
    internal_energy.wait_for(state="hidden")

    search.fill("ENERGY")
    internal_energy.wait_for(state="visible")
    current_z.wait_for(state="detached")
    assert page.get_by_role("button", name="▾0D", exact=True).get_attribute(
        "aria-expanded"
    ) == "true"

    search.fill("fixture/images")
    current_z.wait_for(state="visible")
    internal_energy.wait_for(state="detached")

    search.fill("not-present")
    page.get_by_text("No matching variables", exact=True).wait_for(
        state="visible"
    )

    search.fill("")
    current_z.wait_for(state="visible")
    internal_energy.wait_for(state="hidden")
    assert page.get_by_role("button", name="▸0D", exact=True).get_attribute(
        "aria-expanded"
    ) == "false"


def test_grid_selection_assignment_and_layout_controls(page, seurat_server):
    _open_app(page, seurat_server)

    empty_cell = page.locator('.seurat-dropcell[data-cell-index="2"]')
    empty_cell.click()
    page.wait_for_function(
        "document.querySelector('.seurat-dropcell[data-cell-index=\"2\"]')"
        ".getAttribute('data-cell-active') === '1'"
    )

    variable = page.locator('[data-item="current_z"]')
    variable.drag_to(empty_cell)
    page.wait_for_function(
        "document.querySelector('.seurat-dropcell[data-cell-index=\"2\"]')"
        ".getAttribute('data-cell-filled') === '1'"
    )
    assert empty_cell.get_by_text("current_z", exact=True).is_visible()

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Grid size 1 x 3 ▾", exact=True).click()
    page.get_by_role("button", name="2 x 2", exact=True).click()
    page.wait_for_function("document.querySelectorAll('.seurat-dropcell').length === 4")


def test_freeform_canvas_drag_resize_toggles_and_variable_drop(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Freeform", exact=True).click()
    canvas = page.locator(".seurat-freeform-canvas")
    canvas.wait_for(state="visible")
    tiles = canvas.locator(":scope > .seurat-dropcell")
    assert tiles.count() == 2
    assert canvas.evaluate("element => getComputedStyle(element).backgroundImage") == "none"
    page.wait_for_function(
        """() => {
            const canvas = document.querySelector('.seurat-freeform-canvas');
            const first = document.querySelector('[data-tile-id="tile-1"]');
            const second = document.querySelector('[data-tile-id="tile-2"]');
            if (!canvas || !first || !second) return false;
            const firstBounds = first.getBoundingClientRect();
            const secondBounds = second.getBoundingClientRect();
            const expectedWidth = canvas.clientWidth * 10 / 24 - 4;
            return Math.abs(firstBounds.width - expectedWidth) < 1
                && secondBounds.left > firstBounds.left;
        }"""
    )
    first_bounds = tiles.nth(0).bounding_box()
    second_bounds = tiles.nth(1).bounding_box()
    assert first_bounds is not None
    assert second_bounds is not None
    gutter = second_bounds["x"] - (first_bounds["x"] + first_bounds["width"])
    assert 3 <= gutter <= 5
    assert page.get_by_role("button", name="Snap to grid", exact=True).get_attribute(
        "aria-pressed"
    ) == "true"
    assert page.get_by_role("button", name="Nudge others", exact=True).get_attribute(
        "aria-pressed"
    ) == "true"

    page.get_by_role("button", name="Settings", exact=True).click()
    first = canvas.locator('[data-tile-id="tile-1"]')
    _drag(page, first.locator(".seurat-tile-header"), delta_y=9 * 24)
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-y') === '9'"
    )

    second = canvas.locator('[data-tile-id="tile-2"]')
    _drag(
        page,
        second.locator(".seurat-canvas-resize-handle"),
        delta_x=90,
        delta_y=48,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-2\"]')"
        ".getAttribute('data-canvas-w') === '12'"
    )
    assert second.get_attribute("data-canvas-h") == "10"
    page.wait_for_function(
        "() => { const canvas = document.querySelector("
        "'.seurat-freeform-canvas'); const tile = document.querySelector("
        "'[data-tile-id=\"tile-2\"]'); return canvas && tile"
        " && Math.abs(tile.getBoundingClientRect().width"
        " - (canvas.clientWidth * 12 / 24 - 4)) < 1; }"
    )
    canvas_width = canvas.evaluate("element => element.clientWidth")
    _drag(
        page,
        second.locator(".seurat-canvas-resize-handle"),
        delta_x=-11 * canvas_width / 24,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-2\"]')"
        ".getAttribute('data-canvas-w') === '2'"
    )

    variable = page.locator('[data-item="internal_energy"]')
    variable.drag_to(canvas, target_position={"x": 540, "y": 340})
    page.wait_for_function(
        "document.querySelectorAll('.seurat-freeform-canvas > .seurat-dropcell').length === 3"
    )
    added = canvas.locator('[data-tile-id="tile-3"]')
    added_bounds = added.bounding_box()
    assert added_bounds is not None
    assert added.get_attribute("data-canvas-w") == "2"
    assert abs(added_bounds["width"] - added_bounds["height"]) <= 13

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Show grid", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.seurat-freeform-canvas')"
        ".classList.contains('show-grid')"
    )
    overlay = canvas.locator(".seurat-canvas-grid-overlay")
    overlay.wait_for(state="visible")
    vertical_lines = overlay.locator(".seurat-canvas-grid-line.is-vertical")
    horizontal_lines = overlay.locator(".seurat-canvas-grid-line.is-horizontal")
    assert vertical_lines.count() == 23
    assert horizontal_lines.count() >= 12
    assert overlay.evaluate("element => getComputedStyle(element).backgroundImage") == "none"
    assert vertical_lines.first.evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgba(54, 75, 98, 0.38)"
    assert vertical_lines.nth(3).evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgba(40, 62, 86, 0.58)"

    rendered_line = Image.open(
        io.BytesIO(vertical_lines.first.screenshot())
    ).convert("RGB")
    assert min(
        sum(rendered_line.getpixel((x, y)))
        for x in range(rendered_line.width)
        for y in range(rendered_line.height)
    ) <= 650

    before_columns_bounds = added.bounding_box()
    assert before_columns_bounds is not None
    page.get_by_role("button", name="48 columns", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.seurat-freeform-canvas')"
        ".getAttribute('data-canvas-cols') === '48'"
    )
    page.wait_for_timeout(180)
    after_columns_bounds = added.bounding_box()
    assert after_columns_bounds is not None
    assert abs(after_columns_bounds["width"] - before_columns_bounds["width"]) <= 2
    assert overlay.get_attribute("data-grid-columns") == "48"
    assert vertical_lines.count() == 47

    for columns in (12, 24, 36):
        page.get_by_role("button", name=f"{columns} columns", exact=True).click()
        page.wait_for_function(
            "columns => document.querySelector('.seurat-freeform-canvas')"
            ".getAttribute('data-canvas-cols') === String(columns)",
            arg=columns,
        )
        assert overlay.get_attribute("data-grid-columns") == str(columns)
        assert vertical_lines.count() == columns - 1
        overlay_bounds = overlay.bounding_box()
        first_line_bounds = vertical_lines.first.bounding_box()
        assert overlay_bounds is not None
        assert first_line_bounds is not None
        assert abs(
            first_line_bounds["x"]
            - overlay_bounds["x"]
            - overlay_bounds["width"] / columns
        ) <= 1.5
    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_new_plot_size_is_shared_across_workspace_tabs(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Freeform", exact=True).click()
    increase = page.get_by_role("button", name="Increase new plot size")
    increase.click()
    increase.click()
    page.get_by_text("4 columns", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="Settings", exact=True).click()

    first_bar = page.locator(
        ".seurat-workspace-tab-bar.seurat-workspace-slot-first"
    )
    first_bar.get_by_role("button", name="New tab").click()
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    canvas = page.locator(".seurat-freeform-canvas")
    canvas.wait_for(state="visible")
    assert canvas.get_attribute("data-canvas-default-tile-width") == "4"
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_text("4 columns", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="Settings", exact=True).click()

    page.locator('[data-item="internal_energy"]').drag_to(
        canvas,
        target_position={"x": 260, "y": 180},
    )
    page.wait_for_function(
        "document.querySelectorAll('.seurat-freeform-canvas > .seurat-dropcell').length === 1"
    )
    added = canvas.locator('[data-tile-id="tile-1"]')
    assert added.get_attribute("data-canvas-w") == "4"
    added_bounds = added.bounding_box()
    assert added_bounds is not None
    assert abs(added_bounds["width"] - added_bounds["height"]) <= 13

    page.get_by_role("tab", name="View 1").click()
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_text("4 columns", exact=True).wait_for(state="visible")
    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_crowded_drop_preserves_configured_plot_size(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(
        page, seurat_server, "freeform-column-seam"
    )

    page.get_by_role("button", name="Settings", exact=True).click()
    increase = page.get_by_role("button", name="Increase new plot size")
    for _ in range(10):
        increase.click()
    page.get_by_text("12 columns", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="Settings", exact=True).click()

    canvas = page.locator(".seurat-freeform-canvas")
    canvas.wait_for(state="visible")
    assert canvas.get_attribute("data-canvas-default-tile-width") == "12"
    canvas_width = canvas.evaluate("element => element.clientWidth")
    page.locator('[data-item="internal_energy"]').drag_to(
        canvas,
        target_position={"x": 10 * canvas_width / 24, "y": 4 * 24},
    )
    page.wait_for_function(
        "document.querySelectorAll("
        "'.seurat-freeform-canvas > .seurat-dropcell').length === 3"
    )

    added = canvas.locator('[data-tile-id="tile-3"]')
    assert added.get_attribute("data-canvas-w") == "12"
    added_bounds = added.bounding_box()
    assert added_bounds is not None
    assert abs(added_bounds["width"] - added_bounds["height"]) <= 13
    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_canvas_zoom_fit_and_scaled_pointer_geometry(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Freeform", exact=True).click()
    page.get_by_role("button", name="Show grid", exact=True).click()
    page.get_by_role("button", name="Settings", exact=True).click()

    canvas = page.locator(".seurat-freeform-canvas")
    canvas.wait_for(state="visible")
    first = canvas.locator('[data-tile-id="tile-1"]')
    page.wait_for_function(
        "() => { const canvas = document.querySelector('.seurat-freeform-canvas');"
        " const tile = document.querySelector('[data-tile-id=\"tile-1\"]');"
        " if (!canvas || !tile) return false;"
        " return Math.abs(tile.getBoundingClientRect().width"
        " - (canvas.clientWidth * 10 / 24 - 4)) < 1; }"
    )
    original_bounds = first.bounding_box()
    assert original_bounds is not None
    assert float(canvas.get_attribute("data-canvas-effective-zoom")) == 1.0

    page.get_by_role("button", name="Zoom out", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.seurat-freeform-canvas')"
        ".getAttribute('data-canvas-effective-zoom') === '0.75'"
    )
    page.wait_for_timeout(180)
    zoomed_bounds = first.bounding_box()
    assert zoomed_bounds is not None
    assert abs(zoomed_bounds["width"] / original_bounds["width"] - 0.75) <= 0.02
    assert first.get_attribute("data-canvas-w") == "10"
    assert page.locator("[data-canvas-zoom-label]").inner_text() == "75%"

    canvas_width = canvas.evaluate("element => element.clientWidth")
    visual_column = canvas_width * 0.75 / 24
    vertical_line = canvas.locator(
        ".seurat-canvas-grid-line.is-vertical"
    ).first.bounding_box()
    canvas_bounds = canvas.bounding_box()
    assert vertical_line is not None
    assert canvas_bounds is not None
    assert abs(vertical_line["x"] - canvas_bounds["x"] - visual_column) <= 1.5

    _drag(
        page,
        first.locator(".seurat-tile-header"),
        delta_y=3 * 24 * 0.75,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-y') === '3'"
    )

    _drag(
        page,
        first.locator(".seurat-canvas-resize-handle"),
        delta_x=2 * visual_column,
        delta_y=2 * 24 * 0.75,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '12'"
    )
    assert first.get_attribute("data-canvas-h") == "10"

    _drag(
        page,
        first.locator(".seurat-tile-header"),
        delta_y=12 * 24 * 0.75,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-y') === '15'"
    )

    page.get_by_role("button", name="Fit", exact=True).click()
    page.wait_for_function(
        "() => { const canvas = document.querySelector('.seurat-freeform-canvas');"
        " return canvas && canvas.getAttribute('data-canvas-fit') === '1'"
        " && Number(canvas.getAttribute('data-canvas-effective-zoom')) < 0.75; }"
    )
    page.wait_for_timeout(180)
    fit_zoom = float(canvas.get_attribute("data-canvas-effective-zoom"))
    assert page.get_by_role("button", name="Fit", exact=True).get_attribute(
        "aria-pressed"
    ) == "true"
    assert page.locator("[data-canvas-zoom-label]").inner_text() == (
        f"{round(fit_zoom * 100)}%"
    )

    canvas_bounds = canvas.bounding_box()
    assert canvas_bounds is not None
    for tile in canvas.locator(":scope > .seurat-dropcell").all():
        tile_bounds = tile.bounding_box()
        assert tile_bounds is not None
        assert tile_bounds["x"] >= canvas_bounds["x"] - 1
        assert tile_bounds["y"] >= canvas_bounds["y"] - 1
        assert tile_bounds["x"] + tile_bounds["width"] <= (
            canvas_bounds["x"] + canvas_bounds["width"] + 1
        )
        assert tile_bounds["y"] + tile_bounds["height"] <= (
            canvas_bounds["y"] + canvas_bounds["height"] + 1
        )

    _drag(
        page,
        first.locator(".seurat-tile-header"),
        delta_y=-5 * 24 * fit_zoom,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-y') === '10'"
    )
    page.wait_for_function(
        "previous => Number(document.querySelector('.seurat-freeform-canvas')"
        ".getAttribute('data-canvas-effective-zoom')) > previous",
        arg=fit_zoom,
    )
    recomputed_fit_zoom = float(
        canvas.get_attribute("data-canvas-effective-zoom")
    )
    assert recomputed_fit_zoom > fit_zoom
    assert page.get_by_role("button", name="Fit", exact=True).get_attribute(
        "aria-pressed"
    ) == "true"

    page.wait_for_function(
        "() => { const canvas = document.querySelector('.seurat-freeform-canvas');"
        " return Math.abs(Number(canvas.getAttribute('data-canvas-zoom'))"
        " - Number(canvas.getAttribute('data-canvas-effective-zoom'))) < 0.002; }"
    )
    page.get_by_role("button", name="Zoom in", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.seurat-freeform-canvas')"
        ".getAttribute('data-canvas-fit') === '0'"
    )
    assert abs(
        float(canvas.get_attribute("data-canvas-effective-zoom"))
        - min(2.0, recomputed_fit_zoom + 0.25)
    ) <= 0.002
    assert page.get_by_role("button", name="Fit", exact=True).get_attribute(
        "aria-pressed"
    ) == "false"
    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_canvas_resize_preview_and_directional_handles(
    page, seurat_server
):
    console_errors, page_errors, response_errors = _open_app(
        page, seurat_server, "freeform-resize"
    )

    canvas = page.locator(".seurat-freeform-canvas")
    tile = canvas.locator('[data-tile-id="tile-1"]')
    placeholder = canvas.locator(":scope > .seurat-canvas-placeholder")
    canvas.wait_for(state="visible")
    page.wait_for_function(
        "document.querySelectorAll('[data-tile-id=\"tile-1\"] "
        ".seurat-canvas-resize-zone').length === 8"
    )
    handles = tile.locator(".seurat-canvas-resize-zone")
    assert handles.count() == 8
    assert tile.locator(".seurat-canvas-resize-handle").count() == 1

    expected_cursors = {
        "top": "ns-resize",
        "right": "ew-resize",
        "bottom": "ns-resize",
        "left": "ew-resize",
        "top-left": "nwse-resize",
        "top-right": "nesw-resize",
        "bottom-left": "nesw-resize",
        "bottom-right": "nwse-resize",
    }
    for edge, cursor in expected_cursors.items():
        handle = tile.locator(f'[data-resize-edge="{edge}"]')
        assert handle.count() == 1
        assert handle.evaluate(
            "element => getComputedStyle(element).cursor"
        ) == cursor
    close_button = tile.locator(".seurat-cell-close")
    assert close_button.evaluate(
        "button => { const bounds = button.getBoundingClientRect();"
        " const hit = document.elementFromPoint("
        "bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);"
        " return hit === button || (hit && hit.closest('.seurat-cell-close')"
        " === button); }"
    )

    canvas_width = canvas.evaluate("element => element.clientWidth")
    column_width = canvas_width / 24

    right_handle = tile.locator('[data-resize-edge="right"]')
    original_bounds = tile.bounding_box()
    assert original_bounds is not None
    _drag(page, right_handle, delta_x=-2 * column_width, release=False)
    placeholder.wait_for(state="visible")
    preview_bounds = placeholder.bounding_box()
    assert preview_bounds is not None
    assert preview_bounds["width"] < original_bounds["width"]
    assert int(
        placeholder.evaluate("element => getComputedStyle(element).zIndex")
    ) > int(tile.evaluate("element => getComputedStyle(element).zIndex"))
    page.mouse.up()
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '6'"
    )
    page.wait_for_timeout(180)
    _drag(page, right_handle, delta_x=2 * column_width)
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '8'"
    )
    page.wait_for_timeout(180)

    edge_cases = (
        ("top", 0, 2, (6, 6, 8, 6)),
        ("bottom", 0, -2, (6, 4, 8, 6)),
        ("left", 2, 0, (8, 4, 6, 8)),
    )
    for edge, dx, dy, expected in edge_cases:
        handle = tile.locator(f'[data-resize-edge="{edge}"]')
        _drag(
            page,
            handle,
            delta_x=dx * column_width,
            delta_y=dy * 24,
        )
        page.wait_for_function(
            "expected => { const tile = document.querySelector("
            "'[data-tile-id=\"tile-1\"]'); return tile"
            " && Number(tile.dataset.canvasX) === expected[0]"
            " && Number(tile.dataset.canvasY) === expected[1]"
            " && Number(tile.dataset.canvasW) === expected[2]"
            " && Number(tile.dataset.canvasH) === expected[3]; }",
            arg=list(expected),
        )
        page.wait_for_timeout(180)
        _drag(
            page,
            handle,
            delta_x=-dx * column_width,
            delta_y=-dy * 24,
        )
        page.wait_for_function(
            "() => { const tile = document.querySelector("
            "'[data-tile-id=\"tile-1\"]'); return tile"
            " && tile.dataset.canvasX === '6'"
            " && tile.dataset.canvasY === '4'"
            " && tile.dataset.canvasW === '8'"
            " && tile.dataset.canvasH === '8'; }"
        )
        page.wait_for_timeout(180)

    corner_cases = (
        ("top-left", 1, 1, (7, 5, 7, 7)),
        ("top-right", -1, 1, (6, 5, 7, 7)),
        ("bottom-left", 1, -1, (7, 4, 7, 7)),
        ("bottom-right", -1, -1, (6, 4, 7, 7)),
    )
    for edge, dx, dy, expected in corner_cases:
        handle = tile.locator(f'[data-resize-edge="{edge}"]')
        _drag(
            page,
            handle,
            delta_x=dx * column_width,
            delta_y=dy * 24,
        )
        page.wait_for_function(
            "expected => { const tile = document.querySelector("
            "'[data-tile-id=\"tile-1\"]'); return tile"
            " && Number(tile.dataset.canvasX) === expected[0]"
            " && Number(tile.dataset.canvasY) === expected[1]"
            " && Number(tile.dataset.canvasW) === expected[2]"
            " && Number(tile.dataset.canvasH) === expected[3]; }",
            arg=list(expected),
        )
        page.wait_for_timeout(180)
        _drag(
            page,
            handle,
            delta_x=-dx * column_width,
            delta_y=-dy * 24,
        )
        page.wait_for_function(
            "() => { const tile = document.querySelector("
            "'[data-tile-id=\"tile-1\"]'); return tile"
            " && tile.dataset.canvasX === '6'"
            " && tile.dataset.canvasY === '4'"
            " && tile.dataset.canvasW === '8'"
            " && tile.dataset.canvasH === '8'; }"
        )
        page.wait_for_timeout(180)

    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_1d_plot_redraws_at_resized_dimensions(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(
        page, seurat_server, "freeform-resize"
    )

    canvas = page.locator(".seurat-freeform-canvas")
    tile = canvas.locator('[data-tile-id="tile-1"]')
    plot = tile.locator(".seurat-plot1d")
    plot.locator("svg").wait_for(state="visible")
    page.evaluate(
        """() => {
            const runtime = window.seuratPlotRuntime;
            const original = runtime.scheduleRender;
            window.__seuratPlotResizeRenderRequests = 0;
            runtime.scheduleRender = function() {
                window.__seuratPlotResizeRenderRequests += 1;
                return original();
            };
        }"""
    )

    def plot_metrics():
        return plot.evaluate(
            """element => {
                const bounds = element.getBoundingClientRect();
                const viewBox = element.querySelector('svg').viewBox.baseVal;
                return {
                    width: bounds.width,
                    height: bounds.height,
                    view_width: viewBox.width,
                    view_height: viewBox.height,
                    series_path: element.querySelector('svg > path')?.getAttribute('d') || '',
                };
            }"""
        )

    initial = plot_metrics()
    assert initial["view_width"] == pytest.approx(initial["width"], abs=1.5)
    assert initial["view_height"] == pytest.approx(initial["height"], abs=1.5)

    canvas_width = canvas.evaluate("element => element.clientWidth")
    _drag(
        page,
        tile.locator('[data-resize-edge="right"]'),
        delta_x=-2 * canvas_width / 24,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '6'"
    )
    page.wait_for_function(
        "previous => { const plot = document.querySelector("
        "'[data-tile-id=\"tile-1\"] .seurat-plot1d');"
        " const bounds = plot.getBoundingClientRect();"
        " const viewBox = plot.querySelector('svg').viewBox.baseVal;"
        " return bounds.width < previous"
        " && Math.abs(viewBox.width - bounds.width) < 1.5; }",
        arg=initial["view_width"],
    )
    narrower = plot_metrics()
    assert narrower["view_width"] < initial["view_width"]
    assert narrower["view_width"] == pytest.approx(narrower["width"], abs=1.5)
    assert narrower["view_height"] == pytest.approx(narrower["height"], abs=1.5)
    assert narrower["series_path"] != initial["series_path"]
    assert page.evaluate("window.__seuratPlotResizeRenderRequests") > 0

    _drag(
        page,
        tile.locator('[data-resize-edge="bottom"]'),
        delta_y=-2 * 24,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-h') === '6'"
    )
    page.wait_for_function(
        "previous => { const plot = document.querySelector("
        "'[data-tile-id=\"tile-1\"] .seurat-plot1d');"
        " const bounds = plot.getBoundingClientRect();"
        " const viewBox = plot.querySelector('svg').viewBox.baseVal;"
        " return bounds.height < previous"
        " && Math.abs(viewBox.height - bounds.height) < 1.5; }",
        arg=narrower["view_height"],
    )
    shorter = plot_metrics()
    assert shorter["view_height"] < narrower["view_height"], (narrower, shorter)
    assert shorter["view_width"] == pytest.approx(shorter["width"], abs=1.5)
    assert shorter["view_height"] == pytest.approx(shorter["height"], abs=1.5)
    assert shorter["series_path"] != narrower["series_path"]

    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_vertical_seam_inserts_tile_between_neighbors(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Freeform", exact=True).click()
    page.get_by_role("button", name="Settings", exact=True).click()
    canvas = page.locator(".seurat-freeform-canvas")
    variable = page.locator('[data-item="internal_energy"]')
    canvas_width = canvas.evaluate("element => element.clientWidth")
    variable.drag_to(
        canvas,
        target_position={"x": 9.8 * canvas_width / 24, "y": 0.1 * 24},
    )
    page.wait_for_function(
        "document.querySelectorAll('.seurat-freeform-canvas > .seurat-dropcell').length === 3"
    )

    moving = canvas.locator('[data-tile-id="tile-3"]')
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-3\"]')"
        ".getAttribute('data-canvas-x') === '10'"
    )

    right = canvas.locator('[data-tile-id="tile-2"]')
    inserted_right = int(moving.get_attribute("data-canvas-x")) + int(
        moving.get_attribute("data-canvas-w")
    )
    assert int(right.get_attribute("data-canvas-x")) == inserted_right
    assert int(right.get_attribute("data-canvas-w")) >= 2
    assert (
        int(right.get_attribute("data-canvas-x"))
        + int(right.get_attribute("data-canvas-w"))
        <= 24
    )
    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_width_resize_pushes_right_neighbor_horizontally(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(
        page,
        seurat_server,
        "freeform-column-seam",
    )

    canvas = page.locator(".seurat-freeform-canvas")
    first = canvas.locator('[data-tile-id="tile-1"]')
    second = canvas.locator('[data-tile-id="tile-2"]')
    canvas_width = canvas.evaluate("element => element.clientWidth")

    _drag(
        page,
        first.locator(".seurat-canvas-resize-handle"),
        delta_x=2 * canvas_width / 24,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '12' && "
        "document.querySelector('[data-tile-id=\"tile-2\"]')"
        ".getAttribute('data-canvas-x') === '12'"
    )

    assert first.get_attribute("data-canvas-y") == "0"
    assert second.get_attribute("data-canvas-y") == "0"
    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_horizontal_seam_inserts_tile_between_neighbors(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(
        page,
        seurat_server,
        "freeform-row-seam",
    )

    canvas = page.locator(".seurat-freeform-canvas")
    first = canvas.locator('[data-tile-id="tile-1"]')
    canvas_width = canvas.evaluate("element => element.clientWidth")

    variable = page.locator('[data-item="internal_energy"]')
    variable.drag_to(
        canvas,
        target_position={"x": 10.1 * canvas_width / 24, "y": 7.8 * 24},
    )
    page.wait_for_function(
        "document.querySelectorAll('.seurat-freeform-canvas > .seurat-dropcell').length === 3"
    )
    moving = canvas.locator('[data-tile-id="tile-3"]')
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-3\"]')"
        ".getAttribute('data-canvas-y') === '8'"
    )

    inserted_height = int(moving.get_attribute("data-canvas-h"))
    assert moving.get_attribute("data-canvas-x") == "10"
    assert first.get_attribute("data-canvas-y") == str(8 + inserted_height)
    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_tile_moves_to_another_freeform_pane(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Freeform", exact=True).click()
    page.get_by_role("button", name="Settings", exact=True).click()
    pane_one_bar = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    _split_workspace_pane_by_drag(page, pane_one_bar, "horizontal")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")
    page.get_by_role("tab", name="View 1").click()

    source = page.locator(
        '.seurat-freeform-canvas[data-pane-id="pane-1"] '
        '.seurat-dropcell[data-tile-id="tile-1"] .seurat-tile-header'
    )
    destination = page.locator(
        '.seurat-freeform-preview[data-pane-id="pane-2"]'
    )
    source_bounds = source.bounding_box()
    destination_bounds = destination.bounding_box()
    assert source_bounds is not None
    assert destination_bounds is not None
    source_center_x = source_bounds["x"] + source_bounds["width"] / 2
    source_center_y = source_bounds["y"] + source_bounds["height"] / 2
    destination_center_x = (
        destination_bounds["x"] + destination_bounds["width"] / 2
    )
    destination_center_y = (
        destination_bounds["y"] + destination_bounds["height"] / 2
    )
    _drag(
        page,
        source,
        delta_x=destination_center_x - source_center_x,
        delta_y=destination_center_y - source_center_y,
    )

    destination_grid = page.locator(
        '.seurat-freeform-canvas[data-pane-id="pane-2"]'
    )
    destination_grid.wait_for(state="visible")
    assert destination_grid.locator(
        ':scope > .seurat-dropcell[data-tile-id="tile-1"]'
    ).count() == 1
    assert page.locator(
        '.seurat-freeform-preview[data-pane-id="pane-1"] > .seurat-dropcell'
    ).count() == 1
    assert page.locator(".seurat-canvas-cross-pane-ghost").count() == 0
    assert page_errors == []
    assert console_errors == [], response_errors


def test_cell_context_menu_opens(page, seurat_server):
    _open_app(page, seurat_server)

    cell = page.locator('.seurat-dropcell[data-cell-index="0"]')
    cell.click(button="right")

    menu = page.locator("#seurat-context-menu")
    menu.wait_for(state="visible")
    assert menu.get_by_text("internal_energy", exact=True).is_visible()
    assert menu.get_by_text("Select Cell", exact=True).is_visible()


def test_variable_context_menu_opens(page, seurat_server):
    _open_app(page, seurat_server)

    variable = page.locator('[data-item="internal_energy"]')
    variable.click(button="right")

    menu = page.locator("#seurat-context-menu")
    menu.wait_for(state="visible")
    assert menu.get_by_text("internal_energy", exact=True).is_visible()
    assert menu.get_by_text("Add To Grid", exact=True).is_visible()
    assert menu.get_by_text("Select Variable", exact=True).is_visible()


def test_grid_cell_drag_moves_content(page, seurat_server):
    _open_app(page, seurat_server)

    source = page.locator('.seurat-dropcell[data-cell-index="0"]')
    target = page.locator('.seurat-dropcell[data-cell-index="2"]')
    source.drag_to(target)

    page.wait_for_function(
        "document.querySelector('.seurat-dropcell[data-cell-index=\"0\"]')"
        ".getAttribute('data-cell-filled') === '0'"
    )
    assert target.get_by_text("internal_energy", exact=True).is_visible()


def test_interaction_runtime_releases_and_restores_handlers(page, seurat_server):
    _open_app(page, seurat_server)

    root = page.locator(".v-application")
    menu = page.locator("#seurat-context-menu")
    cell = page.locator('.seurat-dropcell[data-cell-index="0"]')

    root.evaluate("root => window.seuratInteractionRuntime.unmount(root)")
    assert root.get_attribute("data-seurat-interaction-runtime-owner") is None
    cell.click(button="right")
    assert not menu.is_visible()

    root.evaluate("root => window.seuratInteractionRuntime.mount(root)")
    root.evaluate("root => window.seuratInteractionRuntime.mount(root)")
    assert root.get_attribute("data-seurat-interaction-runtime-owner") == "mounted"
    page.evaluate(
        """() => {
            const originalTrigger = window.trame.trigger.bind(window.trame);
            window.__seuratInteractionTriggerCounts = {};
            window.trame.trigger = (name, args) => {
                const counts = window.__seuratInteractionTriggerCounts;
                counts[name] = (counts[name] || 0) + 1;
                return originalTrigger(name, args);
            };
        }"""
    )
    cell.click(button="right")
    menu.wait_for(state="visible")
    assert menu.get_by_text("internal_energy", exact=True).is_visible()
    assert (
        page.evaluate("window.__seuratInteractionTriggerCounts.show_cell_context_menu")
        == 1
    )


def test_floating_panel_drag_moves_and_clamps_panel(page, seurat_server):
    _open_app(page, seurat_server)

    panel = page.locator("#seurat-plot-settings-panel")
    panel.evaluate("panel => { panel.style.display = 'block'; }")
    handle = panel.locator(".seurat-floating-panel-drag-handle")
    initial = panel.bounding_box()
    assert initial is not None

    _drag(page, handle, delta_x=55, delta_y=35)
    moved = panel.bounding_box()
    assert moved["x"] == pytest.approx(initial["x"] + 55, abs=2)
    assert moved["y"] == pytest.approx(initial["y"] + 35, abs=2)
    assert not panel.evaluate("panel => panel.classList.contains('is-dragging')")

    _drag(page, handle, delta_x=-2000, delta_y=-2000)
    clamped = panel.bounding_box()
    assert clamped["x"] == pytest.approx(8, abs=1)
    assert clamped["y"] == pytest.approx(8, abs=1)


def test_floating_panel_runtime_cleans_up_and_owns_window_resize(
    page, seurat_server
):
    _open_app(page, seurat_server)

    root = page.locator(".v-application")
    panel = page.locator("#seurat-plot-settings-panel")
    panel.evaluate("panel => { panel.style.display = 'block'; }")
    handle = panel.locator(".seurat-floating-panel-drag-handle")

    _drag(page, handle, delta_x=20, delta_y=10, release=False)
    assert handle.evaluate("handle => handle.hasPointerCapture(1)")
    assert panel.evaluate("panel => panel.classList.contains('is-dragging')")

    root.evaluate("root => window.seuratInteractionRuntime.unmount(root)")
    assert not handle.evaluate("handle => handle.hasPointerCapture(1)")
    assert not panel.evaluate("panel => panel.classList.contains('is-dragging')")
    page.mouse.up()

    panel.evaluate("panel => { panel.style.left = '2000px'; panel.style.top = '2000px'; }")
    page.evaluate("window.dispatchEvent(new Event('resize'))")
    assert panel.get_attribute("style").find("left: 2000px") >= 0

    root.evaluate("root => window.seuratInteractionRuntime.mount(root)")
    root.evaluate("root => window.seuratInteractionRuntime.mount(root)")
    page.evaluate("window.dispatchEvent(new Event('resize'))")
    clamped = panel.bounding_box()
    assert clamped["x"] + clamped["width"] <= page.viewport_size["width"] - 7
    assert clamped["y"] + clamped["height"] <= page.viewport_size["height"] - 7


def test_grid_runtime_releases_and_restores_timeline_handlers(page, seurat_server):
    _open_app(page, seurat_server)

    root = page.locator(".seurat-content-column")
    label = page.locator("#seurat-vcr-time-value")
    forward = page.get_by_title("Forward step")

    root.evaluate("root => window.seuratGridRuntime.unmount(root)")
    assert root.get_attribute("data-seurat-grid-runtime-owner") is None
    assert root.get_attribute("data-seurat-timeline-runtime-owner") is None
    forward.click()
    assert label.text_content() == "Step = 0"

    root.evaluate("root => window.seuratGridRuntime.mount(root)")
    assert root.get_attribute("data-seurat-grid-runtime-owner") == "mounted"
    assert root.get_attribute("data-seurat-timeline-runtime-owner") == "mounted"
    forward.click()
    page.wait_for_function(
        "document.querySelector('#seurat-vcr-time-value').textContent === 'Step = 1'"
    )


def test_media_viewport_pan_zoom_and_reset_request(page, seurat_server):
    _open_app(page, seurat_server)

    viewport = page.locator(
        '.seurat-dropcell[data-cell-index="1"] .seurat-panzoom-viewport'
    )
    bounds = viewport.bounding_box()
    assert bounds is not None
    page.mouse.move(
        bounds["x"] + bounds["width"] / 2,
        bounds["y"] + bounds["height"] / 2,
    )
    page.mouse.wheel(0, -120)
    assert viewport.evaluate("viewport => viewport.__seuratPanZoomState.scale") > 1

    viewport.dblclick()
    assert viewport.evaluate(
        "viewport => viewport.__seuratPanZoomState"
    ) == pytest.approx({"scale": 1, "tx": 0, "ty": 0})

    page.keyboard.down("Shift")
    _drag(page, viewport, delta_x=35, delta_y=20)
    page.keyboard.up("Shift")
    panned = viewport.evaluate("viewport => viewport.__seuratPanZoomState")
    assert panned["scale"] == pytest.approx(1)
    assert panned["tx"] == pytest.approx(35, abs=1)
    assert panned["ty"] == pytest.approx(20, abs=1)

    _drag(page, viewport, delta_y=-30, button="middle")
    zoomed = viewport.evaluate("viewport => viewport.__seuratPanZoomState")
    assert zoomed["scale"] > 1

    request = page.locator("#seurat-reset-view-request")
    request.evaluate(
        "element => element.setAttribute('data-reset-view-request', "
        "JSON.stringify({ cell_index: 1, nonce: 1 }))"
    )
    page.wait_for_function(
        "document.querySelector('.seurat-dropcell[data-cell-index=\"1\"] "
        ".seurat-panzoom-viewport').__seuratPanZoomState.scale === 1"
    )
    reset = viewport.evaluate("viewport => viewport.__seuratPanZoomState")
    assert reset == pytest.approx({"scale": 1, "tx": 0, "ty": 0})


def test_media_pan_zoom_lifecycle_cleanup_and_idempotent_remount(
    page, seurat_server
):
    _open_app(page, seurat_server)

    root = page.locator(".seurat-content-column")
    viewport = page.locator(
        '.seurat-dropcell[data-cell-index="1"] .seurat-panzoom-viewport'
    )
    viewport.dblclick()

    page.keyboard.down("Shift")
    _drag(page, viewport, delta_x=20, delta_y=10, release=False)
    assert viewport.evaluate("viewport => viewport.hasPointerCapture(1)")
    assert viewport.evaluate("viewport => viewport.classList.contains('is-panning')")

    root.evaluate("root => window.seuratGridRuntime.unmount(root)")
    assert root.get_attribute("data-seurat-media-runtime-owner") is None
    assert not viewport.evaluate("viewport => viewport.hasPointerCapture(1)")
    assert not viewport.evaluate(
        "viewport => viewport.classList.contains('is-panning')"
    )
    assert not page.locator("body").evaluate(
        "body => body.classList.contains('seurat-panzoom-panning')"
    )
    page.mouse.up()
    page.keyboard.up("Shift")

    before_unmounted_wheel = viewport.evaluate(
        "viewport => ({ ...viewport.__seuratPanZoomState })"
    )
    bounds = viewport.bounding_box()
    page.mouse.move(
        bounds["x"] + bounds["width"] / 2,
        bounds["y"] + bounds["height"] / 2,
    )
    page.mouse.wheel(0, -100)
    assert viewport.evaluate(
        "viewport => viewport.__seuratPanZoomState"
    ) == pytest.approx(before_unmounted_wheel)

    root.evaluate("root => window.seuratGridRuntime.mount(root)")
    root.evaluate("root => window.seuratGridRuntime.mount(root)")
    assert root.get_attribute("data-seurat-media-runtime-owner") == "mounted"
    viewport.dblclick()
    page.mouse.wheel(0, -100)
    assert viewport.evaluate(
        "viewport => viewport.__seuratPanZoomState.scale"
    ) == pytest.approx(1.161834, abs=0.001)


def test_plot_hover_pan_zoom_and_reset_request(page, seurat_server):
    _open_app(page, seurat_server)

    plot = page.locator('.seurat-dropcell[data-cell-index="0"] .seurat-plot1d')
    hover_point = plot.evaluate(
        """plot => {
            const point = plot.__seuratPlotMeta.hoverSeries[0].points[20];
            const rect = plot.getBoundingClientRect();
            return { x: rect.left + point.px, y: rect.top + point.py };
        }"""
    )
    page.keyboard.down("Control")
    page.mouse.move(hover_point["x"], hover_point["y"])
    assert plot.evaluate(
        "plot => plot.__seuratPlotMeta.hoverGroup.getAttribute('display')"
    ) is None
    assert plot.evaluate(
        "plot => plot.__seuratPlotMeta.hoverTip.style.display"
    ) == "block"
    hover_text = plot.evaluate(
        "plot => plot.__seuratPlotMeta.hoverTip.textContent"
    )
    assert "\\n" not in hover_text
    hover_lines = hover_text.splitlines()
    assert len(hover_lines) == 2
    assert hover_lines[0].startswith("x: ")
    assert hover_lines[1].startswith("y: ")
    page.keyboard.up("Control")
    assert plot.evaluate(
        "plot => plot.__seuratPlotMeta.hoverGroup.getAttribute('display')"
    ) == "none"

    initial_axes = plot.evaluate(
        "plot => ({"
        " x: { ...plot.__seuratPlotMeta.xAxis },"
        " y: { ...plot.__seuratPlotMeta.yAxis }"
        "})"
    )
    bounds = plot.bounding_box()
    page.mouse.move(
        bounds["x"] + bounds["width"] / 2,
        bounds["y"] + bounds["height"] / 2,
    )
    page.mouse.wheel(0, -120)
    wheel_state = plot.evaluate("plot => ({ ...plot.__seuratPlotViewState })")
    assert wheel_state["xMax"] - wheel_state["xMin"] < (
        initial_axes["x"]["max"] - initial_axes["x"]["min"]
    )

    plot.dblclick()
    assert plot.evaluate("plot => plot.__seuratPlotViewState") is None

    page.keyboard.down("Shift")
    _drag(page, plot, delta_x=30, delta_y=15)
    page.keyboard.up("Shift")
    pan_state = plot.evaluate("plot => ({ ...plot.__seuratPlotViewState })")
    assert pan_state["xMin"] != pytest.approx(initial_axes["x"]["min"])
    assert pan_state["yMin"] != pytest.approx(initial_axes["y"]["min"])

    _drag(page, plot, delta_y=-25, button="middle")
    middle_zoom_state = plot.evaluate(
        "plot => ({ ...plot.__seuratPlotViewState })"
    )
    assert middle_zoom_state["xMax"] - middle_zoom_state["xMin"] < (
        pan_state["xMax"] - pan_state["xMin"]
    )

    request = page.locator("#seurat-reset-view-request")
    request.evaluate(
        "element => element.setAttribute('data-reset-view-request', "
        "JSON.stringify({ cell_index: 0, nonce: 2 }))"
    )
    page.wait_for_function(
        "document.querySelector('.seurat-dropcell[data-cell-index=\"0\"] "
        ".seurat-plot1d').__seuratPlotViewState === null"
    )


def test_plot_runtime_cleans_up_observers_and_remounts_idempotently(
    page, seurat_server
):
    _open_app(page, seurat_server)

    root = page.locator(".seurat-content-column")
    plot = page.locator('.seurat-dropcell[data-cell-index="0"] .seurat-plot1d')
    plot.dblclick()

    page.keyboard.down("Shift")
    _drag(page, plot, delta_x=20, delta_y=10, release=False)
    assert plot.evaluate("plot => plot.hasPointerCapture(1)")
    assert plot.evaluate("plot => plot.classList.contains('is-panning')")

    root.evaluate("root => window.seuratGridRuntime.unmount(root)")
    assert root.get_attribute("data-seurat-plot-runtime-owner") is None
    assert not plot.evaluate("plot => plot.hasPointerCapture(1)")
    assert not plot.evaluate("plot => plot.classList.contains('is-panning')")
    assert not page.locator("body").evaluate(
        "body => body.classList.contains('seurat-plot-panning')"
    )
    page.mouse.up()
    page.keyboard.up("Shift")

    plot.evaluate("plot => { plot.__seuratPlotRenderKey = 'unmounted'; }")
    page.evaluate("window.seuratGridRuntime.schedulePlotRender()")
    plot.evaluate(
        "plot => plot.setAttribute('data-plot-settings', "
        "JSON.stringify({ background_color: '#ffeeee' }))"
    )
    page.wait_for_timeout(100)
    assert plot.evaluate("plot => plot.__seuratPlotRenderKey") == "unmounted"

    root.evaluate("root => window.seuratGridRuntime.mount(root)")
    root.evaluate("root => window.seuratGridRuntime.mount(root)")
    assert root.get_attribute("data-seurat-plot-runtime-owner") == "mounted"
    page.wait_for_function(
        "document.querySelector('.seurat-plot1d').__seuratPlotRenderKey !== 'unmounted'"
    )
    plot.dblclick()
    initial_span = plot.evaluate(
        "plot => plot.__seuratPlotMeta.xAxis.max - plot.__seuratPlotMeta.xAxis.min"
    )
    bounds = plot.bounding_box()
    page.mouse.move(
        bounds["x"] + bounds["width"] / 2,
        bounds["y"] + bounds["height"] / 2,
    )
    page.mouse.wheel(0, -100)
    zoomed_span = plot.evaluate(
        "plot => plot.__seuratPlotViewState.xMax - plot.__seuratPlotViewState.xMin"
    )
    assert zoomed_span / initial_span == pytest.approx(0.860708, abs=0.002)


def test_variable_panel_resize_supports_keyboard_and_pointer(page, seurat_server):
    _open_app(page, seurat_server)

    panel = page.locator("#seurat-variable-column")
    handle = page.locator("[data-variable-panel-resizer]")
    initial_width = panel.bounding_box()["width"]

    handle.focus()
    handle.press("ArrowRight")
    keyboard_width = panel.bounding_box()["width"]
    assert keyboard_width == pytest.approx(initial_width + 10, abs=1)
    assert float(handle.get_attribute("aria-valuenow")) == pytest.approx(
        keyboard_width, abs=1
    )

    _drag(page, handle, delta_x=40)
    pointer_width = panel.bounding_box()["width"]
    assert pointer_width == pytest.approx(keyboard_width + 40, abs=2)
    assert not page.locator("body").evaluate(
        "body => body.classList.contains('seurat-variable-panel-resizing')"
    )


def test_grid_column_resize_updates_track_state(page, seurat_server):
    _open_app(page, seurat_server)

    grid = page.locator(".seurat-main-grid")
    handle = page.locator(
        '.seurat-dropcell[data-cell-index="0"] '
        '.seurat-grid-col-resize-handle[data-resize-edge="right"]'
    )
    _drag(page, handle, delta_x=45)

    page.wait_for_function(
        "Number(document.querySelector('.seurat-main-grid')"
        ".getAttribute('data-grid-column-sizes').split(',')[0]) > 320"
    )
    sizes = [float(value) for value in grid.get_attribute("data-grid-column-sizes").split(",")]
    assert sizes[0] == pytest.approx(325, abs=2)
    assert sizes[1:] == pytest.approx([280, 280], abs=1)


def test_fit_grid_column_resize_updates_track_weights(page, seurat_server):
    _open_app(page, seurat_server)

    grid = page.locator(".seurat-main-grid")
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("button", name="Fit window", exact=True).click()
    page.get_by_role("button", name="Settings", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.seurat-main-grid')"
        ".getAttribute('data-grid-sizing-mode') === 'fit'"
    )
    initial_weights = [
        float(value)
        for value in grid.get_attribute("data-grid-column-weights").split(",")
    ]
    plot = page.locator('.seurat-dropcell[data-cell-index="0"] .seurat-plot1d')
    page.wait_for_function(
        "() => { const plot = document.querySelector('.seurat-plot1d');"
        " const svg = plot && plot.querySelector('svg');"
        " if (!plot || !svg || !plot.__seuratPlotMeta) return false;"
        " const bounds = plot.getBoundingClientRect();"
        " const viewBox = svg.viewBox.baseVal;"
        " return Math.abs(viewBox.width - Math.round(bounds.width)) < 1"
        " && Math.abs(viewBox.height - Math.round(bounds.height)) < 1; }"
    )
    initial_plot_width = plot.evaluate("plot => plot.__seuratPlotMeta.plotW")
    undo_button, redo_button = page.locator(".seurat-history-button").all()
    handle = page.locator(
        '.seurat-dropcell[data-cell-index="0"] '
        '.seurat-grid-col-resize-handle[data-resize-edge="right"]'
    )
    _drag(page, handle, delta_x=30)

    page.wait_for_function(
        "Number(document.querySelector('.seurat-main-grid')"
        ".getAttribute('data-grid-column-weights').split(',')[0]) > 1"
    )
    weights = [
        float(value)
        for value in grid.get_attribute("data-grid-column-weights").split(",")
    ]
    assert weights[0] > 1
    assert weights[1] < 1
    assert weights[0] + weights[1] == pytest.approx(2, abs=0.001)
    assert weights[2] == pytest.approx(1)
    page.wait_for_function(
        "width => document.querySelector('.seurat-plot1d')"
        ".__seuratPlotMeta.plotW > width",
        arg=initial_plot_width,
    )

    undo_button.click()
    page.wait_for_function(
        "expected => document.querySelector('.seurat-main-grid')"
        ".dataset.gridColumnWeights.split(',').map(Number)"
        ".every((value, i) => Math.abs(value - expected[i]) < 0.000001)",
        arg=initial_weights,
    )
    page.wait_for_function(
        "width => Math.abs(document.querySelector('.seurat-plot1d')"
        ".__seuratPlotMeta.plotW - width) < 1",
        arg=initial_plot_width,
    )

    redo_button.click()
    page.wait_for_function(
        "expected => document.querySelector('.seurat-main-grid')"
        ".dataset.gridColumnWeights.split(',').map(Number)"
        ".every((value, i) => Math.abs(value - expected[i]) < 0.000001)",
        arg=weights,
    )


def test_grid_row_resize_updates_track_state(page, seurat_server):
    _open_app(page, seurat_server)

    grid = page.locator(".seurat-main-grid")
    handle = page.locator(
        '.seurat-dropcell[data-cell-index="0"] '
        '.seurat-grid-row-resize-handle[data-resize-edge="bottom"]'
    )
    _drag(page, handle, delta_y=35)

    page.wait_for_function(
        "Number(document.querySelector('.seurat-main-grid')"
        ".getAttribute('data-grid-row-sizes').split(',')[0]) > 380"
    )
    sizes = [float(value) for value in grid.get_attribute("data-grid-row-sizes").split(",")]
    assert sizes == pytest.approx([387], abs=2)


def test_grid_corner_resize_updates_both_track_axes(page, seurat_server):
    _open_app(page, seurat_server)

    grid = page.locator(".seurat-main-grid")
    handle = page.locator(
        '.seurat-dropcell[data-cell-index="0"] .seurat-grid-corner-bottom-right'
    )
    _drag(page, handle, delta_x=30, delta_y=25)

    page.wait_for_function(
        "(() => { const grid = document.querySelector('.seurat-main-grid');"
        " return Number(grid.getAttribute('data-grid-column-sizes').split(',')[0]) > 300"
        " && Number(grid.getAttribute('data-grid-row-sizes').split(',')[0]) > 370; })()"
    )
    column_sizes = [
        float(value)
        for value in grid.get_attribute("data-grid-column-sizes").split(",")
    ]
    row_sizes = [float(value) for value in grid.get_attribute("data-grid-row-sizes").split(",")]
    assert column_sizes[0] == pytest.approx(310, abs=2)
    assert row_sizes[0] == pytest.approx(377, abs=2)


@pytest.mark.parametrize("layout_mode", ["uniform", "spanning"])
def test_grid_corner_resize_undo_redo_restores_both_axes(
    page, seurat_server, layout_mode
):
    console_errors, page_errors, response_errors = _open_app(page, seurat_server)
    if layout_mode == "spanning":
        page.get_by_role("button", name="Settings", exact=True).click()
        page.get_by_role("button", name="Spanning", exact=True).click()

    grid = page.locator(".seurat-main-grid")
    plot = page.locator('.seurat-dropcell[data-cell-index="0"] .seurat-plot1d')
    undo_button, redo_button = page.locator(".seurat-history-button").all()
    page.wait_for_function(
        "() => { const plot = document.querySelector('.seurat-plot1d');"
        " const svg = plot && plot.querySelector('svg');"
        " if (!plot || !svg || !plot.__seuratPlotMeta) return false;"
        " const bounds = plot.getBoundingClientRect();"
        " const viewBox = svg.viewBox.baseVal;"
        " return Math.abs(viewBox.width - Math.round(bounds.width)) < 1"
        " && Math.abs(viewBox.height - Math.round(bounds.height)) < 1; }"
    )
    initial_columns = [
        float(value)
        for value in grid.get_attribute("data-grid-column-sizes").split(",")
    ]
    initial_rows = [
        float(value)
        for value in grid.get_attribute("data-grid-row-sizes").split(",")
    ]
    initial_plot_bounds = plot.bounding_box()
    assert initial_plot_bounds is not None

    handle = page.locator(
        '.seurat-dropcell[data-cell-index="0"] .seurat-grid-corner-bottom-right'
    )
    _drag(page, handle, delta_x=30, delta_y=25)
    page.wait_for_function(
        "(() => { const grid = document.querySelector('.seurat-main-grid');"
        " return Number(grid.dataset.gridColumnSizes.split(',')[0]) > 300"
        " && Number(grid.dataset.gridRowSizes.split(',')[0]) > 370; })()"
    )
    resized_columns = [
        float(value)
        for value in grid.get_attribute("data-grid-column-sizes").split(",")
    ]
    resized_rows = [
        float(value)
        for value in grid.get_attribute("data-grid-row-sizes").split(",")
    ]
    page.wait_for_function(
        "initial => { const plot = document.querySelector('.seurat-plot1d');"
        " const svg = plot && plot.querySelector('svg');"
        " if (!plot || !svg) return false;"
        " const bounds = plot.getBoundingClientRect();"
        " const viewBox = svg.viewBox.baseVal;"
        " return bounds.width > initial.width && bounds.height > initial.height"
        " && Math.abs(viewBox.width - Math.round(bounds.width)) < 1"
        " && Math.abs(viewBox.height - Math.round(bounds.height)) < 1; }",
        arg=initial_plot_bounds,
    )
    assert "Undo Resize grid track" in undo_button.get_attribute("title")

    undo_button.click()
    page.wait_for_function(
        "expected => { const grid = document.querySelector('.seurat-main-grid');"
        " const columns = grid.dataset.gridColumnSizes.split(',').map(Number);"
        " const rows = grid.dataset.gridRowSizes.split(',').map(Number);"
        " return columns.every((value, i) => Math.abs(value - expected.columns[i]) < 0.01)"
        " && rows.every((value, i) => Math.abs(value - expected.rows[i]) < 0.01); }",
        arg={"columns": initial_columns, "rows": initial_rows},
    )
    page.wait_for_function(
        "initial => { const plot = document.querySelector('.seurat-plot1d');"
        " const svg = plot && plot.querySelector('svg');"
        " if (!plot || !svg) return false;"
        " const bounds = plot.getBoundingClientRect();"
        " const viewBox = svg.viewBox.baseVal;"
        " return Math.abs(bounds.width - initial.width) < 1"
        " && Math.abs(bounds.height - initial.height) < 1"
        " && Math.abs(viewBox.width - Math.round(bounds.width)) < 1"
        " && Math.abs(viewBox.height - Math.round(bounds.height)) < 1; }",
        arg=initial_plot_bounds,
    )

    redo_button.click()
    page.wait_for_function(
        "expected => { const grid = document.querySelector('.seurat-main-grid');"
        " const columns = grid.dataset.gridColumnSizes.split(',').map(Number);"
        " const rows = grid.dataset.gridRowSizes.split(',').map(Number);"
        " return columns.every((value, i) => Math.abs(value - expected.columns[i]) < 0.01)"
        " && rows.every((value, i) => Math.abs(value - expected.rows[i]) < 0.01); }",
        arg={"columns": resized_columns, "rows": resized_rows},
    )

    assert page_errors == []
    assert console_errors == [], response_errors


def test_freeform_resize_undo_redo_restores_geometry_and_plot(page, seurat_server):
    console_errors, page_errors, response_errors = _open_app(
        page, seurat_server, "freeform-resize"
    )
    canvas = page.locator(".seurat-freeform-canvas")
    tile = canvas.locator('[data-tile-id="tile-1"]')
    plot = tile.locator(".seurat-plot1d")
    undo_button, redo_button = page.locator(".seurat-history-button").all()
    canvas_width = canvas.evaluate("element => element.clientWidth")
    initial_plot_width = plot.evaluate("plot => plot.__seuratPlotMeta.plotW")

    _drag(
        page,
        tile.locator('[data-resize-edge="right"]'),
        delta_x=2 * canvas_width / 24,
    )
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '10'"
    )
    page.wait_for_function(
        "width => document.querySelector('.seurat-plot1d')"
        ".__seuratPlotMeta.plotW > width",
        arg=initial_plot_width,
    )
    assert "Undo Move or resize plot" in undo_button.get_attribute("title")

    undo_button.click()
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '8'"
    )
    page.wait_for_function(
        "width => Math.abs(document.querySelector('.seurat-plot1d')"
        ".__seuratPlotMeta.plotW - width) < 1",
        arg=initial_plot_width,
    )

    redo_button.click()
    page.wait_for_function(
        "document.querySelector('[data-tile-id=\"tile-1\"]')"
        ".getAttribute('data-canvas-w') === '10'"
    )

    assert page_errors == []
    assert console_errors == [], response_errors


def test_resize_runtime_cleans_up_and_mount_is_idempotent(page, seurat_server):
    _open_app(page, seurat_server)

    root = page.locator(".v-application")
    grid = page.locator(".seurat-main-grid")
    variable_handle = page.locator("[data-variable-panel-resizer]")

    _drag(page, variable_handle, delta_x=25, release=False)
    assert page.locator("body").evaluate(
        "body => body.classList.contains('seurat-variable-panel-resizing')"
    )
    assert variable_handle.evaluate(
        "handle => handle.hasPointerCapture(1)"
    )
    root.evaluate("root => window.seuratResizeRuntime.unmount(root)")
    assert root.get_attribute("data-seurat-resize-runtime-owner") is None
    assert not page.locator("body").evaluate(
        "body => body.classList.contains('seurat-variable-panel-resizing')"
    )
    assert not variable_handle.evaluate(
        "handle => handle.classList.contains('seurat-variable-resizer-active')"
    )
    assert not variable_handle.evaluate(
        "handle => handle.hasPointerCapture(1)"
    )
    page.mouse.up()

    panel = page.locator("#seurat-variable-column")
    unmounted_width = panel.bounding_box()["width"]
    variable_handle.focus()
    variable_handle.press("ArrowRight")
    assert panel.bounding_box()["width"] == pytest.approx(unmounted_width, abs=1)

    root.evaluate("root => window.seuratResizeRuntime.mount(root)")
    root.evaluate("root => window.seuratResizeRuntime.mount(root)")
    assert root.get_attribute("data-seurat-resize-runtime-owner") == "mounted"
    page.evaluate(
        """() => {
            const originalTrigger = window.trame.trigger.bind(window.trame);
            window.__seuratResizeTriggerCounts = {};
            window.__seuratResizeRenderCount = 0;
            const originalRender = window.seuratGridRuntime.schedulePlotRender;
            window.seuratGridRuntime.schedulePlotRender = (...args) => {
                window.__seuratResizeRenderCount += 1;
                return originalRender(...args);
            };
            window.trame.trigger = (name, args) => {
                const counts = window.__seuratResizeTriggerCounts;
                counts[name] = (counts[name] || 0) + 1;
                return originalTrigger(name, args);
            };
        }"""
    )
    grid_handle = page.locator(
        '.seurat-dropcell[data-cell-index="0"] '
        '.seurat-grid-col-resize-handle[data-resize-edge="right"]'
    )
    _drag(page, grid_handle, delta_x=20)
    assert page.evaluate(
        "window.__seuratResizeTriggerCounts.commit_grid_track_resize_trigger"
    ) == 1
    assert not grid.evaluate("grid => grid.classList.contains('is-resizing')")
    assert not page.locator("body").evaluate(
        "body => body.classList.contains('seurat-grid-col-resizing')"
    )
    root.evaluate("root => window.seuratResizeRuntime.unmount(root)")
    render_count_after_unmount = page.evaluate("window.__seuratResizeRenderCount")
    page.wait_for_timeout(250)
    assert page.evaluate("window.__seuratResizeRenderCount") == render_count_after_unmount


def test_schema_less_timeline_uses_step_indices(page, seurat_server):
    _open_app(page, seurat_server, mode="step")

    label = page.locator("#seurat-vcr-time-value")
    image = page.locator('img[data-grid-image-sequence="1"]')
    label.wait_for(state="visible")
    assert label.text_content() == "Step = 0"
    assert image.get_attribute("data-current-frame") == "0"

    page.get_by_title("Forward step").click()

    page.wait_for_function(
        "document.querySelector('#seurat-vcr-time-value').textContent === 'Step = 1'"
    )
    assert image.get_attribute("data-current-frame") == "1"


def test_schema_less_timeline_play_advances_frames(page, seurat_server):
    _open_app(page, seurat_server, mode="step")

    image = page.locator('img[data-grid-image-sequence="1"]')
    play_toggle = page.locator('[data-vcr-action="toggle"]')
    assert image.get_attribute("data-current-frame") == "0"
    assert play_toggle.get_attribute("title") == "Play all"

    play_toggle.click()
    assert play_toggle.get_attribute("title") == "Pause all"
    page.wait_for_function(
        "Number(document.querySelector('img[data-grid-image-sequence=\"1\"]')"
        ".getAttribute('data-current-frame')) > 0"
    )
    assert play_toggle.get_attribute("title") == "Pause all"
    assert play_toggle.text_content() == "⏸"

    play_toggle.click()
    paused_frame = image.get_attribute("data-current-frame")
    page.wait_for_timeout(750)

    assert image.get_attribute("data-current-frame") == paused_frame
    assert play_toggle.get_attribute("title") == "Play all"
    assert play_toggle.text_content() == "▶"


def test_schema_less_timeline_play_survives_media_attribute_updates(
    page, seurat_server
):
    _open_app(page, seurat_server, mode="step")

    image = page.locator('img[data-grid-image-sequence="1"]')
    play_toggle = page.locator('[data-vcr-action="toggle"]')
    page.evaluate(
        """() => {
            window.__seuratPlayMutationTimer = window.setInterval(() => {
                const image = document.querySelector(
                    'img[data-grid-image-sequence="1"]'
                );
                const frameCount = image.getAttribute("data-frame-count");
                image.setAttribute(
                    "data-frame-count",
                    frameCount === "35" ? "035" : "35"
                );
            }, 50);
        }"""
    )

    try:
        play_toggle.click()
        page.wait_for_function(
            "Number(document.querySelector('img[data-grid-image-sequence=\"1\"]')"
            ".getAttribute('data-current-frame')) > 0",
            timeout=3000,
        )
    finally:
        page.evaluate(
            """() => {
                window.clearInterval(window.__seuratPlayMutationTimer);
                delete window.__seuratPlayMutationTimer;
            }"""
        )


def test_schema_less_timeline_cursor_uses_step_not_normalized_progress(
    page, seurat_server
):
    _open_app(page, seurat_server, mode="step")

    slider = page.locator("#seurat-vcr-step-slider")
    image = page.locator('img[data-grid-image-sequence="1"]')
    slider.evaluate(
        """element => {
            element.value = "30";
            element.dispatchEvent(new Event("input", { bubbles: true }));
        }"""
    )
    page.wait_for_function(
        "document.querySelector('#seurat-vcr-time-value').textContent === 'Step = 30'"
    )

    assert image.get_attribute("data-current-frame") == "30"
    frame = page.locator(".seurat-plot1d svg rect").first
    cursor = page.locator(".seurat-plot1d-cursor-line")
    frame_x = float(frame.get_attribute("x"))
    frame_width = float(frame.get_attribute("width"))
    cursor_x = float(cursor.get_attribute("x1"))
    cursor_progress = (cursor_x - frame_x) / frame_width
    assert cursor_progress == pytest.approx(30.0 / 79.0, abs=0.01)


def test_physical_timeline_uses_declared_time_values(page, seurat_server):
    _open_app(page, seurat_server, mode="physical")

    label = page.locator("#seurat-vcr-time-value")
    slider = page.locator("#seurat-vcr-step-slider")
    image = page.locator('img[data-grid-image-sequence="1"]')
    label.wait_for(state="visible")
    assert label.text_content() == "Time = 0"
    assert image.get_attribute("data-current-frame") == "0"
    label_box = label.bounding_box()
    slider_box = slider.bounding_box()
    assert label_box is not None
    assert slider_box is not None
    assert label_box["y"] + label_box["height"] <= slider_box["y"] + 1
    slider_width = slider_box["width"]

    page.get_by_title("Forward step").click()

    page.wait_for_function(
        "document.querySelector('#seurat-vcr-time-value').textContent === 'Time = 0.25'"
    )
    assert image.get_attribute("data-current-frame") == "1"
    label_box = label.bounding_box()
    slider_box = slider.bounding_box()
    assert label_box is not None
    assert slider_box is not None
    assert label_box["y"] + label_box["height"] <= slider_box["y"] + 1
    assert slider_box["width"] == pytest.approx(slider_width, abs=1)


def test_multi_axis_slider_uses_active_axis_and_marks_incompatible_tiles(
    page, seurat_server
):
    _open_app(page, seurat_server, mode="multi-axis")

    label = page.locator("#seurat-vcr-time-value")
    slider = page.locator("#seurat-vcr-step-slider")
    waveform = page.locator('.seurat-dropcell[data-cell-index="1"]')
    incompatible = page.locator('.seurat-dropcell[data-cell-index="2"]')
    label.wait_for(state="visible")
    assert label.text_content() == "Shot number = 15"
    assert slider.get_attribute("max") == "2"

    page.get_by_title("Forward step").click()

    page.wait_for_function(
        "document.querySelector('#seurat-vcr-time-value').textContent === "
        "'Shot number = 16'"
    )
    page.wait_for_function(
        "document.querySelector('.seurat-dropcell[data-cell-index=\"1\"]')"
        ".getAttribute('data-selection-axis').includes('\"value\":16')"
    )
    assert waveform.get_attribute("data-axis-sync-status") == "synchronized"
    assert incompatible.get_attribute("data-axis-sync-status") == "incompatible"

    incompatible.click()

    page.wait_for_function(
        "document.querySelector('#seurat-vcr-time-value').textContent === "
        "'Time within shot = 0 s'"
    )
    assert slider.get_attribute("max") == "2"


def test_mixed_step_sequence_uses_declared_time_for_split_plot_cursor(
    page, seurat_server
):
    _open_app(page, seurat_server, mode="mixed")

    first_bar = page.locator(
        '.seurat-workspace-tab-bar[data-pane-frame-id="pane-1"]'
    )
    _split_workspace_pane_by_drag(page, first_bar, "vertical")
    page.get_by_role("tab", name="View 2").wait_for(state="visible")

    slider = page.locator("#seurat-vcr-step-slider")
    image = page.locator(
        '.seurat-workspace-grid-preview[data-pane-frame-id="pane-1"] '
        'img[data-grid-image-sequence="1"]'
    )
    slider.evaluate(
        """element => {
            element.value = "1";
            element.dispatchEvent(new Event("input", { bubbles: true }));
        }"""
    )
    page.wait_for_function(
        "document.querySelector('#seurat-vcr-time-value').textContent === 'Step = 0.25'"
    )
    assert image.get_attribute("data-current-frame") == "1"

    preview = page.locator(
        '.seurat-workspace-grid-preview[data-pane-frame-id="pane-1"]'
    )
    frame = preview.locator(".seurat-plot1d svg rect").first
    cursor = preview.locator(".seurat-plot1d-cursor-line")
    frame_x = float(frame.get_attribute("x"))
    frame_width = float(frame.get_attribute("width"))
    cursor_progress = (float(cursor.get_attribute("x1")) - frame_x) / frame_width
    assert cursor_progress == pytest.approx(0.25, abs=0.01)

    page.get_by_role("tab", name="View 1").click()
    active = page.locator(
        '.seurat-workspace-active-grid[data-pane-frame-id="pane-1"]'
    )
    active_cursor = active.locator(".seurat-plot1d-cursor-line")
    active_cursor.wait_for(state="attached")
    active_frame = active.locator(".seurat-plot1d svg rect").first
    active_progress = (
        float(active_cursor.get_attribute("x1"))
        - float(active_frame.get_attribute("x"))
    ) / float(active_frame.get_attribute("width"))
    assert active_progress == pytest.approx(0.25, abs=0.01)
