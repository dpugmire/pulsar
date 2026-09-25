(function initPulsarClient() {
  "use strict";

  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  let gridRuntimeRoot = null;

  function runtime(name, methods) {
    const candidate = runtimes[name];
    if (!candidate) return null;
    for (const method of methods) {
      if (typeof candidate[method] !== "function") return null;
    }
    return candidate;
  }

  function mediaRuntime() {
    return runtime("media", ["mount", "unmount", "resetViewForCellIndex"]);
  }

  function plotRuntime() {
    return runtime("plot", ["mount", "unmount", "resetViewForCellIndex", "scheduleRender"]);
  }

  function timelineRuntime() {
    return runtime("timeline", ["mount", "unmount", "runAction", "refreshPlotCursors"]);
  }

  function resetGridViewForCellIndex(cellIndex) {
    const idx = Number(cellIndex);
    if (!Number.isInteger(idx) || idx < 0) return;
    const media = mediaRuntime();
    if (media) media.resetViewForCellIndex(idx);
    const plot = plotRuntime();
    if (plot) plot.resetViewForCellIndex(idx);
  }

  function schedulePlotRender() {
    const plot = plotRuntime();
    if (plot) plot.scheduleRender();
  }

  function runGridVcrAction(action) {
    const timeline = timelineRuntime();
    if (timeline) timeline.runAction(action);
  }

  function unmountGridRuntime(root) {
    if (!root || root !== gridRuntimeRoot) return;
    const plot = plotRuntime();
    if (plot) plot.unmount(root);
    const media = mediaRuntime();
    if (media) media.unmount(root);
    const timeline = timelineRuntime();
    if (timeline) timeline.unmount(root);
    root.removeAttribute("data-pulsar-grid-runtime-owner");
    gridRuntimeRoot = null;
  }

  function mountGridRuntime(root) {
    if (!root || root === gridRuntimeRoot) return;
    if (gridRuntimeRoot) unmountGridRuntime(gridRuntimeRoot);
    gridRuntimeRoot = root;
    root.setAttribute("data-pulsar-grid-runtime-owner", "mounted");

    const timeline = timelineRuntime();
    if (timeline) timeline.mount(root);

    const media = mediaRuntime();
    if (media) {
      media.mount(root, {
        onResetViewRequest: resetGridViewForCellIndex,
      });
    }

    const plot = plotRuntime();
    if (plot) {
      plot.mount(root, {
        onCursorRefresh: timeline
          ? timeline.refreshPlotCursors
          : null,
      });
    }
  }

  const grid = runtimes.grid || window.pulsarGridRuntime || {};
  grid.mount = mountGridRuntime;
  grid.unmount = unmountGridRuntime;
  grid.resetViewForCellIndex = resetGridViewForCellIndex;
  grid.schedulePlotRender = schedulePlotRender;
  grid.runVcrAction = runGridVcrAction;
  runtimes.grid = grid;
  window.pulsarGridRuntime = grid;
})();
