(function initSeuratTimelineRuntime() {
  "use strict";
  let runtimeRoot = null;

  function gridRuntimeQuery(selector) {
    const root = runtimeRoot || document;
    return root.querySelector ? root.querySelector(selector) : null;
  }

  function gridRuntimeQueryAll(selector) {
    const root = runtimeRoot || document;
    return root.querySelectorAll ? root.querySelectorAll(selector) : [];
  }

  function gridRuntimeElementById(id) {
    return gridRuntimeQuery("#" + id);
  }

  function inferFpsForVideos(videos) {
    const DEFAULT_FPS = 2.0;
    for (const v of (videos || [])) {
      const fpsAttr = Number(v && v.getAttribute && v.getAttribute("data-fps"));
      if (Number.isFinite(fpsAttr) && fpsAttr > 0) {
        return fpsAttr;
      }
    }
    return DEFAULT_FPS;
  }

  function getVideoFrameCount(video) {
    const count = Number(video && video.getAttribute && video.getAttribute("data-frame-count"));
    return Number.isFinite(count) && count > 0 ? Math.floor(count) : null;
  }

  function getCommonVideoFrameCount(videos) {
    let count = Infinity;
    for (const v of (videos || [])) {
      const frameCount = getVideoFrameCount(v);
      if (frameCount !== null) {
        count = Math.min(count, frameCount);
      }
    }
    return Number.isFinite(count) ? count : null;
  }

  function parseVideoFrameIndices(video) {
    const raw = String(video && video.getAttribute && video.getAttribute("data-frame-indices") || "");
    if (!raw) return [];
    const values = [];
    for (const part of raw.split(",")) {
      const value = Number(part);
      if (Number.isFinite(value)) values.push(value);
    }
    return values;
  }

  function frameOrdinalFromTime(rawSeconds, videos) {
    const fps = inferFpsForVideos(videos);
    const count = getCommonVideoFrameCount(videos);
    const rawOrdinal = Math.round(Math.max(0, Number(rawSeconds) || 0) * fps);
    if (count !== null) {
      return Math.max(0, Math.min(rawOrdinal, Math.max(0, count - 1)));
    }
    return Math.max(0, rawOrdinal);
  }

  function timeForFrameOrdinal(rawOrdinal, videos) {
    const fps = inferFpsForVideos(videos);
    const count = getCommonVideoFrameCount(videos);
    let ordinal = Math.round(Number(rawOrdinal) || 0);
    if (count !== null) {
      ordinal = Math.max(0, Math.min(ordinal, Math.max(0, count - 1)));
    } else {
      ordinal = Math.max(0, ordinal);
    }
    return ordinal / fps;
  }

  function videoFrameLabel(rawOrdinal, videos) {
    const ordinal = Math.max(0, Math.round(Number(rawOrdinal) || 0));
    const firstVideo = (videos || [])[0];
    const indices = parseVideoFrameIndices(firstVideo);
    if (ordinal < indices.length) {
      const value = indices[ordinal];
      return Number.isInteger(value) ? String(value) : String(value);
    }
    return String(ordinal);
  }

  function getGridImageSequencesSafe() {
    if (typeof getGridImageSequences === "function") {
      return getGridImageSequences();
    }
    return Array.from(gridRuntimeQueryAll('img[data-grid-image-sequence="1"]'));
  }

  function parseImageSequenceSources(el) {
    const raw = String(el && el.getAttribute && el.getAttribute("data-frame-sources") || "[]");
    try {
      const sources = JSON.parse(raw);
      return Array.isArray(sources) ? sources.filter(function(src) { return !!src; }) : [];
    } catch (_err) {
      return [];
    }
  }

  function parseImageSequenceFrameIndices(el) {
    const raw = String(el && el.getAttribute && el.getAttribute("data-frame-indices") || "");
    if (!raw) return [];
    const values = [];
    for (const part of raw.split(",")) {
      const value = Number(part);
      if (Number.isFinite(value)) values.push(value);
    }
    return values;
  }

  function parseImageSequenceTimeValues(el) {
    const raw = String(el && el.getAttribute && el.getAttribute("data-time-values") || "");
    if (!raw) return [];
    const values = [];
    for (const part of raw.split(",")) {
      const value = Number(part);
      if (Number.isFinite(value)) values.push(value);
    }
    return values;
  }

  function imageSequenceHasPhysicalTime(el) {
    const mode = String(el && el.getAttribute && el.getAttribute("data-time-mode") || "").trim().toLowerCase();
    return mode === "physical_time" && parseImageSequenceTimeValues(el).length > 0;
  }

  function imageSequencesHavePhysicalTime(sequences) {
    const values = sequences || [];
    return values.length > 0 && values.every(imageSequenceHasPhysicalTime);
  }

  function isVisibleGridCell(cell) {
    if (!cell) return false;
    try {
      const style = window.getComputedStyle(cell);
      if (style && style.display === "none") return false;
    } catch (_err) {
      // Keep going; visibility is best-effort here.
    }
    return true;
  }

  function collectPlotTimeValues(plots) {
    const plot = plotRuntime();
    return plot ? plot.collectTimelineValues(plots || plot.getPlots()) : [];
  }

  function uniqueSortedTimelineValues(values) {
    const sorted = (values || [])
      .map(function(value) { return Number(value); })
      .filter(function(value) { return Number.isFinite(value); })
      .sort(function(a, b) { return a - b; });
    const result = [];
    for (const value of sorted) {
      if (!result.length) {
        result.push(value);
        continue;
      }
      const previous = result[result.length - 1];
      const tolerance = Math.max(1e-12, 1e-9 * Math.max(1, Math.abs(previous), Math.abs(value)));
      if (Math.abs(value - previous) > tolerance) result.push(value);
    }
    return result;
  }

  function selectionAxisForGridCell(cell) {
    if (!cell || !cell.getAttribute) return null;
    const raw = String(cell.getAttribute("data-selection-axis") || "");
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      const values = Array.isArray(parsed.values)
        ? parsed.values.map(Number).filter(Number.isFinite)
        : [];
      if (!values.length) return null;
      return {
        id: String(parsed.id || ""),
        key: String(parsed.key || parsed.id || ""),
        kind: String(parsed.kind || ""),
        label: String(parsed.label || parsed.id || "Axis"),
        unit: String(parsed.unit || ""),
        isDefault: !!parsed.default,
        index: Number.isFinite(Number(parsed.index)) ? Number(parsed.index) : 0,
        values,
        explicit: true,
      };
    } catch (_err) {
      return null;
    }
  }

  function timelineForGridCell(cell) {
    if (!cell || !isVisibleGridCell(cell)) {
      return { values: [], hasPlot: false, hasSequence: false };
    }

    const selectionAxis = selectionAxisForGridCell(cell);
    if (selectionAxis) {
      return {
        values: selectionAxis.values,
        hasPlot: !!(cell.querySelector && cell.querySelector(".seurat-plot1d")),
        hasSequence: !!(cell.querySelector && cell.querySelector('img[data-grid-image-sequence="1"]')),
        axis: selectionAxis,
      };
    }

    const plots = Array.from(cell.querySelectorAll ? cell.querySelectorAll(".seurat-plot1d") : []);
    const sequences = Array.from(cell.querySelectorAll ? cell.querySelectorAll('img[data-grid-image-sequence="1"]') : []);
    const values = [];
    const plotValues = collectPlotTimeValues(plots);
    values.push.apply(values, plotValues);

    let sequenceValueCount = 0;
    for (const el of sequences) {
      if (!imageSequenceHasPhysicalTime(el)) continue;
      const times = parseImageSequenceTimeValues(el);
      if (times.length) {
        sequenceValueCount += times.length;
        values.push.apply(values, times);
      }
    }

    const timelineValues = uniqueSortedTimelineValues(values);
    return {
      values: timelineValues,
      hasPlot: plotValues.length > 0,
      hasSequence: sequenceValueCount > 0,
      axis: timelineValues.length ? {
        id: "legacy-time",
        key: "legacy:time",
        kind: "time",
        label: "Time",
        unit: "",
        values: timelineValues,
        explicit: false,
      } : null,
    };
  }

  function selectedTimelineDriverCell() {
    const cell = gridRuntimeQuery('.seurat-dropcell[data-timeline-driver="1"]');
    return cell && isVisibleGridCell(cell) ? cell : null;
  }

  function activeTimelineCell() {
    const cell = gridRuntimeQuery('.seurat-dropcell[data-cell-active="1"]');
    return cell && isVisibleGridCell(cell) ? cell : null;
  }

  function autoTimelineDriver() {
    const cells = Array.from(gridRuntimeQueryAll(".seurat-dropcell"));
    let best = null;
    for (const cell of cells) {
      const timeline = timelineForGridCell(cell);
      if (!timeline.values.length) continue;
      const rawIndex = Number(cell.getAttribute("data-cell-index"));
      const index = Number.isFinite(rawIndex) ? rawIndex : cells.indexOf(cell);
      const candidate = {
        cell,
        values: timeline.values,
        hasPlot: timeline.hasPlot,
        index,
        axis: timeline.axis,
        isDefault: !!(timeline.axis && timeline.axis.isDefault),
      };
      if (
        !best
        || (candidate.isDefault && !best.isDefault)
        || (
          candidate.isDefault === best.isDefault
          && candidate.values.length > best.values.length
        )
        || (
          candidate.isDefault === best.isDefault
          && candidate.values.length === best.values.length
          && candidate.hasPlot
          && !best.hasPlot
        )
        || (
          candidate.isDefault === best.isDefault
          && candidate.values.length === best.values.length
          && candidate.hasPlot === best.hasPlot
          && candidate.index < best.index
        )
      ) {
        best = candidate;
      }
    }
    return best || { values: [], axis: null };
  }

  function getActiveSelectionAxis(sequences, plots) {
    sequences = sequences || getGridImageSequencesSafe();
    plots = plots || (typeof getGridPlots === "function" ? getGridPlots() : []);
    const hasIndexOnlySequence = sequences.length
      && !imageSequencesHavePhysicalTime(sequences);

    const selected = selectedTimelineDriverCell();
    if (selected) {
      const selectedTimeline = timelineForGridCell(selected);
      if (selectedTimeline.values.length) {
        if (selectedTimeline.axis && selectedTimeline.axis.explicit) {
          return selectedTimeline.axis;
        }
        if (hasIndexOnlySequence) return null;
        return selectedTimeline.axis;
      }
    }

    const active = activeTimelineCell();
    if (active) {
      const activeTimeline = timelineForGridCell(active);
      if (activeTimeline.values.length) {
        if (activeTimeline.axis && activeTimeline.axis.explicit) {
          return activeTimeline.axis;
        }
        if (hasIndexOnlySequence) return null;
        return activeTimeline.axis;
      }
    }

    const auto = autoTimelineDriver();
    if (auto.values.length) {
      if (auto.axis && auto.axis.explicit) return auto.axis;
      if (hasIndexOnlySequence) return null;
      return auto.axis;
    }

    if (hasIndexOnlySequence) return null;

    const values = [];
    for (const el of (sequences || [])) {
      if (!imageSequenceHasPhysicalTime(el)) continue;
      values.push.apply(values, parseImageSequenceTimeValues(el));
    }
    values.push.apply(values, collectPlotTimeValues(plots));
    const timelineValues = uniqueSortedTimelineValues(values);
    return timelineValues.length ? {
      id: "legacy-time",
      key: "legacy:time",
      kind: "time",
      label: "Time",
      unit: "",
      values: timelineValues,
      explicit: false,
    } : null;
  }

  function getPhysicalTimeline(sequences, plots) {
    const axis = getActiveSelectionAxis(sequences, plots);
    return axis && Array.isArray(axis.values) ? axis.values : [];
  }

  function elementSelectionAxis(el) {
    const cell = el && el.closest ? el.closest(".seurat-dropcell") : null;
    return selectionAxisForGridCell(cell);
  }

  function elementMatchesActiveAxis(el, activeAxis) {
    if (!activeAxis || !activeAxis.explicit) return true;
    const axis = elementSelectionAxis(el);
    return !!(axis && axis.key && axis.key === activeAxis.key);
  }

  function updateAxisCompatibility(activeAxis) {
    for (const cell of Array.from(gridRuntimeQueryAll(".seurat-dropcell"))) {
      const axis = selectionAxisForGridCell(cell);
      const currentStatus = String(cell.getAttribute("data-axis-sync-status") || "");
      if (!activeAxis || !activeAxis.explicit || !axis) {
        if (currentStatus === "incompatible" || currentStatus === "synchronized") {
          cell.setAttribute("data-axis-sync-status", "");
        }
        continue;
      }
      if (axis.key !== activeAxis.key) {
        cell.setAttribute("data-axis-sync-status", "incompatible");
      } else if (["", "incompatible", "synchronized"].includes(currentStatus)) {
        cell.setAttribute("data-axis-sync-status", "synchronized");
      }
    }
  }

  function timelineIndexAtOrBefore(rawTime, timeline) {
    const values = timeline || [];
    if (!values.length) return 0;
    const t = Number(rawTime);
    if (!Number.isFinite(t) || t <= values[0]) return 0;
    if (t >= values[values.length - 1]) return values.length - 1;

    let lo = 0;
    let hi = values.length;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (values[mid] <= t) lo = mid + 1;
      else hi = mid;
    }
    return Math.max(0, Math.min(lo - 1, values.length - 1));
  }

  function timelineIndexNearest(rawTime, timeline) {
    const values = timeline || [];
    if (!values.length) return 0;
    const lower = timelineIndexAtOrBefore(rawTime, values);
    const upper = Math.min(lower + 1, values.length - 1);
    const t = Number(rawTime);
    if (!Number.isFinite(t)) return lower;
    return Math.abs(values[upper] - t) < Math.abs(t - values[lower]) ? upper : lower;
  }

  function timeForTimelineIndex(rawIndex, timeline) {
    const values = timeline || [];
    if (!values.length) return 0;
    let index = Math.round(Number(rawIndex) || 0);
    index = Math.max(0, Math.min(index, values.length - 1));
    return values[index];
  }

  function imageSequenceFrameForTime(el, rawTime) {
    const sources = parseImageSequenceSources(el);
    if (!sources.length) return 0;

    const times = imageSequenceHasPhysicalTime(el) ? parseImageSequenceTimeValues(el) : [];
    if (!times.length) {
      return Math.max(0, Math.min(Math.round(Number(rawTime) || 0), sources.length - 1));
    }

    const index = timelineIndexAtOrBefore(rawTime, times);
    return Math.max(0, Math.min(index, sources.length - 1));
  }

  function formatTimelineValue(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    if (Number.isInteger(number)) return String(number);
    const absValue = Math.abs(number);
    if (absValue > 0 && (absValue < 1e-3 || absValue >= 1e6)) {
      return number.toExponential(6).replace(/0+e/, "e");
    }
    return String(Number(number.toPrecision(7)));
  }

  function getImageSequenceFrameCount(el) {
    const count = Number(el && el.getAttribute && el.getAttribute("data-frame-count"));
    if (Number.isFinite(count) && count > 0) return Math.floor(count);
    return parseImageSequenceSources(el).length || null;
  }

  function getCommonImageSequenceFrameCount(sequences) {
    let count = Infinity;
    for (const el of (sequences || [])) {
      const frameCount = getImageSequenceFrameCount(el);
      if (frameCount !== null) count = Math.min(count, frameCount);
    }
    return Number.isFinite(count) ? count : null;
  }

  function clampImageSequenceFrame(rawOrdinal, sequences) {
    const count = getCommonImageSequenceFrameCount(sequences);
    let ordinal = Math.round(Number(rawOrdinal) || 0);
    ordinal = Math.max(0, ordinal);
    if (count !== null) ordinal = Math.min(ordinal, Math.max(0, count - 1));
    return ordinal;
  }

  function imageSequenceFrameTimelineValue(rawOrdinal, sequences) {
    const ordinal = clampImageSequenceFrame(rawOrdinal, sequences);
    const firstSequence = (sequences || [])[0];
    const timeValues = parseImageSequenceTimeValues(firstSequence);
    if (ordinal < timeValues.length) {
      return timeValues[ordinal];
    }
    const indices = parseImageSequenceFrameIndices(firstSequence);
    if (ordinal < indices.length) {
      return indices[ordinal];
    }
    return ordinal;
  }

  function imageSequenceFrameLabel(rawOrdinal, sequences) {
    return formatTimelineValue(
      imageSequenceFrameTimelineValue(rawOrdinal, sequences)
    );
  }

  function inferFpsForImageSequences(sequences) {
    const DEFAULT_FPS = 2.0;
    for (const el of (sequences || [])) {
      const fpsAttr = Number(el && el.getAttribute && el.getAttribute("data-fps"));
      if (Number.isFinite(fpsAttr) && fpsAttr > 0) return fpsAttr;
    }
    return DEFAULT_FPS;
  }

  function setImageSequenceFrame(rawOrdinal, sequences) {
    const ordinal = clampImageSequenceFrame(rawOrdinal, sequences);
    const activeAxis = getActiveSelectionAxis(sequences, getGridPlots());
    for (const el of (sequences || [])) {
      if (!elementMatchesActiveAxis(el, activeAxis)) continue;
      const sources = parseImageSequenceSources(el);
      if (!sources.length) continue;
      const idx = Math.max(0, Math.min(ordinal, sources.length - 1));
      if (el.getAttribute("src") !== sources[idx]) {
        el.setAttribute("src", sources[idx]);
      }
      el.setAttribute("data-current-frame", String(idx));
    }
    return ordinal;
  }

  function setImageSequencesForTime(rawTime, sequences) {
    const t = Number(rawTime);
    const activeAxis = getActiveSelectionAxis(sequences, getGridPlots());
    for (const el of (sequences || [])) {
      if (!elementMatchesActiveAxis(el, activeAxis)) continue;
      const sources = parseImageSequenceSources(el);
      if (!sources.length) continue;
      const idx = imageSequenceFrameForTime(el, t);
      if (el.getAttribute("src") !== sources[idx]) {
        el.setAttribute("src", sources[idx]);
      }
      el.setAttribute("data-current-frame", String(idx));
    }
    return Number.isFinite(t) ? t : 0;
  }

  function getReferenceImageSequenceFrame(sequences) {
    for (const el of (sequences || [])) {
      const value = Number(el && el.getAttribute && el.getAttribute("data-current-frame"));
      if (Number.isFinite(value) && value >= 0) return Math.round(value);
    }
    return 0;
  }

  function getReferenceImageSequenceTime(sequences) {
    for (const el of (sequences || [])) {
      const frame = Number(el && el.getAttribute && el.getAttribute("data-current-frame"));
      if (!Number.isFinite(frame) || frame < 0) continue;
      const times = imageSequenceHasPhysicalTime(el) ? parseImageSequenceTimeValues(el) : [];
      const index = Math.max(0, Math.min(Math.round(frame), Math.max(0, times.length - 1)));
      if (index < times.length) return times[index];
    }
    return getReferenceImageSequenceFrame(sequences);
  }

  function getVcrSliderFrameValue() {
    const slider = gridRuntimeElementById("seurat-vcr-step-slider");
    const raw = Number(slider && slider.value);
    if (Number.isFinite(raw) && raw >= 0) {
      return Math.round(raw);
    }
    return 0;
  }

  function getVcrSliderTimeValue(videos, plots) {
    videos = videos || [];
    plots = plots || (typeof getGridPlots === "function" ? getGridPlots() : []);
    const sequences = getGridImageSequencesSafe();
    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length) {
      return timeForTimelineIndex(getVcrSliderFrameValue(), timeline);
    }
    if (sequences.length) {
      return getVcrSliderFrameValue();
    }
    if (videos.length) {
      return timeForFrameOrdinal(getVcrSliderFrameValue(), videos);
    }

    const slider = gridRuntimeElementById("seurat-vcr-step-slider");
    const raw = Number(slider && slider.value);
    const max = Math.max(1, Number(slider && slider.max) || 500);
    const bounds = (typeof getMediaTimelineBounds === "function")
      ? getMediaTimelineBounds(videos, plots)
      : { start: 0, end: 0 };
    const start = Number.isFinite(bounds.start) ? bounds.start : 0;
    const end = Number.isFinite(bounds.end) ? bounds.end : start;
    const progress = Math.max(0, Math.min(1, (Number.isFinite(raw) ? raw : 0) / max));
    return start + progress * (end - start);
  }

  function updateVcrTimeLabelFromSeconds(rawSeconds, videos, plots) {
    videos = videos || [];
    plots = plots || (typeof getGridPlots === "function" ? getGridPlots() : []);
    const sequences = getGridImageSequencesSafe();
    const bounds = (typeof getMediaTimelineBounds === "function")
      ? getMediaTimelineBounds(videos, plots)
      : { start: 0, end: 0, usesVideos: !!(videos && videos.length) };
    const label = gridRuntimeElementById("seurat-vcr-time-value");
    const activeAxis = getActiveSelectionAxis(sequences, plots);
    const axisKey = String(activeAxis && activeAxis.key || "");
    const axisChanged = !!axisKey && axisKey !== gridVcrState.axisKey;
    const initialAxisIndex = activeAxis && Array.isArray(activeAxis.values)
      ? Math.max(0, Math.min(Math.round(Number(activeAxis.index) || 0), activeAxis.values.length - 1))
      : 0;
    if (axisChanged) {
      gridVcrState.timelinePosition = initialAxisIndex;
      gridVcrState.lastNotifiedAxisIndex = initialAxisIndex;
    }
    const seconds = axisChanged && activeAxis && activeAxis.values.length
      ? Number(activeAxis.values[initialAxisIndex])
      : Number(rawSeconds);
    const safeSeconds = (typeof clampTimeForMedia === "function")
      ? clampTimeForMedia(seconds, videos, plots)
      : (Number.isFinite(seconds) && seconds >= 0 ? seconds : 0);
    const fps = inferFpsForVideos(videos);
    const timeline = getPhysicalTimeline(sequences, plots);
    gridVcrState.axisKey = axisKey;
    updateAxisCompatibility(activeAxis);
    if (label) {
      if (activeAxis && activeAxis.explicit && timeline.length) {
        label.textContent = String(activeAxis.label || "Axis") + " = "
          + formatTimelineValue(safeSeconds)
          + (activeAxis.unit ? " " + activeAxis.unit : "");
      } else if (timeline.length) {
        label.textContent = "Time = " + formatTimelineValue(safeSeconds);
      } else if (sequences.length) {
        const ordinal = clampImageSequenceFrame(safeSeconds, sequences);
        label.textContent = "Step = " + imageSequenceFrameLabel(ordinal, sequences);
      } else if (videos && videos.length) {
        const ordinal = frameOrdinalFromTime(safeSeconds, videos);
        label.textContent = "Time = " + videoFrameLabel(ordinal, videos);
      } else {
        label.textContent = (plots.length ? "Step = " : "Time = ") + formatTimelineValue(safeSeconds);
      }
      label.setAttribute("title", label.textContent || "");
    }

    const slider = gridRuntimeElementById("seurat-vcr-step-slider");
    if (typeof updatePlotCursors === "function") {
      updatePlotCursors(safeSeconds, videos);
    }
    gridVcrState.syncTime = safeSeconds;
    if (!slider) return;

    if (activeAxis && activeAxis.explicit) {
      const axisLabel = String(activeAxis.label || "Axis");
      slider.setAttribute("aria-label", axisLabel);
      slider.setAttribute("title", axisLabel + " selection");
    } else {
      slider.setAttribute("aria-label", timeline.length ? "Time" : "Timestep");
      slider.setAttribute("title", timeline.length ? "Time selection" : "Timestep (frame index)");
    }

    if (timeline.length) {
      const maxFrames = Math.max(0, timeline.length - 1);
      slider.min = "0";
      slider.max = String(maxFrames);
      slider.step = "1";
      slider.value = String(Math.max(0, Math.min(timelineIndexNearest(safeSeconds, timeline), maxFrames)));
    } else if (sequences.length) {
      const count = getCommonImageSequenceFrameCount(sequences);
      const maxFrames = count !== null ? Math.max(0, count - 1) : 0;
      const frameValue = clampImageSequenceFrame(safeSeconds, sequences);
      slider.min = "0";
      slider.max = String(maxFrames);
      slider.step = "1";
      slider.value = String(Math.max(0, Math.min(frameValue, maxFrames)));
    } else if (videos && videos.length) {
      const count = getCommonVideoFrameCount(videos);
      let maxFrames = count !== null ? Math.max(0, count - 1) : 1;
      if (count === null) {
        let minDuration = Infinity;
        for (const v of (videos || [])) {
          const d = Number(v && v.duration);
          if (Number.isFinite(d) && d > 0) {
            minDuration = Math.min(minDuration, d);
          }
        }
        if (Number.isFinite(minDuration)) {
          maxFrames = Math.max(1, Math.round(Math.max(0, minDuration - 0.04) * fps));
        }
      }
      slider.min = "0";
      slider.max = String(maxFrames);
      slider.step = "1";

      const frameValue = frameOrdinalFromTime(safeSeconds, videos);
      const clamped = Math.max(0, Math.min(frameValue, maxFrames));
      slider.value = String(clamped);
    } else {
      const maxFrames = 500;
      const start = Number.isFinite(bounds.start) ? bounds.start : 0;
      const end = Number.isFinite(bounds.end) ? bounds.end : start;
      const range = Math.max(1e-12, end - start);
      const progress = Math.max(0, Math.min(1, (safeSeconds - start) / range));
      slider.min = "0";
      slider.max = String(maxFrames);
      slider.step = "1";
      slider.value = String(Math.round(progress * maxFrames));
    }
  }
  const gridVcrState = {
    playing: false,
    syncTime: 0,
    timelinePosition: 0,
    syncTimer: null,
    lastTickMs: 0,
    axisKey: "",
    lastNotifiedAxisIndex: -1,
  };
  let notifyingAxisSelection = false;

  function notifyAxisSelectionChanged() {
    const axis = getActiveSelectionAxis(
      getGridImageSequencesSafe(),
      typeof getGridPlots === "function" ? getGridPlots() : []
    );
    if (!axis || !axis.explicit) return;
    const slider = gridRuntimeElementById("seurat-vcr-step-slider");
    const index = Math.round(Number(slider && slider.value) || 0);
    if (index === gridVcrState.lastNotifiedAxisIndex) return;
    gridVcrState.lastNotifiedAxisIndex = index;
    if (!slider) return;
    notifyingAxisSelection = true;
    slider.dispatchEvent(new Event("change", { bubbles: true }));
    notifyingAxisSelection = false;
  }

  function updateGridVcrToggleButton() {
    const button = gridRuntimeQuery('[data-vcr-action="toggle"]');
    if (!button) return;
    const label = gridVcrState.playing ? "Pause all" : "Play all";
    button.textContent = gridVcrState.playing ? "⏸" : "▶";
    button.setAttribute("title", label);
    button.setAttribute("aria-label", label);
  }

  function setGridVcrPlaying(playing) {
    gridVcrState.playing = !!playing;
    updateGridVcrToggleButton();
  }

  let gridMediaSyncTimer = null;
  let gridMediaObserver = null;

  function getGridVideos() {
    return Array.from(gridRuntimeQueryAll('video[data-grid-video="1"]'));
  }

  function getGridImageSequences() {
    return Array.from(gridRuntimeQueryAll('img[data-grid-image-sequence="1"]'));
  }

  function isGridVideo(target) {
    return !!(target && target.matches && target.matches('video[data-grid-video="1"]'));
  }

  function getGridPlots() {
    const plot = plotRuntime();
    return plot ? plot.getPlots() : Array.from(gridRuntimeQueryAll(".seurat-plot1d"));
  }


  function getPlotTimelineBounds(plots) {
    const plot = plotRuntime();
    return plot ? plot.getTimelineBounds(plots || plot.getPlots()) : null;
  }

  function getMediaTimelineBounds(videos, plots) {
    const sequences = getGridImageSequences();
    const timeline = getPhysicalTimeline(sequences, plots || getGridPlots());
    if (timeline.length) {
      return {
        start: timeline[0],
        end: timeline[timeline.length - 1],
        usesVideos: false,
        usesImageSequence: !!sequences.length,
        usesPhysicalTimeline: true,
      };
    }

    const sequenceCount = getCommonImageSequenceFrameCount(sequences);
    if (sequenceCount !== null) {
      return { start: 0, end: Math.max(0, sequenceCount - 1), usesVideos: false, usesImageSequence: true, usesPhysicalTimeline: false };
    }
    const videoEnd = getCommonEndTime(videos || []);
    if (videoEnd !== null) {
      return { start: 0, end: videoEnd, usesVideos: true, usesImageSequence: false, usesPhysicalTimeline: false };
    }
    const plotBounds = getPlotTimelineBounds(plots || getGridPlots());
    if (plotBounds) {
      return { start: plotBounds.start, end: plotBounds.end, usesVideos: false, usesImageSequence: false, usesPhysicalTimeline: false };
    }
    return { start: 0, end: 0, usesVideos: false, usesImageSequence: false, usesPhysicalTimeline: false };
  }

  function clampTimeForMedia(rawTime, videos, plots) {
    const bounds = getMediaTimelineBounds(videos || [], plots || getGridPlots());
    let t = Number(rawTime);
    if (!Number.isFinite(t)) t = bounds.start;
    t = Math.max(bounds.start, t);
    t = Math.min(t, bounds.end);
    return t;
  }

  function updatePlotCursors(rawTime, videos) {
    const plot = plotRuntime();
    if (!plot) return;
    const plots = plot.getPlots();
    if (!plots.length) return;
    const sequences = getGridImageSequencesSafe();
    const activeAxis = getActiveSelectionAxis(sequences, plots);
    const bounds = getMediaTimelineBounds(videos || [], plots);
    const t = clampTimeForMedia(rawTime, videos || [], plots);
    const cursorValue = sequences.length && !getPhysicalTimeline(sequences, plots).length
      ? imageSequenceFrameTimelineValue(t, sequences)
      : t;
    const denom = Math.max(1e-12, bounds.end - bounds.start);
    // Step and physical timelines use declared plot coordinates. For
    // sequence-driven timelines, the frame's declared value is the plot
    // coordinate even when the sequence itself is indexed by ordinal.
    // Only elapsed video time needs normalization onto each plot's domain.
    const progress = bounds.usesVideos
      ? ((t - bounds.start) / denom)
      : null;
    plot.updateCursors(
      cursorValue,
      progress,
      activeAxis && activeAxis.explicit ? activeAxis.key : ""
    );
  }


  function getCommonEndTime(videos) {
    const count = getCommonVideoFrameCount(videos);
    if (count !== null) {
      return timeForFrameOrdinal(Math.max(0, count - 1), videos);
    }
    let minDuration = Infinity;
    for (const v of videos) {
      const d = Number(v && v.duration);
      if (Number.isFinite(d) && d > 0) {
        minDuration = Math.min(minDuration, d);
      }
    }
    if (!Number.isFinite(minDuration)) {
      return null;
    }
    return Math.max(0, minDuration - 0.04);
  }

  function clampTimeForVideos(rawTime, videos) {
    return clampTimeForMedia(rawTime, videos || [], getGridPlots());
  }

  function getReferenceTime(videos) {
    for (const v of videos) {
      const t = Number(v && v.currentTime);
      if (Number.isFinite(t) && t >= 0) {
        return t;
      }
    }
    return 0;
  }

  function inferFrameStepSeconds(videos, plots) {
    if (videos && videos.length) {
      const fps = inferFpsForVideos(videos);
      return 1.0 / fps;
    }
    const bounds = getMediaTimelineBounds(videos || [], plots || getGridPlots());
    const range = Math.max(1e-12, bounds.end - bounds.start);
    return range / 200.0;
  }

  function setAllVideoTimes(videos, rawTime) {
    const t = clampTimeForVideos(rawTime, videos);
    for (const v of videos) {
      try {
        v.currentTime = t;
      } catch (_err) {
        // Ignore seek errors for unloaded videos.
      }
    }
    gridVcrState.syncTime = t;
    updatePlotCursors(t, videos);
    return t;
  }

  function pauseAllVideos(videos) {
    for (const v of videos) {
      try {
        v.pause();
      } catch (_err) {
        // Ignore pause errors.
      }
    }
  }

  function playAllVideos(videos) {
    for (const v of videos) {
      try {
        const p = v.play();
        if (p && typeof p.catch === "function") {
          p.catch(function() {});
        }
      } catch (_err) {
        // Ignore autoplay failures per stream.
      }
    }
  }

  function applyPhysicalTimelineTime(rawTime, sequences, videos, plots) {
    sequences = sequences || getGridImageSequences();
    videos = videos || getGridVideos();
    plots = plots || getGridPlots();
    const t = clampTimeForMedia(rawTime, videos, plots);
    if (sequences.length) {
      setImageSequencesForTime(t, sequences);
    }
    if (videos.length) {
      setAllVideoTimes(videos, t);
    } else {
      gridVcrState.syncTime = t;
      updatePlotCursors(t, videos);
    }
    gridVcrState.syncTime = t;

    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length) {
      gridVcrState.timelinePosition = timelineIndexNearest(t, timeline);
    }
    updateVcrTimeLabelFromSeconds(t, videos, plots);
    return t;
  }

  function stepPhysicalTimelineBy(frameCount, sequences, videos, plots) {
    sequences = sequences || getGridImageSequences();
    videos = videos || getGridVideos();
    plots = plots || getGridPlots();
    const timeline = getPhysicalTimeline(sequences, plots);
    if (!timeline.length) return null;
    const base = Number.isFinite(gridVcrState.syncTime)
      ? gridVcrState.syncTime
      : (sequences.length ? getReferenceImageSequenceTime(sequences) : timeline[0]);
    const nextIndex = Math.max(
      0,
      Math.min(timelineIndexNearest(base, timeline) + Number(frameCount || 0), timeline.length - 1)
    );
    return applyPhysicalTimelineTime(timeline[nextIndex], sequences, videos, plots);
  }

  function stopSyncTimer() {
    if (gridVcrState.syncTimer) {
      clearInterval(gridVcrState.syncTimer);
      gridVcrState.syncTimer = null;
    }
  }

  function syncGridVideosNow() {
    if (!gridVcrState.playing) {
      stopSyncTimer();
      const sequencesNow = getGridImageSequences();
      const videosNow = getGridVideos();
      const plotsNow = getGridPlots();
      if (sequencesNow.length) {
        const timelineNow = getPhysicalTimeline(sequencesNow, plotsNow);
        if (timelineNow.length) {
          const target = Number.isFinite(gridVcrState.syncTime)
            ? gridVcrState.syncTime
            : getReferenceImageSequenceTime(sequencesNow);
          applyPhysicalTimelineTime(target, sequencesNow, videosNow, plotsNow);
        } else {
          updateVcrTimeLabelFromSeconds(getReferenceImageSequenceFrame(sequencesNow), videosNow, plotsNow);
        }
      } else if (videosNow.length) {
        updateVcrTimeLabelFromSeconds(getReferenceTime(videosNow), videosNow);
      } else if (plotsNow.length) {
        updateVcrTimeLabelFromSeconds(gridVcrState.syncTime, [], plotsNow);
      } else {
        updateVcrTimeLabelFromSeconds(0, []);
      }
      return;
    }

    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (sequences.length) {
      const timeline = getPhysicalTimeline(sequences, plots);
      if (timeline.length) {
        const now = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
        const last = Number(gridVcrState.lastTickMs);
        const dt = Number.isFinite(last) && last > 0 ? Math.max(0, (now - last) / 1000.0) : 0.16;
        gridVcrState.lastTickMs = now;
        const fps = inferFpsForImageSequences(sequences);
        let position = Number(gridVcrState.timelinePosition);
        if (!Number.isFinite(position)) {
          position = timelineIndexNearest(gridVcrState.syncTime, timeline);
        }
        const nextPosition = Math.min(Math.max(0, timeline.length - 1), position + dt * fps);
        const nextIndex = Math.max(0, Math.min(Math.floor(nextPosition + 1e-9), timeline.length - 1));
        const nextTime = timeline[nextIndex];
        setImageSequencesForTime(nextTime, sequences);
        gridVcrState.timelinePosition = nextPosition;
        gridVcrState.syncTime = nextTime;
        updateVcrTimeLabelFromSeconds(nextTime, videos, plots);
        notifyAxisSelectionChanged();
        if (nextPosition >= Math.max(0, timeline.length - 1)) {
          setGridVcrPlaying(false);
          stopSyncTimer();
        }
        return;
      }

      const count = getCommonImageSequenceFrameCount(sequences);
      if (count === null || count <= 0) {
        setGridVcrPlaying(false);
        stopSyncTimer();
        updateVcrTimeLabelFromSeconds(0, videos, plots);
        return;
      }

      const now = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      const last = Number(gridVcrState.lastTickMs);
      const dt = Number.isFinite(last) && last > 0 ? Math.max(0, (now - last) / 1000.0) : 0.16;
      gridVcrState.lastTickMs = now;
      const fps = inferFpsForImageSequences(sequences);
      const nextPosition = Math.min(Math.max(0, count - 1), Number(gridVcrState.syncTime || 0) + dt * fps);
      setImageSequenceFrame(Math.floor(nextPosition + 1e-9), sequences);
      gridVcrState.syncTime = nextPosition;
      updateVcrTimeLabelFromSeconds(nextPosition, videos, plots);
      if (nextPosition >= Math.max(0, count - 1)) {
        setGridVcrPlaying(false);
        stopSyncTimer();
      }
      return;
    }

    if (!videos.length) {
      if (!plots.length) {
        setGridVcrPlaying(false);
        stopSyncTimer();
        updateVcrTimeLabelFromSeconds(0, []);
        return;
      }

      const activeAxis = getActiveSelectionAxis([], plots);
      const timeline = getPhysicalTimeline([], plots);
      if (activeAxis && activeAxis.explicit && timeline.length) {
        const now = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
        const last = Number(gridVcrState.lastTickMs);
        const dt = Number.isFinite(last) && last > 0 ? Math.max(0, (now - last) / 1000.0) : 0.16;
        gridVcrState.lastTickMs = now;
        let position = Number(gridVcrState.timelinePosition);
        if (!Number.isFinite(position)) {
          position = timelineIndexNearest(gridVcrState.syncTime, timeline);
        }
        const nextPosition = Math.min(
          Math.max(0, timeline.length - 1),
          position + dt * inferFpsForImageSequences([])
        );
        const nextIndex = Math.max(
          0,
          Math.min(Math.floor(nextPosition + 1e-9), timeline.length - 1)
        );
        const nextValue = timeline[nextIndex];
        gridVcrState.timelinePosition = nextPosition;
        gridVcrState.syncTime = nextValue;
        updateVcrTimeLabelFromSeconds(nextValue, [], plots);
        notifyAxisSelectionChanged();
        if (nextPosition >= Math.max(0, timeline.length - 1)) {
          setGridVcrPlaying(false);
          stopSyncTimer();
        }
        return;
      }

      const now = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      const last = Number(gridVcrState.lastTickMs);
      const dt = Number.isFinite(last) && last > 0 ? Math.max(0, (now - last) / 1000.0) : 0.16;
      gridVcrState.lastTickMs = now;
      const bounds = getMediaTimelineBounds([], plots);
      const rate = Math.max(1e-12, bounds.end - bounds.start) / 8.0;
      const next = clampTimeForMedia(gridVcrState.syncTime + dt * rate, [], plots);
      gridVcrState.syncTime = next;
      updateVcrTimeLabelFromSeconds(next, [], plots);
      notifyAxisSelectionChanged();
      if (next >= (bounds.end - 1e-9)) {
        setGridVcrPlaying(false);
        stopSyncTimer();
      }
      return;
    }

    const ref = videos[0];
    const refTime = clampTimeForVideos(ref && ref.currentTime, videos);
    const commonEnd = getCommonEndTime(videos);
    if (commonEnd !== null && refTime >= (commonEnd - 0.02)) {
      pauseAllVideos(videos);
      const stopAt = setAllVideoTimes(videos, commonEnd);
      gridVcrState.syncTime = stopAt;
      setGridVcrPlaying(false);
      stopSyncTimer();
      updateVcrTimeLabelFromSeconds(stopAt, videos);
      return;
    }

    gridVcrState.syncTime = refTime;
    updateVcrTimeLabelFromSeconds(refTime, videos);
    for (let i = 1; i < videos.length; i += 1) {
      const v = videos[i];
      const t = Number(v && v.currentTime);
      if (!Number.isFinite(t)) {
        continue;
      }
      if (Math.abs(t - refTime) > 0.12) {
        try {
          v.currentTime = refTime;
        } catch (_err) {
          // Ignore seek errors for unloaded streams.
        }
      }
    }
  }

  function startSyncTimer() {
    stopSyncTimer();
    gridVcrState.syncTimer = setInterval(syncGridVideosNow, 160);
  }

  function currentVcrSliderTarget(videos, plots) {
    const slider = gridRuntimeElementById("seurat-vcr-step-slider");
    if (slider) {
      const target = getVcrSliderTimeValue(videos || [], plots || []);
      if (Number.isFinite(target)) return target;
    }
    const stateTime = Number(gridVcrState.syncTime);
    if (Number.isFinite(stateTime)) return stateTime;
    const windowTime = Number(gridVcrState.syncTime);
    return Number.isFinite(windowTime) ? windowTime : 0;
  }

  function syncGridMediaToCurrentVcrTime() {
    // The playback timer already re-queries and synchronizes all grid media.
    // Resyncing from the slider during playback discards fractional progress
    // whenever Vue updates an observed media attribute between timer ticks.
    if (gridVcrState.playing) return;

    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }

    const target = currentVcrSliderTarget(videos, plots);
    if (sequences.length) {
      if (getPhysicalTimeline(sequences, plots).length) {
        applyPhysicalTimelineTime(target, sequences, videos, plots);
      } else {
        const frame = setImageSequenceFrame(target, sequences);
        gridVcrState.syncTime = frame;
        gridVcrState.timelinePosition = frame;
        updateVcrTimeLabelFromSeconds(frame, videos, plots);
      }
      return;
    }
    if (videos.length) {
      const t = setAllVideoTimes(videos, target);
      gridVcrState.syncTime = t;
      updateVcrTimeLabelFromSeconds(t, videos, plots);
      if (gridVcrState.playing) {
        playAllVideos(videos);
      } else {
        pauseAllVideos(videos);
      }
      return;
    }

    const t = clampTimeForMedia(target, [], plots);
    gridVcrState.syncTime = t;
    updateVcrTimeLabelFromSeconds(t, [], plots);
  }

  function scheduleGridMediaSyncToCurrentVcrTime() {
    if (gridMediaSyncTimer) {
      clearTimeout(gridMediaSyncTimer);
    }
    gridMediaSyncTimer = setTimeout(function() {
      gridMediaSyncTimer = null;
      syncGridMediaToCurrentVcrTime();
    }, 30);
  }

  function mutationTouchesGridMedia(mutation) {
    if (!mutation) return false;
    if (mutation.type === "attributes") {
      const target = mutation.target;
      return !!(
        target
        && target.matches
        && (
          target.matches('img[data-grid-image-sequence="1"]')
          || target.matches('video[data-grid-video="1"]')
          || target.matches(".seurat-plot1d")
          || target.matches(".seurat-dropcell")
        )
      );
    }
    for (const node of Array.from(mutation.addedNodes || [])) {
      if (!node || node.nodeType !== 1) continue;
      if (
        (node.matches && (
          node.matches('img[data-grid-image-sequence="1"]')
          || node.matches('video[data-grid-video="1"]')
          || node.matches(".seurat-plot1d")
          || node.matches(".seurat-dropcell")
        ))
        || (node.querySelector && node.querySelector(
          'img[data-grid-image-sequence="1"], video[data-grid-video="1"], .seurat-plot1d, .seurat-dropcell'
        ))
      ) {
        return true;
      }
    }
    return false;
  }

  function seekAllVideosBy(deltaSeconds) {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }
    if (sequences.length) {
      const timeline = getPhysicalTimeline(sequences, plots);
      if (timeline.length) {
        const step = Number(deltaSeconds || 0) >= 0 ? 1 : -1;
        stepPhysicalTimelineBy(step, sequences, videos, plots);
        return;
      }
      const next = setImageSequenceFrame(
        getReferenceImageSequenceFrame(sequences) + Number(deltaSeconds || 0),
        sequences
      );
      gridVcrState.syncTime = next;
      gridVcrState.timelinePosition = next;
      updateVcrTimeLabelFromSeconds(next, videos, plots);
      return;
    }
    const base = clampTimeForMedia(
      Number.isFinite(gridVcrState.syncTime) ? gridVcrState.syncTime : getReferenceTime(videos),
      videos,
      plots
    );
    const next = setAllVideoTimes(videos, base + deltaSeconds);
    gridVcrState.syncTime = next;
    updateVcrTimeLabelFromSeconds(next, videos, plots);
    if (gridVcrState.playing) {
      if (videos.length) playAllVideos(videos);
      gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      startSyncTimer();
    } else {
      pauseAllVideos(videos);
    }
  }

  function stepAllVideosByFrames(frameCount) {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) return;
    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length && !videos.length) {
      stepPhysicalTimelineBy(frameCount, sequences, videos, plots);
      if (!gridVcrState.playing) pauseAllVideos(videos);
      return;
    }
    if (sequences.length) {
      const next = setImageSequenceFrame(
        getReferenceImageSequenceFrame(sequences) + Number(frameCount || 0),
        sequences
      );
      gridVcrState.syncTime = next;
      gridVcrState.timelinePosition = next;
      updateVcrTimeLabelFromSeconds(next, videos, plots);
      if (!gridVcrState.playing) pauseAllVideos(videos);
      return;
    }
    if (videos.length) {
      const count = getCommonVideoFrameCount(videos);
      if (count !== null) {
        const baseTime = clampTimeForMedia(
          Number.isFinite(gridVcrState.syncTime) ? gridVcrState.syncTime : getReferenceTime(videos),
          videos,
          plots
        );
        const baseOrdinal = frameOrdinalFromTime(baseTime, videos);
        const nextOrdinal = Math.max(
          0,
          Math.min(baseOrdinal + Number(frameCount || 0), Math.max(0, count - 1))
        );
        const next = setAllVideoTimes(videos, timeForFrameOrdinal(nextOrdinal, videos));
        gridVcrState.syncTime = next;
        updateVcrTimeLabelFromSeconds(next, videos, plots);
        if (gridVcrState.playing) {
          playAllVideos(videos);
          gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
          startSyncTimer();
        } else {
          pauseAllVideos(videos);
        }
        return;
      }
    }
    const frameStep = inferFrameStepSeconds(videos, plots);
    seekAllVideosBy(frameStep * Number(frameCount || 0));
  }

  function seekAllVideosToSlider() {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }
    const targetSeconds = getVcrSliderTimeValue(videos, plots);
    if (sequences.length) {
      if (getPhysicalTimeline(sequences, plots).length) {
        applyPhysicalTimelineTime(targetSeconds, sequences, videos, plots);
      } else {
        const frame = setImageSequenceFrame(targetSeconds, sequences);
        gridVcrState.syncTime = frame;
        gridVcrState.timelinePosition = frame;
        updateVcrTimeLabelFromSeconds(frame, videos, plots);
      }
      return;
    }
    const t = setAllVideoTimes(videos, targetSeconds);
    gridVcrState.syncTime = t;
    updateVcrTimeLabelFromSeconds(t, videos, plots);
    if (gridVcrState.playing) {
      if (videos.length) playAllVideos(videos);
      gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      startSyncTimer();
    } else {
      pauseAllVideos(videos);
    }
  }

  function setAllToStart() {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }
    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length && !videos.length) {
      applyPhysicalTimelineTime(timeline[0], sequences, videos, plots);
      return;
    }
    if (sequences.length) {
      const frame = setImageSequenceFrame(0, sequences);
      gridVcrState.syncTime = frame;
      gridVcrState.timelinePosition = frame;
      updateVcrTimeLabelFromSeconds(frame, videos, plots);
      return;
    }
    const bounds = getMediaTimelineBounds(videos, plots);
    const t = setAllVideoTimes(videos, bounds.start);
    gridVcrState.syncTime = t;
    updateVcrTimeLabelFromSeconds(t, videos, plots);
    if (gridVcrState.playing) {
      if (videos.length) playAllVideos(videos);
      gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      startSyncTimer();
    } else {
      pauseAllVideos(videos);
    }
  }

  function setAllToEnd() {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }
    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length && !videos.length) {
      applyPhysicalTimelineTime(timeline[timeline.length - 1], sequences, videos, plots);
      return;
    }
    if (sequences.length) {
      const count = getCommonImageSequenceFrameCount(sequences);
      const frame = setImageSequenceFrame(count !== null ? Math.max(0, count - 1) : 0, sequences);
      gridVcrState.syncTime = frame;
      gridVcrState.timelinePosition = frame;
      updateVcrTimeLabelFromSeconds(frame, videos, plots);
      return;
    }
    const bounds = getMediaTimelineBounds(videos, plots);
    const target = bounds.end;
    const t = setAllVideoTimes(videos, target);
    gridVcrState.syncTime = t;
    updateVcrTimeLabelFromSeconds(t, videos, plots);
    if (gridVcrState.playing) {
      if (videos.length) playAllVideos(videos);
      gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      startSyncTimer();
    } else {
      pauseAllVideos(videos);
    }
  }

  function playAllFromSyncTime() {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }
    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length && !videos.length) {
      const base = Number.isFinite(gridVcrState.syncTime)
        ? clampTimeForMedia(gridVcrState.syncTime, videos, plots)
        : timeline[0];
      applyPhysicalTimelineTime(base, sequences, videos, plots);
      gridVcrState.timelinePosition = timelineIndexNearest(base, timeline);
      setGridVcrPlaying(true);
      gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      startSyncTimer();
      return;
    }
    if (sequences.length) {
      const frame = setImageSequenceFrame(
        Number.isFinite(gridVcrState.syncTime) ? gridVcrState.syncTime : getReferenceImageSequenceFrame(sequences),
        sequences
      );
      gridVcrState.syncTime = frame;
      gridVcrState.timelinePosition = frame;
      updateVcrTimeLabelFromSeconds(frame, videos, plots);
      setGridVcrPlaying(true);
      gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
      startSyncTimer();
      return;
    }
    const base = setAllVideoTimes(
      videos,
      Number.isFinite(gridVcrState.syncTime) ? gridVcrState.syncTime : getReferenceTime(videos)
    );
    gridVcrState.syncTime = base;
    updateVcrTimeLabelFromSeconds(base, videos, plots);
    setGridVcrPlaying(true);
    gridVcrState.lastTickMs = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
    if (videos.length) playAllVideos(videos);
    startSyncTimer();
  }

  function pauseAllAtCurrentTime() {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }
    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length && !videos.length) {
      gridVcrState.syncTime = clampTimeForMedia(gridVcrState.syncTime, videos, plots);
      gridVcrState.timelinePosition = timelineIndexNearest(gridVcrState.syncTime, timeline);
      setImageSequencesForTime(gridVcrState.syncTime, sequences);
    } else {
      gridVcrState.syncTime = sequences.length
        ? getReferenceImageSequenceFrame(sequences)
        : clampTimeForMedia(videos.length ? getReferenceTime(videos) : gridVcrState.syncTime, videos, plots);
      gridVcrState.timelinePosition = gridVcrState.syncTime;
    }
    setGridVcrPlaying(false);
    stopSyncTimer();
    pauseAllVideos(videos);
    updateVcrTimeLabelFromSeconds(gridVcrState.syncTime, videos, plots);
  }

  function stopAllVideos() {
    const sequences = getGridImageSequences();
    const videos = getGridVideos();
    const plots = getGridPlots();
    if (!sequences.length && !videos.length && !plots.length) {
      updateVcrTimeLabelFromSeconds(0, []);
      return;
    }
    setGridVcrPlaying(false);
    stopSyncTimer();
    pauseAllVideos(videos);
    const timeline = getPhysicalTimeline(sequences, plots);
    if (timeline.length && !videos.length) {
      applyPhysicalTimelineTime(timeline[0], sequences, videos, plots);
      return;
    }
    if (sequences.length) {
      gridVcrState.syncTime = setImageSequenceFrame(0, sequences);
      gridVcrState.timelinePosition = gridVcrState.syncTime;
      updateVcrTimeLabelFromSeconds(gridVcrState.syncTime, videos, plots);
      return;
    }
    const bounds = getMediaTimelineBounds(videos, plots);
    gridVcrState.syncTime = setAllVideoTimes(videos, bounds.start);
    updateVcrTimeLabelFromSeconds(gridVcrState.syncTime, videos, plots);
  }

  function runGridVcrAction(action) {
    const a = String(action || "").trim().toLowerCase();
    if (!a) return;
    if (a === "start") {
      setAllToStart();
      return;
    }
    if (a === "frameback") {
      stepAllVideosByFrames(-1);
      return;
    }
    if (a === "frame") {
      stepAllVideosByFrames(1);
      return;
    }
    if (a === "slider") {
      seekAllVideosToSlider();
      return;
    }
    if (a === "back") {
      stepAllVideosByFrames(-1);
      return;
    }
    if (a === "toggle") {
      if (gridVcrState.playing) pauseAllAtCurrentTime();
      else playAllFromSyncTime();
      return;
    }
    if (a === "play") {
      playAllFromSyncTime();
      return;
    }
    if (a === "pause") {
      pauseAllAtCurrentTime();
      return;
    }
    if (a === "stop") {
      stopAllVideos();
      return;
    }
    if (a === "forward") {
      stepAllVideosByFrames(1);
      return;
    }
    if (a === "end") {
      setAllToEnd();
    }
  }

  function onGridRuntimeSlider(e) {
    const target = e && e.target;
    if (target && target.id === "seurat-vcr-step-slider") {
      if (notifyingAxisSelection) return;
      gridVcrState.lastNotifiedAxisIndex = Math.round(Number(target.value) || 0);
      runGridVcrAction("slider");
    }
  }

  function onGridRuntimeClick(e) {
    const target = e && e.target;
    const button = target && target.closest ? target.closest("[data-vcr-action]") : null;
    if (!button || !runtimeRoot || !runtimeRoot.contains(button)) return;
    e.preventDefault();
    runGridVcrAction(button.getAttribute("data-vcr-action") || "");
    notifyAxisSelectionChanged();
  }

  function onGridVideoLoadedMetadata(e) {
    const target = e && e.target;
    if (!isGridVideo(target)) return;
    const videos = getGridVideos();
    if (!videos.length) return;
    const t = setAllVideoTimes(videos, gridVcrState.syncTime);
    gridVcrState.syncTime = t;
    updateVcrTimeLabelFromSeconds(t, videos);
    if (gridVcrState.playing) {
      playAllVideos(videos);
      startSyncTimer();
    }
  }

  function onGridVideoEnded(e) {
    const target = e && e.target;
    if (!isGridVideo(target) || !gridVcrState.playing) return;
    const videos = getGridVideos();
    if (!videos.length) return;
    setGridVcrPlaying(false);
    stopSyncTimer();
    pauseAllVideos(videos);
    const endTime = getCommonEndTime(videos);
    const t = setAllVideoTimes(
      videos,
      endTime !== null ? endTime : getReferenceTime(videos)
    );
    gridVcrState.syncTime = t;
    updateVcrTimeLabelFromSeconds(t, videos);
  }

  function plotRuntime() {
    const seurat = window.seurat || {};
    const runtimes = seurat.runtimes || {};
    const runtime = runtimes.plot || window.seuratPlotRuntime;
    return runtime &&
      typeof runtime.getPlots === "function" &&
      typeof runtime.collectTimelineValues === "function" &&
      typeof runtime.getTimelineBounds === "function" &&
      typeof runtime.updateCursors === "function"
      ? runtime
      : null;
  }

  function refreshPlotCursors() {
    updatePlotCursors(gridVcrState.syncTime || 0, getGridVideos());
  }

  function unmountTimelineRuntime(root) {
    if (!root || root !== runtimeRoot) return;
    root.removeEventListener("input", onGridRuntimeSlider, true);
    root.removeEventListener("change", onGridRuntimeSlider, true);
    root.removeEventListener("click", onGridRuntimeClick);
    root.removeEventListener("loadedmetadata", onGridVideoLoadedMetadata, true);
    root.removeEventListener("ended", onGridVideoEnded, true);
    if (gridMediaObserver) {
      gridMediaObserver.disconnect();
      gridMediaObserver = null;
    }
    if (gridMediaSyncTimer) {
      clearTimeout(gridMediaSyncTimer);
      gridMediaSyncTimer = null;
    }
    stopSyncTimer();
    root.removeAttribute("data-seurat-timeline-runtime-owner");
    runtimeRoot = null;
  }

  function mountTimelineRuntime(root) {
    if (!root || root === runtimeRoot) return;
    if (runtimeRoot) unmountTimelineRuntime(runtimeRoot);
    runtimeRoot = root;
    root.setAttribute("data-seurat-timeline-runtime-owner", "mounted");
    updateGridVcrToggleButton();
    root.addEventListener("input", onGridRuntimeSlider, true);
    root.addEventListener("change", onGridRuntimeSlider, true);
    root.addEventListener("click", onGridRuntimeClick);
    root.addEventListener("loadedmetadata", onGridVideoLoadedMetadata, true);
    root.addEventListener("ended", onGridVideoEnded, true);
    gridMediaObserver = new MutationObserver(function(mutations) {
      if ((mutations || []).some(mutationTouchesGridMedia)) {
        scheduleGridMediaSyncToCurrentVcrTime();
      }
    });
    gridMediaObserver.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-frame-count", "data-frame-indices", "data-frame-sources", "data-time-values", "data-time-mode", "data-plot", "data-plot-settings", "data-plot-axis-key", "data-selection-axis", "data-cell-active", "data-timeline-driver"],
    });
    scheduleGridMediaSyncToCurrentVcrTime();
  }

  const seurat = window.seurat = window.seurat || {};
  const runtimes = seurat.runtimes = seurat.runtimes || {};
  const runtime = runtimes.timeline || {};
  runtime.mount = mountTimelineRuntime;
  runtime.unmount = unmountTimelineRuntime;
  runtime.runAction = runGridVcrAction;
  runtime.refreshPlotCursors = refreshPlotCursors;
  runtime.scheduleMediaSync = scheduleGridMediaSyncToCurrentVcrTime;
  runtimes.timeline = runtime;
  window.seuratTimelineRuntime = runtime;
})();
