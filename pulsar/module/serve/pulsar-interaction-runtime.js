(function registerPulsarInteractionRuntime() {
  const mountedRoots = new WeakMap();
  const workspaceGridCellMime =
    "application/x-pulsar-workspace-grid-cell";

  function trameTrigger(name, args) {
    if (window.trame && window.trame.trigger) {
      window.trame.trigger(name, args || []);
    }
  }

  function closestWithinRoot(target, selector, root) {
    if (!target || !target.closest) return null;
    const element = target.closest(selector);
    return element && root.contains(element) ? element : null;
  }

  function createHandlers(root) {
    let floatingDrag = null;
    let floatingResize = null;
    let workspaceSplitDrag = null;
    let workspaceTabDrag = null;
    let tabOverflowFrame = 0;
    let tabOverflowMutationObserver = null;
    const floatingPanelResizeObserver =
      typeof ResizeObserver === "function"
        ? new ResizeObserver((entries) => {
            for (const entry of entries) {
              const panel = entry.target;
              if (!panel.offsetWidth || !panel.offsetHeight) continue;
              if (
                panel.classList.contains("pulsar-provenance-panel") &&
                (panel.style.width || panel.style.height)
              ) {
                panel.classList.add("is-user-resized");
              }
              const rect = panel.getBoundingClientRect();
              const position = clampFloatingPanel(panel, rect.left, rect.top);
              panel.style.left = position.left + "px";
              panel.style.top = position.top + "px";
            }
          })
        : null;
    const visibleWorkspaceTabs = new WeakMap();
    const tabOverflowResizeObserver =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(scheduleWorkspaceTabOverflowUpdate)
        : null;

    function updateWorkspaceTabOverflow() {
      tabOverflowFrame = 0;
      syncWorkspaceLayoutGeometry();
      for (const viewport of root.querySelectorAll(
        ".pulsar-workspace-tabs-viewport"
      )) {
        const tabs = viewport.querySelector(".pulsar-workspace-tabs");
        if (!tabs) continue;
        if (tabOverflowResizeObserver) tabOverflowResizeObserver.observe(tabs);
        const activeTab = tabs.querySelector(
          ".pulsar-workspace-tab.is-pane-tab-active"
        );
        const activeTabId = activeTab
          ? activeTab.getAttribute("data-tab-id") || ""
          : "";
        if (activeTabId && visibleWorkspaceTabs.get(viewport) !== activeTabId) {
          const shell = activeTab.closest(".pulsar-workspace-tab-shell");
          if (shell) {
            const tabsRect = tabs.getBoundingClientRect();
            const shellRect = shell.getBoundingClientRect();
            const shellLeft = tabs.scrollLeft + shellRect.left - tabsRect.left;
            const addButton = tabs.querySelector(".pulsar-workspace-tab-add");
            const isLastTab =
              !shell.nextElementSibling || shell.nextElementSibling === addButton;
            const targetRect =
              isLastTab && addButton
                ? addButton.getBoundingClientRect()
                : shellRect;
            const shellRight =
              tabs.scrollLeft + targetRect.right - tabsRect.left;
            if (shellLeft < tabs.scrollLeft) tabs.scrollLeft = shellLeft;
            else if (shellRight > tabs.scrollLeft + tabs.clientWidth) {
              tabs.scrollLeft = shellRight - tabs.clientWidth;
            }
          }
          visibleWorkspaceTabs.set(viewport, activeTabId);
        }
        const maximum = Math.max(0, tabs.scrollWidth - tabs.clientWidth);
        viewport.classList.toggle("has-overflow-left", tabs.scrollLeft > 1);
        viewport.classList.toggle(
          "has-overflow-right",
          maximum > 1 && tabs.scrollLeft < maximum - 1
        );
      }
    }

    function scheduleWorkspaceTabOverflowUpdate() {
      if (tabOverflowFrame) return;
      tabOverflowFrame = window.requestAnimationFrame(
        updateWorkspaceTabOverflow
      );
    }

    function onWorkspaceTabsScroll(event) {
      const target = event && event.target;
      if (target && target.classList.contains("pulsar-workspace-tabs")) {
        scheduleWorkspaceTabOverflowUpdate();
      }
    }

    function clampFloatingPanel(panel, left, top) {
      const margin = 8;
      const width = panel.offsetWidth || 560;
      const height = panel.offsetHeight || 360;
      const maxLeft = Math.max(margin, window.innerWidth - width - margin);
      const maxTop = Math.max(margin, window.innerHeight - height - margin);
      return {
        left: Math.max(margin, Math.min(left, maxLeft)),
        top: Math.max(margin, Math.min(top, maxTop)),
      };
    }

    function releasePointerCapture(drag) {
      if (!drag || !drag.handle || drag.pointerId === undefined) return;
      try {
        if (
          !drag.handle.hasPointerCapture ||
          drag.handle.hasPointerCapture(drag.pointerId)
        ) {
          drag.handle.releasePointerCapture(drag.pointerId);
        }
      } catch (_) {
        // The pointer may already have been released by the browser.
      }
    }

    function finishFloatingDrag() {
      if (!floatingDrag) return;
      const current = floatingDrag;
      floatingDrag = null;
      current.panel.classList.remove("is-dragging");
      releasePointerCapture(current);
    }

    function finishFloatingResize() {
      if (!floatingResize) return;
      const current = floatingResize;
      floatingResize = null;
      current.panel.classList.remove("is-resizing");
      releasePointerCapture(current);
    }

    function workspaceLayoutTree() {
      const surface = root.querySelector(".pulsar-workspace-layout-surface");
      if (!surface) return null;
      try {
        return {
          surface,
          tree: JSON.parse(surface.getAttribute("data-layout-tree") || "{}"),
        };
      } catch (_) {
        return null;
      }
    }

    function workspaceFrameElements(attribute, value) {
      return Array.from(root.querySelectorAll("[" + attribute + "]")).filter(
        (element) => element.getAttribute(attribute) === value
      );
    }

    function applyWorkspaceLayoutGeometry(tree) {
      const surface = root.querySelector(".pulsar-workspace-layout-surface");
      if (!surface) return;
      const surfaceBounds = surface.getBoundingClientRect();

      function visit(node, left, top, width, height) {
        if (!node || node.kind !== "split") {
          const paneId = String((node && node.pane_id) || "");
          for (const element of workspaceFrameElements(
            "data-pane-frame-id",
            paneId
          )) {
            element.style.setProperty(
              "--pane-left",
              (surfaceBounds.width * left) / 100 + "px"
            );
            element.style.setProperty(
              "--pane-top",
              (surfaceBounds.height * top) / 100 + "px"
            );
            element.style.setProperty(
              "--pane-width",
              (surfaceBounds.width * width) / 100 + "px"
            );
            element.style.setProperty(
              "--pane-height",
              (surfaceBounds.height * height) / 100 + "px"
            );
          }
          return;
        }
        const ratio = Math.max(0.15, Math.min(0.85, Number(node.ratio) || 0.5));
        const splitId = String(node.id || "");
        const horizontal = node.direction !== "vertical";
        const boundary = horizontal
          ? left + width * ratio
          : top + height * ratio;
        for (const handle of workspaceFrameElements(
          "data-split-frame-id",
          splitId
        )) {
          handle.style.setProperty(
            "--split-left",
            (surfaceBounds.width * (horizontal ? boundary : left)) / 100 +
              "px"
          );
          handle.style.setProperty(
            "--split-top",
            (surfaceBounds.height * (horizontal ? top : boundary)) / 100 +
              "px"
          );
          handle.style.setProperty(
            "--split-span",
            ((horizontal ? surfaceBounds.height : surfaceBounds.width) *
              (horizontal ? height : width)) /
              100 +
              "px"
          );
          handle.setAttribute("data-split-ratio", String(ratio));
          handle.setAttribute("data-container-left", String(left));
          handle.setAttribute("data-container-top", String(top));
          handle.setAttribute("data-container-width", String(width));
          handle.setAttribute("data-container-height", String(height));
          handle.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
        }
        if (horizontal) {
          visit(node.first, left, top, width * ratio, height);
          visit(node.second, boundary, top, width * (1 - ratio), height);
        } else {
          visit(node.first, left, top, width, height * ratio);
          visit(node.second, left, boundary, width, height * (1 - ratio));
        }
      }

      visit(tree, 0, 0, 100, 100);
    }

    function syncWorkspaceLayoutGeometry() {
      if (workspaceSplitDrag) {
        applyWorkspaceLayoutGeometry(workspaceSplitDrag.tree);
        return;
      }
      const layout = workspaceLayoutTree();
      if (layout) applyWorkspaceLayoutGeometry(layout.tree);
    }

    function findWorkspaceSplit(node, splitId) {
      if (!node || node.kind !== "split") return null;
      if (String(node.id || "") === splitId) return node;
      return (
        findWorkspaceSplit(node.first, splitId) ||
        findWorkspaceSplit(node.second, splitId)
      );
    }

    function workspacePaneIds(node, result) {
      const paneIds = result || [];
      if (!node || node.kind !== "split") {
        const paneId = String((node && node.pane_id) || "");
        if (paneId) paneIds.push(paneId);
        return paneIds;
      }
      workspacePaneIds(node.first, paneIds);
      workspacePaneIds(node.second, paneIds);
      return paneIds;
    }

    function clearWorkspaceSplitFeedback(drag) {
      for (const preview of root.querySelectorAll(
        ".pulsar-workspace-tab-dock-preview.is-split-resize-first, " +
          ".pulsar-workspace-tab-dock-preview.is-split-resize-second"
      )) {
        preview.classList.remove(
          "is-split-resize-first",
          "is-split-resize-second"
        );
      }
      const handle = drag && drag.handle;
      if (!handle) return;
      handle.removeAttribute("aria-valuetext");
      const readout = handle.querySelector(".pulsar-workspace-split-readout");
      if (readout) readout.textContent = "";
    }

    function updateWorkspaceSplitFeedback(drag) {
      if (!drag) return;
      const firstPercent = Math.round(drag.ratio * 100);
      const secondPercent = 100 - firstPercent;
      const label = firstPercent + "% / " + secondPercent + "%";
      drag.handle.setAttribute("aria-valuetext", label);
      const readout = drag.handle.querySelector(
        ".pulsar-workspace-split-readout"
      );
      if (readout) readout.textContent = label;
    }

    function showWorkspaceSplitFeedback(drag) {
      if (!drag) return;
      const firstPaneIds = new Set(workspacePaneIds(drag.split.first));
      const secondPaneIds = new Set(workspacePaneIds(drag.split.second));
      for (const preview of root.querySelectorAll(
        ".pulsar-workspace-tab-dock-preview"
      )) {
        const paneId = preview.getAttribute("data-tab-dock-pane-id") || "";
        if (firstPaneIds.has(paneId))
          preview.classList.add("is-split-resize-first");
        else if (secondPaneIds.has(paneId))
          preview.classList.add("is-split-resize-second");
      }
      updateWorkspaceSplitFeedback(drag);
    }

    function finishWorkspaceSplitDrag(commit) {
      if (!workspaceSplitDrag) return;
      const current = workspaceSplitDrag;
      workspaceSplitDrag = null;
      current.handle.classList.remove("is-resizing");
      document.body.classList.remove(
        "pulsar-pane-resizing-horizontal",
        "pulsar-pane-resizing-vertical"
      );
      clearWorkspaceSplitFeedback(current);
      releasePointerCapture(current);
      if (commit) {
        trameTrigger("resize_workspace_split_trigger", [
          current.splitId,
          current.ratio,
        ]);
      } else {
        applyWorkspaceLayoutGeometry(current.originalTree);
      }
    }

    function onPointerDown(event) {
      if (event.button !== undefined && event.button !== 0) return;
      const resizeHandle = closestWithinRoot(
        event && event.target,
        ".pulsar-provenance-resize-handle",
        root
      );
      if (resizeHandle) {
        const panel = closestWithinRoot(
          resizeHandle,
          ".pulsar-provenance-panel",
          root
        );
        if (!panel) return;
        finishFloatingDrag();
        finishFloatingResize();
        const rect = panel.getBoundingClientRect();
        const style = window.getComputedStyle(panel);
        floatingResize = {
          panel,
          handle: resizeHandle,
          pointerId: event.pointerId,
          startX: Number(event.clientX) || 0,
          startY: Number(event.clientY) || 0,
          width: rect.width,
          height: rect.height,
          minWidth: parseFloat(style.minWidth) || 0,
          minHeight: parseFloat(style.minHeight) || 0,
          maxWidth: parseFloat(style.maxWidth) || window.innerWidth,
          maxHeight: parseFloat(style.maxHeight) || window.innerHeight,
        };
        panel.classList.add("is-resizing", "is-user-resized");
        try {
          resizeHandle.setPointerCapture(event.pointerId);
        } catch (_) {
          // Pointer capture is best-effort for older browser implementations.
        }
        event.preventDefault();
        return;
      }
      const splitHandle = closestWithinRoot(
        event && event.target,
        ".pulsar-workspace-splitter",
        root
      );
      if (splitHandle) {
        const layout = workspaceLayoutTree();
        const splitId = splitHandle.getAttribute("data-split-id") || "";
        const split = layout && findWorkspaceSplit(layout.tree, splitId);
        if (!layout || !split) return;
        finishFloatingDrag();
        finishWorkspaceSplitDrag(false);
        workspaceSplitDrag = {
          handle: splitHandle,
          pointerId: event.pointerId,
          surface: layout.surface,
          tree: layout.tree,
          originalTree: JSON.parse(JSON.stringify(layout.tree)),
          split,
          splitId,
          direction: split.direction === "vertical" ? "vertical" : "horizontal",
          ratio: Math.max(0.15, Math.min(0.85, Number(split.ratio) || 0.5)),
          containerLeft: Number(splitHandle.getAttribute("data-container-left")) || 0,
          containerTop: Number(splitHandle.getAttribute("data-container-top")) || 0,
          containerWidth: Number(splitHandle.getAttribute("data-container-width")) || 100,
          containerHeight: Number(splitHandle.getAttribute("data-container-height")) || 100,
        };
        splitHandle.classList.add("is-resizing");
        showWorkspaceSplitFeedback(workspaceSplitDrag);
        document.body.classList.add(
          workspaceSplitDrag.direction === "vertical"
            ? "pulsar-pane-resizing-horizontal"
            : "pulsar-pane-resizing-vertical"
        );
        try {
          splitHandle.setPointerCapture(event.pointerId);
        } catch (_) {
          // Pointer capture is best-effort for older browser implementations.
        }
        event.preventDefault();
        return;
      }
      const handle = closestWithinRoot(
        event && event.target,
        ".pulsar-floating-panel-drag-handle",
        root
      );
      if (!handle) return;
      const panel = closestWithinRoot(handle, ".pulsar-floating-options-panel", root);
      if (!panel) return;
      finishFloatingDrag();
      const rect = panel.getBoundingClientRect();
      floatingDrag = {
        panel,
        handle,
        pointerId: event.pointerId,
        startX: Number(event.clientX) || 0,
        startY: Number(event.clientY) || 0,
        left: rect.left,
        top: rect.top,
      };
      panel.classList.add("is-dragging");
      try {
        handle.setPointerCapture(event.pointerId);
      } catch (_) {
        // Pointer capture is best-effort for older browser implementations.
      }
      event.preventDefault();
    }

    function onPointerMove(event) {
      if (floatingResize) {
        if (
          floatingResize.pointerId !== undefined &&
          event.pointerId !== floatingResize.pointerId
        ) {
          return;
        }
        const dx = (Number(event.clientX) || 0) - floatingResize.startX;
        const dy = (Number(event.clientY) || 0) - floatingResize.startY;
        const rect = floatingResize.panel.getBoundingClientRect();
        const availableWidth = window.innerWidth - rect.left - 8;
        const availableHeight = window.innerHeight - rect.top - 8;
        const maximumWidth = Math.min(
          floatingResize.maxWidth,
          availableWidth
        );
        const maximumHeight = Math.min(
          floatingResize.maxHeight,
          availableHeight
        );
        floatingResize.panel.style.width =
          Math.max(
            floatingResize.minWidth,
            Math.min(maximumWidth, floatingResize.width + dx)
          ) + "px";
        floatingResize.panel.style.height =
          Math.max(
            floatingResize.minHeight,
            Math.min(maximumHeight, floatingResize.height + dy)
          ) + "px";
        event.preventDefault();
        return;
      }
      if (workspaceSplitDrag) {
        if (
          workspaceSplitDrag.pointerId !== undefined &&
          event.pointerId !== workspaceSplitDrag.pointerId
        ) {
          return;
        }
        const bounds = workspaceSplitDrag.surface.getBoundingClientRect();
        const horizontal = workspaceSplitDrag.direction === "horizontal";
        const fullSize = horizontal ? bounds.width : bounds.height;
        const containerStartPercent = horizontal
          ? workspaceSplitDrag.containerLeft
          : workspaceSplitDrag.containerTop;
        const containerPercent = horizontal
          ? workspaceSplitDrag.containerWidth
          : workspaceSplitDrag.containerHeight;
        const containerSize = Math.max(1, (fullSize * containerPercent) / 100);
        const coordinate = horizontal
          ? (Number(event.clientX) || 0) - bounds.left
          : (Number(event.clientY) || 0) - bounds.top;
        const containerStart = (fullSize * containerStartPercent) / 100;
        const minimumPixels = horizontal ? 240 : 180;
        const minimumRatio = Math.min(
          0.45,
          Math.max(0.15, minimumPixels / containerSize)
        );
        const ratio = Math.max(
          minimumRatio,
          Math.min(1 - minimumRatio, (coordinate - containerStart) / containerSize)
        );
        workspaceSplitDrag.ratio = ratio;
        workspaceSplitDrag.split.ratio = ratio;
        applyWorkspaceLayoutGeometry(workspaceSplitDrag.tree);
        updateWorkspaceSplitFeedback(workspaceSplitDrag);
        event.preventDefault();
        return;
      }
      if (!floatingDrag) return;
      if (
        floatingDrag.pointerId !== undefined &&
        event.pointerId !== floatingDrag.pointerId
      ) {
        return;
      }
      const dx = (Number(event.clientX) || 0) - floatingDrag.startX;
      const dy = (Number(event.clientY) || 0) - floatingDrag.startY;
      const position = clampFloatingPanel(
        floatingDrag.panel,
        floatingDrag.left + dx,
        floatingDrag.top + dy
      );
      floatingDrag.panel.style.left = position.left + "px";
      floatingDrag.panel.style.top = position.top + "px";
      event.preventDefault();
    }

    function onPointerEnd(event) {
      if (
        floatingResize &&
        (floatingResize.pointerId === undefined ||
          event.pointerId === floatingResize.pointerId)
      ) {
        finishFloatingResize();
        return;
      }
      if (
        workspaceSplitDrag &&
        (workspaceSplitDrag.pointerId === undefined ||
          event.pointerId === workspaceSplitDrag.pointerId)
      ) {
        finishWorkspaceSplitDrag(event.type !== "pointercancel");
        return;
      }
      if (
        floatingDrag &&
        (floatingDrag.pointerId === undefined ||
          event.pointerId === floatingDrag.pointerId)
      ) {
        finishFloatingDrag();
      }
    }

    function onLostPointerCapture(event) {
      if (floatingResize && event.target === floatingResize.handle) {
        finishFloatingResize();
        return;
      }
      if (workspaceSplitDrag && event.target === workspaceSplitDrag.handle) {
        finishWorkspaceSplitDrag(true);
        return;
      }
      if (floatingDrag && event.target === floatingDrag.handle) {
        finishFloatingDrag();
      }
    }

    function onWindowResize() {
      for (const panel of root.querySelectorAll(".pulsar-floating-options-panel")) {
        const rect = panel.getBoundingClientRect();
        const position = clampFloatingPanel(panel, rect.left, rect.top);
        panel.style.left = position.left + "px";
        panel.style.top = position.top + "px";
      }
      syncWorkspaceLayoutGeometry();
      scheduleWorkspaceTabOverflowUpdate();
    }

    function clearWorkspaceTabDropMarkers() {
      for (const shell of root.querySelectorAll(
        ".pulsar-workspace-tab-shell.is-tab-drop-before, " +
          ".pulsar-workspace-tab-shell.is-tab-drop-after"
      )) {
        shell.classList.remove("is-tab-drop-before", "is-tab-drop-after");
      }
      for (const tabs of root.querySelectorAll(
        ".pulsar-workspace-tabs.is-tab-drop-target"
      )) {
        tabs.classList.remove("is-tab-drop-target");
      }
      for (const target of root.querySelectorAll(
        ".pulsar-workspace-tab-dock-target.is-tab-dock-active"
      )) {
        target.classList.remove("is-tab-dock-active");
      }
      for (const preview of root.querySelectorAll(
        ".pulsar-workspace-tab-dock-preview.is-tab-dock-preview-active"
      )) {
        preview.classList.remove("is-tab-dock-preview-active");
      }
    }

    function finishWorkspaceTabDrag() {
      clearWorkspaceTabDropMarkers();
      for (const tab of root.querySelectorAll(
        ".pulsar-workspace-tab[aria-grabbed='true']"
      )) {
        tab.removeAttribute("aria-grabbed");
      }
      for (const shell of root.querySelectorAll(
        ".pulsar-workspace-tab-shell.is-tab-dragging"
      )) {
        shell.classList.remove("is-tab-dragging");
      }
      root.classList.remove("is-workspace-tab-dragging");
      workspaceTabDrag = null;
    }

    function clearWorkspaceGridDropTargets() {
      for (const cell of root.querySelectorAll(
        ".pulsar-dropcell.pulsar-drop-hover"
      )) {
        cell.classList.remove("pulsar-drop-hover");
      }
      for (const preview of root.querySelectorAll(
        ".pulsar-workspace-grid-preview.is-visualization-drop-target"
      )) {
        preview.classList.remove("is-visualization-drop-target");
      }
    }

    function updateWorkspaceTabDropTarget(event) {
      if (!workspaceTabDrag) return false;
      const target = event && event.target;
      const tabs = closestWithinRoot(target, ".pulsar-workspace-tabs", root);
      clearWorkspaceTabDropMarkers();
      workspaceTabDrag.targetPaneId = null;
      workspaceTabDrag.insertionIndex = null;
      workspaceTabDrag.splitDirection = null;
      const targetShell = tabs
        ? closestWithinRoot(target, ".pulsar-workspace-tab-shell", tabs)
        : null;
      if (!targetShell && updateWorkspaceTabDockTarget(event)) return true;
      if (!tabs) return false;

      const targetPaneId = tabs.getAttribute("data-pane-id") || "";
      if (!targetPaneId) return false;
      tabs.classList.add("is-tab-drop-target");
      workspaceTabDrag.targetPaneId = targetPaneId;

      const shells = Array.from(
        tabs.querySelectorAll(".pulsar-workspace-tab-shell")
      );
      if (targetShell) {
        const targetIndex = shells.indexOf(targetShell);
        if (targetIndex < 0) return false;
        const bounds = targetShell.getBoundingClientRect();
        const before = (Number(event.clientX) || 0) < bounds.left + bounds.width / 2;
        targetShell.classList.add(
          before ? "is-tab-drop-before" : "is-tab-drop-after"
        );
        workspaceTabDrag.insertionIndex = targetIndex + (before ? 0 : 1);
      } else {
        const lastShell = shells[shells.length - 1];
        if (lastShell) lastShell.classList.add("is-tab-drop-after");
        workspaceTabDrag.insertionIndex = shells.length;
      }
      return true;
    }

    function updateWorkspaceTabDockTarget(event) {
      if (!workspaceTabDrag) return false;
      if (root.querySelectorAll(".pulsar-workspace-tab-bar").length >= 4) {
        return false;
      }

      function activateTarget(target) {
        if (!target) return false;
        const paneId = target.getAttribute("data-tab-dock-pane-id") || "";
        const direction =
          target.getAttribute("data-tab-dock-direction") === "vertical"
            ? "vertical"
            : "horizontal";
        if (!paneId) return false;
        workspaceTabDrag.targetPaneId = paneId;
        workspaceTabDrag.splitDirection = direction;
        target.classList.add("is-tab-dock-active");
        const preview = target.closest(".pulsar-workspace-tab-dock-preview");
        if (preview) preview.classList.add("is-tab-dock-preview-active");
        return true;
      }

      const directTarget = closestWithinRoot(
        event && event.target,
        ".pulsar-workspace-tab-dock-target",
        root
      );
      if (directTarget) return activateTarget(directTarget);

      const clientX = Number(event && event.clientX);
      const clientY = Number(event && event.clientY);
      if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return false;

      const previews = Array.from(
        root.querySelectorAll(".pulsar-workspace-tab-dock-preview")
      );
      const preview = previews.find((candidate) => {
        const bounds = candidate.getBoundingClientRect();
        return (
          clientX >= bounds.left &&
          clientX <= bounds.right &&
          clientY >= bounds.top &&
          clientY <= bounds.bottom
        );
      });
      if (!preview) return false;

      const bounds = preview.getBoundingClientRect();
      const rightDistance = bounds.right - clientX;
      const bottomDistance = bounds.bottom - clientY;
      const nearRight =
        rightDistance >= 0 && rightDistance <= bounds.width * 0.15;
      const nearBottom =
        bottomDistance >= 0 && bottomDistance <= bounds.height * 0.15;
      if (!nearRight && !nearBottom) return false;

      const direction = nearBottom ? "vertical" : "horizontal";
      return activateTarget(
        preview.querySelector(
          `.pulsar-workspace-tab-dock-target[data-tab-dock-direction="${direction}"]`
        )
      );
    }

    function onDragStart(event) {
      const target = event && event.target;
      if (!event.dataTransfer) return;

      const workspaceTab = closestWithinRoot(
        target,
        ".pulsar-workspace-tab",
        root
      );
      if (workspaceTab) {
        const paneId = workspaceTab.getAttribute("data-pane-id") || "";
        const tabId = workspaceTab.getAttribute("data-tab-id") || "";
        const shell = workspaceTab.closest(".pulsar-workspace-tab-shell");
        if (!paneId || !tabId || !shell) return;
        finishWorkspaceTabDrag();
        workspaceTabDrag = {
          paneId,
          tabId,
          targetPaneId: null,
          insertionIndex: null,
          splitDirection: null,
        };
        workspaceTab.setAttribute("aria-grabbed", "true");
        shell.classList.add("is-tab-dragging");
        if (root.querySelectorAll(".pulsar-workspace-tab-bar").length < 4) {
          root.classList.add("is-workspace-tab-dragging");
        }
        event.dataTransfer.setData(
          "application/x-pulsar-workspace-tab",
          tabId
        );
        event.dataTransfer.effectAllowed = "move";
        return;
      }

      const variable = closestWithinRoot(target, ".pulsar-draggable-var", root);
      if (variable) {
        const item = variable.getAttribute("data-item") || "";
        if (!item) return;
        event.dataTransfer.setData("text/plain", item);
        event.dataTransfer.setData("application/x-pulsar-var", item);
        event.dataTransfer.effectAllowed = "copy";
        variable.style.opacity = "0.45";
        return;
      }

      const cell = closestWithinRoot(target, ".pulsar-dropcell", root);
      if (!cell) return;
      if (cell.closest(".pulsar-workspace-grid-preview")) return;
      const filled = cell.getAttribute("data-cell-filled");
      const fromIndex = cell.getAttribute("data-cell-index");
      if (filled !== "1" || fromIndex === null) return;
      const sourcePaneId = cell.getAttribute("data-pane-id") || "";
      const sourceTabId = cell.getAttribute("data-tab-id") || "";
      event.dataTransfer.setData("application/x-pulsar-grid-cell", fromIndex);
      if (sourcePaneId && sourceTabId) {
        event.dataTransfer.setData(
          workspaceGridCellMime,
          JSON.stringify({
            paneId: sourcePaneId,
            tabId: sourceTabId,
            cellIndex: Number(fromIndex),
          })
        );
      }
      event.dataTransfer.effectAllowed = "move";
      cell.style.opacity = "0.55";
    }

    function onDragEnd(event) {
      const target = event && event.target;
      if (
        workspaceTabDrag ||
        closestWithinRoot(target, ".pulsar-workspace-tab", root)
      ) {
        finishWorkspaceTabDrag();
        return;
      }
      const variable = closestWithinRoot(target, ".pulsar-draggable-var", root);
      if (variable) variable.style.opacity = "1";
      const cell = closestWithinRoot(target, ".pulsar-dropcell", root);
      if (cell) cell.style.opacity = "1";
      clearWorkspaceGridDropTargets();
    }

    function onDragOver(event) {
      if (workspaceTabDrag) {
        if (updateWorkspaceTabDropTarget(event)) {
          event.preventDefault();
          if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        }
        return;
      }
      const cell = closestWithinRoot(
        event && event.target,
        ".pulsar-dropcell",
        root
      );
      if (!cell) return;
      const preview = cell.closest(".pulsar-workspace-grid-preview");
      const types = event.dataTransfer
        ? Array.from(event.dataTransfer.types || [])
        : [];
      const workspaceCellDrag = types.includes(workspaceGridCellMime);
      if (preview && !workspaceCellDrag) return;
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = types.includes(
          "application/x-pulsar-grid-cell"
        )
          ? "move"
          : "copy";
      }
      cell.classList.add("pulsar-drop-hover");
      if (preview) {
        preview.classList.add("is-visualization-drop-target");
      }
    }

    function onDragLeave(event) {
      if (workspaceTabDrag) {
        if (!root.contains(event.relatedTarget)) {
          clearWorkspaceTabDropMarkers();
          workspaceTabDrag.targetPaneId = null;
          workspaceTabDrag.insertionIndex = null;
          workspaceTabDrag.splitDirection = null;
        }
        return;
      }
      const cell = closestWithinRoot(
        event && event.target,
        ".pulsar-dropcell",
        root
      );
      if (cell && !cell.contains(event.relatedTarget)) {
        cell.classList.remove("pulsar-drop-hover");
        const preview = cell.closest(".pulsar-workspace-grid-preview");
        if (preview && !preview.contains(event.relatedTarget)) {
          preview.classList.remove("is-visualization-drop-target");
        }
      }
    }

    function onDrop(event) {
      if (workspaceTabDrag) {
        const accepted = updateWorkspaceTabDropTarget(event);
        const sourcePaneId = workspaceTabDrag.paneId;
        const targetPaneId = workspaceTabDrag.targetPaneId;
        const tabId = workspaceTabDrag.tabId;
        const insertionIndex = workspaceTabDrag.insertionIndex;
        const splitDirection = workspaceTabDrag.splitDirection;
        if (accepted) event.preventDefault();
        finishWorkspaceTabDrag();
        if (accepted && splitDirection && targetPaneId) {
          trameTrigger("split_workspace_tab_trigger", [
            sourcePaneId,
            tabId,
            targetPaneId,
            splitDirection,
          ]);
        } else if (accepted && Number.isInteger(insertionIndex)) {
          if (sourcePaneId === targetPaneId) {
            trameTrigger("reorder_workspace_tab_trigger", [
              sourcePaneId,
              tabId,
              insertionIndex,
            ]);
          } else {
            trameTrigger("move_workspace_tab_trigger", [
              sourcePaneId,
              tabId,
              targetPaneId,
              insertionIndex,
            ]);
          }
        }
        return;
      }
      const cell = closestWithinRoot(
        event && event.target,
        ".pulsar-dropcell",
        root
      );
      if (!cell) return;
      event.preventDefault();
      const preview = cell.closest(".pulsar-workspace-grid-preview");

      const fromCell = event.dataTransfer
        ? event.dataTransfer.getData("application/x-pulsar-grid-cell") || ""
        : "";
      const targetIndex = cell.getAttribute("data-cell-index");
      if (preview) {
        const workspaceCell = event.dataTransfer
          ? event.dataTransfer.getData(workspaceGridCellMime) || ""
          : "";
        const targetPaneId = cell.getAttribute("data-pane-id") || "";
        const targetTabId = cell.getAttribute("data-tab-id") || "";
        clearWorkspaceGridDropTargets();
        if (targetIndex === null || !targetPaneId || !targetTabId) return;
        if (workspaceCell) {
          try {
            const source = JSON.parse(workspaceCell);
            if (
              source &&
              source.paneId &&
              source.tabId &&
              Number.isInteger(Number(source.cellIndex))
            ) {
              trameTrigger("move_workspace_grid_cell_trigger", [
                source.paneId,
                source.tabId,
                Number(source.cellIndex),
                targetPaneId,
                targetTabId,
                Number(targetIndex),
              ]);
            }
          } catch (_error) {
            return;
          }
          return;
        }
        return;
      }
      clearWorkspaceGridDropTargets();
      if (fromCell !== "" && targetIndex !== null) {
        trameTrigger("move_grid_cell_trigger", [fromCell, targetIndex]);
        return;
      }

      const item = event.dataTransfer
        ? event.dataTransfer.getData("text/plain") ||
          event.dataTransfer.getData("application/x-pulsar-var") ||
          ""
        : "";
      if (item && targetIndex !== null) {
        trameTrigger("assign_var_to_grid_cell_trigger", [item, targetIndex]);
      }
    }

    function onContextMenu(event) {
      const target = event && event.target;
      if (closestWithinRoot(target, "#pulsar-context-menu", root)) return;

      const workspaceTab = closestWithinRoot(
        target,
        ".pulsar-workspace-tab",
        root
      );
      if (workspaceTab) {
        event.preventDefault();
        const paneId = workspaceTab.getAttribute("data-pane-id") || "";
        const tabId = workspaceTab.getAttribute("data-tab-id") || "";
        if (paneId && tabId) {
          trameTrigger("show_tab_context_menu", [
            paneId,
            tabId,
            event.clientX || 0,
            event.clientY || 0,
          ]);
        }
        return;
      }

      const variable = closestWithinRoot(target, ".pulsar-draggable-var", root);
      if (variable) {
        event.preventDefault();
        const item = variable.getAttribute("data-item") || "";
        if (item) {
          trameTrigger("show_item_context_menu", [
            item,
            event.clientX || 0,
            event.clientY || 0,
          ]);
        }
        return;
      }

      const cell = closestWithinRoot(target, ".pulsar-dropcell", root);
      if (cell) {
        if (cell.closest(".pulsar-workspace-grid-preview")) return;
        event.preventDefault();
        const index = cell.getAttribute("data-cell-index");
        if (index !== null) {
          trameTrigger("show_cell_context_menu", [
            index,
            event.clientX || 0,
            event.clientY || 0,
          ]);
        }
        return;
      }

      trameTrigger("hide_context_menu_trigger", []);
    }

    function onClick(event) {
      if (!closestWithinRoot(event && event.target, "#pulsar-context-menu", root)) {
        trameTrigger("hide_context_menu_trigger", []);
      }
    }

    function onDoubleClick(event) {
      const handle = closestWithinRoot(
        event && event.target,
        ".pulsar-workspace-splitter",
        root
      );
      if (!handle) return;
      const splitId = handle.getAttribute("data-split-id") || "";
      if (!splitId) return;
      trameTrigger("resize_workspace_split_trigger", [splitId, 0.5]);
      event.preventDefault();
    }

    const handlers = {
      root: {
        dragstart: onDragStart,
        dragend: onDragEnd,
        dragover: onDragOver,
        dragleave: onDragLeave,
        drop: onDrop,
        contextmenu: onContextMenu,
        click: onClick,
        dblclick: onDoubleClick,
      },
      capture: {
        pointerdown: onPointerDown,
        pointermove: onPointerMove,
        pointerup: onPointerEnd,
        pointercancel: onPointerEnd,
        lostpointercapture: onLostPointerCapture,
        scroll: onWorkspaceTabsScroll,
      },
      window: {
        resize: onWindowResize,
      },
      cleanup() {
        finishFloatingDrag();
        finishFloatingResize();
        finishWorkspaceSplitDrag(false);
        finishWorkspaceTabDrag();
        clearWorkspaceGridDropTargets();
        if (tabOverflowFrame) {
          window.cancelAnimationFrame(tabOverflowFrame);
          tabOverflowFrame = 0;
        }
        if (tabOverflowMutationObserver) {
          tabOverflowMutationObserver.disconnect();
          tabOverflowMutationObserver = null;
        }
        if (floatingPanelResizeObserver) {
          floatingPanelResizeObserver.disconnect();
        }
        if (tabOverflowResizeObserver) tabOverflowResizeObserver.disconnect();
        for (const panel of root.querySelectorAll(
          ".pulsar-floating-options-panel.is-dragging"
        )) {
          panel.classList.remove("is-dragging");
        }
      },
    };

    if (typeof MutationObserver === "function") {
      tabOverflowMutationObserver = new MutationObserver(
        scheduleWorkspaceTabOverflowUpdate
      );
      tabOverflowMutationObserver.observe(root, {
        attributes: true,
        attributeFilter: ["class"],
        childList: true,
        subtree: true,
      });
    }
    if (floatingPanelResizeObserver) {
      for (const panel of root.querySelectorAll(".pulsar-provenance-panel")) {
        floatingPanelResizeObserver.observe(panel);
      }
    }
    scheduleWorkspaceTabOverflowUpdate();

    return handlers;
  }

  function mount(root) {
    if (!root || mountedRoots.has(root)) return;
    const handlers = createHandlers(root);
    for (const [eventName, handler] of Object.entries(handlers.root)) {
      root.addEventListener(eventName, handler);
    }
    for (const [eventName, handler] of Object.entries(handlers.capture)) {
      root.addEventListener(eventName, handler, true);
    }
    for (const [eventName, handler] of Object.entries(handlers.window)) {
      window.addEventListener(eventName, handler);
    }
    mountedRoots.set(root, handlers);
    root.setAttribute("data-pulsar-interaction-runtime-owner", "mounted");
  }

  function unmount(root) {
    const handlers = root && mountedRoots.get(root);
    if (!root || !handlers) return;
    handlers.cleanup();
    for (const [eventName, handler] of Object.entries(handlers.root)) {
      root.removeEventListener(eventName, handler);
    }
    for (const [eventName, handler] of Object.entries(handlers.capture)) {
      root.removeEventListener(eventName, handler, true);
    }
    for (const [eventName, handler] of Object.entries(handlers.window)) {
      window.removeEventListener(eventName, handler);
    }
    for (const element of root.querySelectorAll(
      ".pulsar-draggable-var, .pulsar-dropcell"
    )) {
      element.style.opacity = "1";
    }
    for (const cell of root.querySelectorAll(".pulsar-drop-hover")) {
      cell.classList.remove("pulsar-drop-hover");
    }
    mountedRoots.delete(root);
    root.removeAttribute("data-pulsar-interaction-runtime-owner");
  }

  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  const runtime = runtimes.interaction || window.pulsarInteractionRuntime || {};
  runtime.mount = mount;
  runtime.unmount = unmount;
  runtime.install = function install(app) {
    app.component("pulsar-interaction-runtime", {
      mounted() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.mount(root);
      },
      beforeUnmount() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.unmount(root);
      },
      template:
        '<span hidden data-pulsar-interaction-runtime="mounted"></span>',
    });
  };

  runtimes.interaction = runtime;
  window.pulsarInteractionRuntime = runtime;
})();
