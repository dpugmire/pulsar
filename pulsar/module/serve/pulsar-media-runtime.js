(function initPulsarMediaRuntime() {
  "use strict";

  const PAN_ZOOM_MIN_SCALE = 0.25;
  const PAN_ZOOM_MAX_SCALE = 8;
  const PAN_ZOOM_WHEEL_OPTIONS = { capture: true, passive: false };

  let runtimeRoot = null;
  let onResetViewRequest = null;
  let panZoomDrag = null;
  let suppressPanZoomClick = false;
  let resetViewObserver = null;
  let resetViewRequestElement = null;
  let lastResetViewRequest = "";
  let panZoomResizeObserver = null;
  let panZoomDomObserver = null;
  let observedPanZoomViewports = null;
  let panZoomScanFrame = 0;

  function runtimeBody() {
    const ownerDocument = runtimeRoot && runtimeRoot.ownerDocument;
    return ownerDocument ? ownerDocument.body : document.body;
  }

  function panZoomContent(viewport) {
    if (!viewport || !viewport.children) return null;
    for (const child of viewport.children) {
      if (child.classList && child.classList.contains("pulsar-panzoom-content")) {
        return child;
      }
    }
    return viewport.querySelector
      ? viewport.querySelector(".pulsar-panzoom-content")
      : null;
  }

  function panZoomState(viewport) {
    if (!viewport.__pulsarPanZoomState) {
      viewport.__pulsarPanZoomState = { scale: 1, tx: 0, ty: 0 };
    }
    return viewport.__pulsarPanZoomState;
  }

  function clampPanZoomScale(scale) {
    const value = Number(scale);
    if (!Number.isFinite(value)) return 1;
    return Math.max(PAN_ZOOM_MIN_SCALE, Math.min(PAN_ZOOM_MAX_SCALE, value));
  }

  function scalarAxisNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatScalarAxisValue(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    if (Math.abs(number) < 1e-12) return "0";
    const magnitude = Math.abs(number);
    if (magnitude >= 1e5 || magnitude < 1e-4) {
      return number
        .toExponential(4)
        .replace(/\.?0+e/, "e")
        .replace(/e([+-])0+/, "e$1");
    }
    return number
      .toPrecision(5)
      .replace(/(\.\d*?[1-9])0+$/, "$1")
      .replace(/\.0+$/, "");
  }

  function scalarFieldDataRect(viewport) {
    if (
      !viewport ||
      !viewport.classList.contains("pulsar-scalar-field-show-axes")
    ) {
      return null;
    }
    const content = panZoomContent(viewport);
    const image = content && content.querySelector
      ? content.querySelector("img")
      : null;
    if (!content || !image) return null;

    const contentWidth = Number(content.clientWidth) || 0;
    const contentHeight = Number(content.clientHeight) || 0;
    if (contentWidth <= 0 || contentHeight <= 0) return null;

    const naturalWidth = Number(image.naturalWidth) || contentWidth;
    const naturalHeight = Number(image.naturalHeight) || contentHeight;
    const containScale = Math.min(
      contentWidth / Math.max(1, naturalWidth),
      contentHeight / Math.max(1, naturalHeight)
    );
    const width = Math.max(1, naturalWidth * containScale);
    const height = Math.max(1, naturalHeight * containScale);
    const imageOffsetX = (contentWidth - width) * 0.5;
    const imageOffsetY = (contentHeight - height) * 0.5;
    const contentLeft = Number(content.offsetLeft) || 0;
    const contentTop = Number(content.offsetTop) || 0;
    const key = [
      viewport.clientWidth,
      viewport.clientHeight,
      contentLeft,
      contentTop,
      contentWidth,
      contentHeight,
      naturalWidth,
      naturalHeight,
    ].join(":");

    if (
      viewport.__pulsarScalarFieldDataRect &&
      viewport.__pulsarScalarFieldDataRectKey === key
    ) {
      return viewport.__pulsarScalarFieldDataRect;
    }

    const rect = {
      contentLeft,
      contentTop,
      imageOffsetX,
      imageOffsetY,
      left: contentLeft + imageOffsetX,
      top: contentTop + imageOffsetY,
      width,
      height,
    };
    viewport.__pulsarScalarFieldDataRectKey = key;
    viewport.__pulsarScalarFieldDataRect = rect;
    return rect;
  }

  function alignScalarFieldAxes(viewport, dataRect) {
    if (!viewport || !dataRect) return;
    const xAxis = viewport.querySelector(".pulsar-scalar-field-x-axis");
    const yAxis = viewport.querySelector(".pulsar-scalar-field-y-axis");
    if (!xAxis || !yAxis) return;

    const viewportWidth = Number(viewport.clientWidth) || 0;
    const viewportHeight = Number(viewport.clientHeight) || 0;
    const imageRight = dataRect.left + dataRect.width;
    const imageBottom = dataRect.top + dataRect.height;
    const xAxisHeight =
      Number.parseFloat(getComputedStyle(xAxis).height) || 40;

    xAxis.style.left = dataRect.left.toFixed(2) + "px";
    xAxis.style.right =
      Math.max(0, viewportWidth - imageRight).toFixed(2) + "px";
    xAxis.style.bottom =
      Math.max(0, viewportHeight - imageBottom - xAxisHeight).toFixed(2) +
      "px";

    yAxis.style.width = Math.max(0, dataRect.left).toFixed(2) + "px";
    yAxis.style.top = dataRect.top.toFixed(2) + "px";
    yAxis.style.bottom =
      Math.max(0, viewportHeight - imageBottom).toFixed(2) + "px";
  }

  function updateScalarAxisTicks(axis, start, end) {
    if (!axis || !Number.isFinite(start) || !Number.isFinite(end)) return;
    for (const tick of axis.querySelectorAll("[data-axis-position]")) {
      const position = scalarAxisNumber(
        tick.getAttribute("data-axis-position")
      );
      if (position === null) continue;
      const value = start + (end - start) * (position / 100);
      const label = tick.querySelector(".pulsar-scalar-field-tick-label");
      const text = formatScalarAxisValue(value);
      if (label && label.textContent !== text) label.textContent = text;
      tick.setAttribute("data-axis-value", String(value));
    }
  }

  function syncScalarFieldAxes(viewport, state) {
    const dataRect = scalarFieldDataRect(viewport);
    if (!dataRect) return;
    alignScalarFieldAxes(viewport, dataRect);

    const xAxis = viewport.querySelector(".pulsar-scalar-field-x-axis");
    const yAxis = viewport.querySelector(".pulsar-scalar-field-y-axis");
    if (!xAxis || !yAxis) return;

    const xStart = scalarAxisNumber(xAxis.getAttribute("data-axis-start"));
    const xEnd = scalarAxisNumber(xAxis.getAttribute("data-axis-end"));
    const yStart = scalarAxisNumber(yAxis.getAttribute("data-axis-start"));
    const yEnd = scalarAxisNumber(yAxis.getAttribute("data-axis-end"));
    if (
      xStart === null ||
      xEnd === null ||
      yStart === null ||
      yEnd === null
    ) {
      return;
    }

    const scale = Math.max(1e-12, Number(state.scale) || 1);
    const tx = Number(state.tx) || 0;
    const ty = Number(state.ty) || 0;
    const xFraction = function(position) {
      return (
        ((dataRect.imageOffsetX + position * dataRect.width - tx) / scale -
          dataRect.imageOffsetX) /
        dataRect.width
      );
    };
    const yFraction = function(position) {
      return (
        ((dataRect.imageOffsetY + position * dataRect.height - ty) / scale -
          dataRect.imageOffsetY) /
        dataRect.height
      );
    };

    const visibleXStart = xStart + (xEnd - xStart) * xFraction(0);
    const visibleXEnd = xStart + (xEnd - xStart) * xFraction(1);
    const valueAtYFraction = function(fraction) {
      return yEnd + (yStart - yEnd) * fraction;
    };
    const visibleYStart = valueAtYFraction(yFraction(1));
    const visibleYEnd = valueAtYFraction(yFraction(0));

    updateScalarAxisTicks(xAxis, visibleXStart, visibleXEnd);
    updateScalarAxisTicks(yAxis, visibleYStart, visibleYEnd);
  }

  function applyPanZoom(viewport) {
    const content = panZoomContent(viewport);
    if (!content) return;
    const state = panZoomState(viewport);
    content.style.transform =
      "translate(" +
      state.tx.toFixed(2) +
      "px, " +
      state.ty.toFixed(2) +
      "px) scale(" +
      state.scale.toFixed(6) +
      ")";
    viewport.classList.toggle(
      "is-panzoomed",
      Math.abs(state.scale - 1) > 1e-6 ||
        Math.abs(state.tx) > 0.5 ||
        Math.abs(state.ty) > 0.5
    );
    syncScalarFieldAxes(viewport, state);
  }

  function resetPanZoom(viewport) {
    const state = panZoomState(viewport);
    state.scale = 1;
    state.tx = 0;
    state.ty = 0;
    applyPanZoom(viewport);
  }

  function resetPanZoomForCellIndex(cellIndex) {
    const idx = Number(cellIndex);
    if (!Number.isInteger(idx) || idx < 0 || !runtimeRoot) return;
    const cell = runtimeRoot.querySelector(
      '.pulsar-dropcell[data-cell-index="' + String(idx) + '"]'
    );
    if (!cell) return;
    const viewports = cell.querySelectorAll
      ? cell.querySelectorAll(".pulsar-panzoom-viewport")
      : [];
    for (const viewport of viewports) {
      resetPanZoom(viewport);
    }
  }

  function setPanZoomScaleAt(viewport, base, clientX, clientY, scale) {
    const rect = viewport.getBoundingClientRect();
    const content = panZoomContent(viewport);
    const state = panZoomState(viewport);
    const nextScale = clampPanZoomScale(scale);
    const localX =
      (Number(clientX) || 0) -
      rect.left -
      (content ? Number(content.offsetLeft) || 0 : 0);
    const localY =
      (Number(clientY) || 0) -
      rect.top -
      (content ? Number(content.offsetTop) || 0 : 0);
    const contentX = (localX - base.tx) / base.scale;
    const contentY = (localY - base.ty) / base.scale;
    state.scale = nextScale;
    state.tx = localX - contentX * nextScale;
    state.ty = localY - contentY * nextScale;
    applyPanZoom(viewport);
  }

  function zoomPanZoomAt(viewport, clientX, clientY, factor) {
    const base = Object.assign({}, panZoomState(viewport));
    setPanZoomScaleAt(viewport, base, clientX, clientY, base.scale * factor);
  }

  function panZoomViewportFromEvent(event) {
    const target = event && event.target;
    const viewport =
      target && target.closest
        ? target.closest(".pulsar-panzoom-viewport")
        : null;
    if (
      !viewport ||
      !runtimeRoot ||
      !runtimeRoot.contains(viewport) ||
      target.closest(".pulsar-grid-track-resize-handle")
    ) {
      return null;
    }
    return viewport;
  }

  function releasePanZoomPointerCapture(drag) {
    if (!drag || !drag.viewport || drag.pointerId === undefined) return;
    try {
      if (
        !drag.viewport.hasPointerCapture ||
        drag.viewport.hasPointerCapture(drag.pointerId)
      ) {
        drag.viewport.releasePointerCapture(drag.pointerId);
      }
    } catch (_) {
      // The pointer may already have been released by the browser.
    }
  }

  function onPanZoomPointerDown(event) {
    const viewport = panZoomViewportFromEvent(event);
    if (!viewport) return;
    const isShiftPan = event.button === 0 && event.shiftKey;
    const isMiddleZoom = event.button === 1;
    if (!isShiftPan && !isMiddleZoom) return;

    finishPanZoomDrag();
    panZoomDrag = {
      viewport,
      mode: isMiddleZoom ? "zoom" : "pan",
      startX: Number(event.clientX) || 0,
      startY: Number(event.clientY) || 0,
      base: Object.assign({}, panZoomState(viewport)),
      pointerId: event.pointerId,
      moved: false,
    };
    viewport.classList.add(isMiddleZoom ? "is-zooming" : "is-panning");
    runtimeBody().classList.add(
      isMiddleZoom ? "pulsar-panzoom-zooming" : "pulsar-panzoom-panning"
    );
    try {
      viewport.setPointerCapture(event.pointerId);
    } catch (_) {
      // Pointer capture is best-effort for older browser implementations.
    }
    event.preventDefault();
    event.stopPropagation();
  }

  function onPanZoomPointerMove(event) {
    if (!panZoomDrag) return;
    if (
      panZoomDrag.pointerId !== undefined &&
      event.pointerId !== panZoomDrag.pointerId
    ) {
      return;
    }
    const dx = (Number(event.clientX) || 0) - panZoomDrag.startX;
    const dy = (Number(event.clientY) || 0) - panZoomDrag.startY;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
      panZoomDrag.moved = true;
    }
    const state = panZoomState(panZoomDrag.viewport);
    if (panZoomDrag.mode === "pan") {
      state.scale = panZoomDrag.base.scale;
      state.tx = panZoomDrag.base.tx + dx;
      state.ty = panZoomDrag.base.ty + dy;
      applyPanZoom(panZoomDrag.viewport);
    } else {
      const factor = Math.exp(-dy * 0.01);
      setPanZoomScaleAt(
        panZoomDrag.viewport,
        panZoomDrag.base,
        panZoomDrag.startX,
        panZoomDrag.startY,
        panZoomDrag.base.scale * factor
      );
    }
    event.preventDefault();
    event.stopPropagation();
  }

  function finishPanZoomDrag(event) {
    if (!panZoomDrag) return;
    const current = panZoomDrag;
    panZoomDrag = null;
    current.viewport.classList.remove("is-panning", "is-zooming");
    runtimeBody().classList.remove(
      "pulsar-panzoom-panning",
      "pulsar-panzoom-zooming"
    );
    suppressPanZoomClick = !!current.moved;
    releasePanZoomPointerCapture(current);
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onPanZoomPointerEnd(event) {
    if (
      panZoomDrag &&
      (panZoomDrag.pointerId === undefined ||
        event.pointerId === panZoomDrag.pointerId)
    ) {
      finishPanZoomDrag(event);
    }
  }

  function onPanZoomLostPointerCapture(event) {
    if (panZoomDrag && event.target === panZoomDrag.viewport) {
      finishPanZoomDrag();
    }
  }

  function onPanZoomWheel(event) {
    const viewport = panZoomViewportFromEvent(event);
    if (!viewport) return;
    const factor = Math.exp(-(Number(event.deltaY) || 0) * 0.0015);
    zoomPanZoomAt(viewport, event.clientX, event.clientY, factor);
    event.preventDefault();
    event.stopPropagation();
  }

  function onPanZoomDoubleClick(event) {
    const viewport = panZoomViewportFromEvent(event);
    if (!viewport) return;
    resetPanZoom(viewport);
    event.preventDefault();
    event.stopPropagation();
  }

  function onPanZoomDragStart(event) {
    const viewport = panZoomViewportFromEvent(event);
    if (viewport && (panZoomDrag || event.shiftKey)) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onPanZoomAuxClick(event) {
    const viewport = panZoomViewportFromEvent(event);
    if (viewport && event.button === 1) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onPanZoomClick(event) {
    if (!suppressPanZoomClick) return;
    suppressPanZoomClick = false;
    const viewport = panZoomViewportFromEvent(event);
    if (!viewport) return;
    event.preventDefault();
    event.stopPropagation();
  }

  function observePanZoomViewport(viewport) {
    if (
      !viewport ||
      !observedPanZoomViewports ||
      observedPanZoomViewports.has(viewport)
    ) {
      return;
    }
    observedPanZoomViewports.add(viewport);
    if (panZoomResizeObserver) panZoomResizeObserver.observe(viewport);
  }

  function scanPanZoomViewports() {
    panZoomScanFrame = 0;
    if (!runtimeRoot) return;
    for (const viewport of runtimeRoot.querySelectorAll(
      ".pulsar-panzoom-viewport"
    )) {
      observePanZoomViewport(viewport);
      applyPanZoom(viewport);
    }
  }

  function schedulePanZoomViewportScan() {
    if (!runtimeRoot || panZoomScanFrame) return;
    panZoomScanFrame = requestAnimationFrame(scanPanZoomViewports);
  }

  function onPanZoomImageLoad(event) {
    const image = event && event.target;
    const viewport =
      image && image.closest
        ? image.closest(".pulsar-panzoom-viewport")
        : null;
    if (!viewport || !runtimeRoot || !runtimeRoot.contains(viewport)) return;
    viewport.__pulsarScalarFieldDataRectKey = "";
    observePanZoomViewport(viewport);
    applyPanZoom(viewport);
  }

  function handleResetViewRequest(raw) {
    const text = String(raw || "");
    if (!text || text === lastResetViewRequest) return;
    lastResetViewRequest = text;
    try {
      const request = JSON.parse(text);
      const cellIndex = request && request.cell_index;
      if (onResetViewRequest) {
        onResetViewRequest(cellIndex);
      } else {
        resetPanZoomForCellIndex(cellIndex);
      }
    } catch (_err) {
      // Ignore malformed transient reset requests.
    }
  }

  function scanResetViewRequest() {
    if (!resetViewRequestElement) return;
    handleResetViewRequest(
      resetViewRequestElement.getAttribute("data-reset-view-request") || ""
    );
  }

  function unmountPanZoomRuntime(root) {
    if (!root || root !== runtimeRoot) return;
    finishPanZoomDrag();
    suppressPanZoomClick = false;
    root.removeEventListener("pointerdown", onPanZoomPointerDown, true);
    root.removeEventListener("pointermove", onPanZoomPointerMove, true);
    root.removeEventListener("pointerup", onPanZoomPointerEnd, true);
    root.removeEventListener("pointercancel", onPanZoomPointerEnd, true);
    root.removeEventListener(
      "lostpointercapture",
      onPanZoomLostPointerCapture,
      true
    );
    root.removeEventListener("wheel", onPanZoomWheel, PAN_ZOOM_WHEEL_OPTIONS);
    root.removeEventListener("dblclick", onPanZoomDoubleClick, true);
    root.removeEventListener("dragstart", onPanZoomDragStart, true);
    root.removeEventListener("auxclick", onPanZoomAuxClick, true);
    root.removeEventListener("click", onPanZoomClick, true);
    root.removeEventListener("load", onPanZoomImageLoad, true);
    if (panZoomScanFrame) {
      cancelAnimationFrame(panZoomScanFrame);
      panZoomScanFrame = 0;
    }
    if (panZoomResizeObserver) {
      panZoomResizeObserver.disconnect();
      panZoomResizeObserver = null;
    }
    if (panZoomDomObserver) {
      panZoomDomObserver.disconnect();
      panZoomDomObserver = null;
    }
    observedPanZoomViewports = null;
    if (resetViewObserver) {
      resetViewObserver.disconnect();
      resetViewObserver = null;
    }
    resetViewRequestElement = null;
    lastResetViewRequest = "";
    onResetViewRequest = null;
    runtimeBody().classList.remove(
      "pulsar-panzoom-panning",
      "pulsar-panzoom-zooming"
    );
    for (const viewport of root.querySelectorAll(
      ".pulsar-panzoom-viewport.is-panning, .pulsar-panzoom-viewport.is-zooming"
    )) {
      viewport.classList.remove("is-panning", "is-zooming");
    }
    root.removeAttribute("data-pulsar-media-runtime-owner");
    runtimeRoot = null;
  }

  function mountPanZoomRuntime(root, options) {
    if (!root) return;
    if (root === runtimeRoot) {
      onResetViewRequest =
        options && typeof options.onResetViewRequest === "function"
          ? options.onResetViewRequest
          : null;
      schedulePanZoomViewportScan();
      return;
    }
    if (runtimeRoot) unmountPanZoomRuntime(runtimeRoot);

    runtimeRoot = root;
    onResetViewRequest =
      options && typeof options.onResetViewRequest === "function"
        ? options.onResetViewRequest
        : null;
    root.setAttribute("data-pulsar-media-runtime-owner", "mounted");
    root.addEventListener("pointerdown", onPanZoomPointerDown, true);
    root.addEventListener("pointermove", onPanZoomPointerMove, true);
    root.addEventListener("pointerup", onPanZoomPointerEnd, true);
    root.addEventListener("pointercancel", onPanZoomPointerEnd, true);
    root.addEventListener(
      "lostpointercapture",
      onPanZoomLostPointerCapture,
      true
    );
    root.addEventListener("wheel", onPanZoomWheel, PAN_ZOOM_WHEEL_OPTIONS);
    root.addEventListener("dblclick", onPanZoomDoubleClick, true);
    root.addEventListener("dragstart", onPanZoomDragStart, true);
    root.addEventListener("auxclick", onPanZoomAuxClick, true);
    root.addEventListener("click", onPanZoomClick, true);
    root.addEventListener("load", onPanZoomImageLoad, true);

    observedPanZoomViewports = new WeakSet();
    panZoomResizeObserver = new ResizeObserver(function(entries) {
      for (const entry of entries || []) {
        if (entry && entry.target) applyPanZoom(entry.target);
      }
    });
    panZoomDomObserver = new MutationObserver(schedulePanZoomViewportScan);
    panZoomDomObserver.observe(root, {
      childList: true,
      subtree: true,
    });
    scanPanZoomViewports();

    lastResetViewRequest = "";
    resetViewRequestElement = root.querySelector("#pulsar-reset-view-request");
    if (resetViewRequestElement) {
      resetViewObserver = new MutationObserver(scanResetViewRequest);
      resetViewObserver.observe(resetViewRequestElement, {
        attributes: true,
        attributeFilter: ["data-reset-view-request"],
      });
      scanResetViewRequest();
    }
  }

  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  const runtime = runtimes.media || window.pulsarMediaRuntime || {};
  runtime.mount = mountPanZoomRuntime;
  runtime.unmount = unmountPanZoomRuntime;
  runtime.resetViewForCellIndex = resetPanZoomForCellIndex;
  runtimes.media = runtime;
  window.pulsarMediaRuntime = runtime;
})();
