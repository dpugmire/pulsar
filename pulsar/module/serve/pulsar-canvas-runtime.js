(function registerPulsarCanvasRuntime() {
  const mountedRoots = new WeakMap();
  const TILE_INSET = 2;

  function trameTrigger(name, args) {
    if (window.trame && window.trame.trigger) window.trame.trigger(name, args || []);
  }

  function schedulePlotRender() {
    const pulsar = window.pulsar || {};
    const runtime = (pulsar.runtimes && pulsar.runtimes.plot)
      || window.pulsarPlotRuntime;
    if (runtime && typeof runtime.scheduleRender === "function") {
      runtime.scheduleRender();
    }
  }

  function closestWithinRoot(target, selector, root) {
    if (!target || !target.closest) return null;
    const element = target.closest(selector);
    return element && root.contains(element) ? element : null;
  }

  function activeCanvas(target, root) {
    const canvas = closestWithinRoot(target, ".pulsar-freeform-canvas", root);
    return canvas && canvas.classList.contains("pulsar-workspace-active-grid") ? canvas : null;
  }

  function clampZoom(value, maximum) {
    return Math.max(0.25, Math.min(maximum == null ? 2 : maximum, Number(value || 1)));
  }

  function canvasMetrics(canvas, zoomOverride) {
    const columns = Number(canvas.dataset.canvasCols || 24);
    const baseRowHeight = Number(canvas.dataset.canvasRowHeight || 24);
    const zoom = clampZoom(
      zoomOverride == null
        ? canvas.dataset.canvasEffectiveZoom || canvas.dataset.canvasZoom || 1
        : zoomOverride
    );
    const baseColumnWidth = canvas.clientWidth / columns;
    return {
      columns,
      zoom,
      baseRowHeight,
      baseColumnWidth,
      rowHeight: baseRowHeight * zoom,
      columnWidth: baseColumnWidth * zoom,
      snap: canvas.dataset.canvasSnap !== "0",
      nudge: canvas.dataset.canvasNudge !== "0",
      dwell: Number(canvas.dataset.canvasDwellMs || 260),
      deadZone: Number(canvas.dataset.canvasDeadZone || 0.55),
    };
  }

  function readLayout(canvas) {
    return Array.from(canvas.querySelectorAll(":scope > .pulsar-dropcell[data-tile-id]"))
      .map((element) => ({
        tile_id: element.dataset.tileId || "",
        tile_type: element.dataset.tileType || "plot",
        x: Number(element.dataset.canvasX || 0),
        y: Number(element.dataset.canvasY || 0),
        w: Number(element.dataset.canvasW || 4),
        h: Number(element.dataset.canvasH || 3),
        element,
      }))
      .filter((item) => item.tile_id);
  }

  function geometryOnly(item) {
    return {
      tile_id: item.tile_id,
      tile_type: item.tile_type,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
    };
  }

  function cloneLayout(items) {
    return items.map((item) => Object.assign({}, geometryOnly(item), { element: item.element }));
  }

  function layoutById(items) {
    return new Map(items.map((item) => [item.tile_id, item]));
  }

  function placeElement(element, item, metrics) {
    if (!element) return;
    element.style.left = `${item.x * metrics.columnWidth + TILE_INSET * metrics.zoom}px`;
    element.style.top = `${item.y * metrics.rowHeight + TILE_INSET * metrics.zoom}px`;
    element.style.width = `${Math.max(1, item.w * metrics.baseColumnWidth - 2 * TILE_INSET)}px`;
    element.style.height = `${Math.max(1, item.h * metrics.baseRowHeight - 2 * TILE_INSET)}px`;
    element.style.transform = `scale(${metrics.zoom})`;
    element.style.transformOrigin = "top left";
  }

  function renderLayout(items, metrics, excludedId) {
    for (const item of items) {
      if (item.tile_id !== excludedId) placeElement(item.element, item, metrics);
    }
  }

  function contentBounds(items) {
    return {
      right: Math.max(0, ...items.map((item) => item.x + item.w)),
      bottom: Math.max(0, ...items.map((item) => item.y + item.h)),
    };
  }

  function fittedZoom(canvas, items) {
    if (!items.length || !canvas.clientWidth || !canvas.clientHeight) return 1;
    const base = canvasMetrics(canvas, 1);
    const bounds = contentBounds(items);
    const padding = 24;
    const availableWidth = Math.max(1, canvas.clientWidth - padding);
    const availableHeight = Math.max(1, canvas.clientHeight - padding);
    const contentWidth = Math.max(1, bounds.right * base.baseColumnWidth);
    const contentHeight = Math.max(1, bounds.bottom * base.baseRowHeight);
    return clampZoom(
      Math.min(1, availableWidth / contentWidth, availableHeight / contentHeight),
      1
    );
  }

  function updateZoomLabel(root, zoom, fit) {
    const label = root.querySelector("[data-canvas-zoom-label]");
    if (!label) return;
    label.textContent = `${Math.round(zoom * 100)}%`;
    label.dataset.canvasFitActive = fit ? "1" : "0";
  }

  function applyCanvasView(canvas, root) {
    if (!canvas || !canvas.classList.contains("pulsar-freeform-canvas")) return;
    const items = readLayout(canvas);
    const fit = canvas.dataset.canvasFit === "1";
    const requestedZoom = clampZoom(canvas.dataset.canvasZoom || 1);
    const zoom = fit
      ? fittedZoom(canvas, items)
      : requestedZoom;
    canvas.dataset.canvasEffectiveZoom = String(zoom);
    const metrics = canvasMetrics(canvas, zoom);
    renderLayout(items, metrics);

    const bounds = contentBounds(items);
    const worldRows = Math.max(13, Math.ceil(bounds.bottom) + 1);
    const worldHeight = worldRows * metrics.baseRowHeight;
    const overlay = canvas.querySelector(":scope > .pulsar-canvas-grid-overlay");
    if (overlay) {
      overlay.style.width = `${canvas.clientWidth}px`;
      overlay.style.height = `${worldHeight}px`;
      overlay.style.minHeight = "0";
      overlay.style.transform = `scale(${zoom})`;
      overlay.style.transformOrigin = "top left";
    }
    const extent = canvas.querySelector(":scope > .pulsar-canvas-extent");
    if (extent) {
      extent.style.left = `${canvas.clientWidth * zoom}px`;
      extent.style.top = `${worldHeight * zoom}px`;
    }
    if (fit) {
      canvas.scrollLeft = 0;
      canvas.scrollTop = 0;
      const syncedZoom = Number(canvas.dataset.canvasFitSyncedZoom || 0);
      if (
        Math.abs(requestedZoom - zoom) > 0.0005 &&
        Math.abs(syncedZoom - zoom) > 0.0005
      ) {
        canvas.dataset.canvasFitSyncedZoom = String(zoom);
        trameTrigger("sync_canvas_fit_zoom_trigger", [
          zoom,
          canvas.dataset.paneId || "",
          canvas.dataset.tabId || "",
        ]);
      }
    } else {
      delete canvas.dataset.canvasFitSyncedZoom;
    }
    updateZoomLabel(root, zoom, fit);
  }

  function installCanvasViewRuntime(root) {
    let frame = 0;
    const observedCanvases = new WeakSet();
    const resizeObserver = new ResizeObserver(() => schedule());

    function refresh() {
      frame = 0;
      const canvases = root.querySelectorAll(
        ".pulsar-freeform-canvas.pulsar-workspace-active-grid"
      );
      for (const canvas of canvases) {
        if (!observedCanvases.has(canvas)) {
          resizeObserver.observe(canvas);
          observedCanvases.add(canvas);
        }
        applyCanvasView(canvas, root);
      }
    }

    function schedule() {
      if (frame) return;
      frame = window.requestAnimationFrame(refresh);
    }

    const mutationObserver = new MutationObserver(schedule);
    mutationObserver.observe(root, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: [
        "data-layout-mode",
        "data-canvas-cols",
        "data-canvas-row-height",
        "data-canvas-zoom",
        "data-canvas-fit",
        "data-canvas-revision",
      ],
    });
    resizeObserver.observe(root);
    schedule();
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      mutationObserver.disconnect();
      resizeObserver.disconnect();
    };
  }

  function canvasPoint(event, canvas, metrics) {
    const bounds = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(metrics.columns, (event.clientX - bounds.left + canvas.scrollLeft) / metrics.columnWidth)),
      y: Math.max(0, (event.clientY - bounds.top + canvas.scrollTop) / metrics.rowHeight),
    };
  }

  function chrome(canvas) {
    return {
      placeholder: canvas.querySelector(":scope > .pulsar-canvas-placeholder"),
      caret: canvas.querySelector(":scope > .pulsar-canvas-insertion-caret"),
      vertical: Array.from(canvas.querySelectorAll(":scope > .pulsar-canvas-guide-v")),
      horizontal: Array.from(canvas.querySelectorAll(":scope > .pulsar-canvas-guide-h")),
    };
  }

  function hideGuides(parts) {
    for (const element of parts.vertical.concat(parts.horizontal)) {
      element.classList.remove("is-visible");
    }
  }

  function hideChrome(parts) {
    parts.placeholder.classList.remove("is-visible", "is-destructive");
    parts.caret.classList.remove("is-visible");
    hideGuides(parts);
  }

  function showPlaceholder(parts, item, metrics, destructive) {
    const element = parts.placeholder;
    placeElement(element, item, metrics);
    element.classList.toggle("is-destructive", Boolean(destructive));
    element.classList.add("is-visible");
  }

  function showCaret(parts, zone, item, metrics) {
    const caret = parts.caret;
    caret.classList.add("is-visible");
    if (zone.orientation === "row") {
      caret.style.left = `${item.x * metrics.columnWidth}px`;
      caret.style.top = `${zone.seam * metrics.rowHeight - 2}px`;
      caret.style.width = `${item.w * metrics.columnWidth}px`;
      caret.style.height = "4px";
    } else {
      caret.style.left = `${zone.seam * metrics.columnWidth - 2}px`;
      caret.style.top = `${item.y * metrics.rowHeight}px`;
      caret.style.width = "4px";
      caret.style.height = `${item.h * metrics.rowHeight}px`;
    }
  }

  function showGuides(parts, item, snapshot, metrics) {
    hideGuides(parts);
    const verticalEdges = new Set();
    const horizontalEdges = new Set();
    for (const other of snapshot) {
      if (other.tile_id === item.tile_id) continue;
      verticalEdges.add(other.x);
      verticalEdges.add(other.x + other.w);
      horizontalEdges.add(other.y);
      horizontalEdges.add(other.y + other.h);
    }
    let verticalIndex = 0;
    let horizontalIndex = 0;
    for (const edge of [item.x, item.x + item.w]) {
      if (verticalEdges.has(edge) && verticalIndex < parts.vertical.length) {
        const guide = parts.vertical[verticalIndex++];
        guide.style.left = `${edge * metrics.columnWidth}px`;
        guide.classList.add("is-visible");
      }
    }
    for (const edge of [item.y, item.y + item.h]) {
      if (horizontalEdges.has(edge) && horizontalIndex < parts.horizontal.length) {
        const guide = parts.horizontal[horizontalIndex++];
        guide.style.top = `${edge * metrics.rowHeight}px`;
        guide.classList.add("is-visible");
      }
    }
  }

  function replaceItem(snapshot, item) {
    return snapshot.map((original) => original.tile_id === item.tile_id ? Object.assign({}, item, { element: original.element }) : Object.assign({}, original));
  }

  function attachElements(items, snapshot) {
    const elements = new Map(snapshot.map((item) => [item.tile_id, item.element]));
    return items.map((item) => Object.assign({}, item, { element: elements.get(item.tile_id) }));
  }

  function createHandlers(root) {
    const engine = window.pulsarCanvasLayout;
    let interaction = null;
    let externalDrop = null;

    function resetPreview() {
      if (!interaction) return;
      renderLayout(interaction.snapshot, interaction.metrics, interaction.tile.tile_id);
      interaction.previewed = false;
    }

    function queueDestructivePreview(key, layout) {
      if (!interaction) return;
      interaction.finalLayout = layout;
      if (interaction.previewKey === key) return;
      interaction.previewKey = key;
      resetPreview();
      if (interaction.timer) window.clearTimeout(interaction.timer);
      interaction.timer = window.setTimeout(() => {
        if (!interaction || interaction.previewKey !== key) return;
        renderLayout(layout, interaction.metrics, interaction.tile.tile_id);
        interaction.previewed = true;
      }, interaction.metrics.dwell);
    }

    function clearDestructivePreview() {
      if (!interaction) return;
      if (interaction.timer) window.clearTimeout(interaction.timer);
      interaction.timer = 0;
      interaction.previewKey = "";
      if (interaction.previewed) resetPreview();
    }

    function clearCrossTarget(state, removeGhost) {
      if (!state) return;
      if (state.crossTarget) {
        state.crossTarget.placeholder.classList.remove(
          "is-visible",
          "is-destructive"
        );
        state.crossTarget.canvas.classList.remove("is-canvas-drop-target");
        state.crossTarget = null;
      }
      state.tileElement.style.opacity = "";
      if (state.ghost) {
        if (removeGhost) {
          state.ghost.remove();
          state.ghost = null;
        } else {
          state.ghost.style.display = "none";
        }
      }
    }

    function updateCrossTarget(event) {
      const state = interaction;
      const elementAtPointer = document.elementFromPoint(
        event.clientX,
        event.clientY
      );
      const target = closestWithinRoot(
        elementAtPointer,
        ".pulsar-freeform-preview",
        root
      );
      if (!target) {
        clearCrossTarget(state, false);
        return false;
      }
      clearDestructivePreview();
      renderLayout(state.snapshot, state.metrics, state.tile.tile_id);
      hideChrome(state.parts);
      const targetMetrics = canvasMetrics(target);
      const point = canvasPoint(event, target, targetMetrics);
      const targetLayout = readLayout(target);
      const desired = engine.normalize(
        Object.assign({}, state.tile, {
          x: point.x - state.tile.w / 2,
          y: point.y - 1,
        }),
        targetMetrics.snap,
        targetMetrics.columns
      );
      const minimum = engine.minimumSize(state.tile.tile_type);
      const fit = engine.fitRectangle(
        Math.round(desired.x),
        Math.round(desired.y),
        desired.w,
        desired.h,
        targetLayout,
        targetMetrics.columns
      );
      const geometry =
        fit.w >= minimum[0] && fit.h >= minimum[1]
          ? Object.assign({}, desired, fit)
          : engine.nearestFree(
              desired,
              targetLayout,
              targetMetrics.columns
            );
      const placeholder = target.querySelector(
        ":scope > .pulsar-canvas-preview-placeholder"
      );
      if (!placeholder) return false;
      if (
        state.crossTarget &&
        state.crossTarget.canvas !== target
      ) {
        clearCrossTarget(state, false);
      }
      showPlaceholder({ placeholder }, geometry, targetMetrics, false);
      target.classList.add("is-canvas-drop-target");
      state.crossTarget = {
        canvas: target,
        placeholder,
        geometry,
      };
      if (!state.ghost) {
        const bounds = state.tileElement.getBoundingClientRect();
        state.ghost = state.tileElement.cloneNode(true);
        state.ghost.classList.remove(
          "is-canvas-dragging",
          "is-canvas-resizing"
        );
        state.ghost.classList.add("pulsar-canvas-cross-pane-ghost");
        state.ghost.setAttribute("aria-hidden", "true");
        state.ghost.style.width = `${bounds.width}px`;
        state.ghost.style.height = `${bounds.height}px`;
        state.ghost.style.transform = "none";
        root.appendChild(state.ghost);
      }
      state.ghost.style.display = "flex";
      state.ghost.style.left = `${event.clientX - state.ghost.offsetWidth / 2}px`;
      state.ghost.style.top = `${event.clientY - 18}px`;
      state.tileElement.style.opacity = "0.18";
      return true;
    }

    function startPointer(event) {
      if (event.button !== 0 || !engine) return;
      const resizeHandle = closestWithinRoot(event.target, ".pulsar-canvas-resize-zone", root);
      const header = closestWithinRoot(event.target, ".pulsar-tile-header", root);
      if (!resizeHandle && !header) return;
      if (header && closestWithinRoot(event.target, "button", root)) return;
      const tileElement = closestWithinRoot(event.target, ".pulsar-dropcell[data-tile-id]", root);
      const canvas = activeCanvas(tileElement, root);
      if (!tileElement || !canvas) return;
      const snapshot = readLayout(canvas);
      const tile = snapshot.find((item) => item.tile_id === tileElement.dataset.tileId);
      if (!tile) return;
      const metrics = canvasMetrics(canvas);
      interaction = {
        canvas,
        metrics,
        parts: chrome(canvas),
        snapshot: cloneLayout(snapshot),
        tile,
        tileElement,
        mode: resizeHandle ? "resize" : "move",
        resizeEdge: resizeHandle
          ? resizeHandle.dataset.resizeEdge || "bottom-right"
          : "",
        pointerId: event.pointerId,
        handle: resizeHandle || header,
        startX: event.clientX,
        startY: event.clientY,
        snappedX: tile.x,
        snappedY: tile.y,
        snappedW: tile.w,
        snappedH: tile.h,
        finalLayout: cloneLayout(snapshot),
        previewKey: "",
        previewed: false,
        timer: 0,
        crossTarget: null,
        ghost: null,
      };
      tileElement.classList.add(resizeHandle ? "is-canvas-resizing" : "is-canvas-dragging");
      canvas.classList.add("is-canvas-interacting");
      try { interaction.handle.setPointerCapture(event.pointerId); } catch (_) {}
      event.preventDefault();
    }

    function moveTile(event) {
      const state = interaction;
      const { metrics, tile, snapshot, parts } = state;
      const minimum = engine.minimumSize(tile.tile_type);
      const continuousX = Math.max(0, Math.min(tile.x + (event.clientX - state.startX) / metrics.columnWidth, metrics.columns - tile.w));
      const continuousY = Math.max(0, tile.y + (event.clientY - state.startY) / metrics.rowHeight);
      placeElement(state.tileElement, Object.assign({}, tile, { x: continuousX, y: continuousY }), metrics);
      let x = continuousX;
      let y = continuousY;
      if (metrics.snap) {
        x = Math.max(0, Math.min(engine.stickySnap(continuousX, state.snappedX, metrics.deadZone), metrics.columns - minimum[0]));
        y = Math.max(0, engine.stickySnap(continuousY, state.snappedY, metrics.deadZone));
        state.snappedX = x;
        state.snappedY = y;
      }
      const desired = engine.normalize(Object.assign({}, tile, { x, y }), metrics.snap, metrics.columns);
      const others = snapshot.filter((item) => item.tile_id !== tile.tile_id);

      if (!metrics.snap) {
        clearDestructivePreview();
        let candidate = desired;
        if (others.some((item) => engine.overlaps(candidate, item))) {
          candidate = engine.nearestFree(candidate, others, metrics.columns);
        }
        state.finalLayout = replaceItem(snapshot, candidate);
        showPlaceholder(parts, candidate, metrics, false);
        showGuides(parts, candidate, snapshot, metrics);
        return;
      }

      const pointer = canvasPoint(event, state.canvas, metrics);
      const zone = metrics.nudge ? engine.insertionZone(
        snapshot,
        tile.tile_id,
        pointer.x,
        pointer.y,
        {
          xTolerance: 10 / metrics.columnWidth,
          yTolerance: 10 / metrics.rowHeight,
        }
      ) : null;
      if (zone && zone.orientation === "row") {
        const inserted = Object.assign({}, tile, {
          x: Math.max(0, Math.min(zone.anchor_x, metrics.columns - tile.w)),
          y: zone.seam,
        });
        const layout = attachElements(engine.verticalPush(replaceItem(snapshot, inserted), tile.tile_id), snapshot);
        parts.placeholder.classList.remove("is-visible");
        showCaret(parts, zone, inserted, metrics);
        hideGuides(parts);
        queueDestructivePreview(`row:${zone.seam}:${inserted.x}`, layout);
        return;
      }
      if (zone && zone.orientation === "column") {
        const moveIds = engine.connectedColumnMoveSet(snapshot, zone.seam, zone.anchor_y, tile.h, tile.tile_id);
        const moveItems = snapshot.filter((item) => moveIds.includes(item.tile_id));
        const size = engine.columnInsertionSize(tile, moveItems, zone.seam, metrics.columns);
        if (size) {
          const layout = attachElements(engine.applyColumnInsertion(snapshot, {
            draggedId: tile.tile_id,
            seam: zone.seam,
            anchorY: zone.anchor_y,
            moveIds,
            width: size.w,
            height: size.h,
            mode: size.mode,
            columns: metrics.columns,
          }), snapshot);
          const inserted = layoutById(layout).get(tile.tile_id);
          parts.placeholder.classList.remove("is-visible");
          showCaret(parts, zone, inserted, metrics);
          hideGuides(parts);
          queueDestructivePreview(`column:${zone.seam}:${zone.anchor_y}:${size.mode}`, layout);
          return;
        }
      }

      parts.caret.classList.remove("is-visible");
      const fit = engine.fitRectangle(desired.x, desired.y, tile.w, tile.h, others, metrics.columns);
      if (fit.w >= minimum[0] && fit.h >= minimum[1]) {
        clearDestructivePreview();
        const fitted = Object.assign({}, desired, { w: fit.w, h: fit.h });
        state.finalLayout = replaceItem(snapshot, fitted);
        showPlaceholder(parts, fitted, metrics, false);
        showGuides(parts, fitted, snapshot, metrics);
      } else if (metrics.nudge) {
        const layout = attachElements(engine.verticalPush(replaceItem(snapshot, desired), tile.tile_id), snapshot);
        showPlaceholder(parts, desired, metrics, true);
        hideGuides(parts);
        queueDestructivePreview(`push:${desired.x}:${desired.y}`, layout);
      } else {
        clearDestructivePreview();
        const free = engine.nearestFree(desired, others, metrics.columns);
        state.finalLayout = replaceItem(snapshot, free);
        showPlaceholder(parts, free, metrics, false);
        showGuides(parts, free, snapshot, metrics);
      }
    }

    function resizeTile(event) {
      const state = interaction;
      const { metrics, tile, snapshot, parts } = state;
      const minimum = engine.minimumSize(tile.tile_type);
      const edge = state.resizeEdge || "bottom-right";
      const movesLeft = edge.includes("left");
      const movesRight = edge.includes("right");
      const movesTop = edge.includes("top");
      const movesBottom = edge.includes("bottom");
      const deltaX = (event.clientX - state.startX) / metrics.columnWidth;
      const deltaY = (event.clientY - state.startY) / metrics.rowHeight;
      const originalRight = tile.x + tile.w;
      const originalBottom = tile.y + tile.h;
      let continuousX = tile.x;
      let continuousY = tile.y;
      let continuousW = tile.w;
      let continuousH = tile.h;

      if (movesLeft) {
        continuousX = Math.max(
          0,
          Math.min(tile.x + deltaX, originalRight - minimum[0])
        );
        continuousW = originalRight - continuousX;
      } else if (movesRight) {
        continuousW = Math.max(
          minimum[0],
          Math.min(tile.w + deltaX, metrics.columns - tile.x)
        );
      }
      if (movesTop) {
        continuousY = Math.max(
          0,
          Math.min(tile.y + deltaY, originalBottom - minimum[1])
        );
        continuousH = originalBottom - continuousY;
      } else if (movesBottom) {
        continuousH = Math.max(minimum[1], tile.h + deltaY);
      }

      placeElement(
        state.tileElement,
        Object.assign({}, tile, {
          x: continuousX,
          y: continuousY,
          w: continuousW,
          h: continuousH,
        }),
        metrics
      );
      schedulePlotRender();
      let x = continuousX;
      let y = continuousY;
      let w = continuousW;
      let h = continuousH;
      if (metrics.snap) {
        if (movesLeft) {
          x = Math.max(
            0,
            Math.min(
              engine.stickySnap(continuousX, state.snappedX, metrics.deadZone),
              originalRight - minimum[0]
            )
          );
          w = originalRight - x;
          state.snappedX = x;
          state.snappedW = w;
        } else if (movesRight) {
          w = Math.max(
            minimum[0],
            Math.min(
              engine.stickySnap(continuousW, state.snappedW, metrics.deadZone),
              metrics.columns - tile.x
            )
          );
          state.snappedW = w;
        }
        if (movesTop) {
          y = Math.max(
            0,
            Math.min(
              engine.stickySnap(continuousY, state.snappedY, metrics.deadZone),
              originalBottom - minimum[1]
            )
          );
          h = originalBottom - y;
          state.snappedY = y;
          state.snappedH = h;
        } else if (movesBottom) {
          h = Math.max(
            minimum[1],
            engine.stickySnap(continuousH, state.snappedH, metrics.deadZone)
          );
          state.snappedH = h;
        }
      }
      let desired = engine.normalize(
        Object.assign({}, tile, { x, y, w, h }),
        metrics.snap,
        metrics.columns
      );
      const others = snapshot.filter((item) => item.tile_id !== tile.tile_id);
      const collides = others.some((item) => engine.overlaps(desired, item));
      if (collides && metrics.nudge) {
        let resolved = replaceItem(snapshot, desired);
        if (desired.w > tile.w) {
          resolved = engine.horizontalResizePush(
            resolved,
            tile.tile_id,
            tile.x + tile.w,
            metrics.columns
          );
          desired = layoutById(resolved).get(tile.tile_id);
        }
        const layout = attachElements(
          engine.verticalPush(resolved, tile.tile_id),
          snapshot
        );
        showPlaceholder(parts, desired, metrics, true);
        hideGuides(parts);
        queueDestructivePreview(
          `resize:${desired.x}:${desired.y}:${desired.w}:${desired.h}`,
          layout
        );
      } else {
        clearDestructivePreview();
        if (collides) {
          const fit = engine.fitRectangle(tile.x, tile.y, desired.w, desired.h, others, metrics.columns);
          if (fit.w >= minimum[0] && fit.h >= minimum[1]) desired = Object.assign({}, desired, { w: fit.w, h: fit.h });
          else desired = Object.assign({}, tile);
        }
        state.finalLayout = replaceItem(snapshot, desired);
        showPlaceholder(parts, desired, metrics, false);
        showGuides(parts, desired, snapshot, metrics);
      }
    }

    function movePointer(event) {
      if (!interaction || event.pointerId !== interaction.pointerId) return;
      if (interaction.mode === "resize") resizeTile(event);
      else if (!updateCrossTarget(event)) moveTile(event);
      event.preventDefault();
    }

    function finishPointer(event, cancelled) {
      if (!interaction || (event.pointerId !== undefined && event.pointerId !== interaction.pointerId)) return;
      const state = interaction;
      interaction = null;
      if (state.timer) window.clearTimeout(state.timer);
      try { state.handle.releasePointerCapture(state.pointerId); } catch (_) {}
      state.tileElement.classList.remove("is-canvas-dragging", "is-canvas-resizing");
      state.canvas.classList.remove("is-canvas-interacting");
      hideChrome(state.parts);
      const crossTarget = state.crossTarget;
      clearCrossTarget(state, true);
      if (crossTarget && !cancelled) {
        renderLayout(state.snapshot, state.metrics);
        trameTrigger("move_workspace_canvas_tile_trigger", [
          state.canvas.dataset.paneId || "",
          state.canvas.dataset.tabId || "",
          Number(state.tileElement.dataset.cellIndex || -1),
          crossTarget.canvas.dataset.paneId || "",
          crossTarget.canvas.dataset.tabId || "",
          JSON.stringify(geometryOnly(crossTarget.geometry)),
        ]);
        return;
      }
      const finalLayout = cancelled ? state.snapshot : state.finalLayout;
      renderLayout(finalLayout, state.metrics);
      schedulePlotRender();
      if (!cancelled) {
        trameTrigger("commit_canvas_layout_trigger", [
          JSON.stringify(finalLayout.map(geometryOnly)),
          state.tile.tile_id,
          state.canvas.dataset.paneId || "",
          state.canvas.dataset.tabId || "",
        ]);
      }
    }

    function variableFromTransfer(event) {
      if (!event.dataTransfer) return "";
      return event.dataTransfer.getData("application/x-pulsar-var") || event.dataTransfer.getData("text/plain") || "";
    }

    function externalInsertionIntent(snapshot, proposed, pointer, metrics) {
      if (!metrics.snap || !metrics.nudge) return null;
      const zone = engine.insertionZone(
        snapshot,
        proposed.tile_id,
        pointer.x,
        pointer.y,
        {
          xTolerance: 10 / metrics.columnWidth,
          yTolerance: 10 / metrics.rowHeight,
        }
      );
      if (!zone) return null;
      if (zone.orientation === "row") {
        const inserted = Object.assign({}, proposed, {
          x: Math.max(0, Math.min(zone.anchor_x, metrics.columns - proposed.w)),
          y: zone.seam,
        });
        const complete = engine.verticalPush(
          snapshot.map(geometryOnly).concat([inserted]),
          proposed.tile_id
        );
        return {
          geometry: complete.find((item) => item.tile_id === proposed.tile_id),
          layout: attachElements(
            complete.filter((item) => item.tile_id !== proposed.tile_id),
            snapshot
          ),
          zone,
          key: `row:${zone.seam}:${inserted.x}`,
        };
      }

      const moveIds = engine.connectedColumnMoveSet(
        snapshot,
        zone.seam,
        zone.anchor_y,
        proposed.h,
        proposed.tile_id
      );
      const moveItems = snapshot.filter((item) => moveIds.includes(item.tile_id));
      const size = engine.columnInsertionSize(
        proposed,
        moveItems,
        zone.seam,
        metrics.columns
      );
      if (!size || size.w < proposed.w) return null;
      const complete = engine.applyColumnInsertion(
        snapshot.map(geometryOnly).concat([proposed]),
        {
          draggedId: proposed.tile_id,
          seam: zone.seam,
          anchorY: zone.anchor_y,
          moveIds,
          width: size.w,
          height: size.h,
          mode: size.mode,
          columns: metrics.columns,
        }
      );
      return {
        geometry: complete.find((item) => item.tile_id === proposed.tile_id),
        layout: attachElements(
          complete.filter((item) => item.tile_id !== proposed.tile_id),
          snapshot
        ),
        zone,
        key: `column:${zone.seam}:${zone.anchor_y}:${size.mode}`,
      };
    }

    function variableDragOver(event) {
      if (!engine) return;
      const canvas = activeCanvas(event.target, root);
      if (!canvas || interaction) return;
      const types = event.dataTransfer ? Array.from(event.dataTransfer.types || []) : [];
      if (!types.includes("application/x-pulsar-var") && !types.includes("text/plain")) return;
      const metrics = canvasMetrics(canvas);
      const point = canvasPoint(event, canvas, metrics);
      const snapshot = readLayout(canvas);
      const initialWidth = Math.max(
        2,
        Math.min(
          12,
          Number(canvas.dataset.canvasDefaultTileWidth || 2)
        )
      );
      const initialHeight = initialWidth * metrics.columnWidth / metrics.rowHeight;
      const proposed = engine.normalize({
        tile_id: "__new__",
        tile_type: "plot",
        x: point.x - initialWidth / 2,
        y: point.y - initialHeight / 2,
        w: initialWidth,
        h: initialHeight,
      }, metrics.snap, metrics.columns);
      const insertion = externalInsertionIntent(snapshot, proposed, point, metrics);
      let geometry;
      let layout = null;
      let zone = null;
      let key;
      if (insertion) {
        ({ geometry, layout, zone, key } = insertion);
      } else {
        const fit = engine.fitRectangle(Math.round(proposed.x), Math.round(proposed.y), proposed.w, proposed.h, snapshot, metrics.columns);
        geometry = fit.w === proposed.w && fit.h === proposed.h
          ? proposed
          : engine.nearestFree(proposed, snapshot, metrics.columns);
        key = `place:${geometry.x}:${geometry.y}:${geometry.w}:${geometry.h}`;
      }

      if (
        externalDrop &&
        externalDrop.canvas === canvas &&
        externalDrop.key === key
      ) {
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
        return;
      }
      clearExternalDrop();
      const parts = chrome(canvas);
      if (zone) {
        parts.placeholder.classList.remove("is-visible");
        showCaret(parts, zone, geometry, metrics);
        hideGuides(parts);
      } else {
        showPlaceholder(parts, geometry, metrics, false);
        showGuides(parts, geometry, snapshot, metrics);
      }
      canvas.classList.add("is-canvas-dragover");
      externalDrop = {
        canvas,
        parts,
        geometry,
        layout,
        snapshot,
        metrics,
        key,
        timer: 0,
        previewed: false,
      };
      if (layout) {
        const target = externalDrop;
        target.timer = window.setTimeout(() => {
          if (externalDrop !== target) return;
          renderLayout(target.layout, target.metrics);
          showGuides(target.parts, target.geometry, target.snapshot, target.metrics);
          target.previewed = true;
        }, metrics.dwell);
      }
      event.preventDefault();
      event.stopPropagation();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    }

    function clearExternalDrop() {
      if (!externalDrop) return;
      if (externalDrop.timer) window.clearTimeout(externalDrop.timer);
      if (externalDrop.previewed) {
        renderLayout(externalDrop.snapshot, externalDrop.metrics);
      }
      hideChrome(externalDrop.parts);
      externalDrop.canvas.classList.remove("is-canvas-dragover");
      externalDrop = null;
    }

    function variableDrop(event) {
      const canvas = activeCanvas(event.target, root);
      if (!externalDrop || canvas !== externalDrop.canvas) return;
      event.preventDefault();
      event.stopPropagation();
      const item = variableFromTransfer(event);
      const target = externalDrop;
      const layoutPayload = target.layout
        ? JSON.stringify(target.layout.map(geometryOnly))
        : "";
      clearExternalDrop();
      if (!item) return;
      trameTrigger("add_var_to_canvas_trigger", [
        item,
        JSON.stringify(geometryOnly(target.geometry)),
        canvas.dataset.paneId || "",
        canvas.dataset.tabId || "",
        layoutPayload,
      ]);
    }

    function dragLeave(event) {
      if (!externalDrop || externalDrop.canvas.contains(event.relatedTarget)) return;
      clearExternalDrop();
    }

    return {
      handlers: {
        pointerdown: startPointer,
        pointermove: movePointer,
        pointerup: (event) => finishPointer(event, false),
        pointercancel: (event) => finishPointer(event, true),
        dragover: variableDragOver,
        drop: variableDrop,
        dragleave: dragLeave,
      },
      cleanup() {
        if (interaction) finishPointer({ pointerId: interaction.pointerId }, true);
        clearExternalDrop();
      },
    };
  }

  function mount(root) {
    if (!root || mountedRoots.has(root)) return;
    const runtimeState = createHandlers(root);
    runtimeState.viewCleanup = installCanvasViewRuntime(root);
    mountedRoots.set(root, runtimeState);
    for (const [eventName, handler] of Object.entries(runtimeState.handlers)) {
      root.addEventListener(eventName, handler, true);
    }
    root.setAttribute("data-pulsar-canvas-runtime-owner", "1");
  }

  function unmount(root) {
    const runtimeState = root && mountedRoots.get(root);
    if (!root || !runtimeState) return;
    runtimeState.cleanup();
    if (runtimeState.viewCleanup) runtimeState.viewCleanup();
    for (const [eventName, handler] of Object.entries(runtimeState.handlers)) {
      root.removeEventListener(eventName, handler, true);
    }
    mountedRoots.delete(root);
    root.removeAttribute("data-pulsar-canvas-runtime-owner");
  }

  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  const runtime = runtimes.canvas || window.pulsarCanvasRuntime || {};
  runtime.mount = mount;
  runtime.unmount = unmount;
  runtime.refresh = function refresh(root) {
    const target = root || document;
    for (const canvas of target.querySelectorAll(
      ".pulsar-freeform-canvas.pulsar-workspace-active-grid"
    )) {
      applyCanvasView(canvas, target);
    }
  };
  runtime.install = function install(app) {
    app.component("pulsar-canvas-runtime", {
      mounted() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.mount(root);
      },
      beforeUnmount() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.unmount(root);
      },
      template: '<span hidden data-pulsar-canvas-runtime="mounted"></span>',
    });
  };
  runtimes.canvas = runtime;
  window.pulsarCanvasRuntime = runtime;
})();
