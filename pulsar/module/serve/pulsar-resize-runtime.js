(function registerPulsarResizeRuntime() {
  const mountedRoots = new WeakMap();
  const MIN_VARIABLE_PANEL_WIDTH = 180;
  const MIN_CONTENT_PANEL_WIDTH = 360;

  function closestWithinRoot(target, selector, root) {
    if (!target || !target.closest) return null;
    const element = target.closest(selector);
    return element && root.contains(element) ? element : null;
  }

  function createRuntime(root) {
    let variablePanelResize = null;
    let trackResize = null;
    const pendingAnimationFrames = new Set();
    const pendingTimeouts = new Set();

    function body() {
      return root.ownerDocument ? root.ownerDocument.body : document.body;
    }

    function releasePointerCapture(resize) {
      if (!resize || !resize.handle || resize.pointerId === undefined) return;
      try {
        if (
          !resize.handle.hasPointerCapture ||
          resize.handle.hasPointerCapture(resize.pointerId)
        ) {
          resize.handle.releasePointerCapture(resize.pointerId);
        }
      } catch (_) {
        // The pointer may already have been released by the browser.
      }
    }

    function variablePanelBounds(panel) {
      const row = panel && panel.parentElement;
      const rowWidth = row ? row.getBoundingClientRect().width : window.innerWidth;
      return {
        min: MIN_VARIABLE_PANEL_WIDTH,
        max: Math.max(
          MIN_VARIABLE_PANEL_WIDTH,
          Math.min(rowWidth * 0.5, rowWidth - MIN_CONTENT_PANEL_WIDTH)
        ),
      };
    }

    function setVariablePanelWidth(panel, rawWidth) {
      if (!panel) return;
      const bounds = variablePanelBounds(panel);
      const width = Math.max(
        bounds.min,
        Math.min(Number(rawWidth) || bounds.min, bounds.max)
      );
      panel.style.flexBasis = width + "px";
      panel.style.width = width + "px";
      const handle = root.querySelector("[data-variable-panel-resizer]");
      if (handle) {
        handle.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
        handle.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
        handle.setAttribute("aria-valuenow", String(Math.round(width)));
      }
    }

    function finishVariablePanelResize() {
      if (!variablePanelResize) return;
      const current = variablePanelResize;
      variablePanelResize = null;
      current.handle.classList.remove("pulsar-variable-resizer-active");
      body().classList.remove("pulsar-variable-panel-resizing");
      releasePointerCapture(current);
    }

    function beginVariablePanelResize(event, handle) {
      const panel = root.querySelector("#pulsar-variable-column");
      if (!panel) return false;
      finishVariablePanelResize();
      variablePanelResize = {
        handle,
        panel,
        pointerId: event.pointerId,
        startX: Number(event.clientX) || 0,
        startWidth: panel.getBoundingClientRect().width,
      };
      handle.classList.add("pulsar-variable-resizer-active");
      body().classList.add("pulsar-variable-panel-resizing");
      try {
        handle.setPointerCapture(event.pointerId);
      } catch (_) {
        // Pointer capture is best-effort for older browser implementations.
      }
      event.preventDefault();
      return true;
    }

    function parseTrackSizes(raw, count, fallback) {
      const text = String(raw || "").trim();
      const pxParts = Array.from(text.matchAll(/(-?\d+(?:\.\d+)?)px\b/g)).map(
        function (match) {
          return Number.parseFloat(match[1]);
        }
      );
      const parts =
        pxParts.length >= count
          ? pxParts
          : text.split(/[,\s]+/).map(function (part) {
              return Number.parseFloat(part);
            });
      const sizes = [];
      for (let i = 0; i < count; i += 1) {
        const value = parts[i];
        sizes.push(Number.isFinite(value) && value > 0 ? value : fallback);
      }
      return sizes;
    }

    function clampTrackSize(value, minimum, maximum) {
      const safeMin = Number.isFinite(minimum) ? minimum : 40;
      const safeMax = Number.isFinite(maximum) ? maximum : 10000;
      return Math.max(safeMin, Math.min(safeMax, value));
    }

    function trackTemplate(sizes) {
      return sizes
        .map(function (size) {
          return String(Math.round(Number(size) || 0)) + "px";
        })
        .join(" ");
    }

    function fitTrackTemplate(weights, minimum) {
      const safeMin = Number.isFinite(minimum) && minimum > 0 ? minimum : 1;
      return weights
        .map(function (weight) {
          const safeWeight = Number.isFinite(weight) && weight > 0 ? weight : 1;
          return (
            "minmax(" +
            String(Math.round(safeMin)) +
            "px, " +
            String(Number(safeWeight.toFixed(6))) +
            "fr)"
          );
        })
        .join(" ");
    }

    function clearTrackResizeClasses() {
      const documentBody = body();
      documentBody.classList.remove("pulsar-grid-col-resizing");
      documentBody.classList.remove("pulsar-grid-row-resizing");
      documentBody.classList.remove("pulsar-grid-corner-resizing");
      documentBody.classList.remove("pulsar-grid-corner-nwse-resizing");
      documentBody.classList.remove("pulsar-grid-corner-nesw-resizing");
    }

    function schedulePlotRerenderForTrackResize(delayMs) {
      const run = function () {
        const runtimes = (window.pulsar && window.pulsar.runtimes) || {};
        const grid = runtimes.grid || window.pulsarGridRuntime;
        if (
          grid &&
          typeof grid.schedulePlotRender === "function"
        ) {
          grid.schedulePlotRender();
        }
      };
      const delay = Number(delayMs);
      if (Number.isFinite(delay) && delay > 0) {
        const timeoutId = window.setTimeout(function () {
          pendingTimeouts.delete(timeoutId);
          run();
        }, delay);
        pendingTimeouts.add(timeoutId);
      } else if (window.requestAnimationFrame) {
        const animationFrameId = window.requestAnimationFrame(function () {
          pendingAnimationFrames.delete(animationFrameId);
          run();
        });
        pendingAnimationFrames.add(animationFrameId);
      } else {
        run();
      }
    }

    function buildTrackResizeAction(grid, axis, edge, index, startX, startY, mode) {
      const isColumn = axis === "column";
      const count = Number(
        grid.getAttribute(isColumn ? "data-grid-cols" : "data-grid-rows")
      );
      if (
        !Number.isInteger(index) ||
        !Number.isInteger(count) ||
        index < 0 ||
        index >= count
      ) {
        return null;
      }

      if (mode === "fit") {
        const neighborIndex = edge === "left" || edge === "top" ? index - 1 : index + 1;
        if (neighborIndex < 0 || neighborIndex >= count) return null;
        const weights = parseTrackSizes(
          grid.getAttribute(
            isColumn ? "data-grid-column-weights" : "data-grid-row-weights"
          ),
          count,
          1
        );
        const computed = window.getComputedStyle(grid);
        const renderedSizes = parseTrackSizes(
          isColumn ? computed.gridTemplateColumns : computed.gridTemplateRows,
          count,
          Number(
            grid.getAttribute(
              isColumn ? "data-grid-column-fallback" : "data-grid-row-fallback"
            )
          ) || 300
        );
        const rawMinSize = Number(
          grid.getAttribute(
            isColumn
              ? "data-grid-fit-min-column-size"
              : "data-grid-fit-min-row-size"
          )
        );
        const minSize = Number.isFinite(rawMinSize) && rawMinSize > 0 ? rawMinSize : 1;
        const currentSize = renderedSizes[index];
        const neighborSize = renderedSizes[neighborIndex];
        const pairSize = currentSize + neighborSize;
        if (!Number.isFinite(pairSize) || pairSize <= 2 * minSize) return null;
        const pairWeight = weights[index] + weights[neighborIndex];
        return {
          axis,
          mode,
          grid,
          index,
          neighborIndex,
          weights,
          startSize: currentSize,
          pairSize,
          pairWeight: Number.isFinite(pairWeight) && pairWeight > 0 ? pairWeight : 2,
          startX,
          startY,
          direction: edge === "left" || edge === "top" ? -1 : 1,
          minSize,
        };
      }

      const fallback = Number(
        grid.getAttribute(
          isColumn ? "data-grid-column-fallback" : "data-grid-row-fallback"
        )
      );
      const sizes = parseTrackSizes(
        grid.getAttribute(isColumn ? "data-grid-column-sizes" : "data-grid-row-sizes"),
        count,
        Number.isFinite(fallback) ? fallback : 300
      );
      return {
        axis,
        mode,
        grid,
        index,
        sizes,
        startSize: sizes[index],
        startX,
        startY,
        direction: edge === "left" || edge === "top" ? -1 : 1,
        minSize: Number(
          grid.getAttribute(
            isColumn ? "data-grid-min-column-size" : "data-grid-min-row-size"
          )
        ),
        maxSize: Number(
          grid.getAttribute(
            isColumn ? "data-grid-max-column-size" : "data-grid-max-row-size"
          )
        ),
      };
    }

    function beginTrackResize(event, grid, handle, actions) {
      if (!actions || !actions.length) return false;
      trackResize = {
        grid,
        handle,
        actions,
        pointerId: event.pointerId,
      };
      handle.classList.add("active");
      grid.classList.add("is-resizing");
      clearTrackResizeClasses();
      const hasColumn = actions.some(function (action) {
        return action.axis === "column";
      });
      const hasRow = actions.some(function (action) {
        return action.axis === "row";
      });
      if (hasColumn && hasRow) {
        body().classList.add("pulsar-grid-corner-resizing");
        body().classList.add(
          handle.classList.contains("pulsar-grid-corner-bottom-left")
            ? "pulsar-grid-corner-nesw-resizing"
            : "pulsar-grid-corner-nwse-resizing"
        );
      } else {
        body().classList.add(
          hasColumn ? "pulsar-grid-col-resizing" : "pulsar-grid-row-resizing"
        );
      }
      try {
        handle.setPointerCapture(event.pointerId);
      } catch (_) {
        // Pointer capture is best-effort for older browser implementations.
      }
      event.preventDefault();
      event.stopPropagation();
      return true;
    }

    function applyTrackResizeAction(action, event) {
      const delta =
        action.axis === "column"
          ? (Number(event.clientX) || 0) - action.startX
          : (Number(event.clientY) || 0) - action.startY;
      if (action.mode === "fit") {
        const minSize = Number.isFinite(action.minSize) ? action.minSize : 1;
        const nextSize = clampTrackSize(
          action.startSize + delta * action.direction,
          minSize,
          action.pairSize - minSize
        );
        const currentWeight = action.pairWeight * (nextSize / action.pairSize);
        action.weights[action.index] = currentWeight;
        action.weights[action.neighborIndex] = action.pairWeight - currentWeight;
        const template = fitTrackTemplate(action.weights, minSize);
        if (action.axis === "column") {
          action.grid.style.gridTemplateColumns = template;
          action.grid.setAttribute("data-grid-column-weights", action.weights.join(","));
        } else {
          action.grid.style.gridTemplateRows = template;
          action.grid.setAttribute("data-grid-row-weights", action.weights.join(","));
        }
        return;
      }

      const nextSize = clampTrackSize(
        action.startSize + delta * action.direction,
        action.minSize,
        action.maxSize
      );
      action.sizes[action.index] = nextSize;
      const template = trackTemplate(action.sizes);
      if (action.axis === "column") {
        action.grid.style.gridTemplateColumns = template;
        action.grid.setAttribute("data-grid-column-sizes", action.sizes.join(","));
      } else {
        action.grid.style.gridTemplateRows = template;
        action.grid.setAttribute("data-grid-row-sizes", action.sizes.join(","));
      }
    }

    function commitTrackResizeActions(actions) {
      if (!window.trame || !window.trame.trigger || !actions.length) return;
      const changes = actions.map(function (action) {
        const fit = action.mode === "fit";
        return {
          axis: action.axis,
          kind: fit ? "weights" : "sizes",
          values: fit ? action.weights : action.sizes,
        };
      });
      window.trame.trigger("commit_grid_track_resize_trigger", [
        JSON.stringify({ changes }),
      ]);
    }

    function finishTrackResize(event, commit) {
      if (!trackResize) return;
      const current = trackResize;
      trackResize = null;
      if (current.handle) current.handle.classList.remove("active");
      if (current.grid) current.grid.classList.remove("is-resizing");
      clearTrackResizeClasses();
      releasePointerCapture(current);
      if (commit !== false) {
        commitTrackResizeActions(current.actions || []);
        schedulePlotRerenderForTrackResize();
        schedulePlotRerenderForTrackResize(80);
        schedulePlotRerenderForTrackResize(180);
      }
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
    }

    function onPointerDown(event) {
      if (event.button !== undefined && event.button !== 0) return;
      const target = event && event.target;
      const variableHandle = closestWithinRoot(
        target,
        "[data-variable-panel-resizer]",
        root
      );
      if (variableHandle) {
        beginVariablePanelResize(event, variableHandle);
        return;
      }

      const handle = closestWithinRoot(
        target,
        ".pulsar-grid-track-resize-handle",
        root
      );
      if (!handle) return;
      const grid = closestWithinRoot(handle, ".pulsar-main-grid", root);
      if (!grid) return;

      const mode = String(grid.getAttribute("data-grid-sizing-mode") || "static");
      const startX = Number(event.clientX) || 0;
      const startY = Number(event.clientY) || 0;

      if (handle.classList.contains("pulsar-grid-corner-resize-handle")) {
        const colEdge = String(handle.getAttribute("data-col-edge") || "right");
        const rowEdge = String(handle.getAttribute("data-row-edge") || "bottom");
        const colIndex = Number(handle.getAttribute("data-col-index"));
        const rowIndex = Number(handle.getAttribute("data-row-index"));
        const actions = [
          buildTrackResizeAction(
            grid,
            "column",
            colEdge,
            colIndex,
            startX,
            startY,
            mode
          ),
          buildTrackResizeAction(
            grid,
            "row",
            rowEdge,
            rowIndex,
            startX,
            startY,
            mode
          ),
        ].filter(Boolean);
        if (actions.length === 2) {
          beginTrackResize(event, grid, handle, actions);
        }
        return;
      }

      const isColumn = handle.classList.contains("pulsar-grid-col-resize-handle");
      const axis = isColumn ? "column" : "row";
      const edge = String(
        handle.getAttribute("data-resize-edge") || (isColumn ? "right" : "bottom")
      );
      const index = Number(
        handle.getAttribute(isColumn ? "data-col-index" : "data-row-index")
      );
      const action = buildTrackResizeAction(
        grid,
        axis,
        edge,
        index,
        startX,
        startY,
        mode
      );
      if (action) beginTrackResize(event, grid, handle, [action]);
    }

    function onPointerMove(event) {
      if (variablePanelResize) {
        if (
          variablePanelResize.pointerId !== undefined &&
          event.pointerId !== variablePanelResize.pointerId
        ) {
          return;
        }
        event.preventDefault();
        setVariablePanelWidth(
          variablePanelResize.panel,
          variablePanelResize.startWidth +
            (Number(event.clientX) || 0) -
            variablePanelResize.startX
        );
        return;
      }
      if (!trackResize) return;
      if (
        trackResize.pointerId !== undefined &&
        event.pointerId !== trackResize.pointerId
      ) {
        return;
      }
      for (const action of trackResize.actions || []) {
        applyTrackResizeAction(action, event);
      }
      schedulePlotRerenderForTrackResize();
      event.preventDefault();
      event.stopPropagation();
    }

    function onPointerUp(event) {
      if (
        variablePanelResize &&
        (variablePanelResize.pointerId === undefined ||
          event.pointerId === variablePanelResize.pointerId)
      ) {
        finishVariablePanelResize();
      }
      if (
        trackResize &&
        (trackResize.pointerId === undefined || event.pointerId === trackResize.pointerId)
      ) {
        finishTrackResize(event, true);
      }
    }

    function onLostPointerCapture(event) {
      if (variablePanelResize && event.target === variablePanelResize.handle) {
        finishVariablePanelResize();
      }
      if (trackResize && event.target === trackResize.handle) {
        finishTrackResize(null, true);
      }
    }

    function onKeyDown(event) {
      const handle = closestWithinRoot(
        event && event.target,
        "[data-variable-panel-resizer]",
        root
      );
      if (!handle) return;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const panel = root.querySelector("#pulsar-variable-column");
      if (!panel) return;
      event.preventDefault();
      const step = event.shiftKey ? 40 : 10;
      const direction = event.key === "ArrowLeft" ? -1 : 1;
      setVariablePanelWidth(
        panel,
        panel.getBoundingClientRect().width + direction * step
      );
    }

    function onPreventGridHandleDefault(event) {
      if (
        closestWithinRoot(
          event && event.target,
          ".pulsar-grid-track-resize-handle",
          root
        )
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    }

    function onBlur() {
      finishVariablePanelResize();
      finishTrackResize(null, true);
    }

    function cleanup() {
      finishVariablePanelResize();
      finishTrackResize(null, false);
      for (const animationFrameId of pendingAnimationFrames) {
        window.cancelAnimationFrame(animationFrameId);
      }
      pendingAnimationFrames.clear();
      for (const timeoutId of pendingTimeouts) {
        window.clearTimeout(timeoutId);
      }
      pendingTimeouts.clear();
      body().classList.remove("pulsar-variable-panel-resizing");
      clearTrackResizeClasses();
      for (const handle of root.querySelectorAll(
        ".pulsar-variable-resizer-active, .pulsar-grid-track-resize-handle.active"
      )) {
        handle.classList.remove("pulsar-variable-resizer-active", "active");
      }
      for (const grid of root.querySelectorAll(".pulsar-main-grid.is-resizing")) {
        grid.classList.remove("is-resizing");
      }
    }

    return {
      handlers: {
        pointerdown: onPointerDown,
        pointermove: onPointerMove,
        pointerup: onPointerUp,
        pointercancel: onPointerUp,
        lostpointercapture: onLostPointerCapture,
        keydown: onKeyDown,
        dragstart: onPreventGridHandleDefault,
        click: onPreventGridHandleDefault,
      },
      onBlur,
      cleanup,
    };
  }

  function mount(root) {
    if (!root || mountedRoots.has(root)) return;
    const runtimeState = createRuntime(root);
    for (const [eventName, handler] of Object.entries(runtimeState.handlers)) {
      root.addEventListener(eventName, handler, true);
    }
    window.addEventListener("blur", runtimeState.onBlur);
    mountedRoots.set(root, runtimeState);
    root.setAttribute("data-pulsar-resize-runtime-owner", "mounted");
  }

  function unmount(root) {
    const runtimeState = root && mountedRoots.get(root);
    if (!root || !runtimeState) return;
    runtimeState.cleanup();
    for (const [eventName, handler] of Object.entries(runtimeState.handlers)) {
      root.removeEventListener(eventName, handler, true);
    }
    window.removeEventListener("blur", runtimeState.onBlur);
    mountedRoots.delete(root);
    root.removeAttribute("data-pulsar-resize-runtime-owner");
  }

  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  const runtime = runtimes.resize || window.pulsarResizeRuntime || {};
  runtime.mount = mount;
  runtime.unmount = unmount;
  runtime.install = function install(app) {
    app.component("pulsar-resize-runtime", {
      mounted() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.mount(root);
      },
      beforeUnmount() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.unmount(root);
      },
      template: '<span hidden data-pulsar-resize-runtime="mounted"></span>',
    });
  };

  runtimes.resize = runtime;
  window.pulsarResizeRuntime = runtime;
})();
