(function initPulsarPlotRuntime() {
  "use strict";

  let runtimeRoot = null;
  let onCursorRefresh = null;

  function runtimeWindow() {
    const ownerDocument = runtimeRoot && runtimeRoot.ownerDocument;
    return ownerDocument && ownerDocument.defaultView
      ? ownerDocument.defaultView
      : window;
  }

  function runtimeBody() {
    const ownerDocument = runtimeRoot && runtimeRoot.ownerDocument;
    return ownerDocument ? ownerDocument.body : document.body;
  }

  function runtimeDocument() {
    return runtimeRoot && runtimeRoot.ownerDocument
      ? runtimeRoot.ownerDocument
      : document;
  }

  function requestCursorRefresh() {
    if (onCursorRefresh) onCursorRefresh();
  }

  function getGridPlots() {
    return runtimeRoot && runtimeRoot.querySelectorAll
      ? Array.from(runtimeRoot.querySelectorAll(".pulsar-plot1d"))
      : [];
  }

  function finiteNumber(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function createSvgNode(name) {
    return runtimeDocument().createElementNS("http://www.w3.org/2000/svg", name);
  }

  function trimPlotNumberText(text) {
    let out = String(text || "");
    if ((out.indexOf("e") >= 0) || (out.indexOf("E") >= 0)) return out;
    while ((out.indexOf(".") >= 0) && out.endsWith("0")) {
      out = out.slice(0, -1);
    }
    if (out.endsWith(".")) out = out.slice(0, -1);
    return out;
  }

  function formatPlotTick(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "";
    const abs = Math.abs(n);
    if ((abs >= 10000) || (abs > 0 && abs < 0.001)) return n.toExponential(2);
    const text = n.toPrecision(3);
    return trimPlotNumberText(text);
  }

  function formatPlotHoverValue(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "";
    const abs = Math.abs(n);
    const text = ((abs >= 10000) || (abs > 0 && abs < 0.001))
      ? n.toExponential(4)
      : n.toPrecision(6);
    return trimPlotNumberText(text);
  }

  function parsePlotData(el) {
    if (!el) return {};
    const raw = el.getAttribute("data-plot") || "{}";
    if (el.__pulsarPlotRaw === raw && el.__pulsarPlotData) {
      return el.__pulsarPlotData;
    }
    if (el.__pulsarPlotRaw !== undefined && el.__pulsarPlotRaw !== raw) {
      el.__pulsarPlotViewState = null;
      el.__pulsarPlotRenderKey = "";
    }
    try {
      el.__pulsarPlotData = JSON.parse(raw);
      el.__pulsarPlotRaw = raw;
    } catch (_err) {
      el.__pulsarPlotData = {};
      el.__pulsarPlotRaw = raw;
    }
    return el.__pulsarPlotData || {};
  }

  function parsePlotSettings(el) {
    if (!el) return {};
    const raw = el.getAttribute("data-plot-settings") || "{}";
    if (el.__pulsarPlotSettingsRaw === raw && el.__pulsarPlotSettings) {
      return el.__pulsarPlotSettings;
    }
    try {
      el.__pulsarPlotSettings = JSON.parse(raw);
      el.__pulsarPlotSettingsRaw = raw;
    } catch (_err) {
      el.__pulsarPlotSettings = {};
      el.__pulsarPlotSettingsRaw = raw;
    }
    return el.__pulsarPlotSettings || {};
  }

  function plotSeriesKey(item, index) {
    const sourceKey = String((item && item.source_key) || "").trim();
    if (sourceKey) return sourceKey;
    const sourceLabel = String((item && item.source_label) || "").trim();
    return sourceLabel || ("series:" + index);
  }

  function normalizeLineStyle(value) {
    const style = String(value || "solid").toLowerCase().replace("_", "-");
    return ["solid", "dash", "dot", "dash-dot"].includes(style) ? style : "solid";
  }

  function lineStyleDashArray(value, lineWidth) {
    const style = normalizeLineStyle(value);
    const width = Math.max(0.5, finiteNumber(lineWidth, 2.5));
    if (style === "dash") return String(4 * width) + " " + String(2.5 * width);
    if (style === "dot") return String(0.8 * width) + " " + String(2 * width);
    if (style === "dash-dot") return String(4 * width) + " " + String(2 * width) + " " + String(0.8 * width) + " " + String(2 * width);
    return "";
  }

  function normalizePlotSettings(raw) {
    raw = raw || {};
    const xScale = String(raw.x_scale || "linear").toLowerCase() === "log" ? "log" : "linear";
    const yScale = String(raw.y_scale || "linear").toLowerCase() === "log" ? "log" : "linear";
    const lineWidth = Math.max(0.5, Math.min(8, finiteNumber(raw.line_width, 2.5)));
    return {
      x_auto: raw.x_auto !== false,
      x_min: finiteNumber(raw.x_min, NaN),
      x_max: finiteNumber(raw.x_max, NaN),
      x_scale: xScale,
      y_auto: raw.y_auto !== false,
      y_min: finiteNumber(raw.y_min, NaN),
      y_max: finiteNumber(raw.y_max, NaN),
      y_scale: yScale,
      series_colors: (raw.series_colors && typeof raw.series_colors === "object") ? raw.series_colors : {},
      series_styles: (raw.series_styles && typeof raw.series_styles === "object") ? raw.series_styles : {},
      line_width: lineWidth,
      show_grid: raw.show_grid !== false,
      show_cursor: raw.show_cursor !== false,
      background_color: String(raw.background_color || "#ffffff"),
      grid_color: String(raw.grid_color || "#e8e8e8"),
      cursor_color: String(raw.cursor_color || "#111111"),
    };
  }

  function positivePlotBounds(series, axisName) {
    const field = axisName === "x" ? "x" : "y";
    let minValue = Infinity;
    let maxValue = -Infinity;
    for (const item of (series || [])) {
      const values = Array.isArray(item && item[field]) ? item[field] : [];
      for (const rawValue of values) {
        const value = Number(rawValue);
        if (Number.isFinite(value) && value > 0) {
          minValue = Math.min(minValue, value);
          maxValue = Math.max(maxValue, value);
        }
      }
    }
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) return null;
    return { min: minValue, max: maxValue };
  }

  function resolvePlotAxis(plot, series, settings, axisName) {
    const autoKey = axisName + "_auto";
    const minKey = axisName + "_min";
    const maxKey = axisName + "_max";
    const scaleKey = axisName + "_scale";
    const scale = settings[scaleKey] === "log" ? "log" : "linear";
    const autoRange = settings[autoKey] !== false;
    let minValue = autoRange
      ? finiteNumber(plot[minKey], axisName === "x" ? 0 : 0)
      : finiteNumber(settings[minKey], NaN);
    let maxValue = autoRange
      ? finiteNumber(plot[maxKey], axisName === "x" ? 1 : 1)
      : finiteNumber(settings[maxKey], NaN);

    if (scale === "log") {
      const positiveBounds = positivePlotBounds(series, axisName);
      if (autoRange && positiveBounds) {
        const logMin = Math.log10(positiveBounds.min);
        const logMax = Math.log10(positiveBounds.max);
        if (Math.abs(logMax - logMin) <= 1e-12) {
          minValue = Math.pow(10, logMin - 0.5);
          maxValue = Math.pow(10, logMax + 0.5);
        } else {
          const pad = (logMax - logMin) * 0.04;
          minValue = Math.pow(10, logMin - pad);
          maxValue = Math.pow(10, logMax + pad);
        }
      }
      if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || minValue <= 0 || maxValue <= 0 || minValue >= maxValue) {
        if (positiveBounds) {
          minValue = positiveBounds.min;
          maxValue = positiveBounds.max;
        } else {
          minValue = 1;
          maxValue = 10;
        }
      }
      let tMin = Math.log10(minValue);
      let tMax = Math.log10(maxValue);
      if (Math.abs(tMax - tMin) <= 1e-12) {
        tMin -= 0.5;
        tMax += 0.5;
        minValue = Math.pow(10, tMin);
        maxValue = Math.pow(10, tMax);
      }
      return {
        min: minValue,
        max: maxValue,
        tMin,
        tMax,
        scale,
        transform: function(value) {
          const n = Number(value);
          return Number.isFinite(n) && n > 0 ? Math.log10(n) : NaN;
        },
        inverse: function(value) {
          return Math.pow(10, value);
        },
      };
    }

    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
      minValue = axisName === "x" ? 0 : 0;
      maxValue = axisName === "x" ? 1 : 1;
    }
    if (Math.abs(maxValue - minValue) <= 1e-12) {
      minValue -= 0.5;
      maxValue += 0.5;
    }
    return {
      min: minValue,
      max: maxValue,
      tMin: minValue,
      tMax: maxValue,
      scale,
      transform: function(value) {
        const n = Number(value);
        return Number.isFinite(n) ? n : NaN;
      },
      inverse: function(value) {
        return value;
      },
    };
  }

  function plotViewRenderKey(el) {
    const state = el && el.__pulsarPlotViewState;
    if (!state) return "view:default";
    const values = [
      state.xScale,
      state.yScale,
      state.xMin,
      state.xMax,
      state.yMin,
      state.yMax,
    ];
    return "view:" + values.map(function(value) {
      const n = Number(value);
      return Number.isFinite(n) ? n.toPrecision(16) : String(value || "");
    }).join(",");
  }

  function plotAxisFromRange(axis, minValue, maxValue) {
    if (!axis) return null;
    let min = Number(minValue);
    let max = Number(maxValue);
    if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) return null;

    if (axis.scale === "log") {
      if (min <= 0 || max <= 0) return null;
      let tMin = Math.log10(min);
      let tMax = Math.log10(max);
      if (!Number.isFinite(tMin) || !Number.isFinite(tMax) || tMin >= tMax) return null;
      if (Math.abs(tMax - tMin) <= 1e-12) {
        const center = (tMin + tMax) * 0.5;
        tMin = center - 0.5;
        tMax = center + 0.5;
        min = Math.pow(10, tMin);
        max = Math.pow(10, tMax);
      }
      return {
        min,
        max,
        tMin,
        tMax,
        scale: "log",
        transform: axis.transform,
        inverse: axis.inverse,
      };
    }

    if (Math.abs(max - min) <= 1e-12) {
      const center = (min + max) * 0.5;
      min = center - 0.5;
      max = center + 0.5;
    }
    return {
      min,
      max,
      tMin: min,
      tMax: max,
      scale: "linear",
      transform: axis.transform,
      inverse: axis.inverse,
    };
  }

  function plotAxisFromTransformRange(axis, tMin, tMax) {
    if (!axis) return null;
    let nextTMin = Number(tMin);
    let nextTMax = Number(tMax);
    if (!Number.isFinite(nextTMin) || !Number.isFinite(nextTMax) || nextTMin >= nextTMax) return null;
    const span = nextTMax - nextTMin;
    if (span <= 1e-12) {
      const center = (nextTMin + nextTMax) * 0.5;
      nextTMin = center - 0.5;
      nextTMax = center + 0.5;
    }
    return plotAxisFromRange(axis, axis.inverse(nextTMin), axis.inverse(nextTMax));
  }

  function plotViewStateForAxes(el, xAxis, yAxis) {
    const state = el && el.__pulsarPlotViewState;
    if (!state) return null;
    if (state.xScale !== xAxis.scale || state.yScale !== yAxis.scale) {
      el.__pulsarPlotViewState = null;
      return null;
    }
    const viewXAxis = plotAxisFromRange(xAxis, state.xMin, state.xMax);
    const viewYAxis = plotAxisFromRange(yAxis, state.yMin, state.yMax);
    if (!viewXAxis || !viewYAxis) {
      el.__pulsarPlotViewState = null;
      return null;
    }
    return { xAxis: viewXAxis, yAxis: viewYAxis };
  }

  function setPlotViewStateFromAxes(el, xAxis, yAxis) {
    if (!el || !xAxis || !yAxis) return;
    el.__pulsarPlotViewState = {
      xScale: xAxis.scale,
      yScale: yAxis.scale,
      xMin: xAxis.min,
      xMax: xAxis.max,
      yMin: yAxis.min,
      yMax: yAxis.max,
    };
    el.__pulsarPlotRenderKey = "";
  }

  function rerenderPlotView(el) {
    if (!el) return;
    renderPlot1d(el);
    requestCursorRefresh();
  }

  function resetPlotView(el) {
    if (!el) return;
    el.__pulsarPlotViewState = null;
    el.__pulsarPlotRenderKey = "";
    renderPlot1d(el);
    requestCursorRefresh();
  }

  function resetPlotViewForCellIndex(cellIndex) {
    const idx = Number(cellIndex);
    if (!Number.isInteger(idx) || idx < 0) return;
    if (!runtimeRoot) return;
    const cell = runtimeRoot.querySelector(
      '.pulsar-dropcell[data-cell-index="' + String(idx) + '"]'
    );
    if (!cell) return;
    const plots = cell.querySelectorAll ? cell.querySelectorAll(".pulsar-plot1d") : [];
    for (const el of plots) {
      resetPlotView(el);
    }
  }
  function plotLocalPoint(el, event) {
    const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : { left: 0, top: 0 };
    return {
      x: (Number(event && event.clientX) || 0) - rect.left,
      y: (Number(event && event.clientY) || 0) - rect.top,
    };
  }

  function clampPlotLocalPoint(meta, point) {
    const left = meta.pad.left;
    const right = meta.pad.left + meta.plotW;
    const top = meta.pad.top;
    const bottom = meta.pad.top + meta.plotH;
    return {
      x: Math.max(left, Math.min(right, Number(point && point.x) || left)),
      y: Math.max(top, Math.min(bottom, Number(point && point.y) || top)),
    };
  }

  function plotAxisTForLocalPoint(axis, meta, point, axisName) {
    const safePoint = clampPlotLocalPoint(meta, point);
    const span = axis.tMax - axis.tMin;
    if (axisName === "y") {
      const fracY = (safePoint.y - meta.pad.top) / Math.max(1, meta.plotH);
      return axis.tMax - fracY * span;
    }
    const fracX = (safePoint.x - meta.pad.left) / Math.max(1, meta.plotW);
    return axis.tMin + fracX * span;
  }

  function zoomPlotAxisAround(axis, centerT, rangeFactor) {
    const factor = Math.max(0.02, Math.min(50, Number(rangeFactor) || 1));
    const nextTMin = centerT - (centerT - axis.tMin) * factor;
    const nextTMax = centerT + (axis.tMax - centerT) * factor;
    return plotAxisFromTransformRange(axis, nextTMin, nextTMax);
  }

  function zoomPlotViewAt(el, event, rangeFactor) {
    if (!el) return;
    renderPlot1d(el);
    const meta = el.__pulsarPlotMeta;
    if (!meta || !meta.xAxis || !meta.yAxis) return;
    const point = plotLocalPoint(el, event);
    const centerX = plotAxisTForLocalPoint(meta.xAxis, meta, point, "x");
    const centerY = plotAxisTForLocalPoint(meta.yAxis, meta, point, "y");
    const nextXAxis = zoomPlotAxisAround(meta.xAxis, centerX, rangeFactor);
    const nextYAxis = zoomPlotAxisAround(meta.yAxis, centerY, rangeFactor);
    if (!nextXAxis || !nextYAxis) return;
    setPlotViewStateFromAxes(el, nextXAxis, nextYAxis);
    rerenderPlotView(el);
  }

  function renderPlot1d(el) {
    const plot = parsePlotData(el);
    const settings = normalizePlotSettings(parsePlotSettings(el));
    const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : { width: 0, height: 0 };
    const width = Math.max(1, Math.round(rect.width || el.clientWidth || 300));
    const height = Math.max(1, Math.round(rect.height || el.clientHeight || 300));
    const renderKey = String(el.__pulsarPlotRaw || "") + "|" + String(el.__pulsarPlotSettingsRaw || "") + "|" + width + "x" + height + "|" + plotViewRenderKey(el);
    if (el.__pulsarPlotRenderKey === renderKey && el.querySelector("svg")) {
      return;
    }

    el.__pulsarPlotRenderKey = renderKey;
    el.innerHTML = "";
    const svg = createSvgNode("svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.style.display = "block";
    svg.style.background = "#ffffff";
    el.appendChild(svg);

    const series = Array.isArray(plot.series) ? plot.series : [];
    if (!series.length) {
      const text = createSvgNode("text");
      text.setAttribute("x", String(width / 2));
      text.setAttribute("y", String(height / 2));
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("font-size", "12");
      text.setAttribute("fill", "#666666");
      text.textContent = "No plot data";
      svg.appendChild(text);
      return;
    }

    const compact = width < 280 || height < 170;
    const showXAxisLabel = height >= 90;
    const tickFontSize = compact ? 10 : 12;
    const axisLabelFontSize = compact ? 11 : 13;
    const pad = {
      left: compact ? Math.max(30, Math.min(44, Math.round(width * 0.2))) : 52,
      right: compact ? 8 : 14,
      top: compact ? 7 : 12,
      bottom: showXAxisLabel
        ? (compact ? Math.max(28, Math.min(36, Math.round(height * 0.25))) : 40)
        : Math.max(16, Math.min(24, Math.round(height * 0.24))),
    };
    const plotW = Math.max(1, width - pad.left - pad.right);
    const plotH = Math.max(1, height - pad.top - pad.bottom);
    const tickCount = Math.max(
      2,
      Math.min(5, Math.floor(Math.min(width / 65, height / 38)))
    );
    const xTickOffset = Math.max(
      10,
      Math.min(20, pad.bottom - (showXAxisLabel ? 14 : 4))
    );
    let xAxis = resolvePlotAxis(plot, series, settings, "x");
    let yAxis = resolvePlotAxis(plot, series, settings, "y");
    const defaultXAxis = xAxis;
    const defaultYAxis = yAxis;
    const viewAxes = plotViewStateForAxes(el, xAxis, yAxis);
    if (viewAxes) {
      xAxis = viewAxes.xAxis;
      yAxis = viewAxes.yAxis;
    }
    const dataXMin = finiteNumber(plot.data_x_min, xAxis.min);
    const dataXMax = finiteNumber(plot.data_x_max, xAxis.max);

    function sx(value) {
      const tv = xAxis.transform(value);
      if (!Number.isFinite(tv)) return NaN;
      return pad.left + ((tv - xAxis.tMin) / (xAxis.tMax - xAxis.tMin)) * plotW;
    }
    function sy(value) {
      const tv = yAxis.transform(value);
      if (!Number.isFinite(tv)) return NaN;
      return pad.top + plotH - ((tv - yAxis.tMin) / (yAxis.tMax - yAxis.tMin)) * plotH;
    }

    const frame = createSvgNode("rect");
    frame.setAttribute("x", String(pad.left));
    frame.setAttribute("y", String(pad.top));
    frame.setAttribute("width", String(plotW));
    frame.setAttribute("height", String(plotH));
    frame.setAttribute("fill", settings.background_color || "#ffffff");
    frame.setAttribute("stroke", "#3f3f3f");
    frame.setAttribute("stroke-width", "1");
    svg.appendChild(frame);

    for (let i = 0; i < tickCount; i += 1) {
      const frac = i / (tickCount - 1);
      const gx = pad.left + frac * plotW;
      const gy = pad.top + frac * plotH;
      if (settings.show_grid) {
        const gridV = createSvgNode("line");
        gridV.setAttribute("x1", String(gx));
        gridV.setAttribute("x2", String(gx));
        gridV.setAttribute("y1", String(pad.top));
        gridV.setAttribute("y2", String(pad.top + plotH));
        gridV.setAttribute("stroke", settings.grid_color || "#e8e8e8");
        svg.appendChild(gridV);

        const gridH = createSvgNode("line");
        gridH.setAttribute("x1", String(pad.left));
        gridH.setAttribute("x2", String(pad.left + plotW));
        gridH.setAttribute("y1", String(gy));
        gridH.setAttribute("y2", String(gy));
        gridH.setAttribute("stroke", settings.grid_color || "#e8e8e8");
        svg.appendChild(gridH);
      }

      const xTick = createSvgNode("text");
      xTick.setAttribute("x", String(gx));
      xTick.setAttribute("y", String(pad.top + plotH + xTickOffset));
      xTick.setAttribute("text-anchor", "middle");
      xTick.setAttribute("font-size", String(tickFontSize));
      xTick.setAttribute("fill", "#333333");
      xTick.textContent = formatPlotTick(xAxis.inverse(xAxis.tMin + frac * (xAxis.tMax - xAxis.tMin)));
      svg.appendChild(xTick);

      const yTick = createSvgNode("text");
      yTick.setAttribute("x", String(pad.left - 8));
      yTick.setAttribute("y", String(gy + 4));
      yTick.setAttribute("text-anchor", "end");
      yTick.setAttribute("font-size", String(tickFontSize));
      yTick.setAttribute("fill", "#333333");
      yTick.textContent = formatPlotTick(yAxis.inverse(yAxis.tMax - frac * (yAxis.tMax - yAxis.tMin)));
      svg.appendChild(yTick);
    }

    const hoverSeries = [];
    for (let i = 0; i < series.length; i += 1) {
      const item = series[i] || {};
      const xs = Array.isArray(item.x) ? item.x : [];
      const ys = Array.isArray(item.y) ? item.y : [];
      const n = Math.min(xs.length, ys.length);
      let d = "";
      let moveNext = true;
      const seriesKey = plotSeriesKey(item, i);
      const seriesStyle = (settings.series_styles && settings.series_styles[seriesKey]) || {};
      const lineStyle = normalizeLineStyle(seriesStyle.line_style || "solid");
      const color = String(seriesStyle.color || settings.series_colors[seriesKey] || item.color || "#1565c0");
      const sourceLabel = String(item.source_label || item.source_key || ("Series " + (i + 1))).trim();
      const pointLabelRanges = (Array.isArray(item.point_label_ranges) ? item.point_label_ranges : [])
        .map(function(value) {
          return {
            start: Number(value && value.start),
            end: Number(value && value.end),
            label: String((value && value.label) || "").trim(),
          };
        })
        .filter(function(value) {
          return Number.isInteger(value.start) && Number.isInteger(value.end)
            && value.start >= 0 && value.end > value.start && value.label;
        })
        .sort(function(a, b) { return a.start - b.start; });
      const breaks = new Set(
        (Array.isArray(item.breaks) ? item.breaks : [])
          .map(function(value) { return Number(value); })
          .filter(function(value) { return Number.isInteger(value) && value > 0; })
      );
      const points = [];
      let pointLabelRangeIndex = 0;
      for (let j = 0; j < n; j += 1) {
        while (
          pointLabelRangeIndex + 1 < pointLabelRanges.length
          && pointLabelRanges[pointLabelRangeIndex + 1].start <= j
        ) {
          pointLabelRangeIndex += 1;
        }
        const pointLabelRange = pointLabelRanges[pointLabelRangeIndex];
        const pointLabel = pointLabelRange
          && pointLabelRange.start <= j
          && j < pointLabelRange.end
          ? pointLabelRange.label
          : "";
        if (breaks.has(j)) {
          moveNext = true;
        }
        const xv = Number(xs[j]);
        const yv = Number(ys[j]);
        if (!Number.isFinite(xv) || !Number.isFinite(yv)) {
          moveNext = true;
          continue;
        }
        const px = sx(xv);
        const py = sy(yv);
        if (!Number.isFinite(px) || !Number.isFinite(py)) {
          moveNext = true;
          continue;
        }
        points.push({
          x: xv,
          y: yv,
          px,
          py,
          sourceLabel,
          pointLabel,
          color,
        });
        d += (moveNext ? " M " : " L ") + px.toFixed(2) + " " + py.toFixed(2);
        moveNext = false;
      }
      if (!d) continue;
      const path = createSvgNode("path");
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", color);
      path.setAttribute("stroke-width", String(settings.line_width));
      const dashArray = lineStyleDashArray(lineStyle, settings.line_width);
      if (dashArray) {
        path.setAttribute("stroke-dasharray", dashArray);
      }
      path.setAttribute("stroke-linejoin", "round");
      path.setAttribute("stroke-linecap", "round");
      svg.appendChild(path);
      points.sort(function(a, b) { return a.px - b.px; });
      hoverSeries.push({ points, sourceLabel, color });
    }

    let cursor = null;
    if (settings.show_cursor) {
      cursor = createSvgNode("line");
      cursor.setAttribute("class", "pulsar-plot1d-cursor-line");
      cursor.setAttribute("x1", String(pad.left));
      cursor.setAttribute("x2", String(pad.left));
      cursor.setAttribute("y1", String(pad.top));
      cursor.setAttribute("y2", String(pad.top + plotH));
      cursor.setAttribute("stroke", settings.cursor_color || "#111111");
      cursor.setAttribute("stroke-width", "2");
      cursor.setAttribute("opacity", "0.85");
      svg.appendChild(cursor);
    }

    const xLabel = String(plot.x_label || "");
    if (xLabel && showXAxisLabel) {
      const label = createSvgNode("text");
      label.setAttribute("x", String(pad.left + plotW / 2));
      label.setAttribute("y", String(height - 10));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("font-size", String(axisLabelFontSize));
      label.setAttribute("fill", "#333333");
      label.textContent = xLabel;
      svg.appendChild(label);
    }

    const hoverGroup = createSvgNode("g");
    hoverGroup.setAttribute("display", "none");
    hoverGroup.setAttribute("pointer-events", "none");

    const hoverLine = createSvgNode("line");
    hoverLine.setAttribute("y1", String(pad.top));
    hoverLine.setAttribute("y2", String(pad.top + plotH));
    hoverLine.setAttribute("stroke", "#4a4a4a");
    hoverLine.setAttribute("stroke-width", "1");
    hoverLine.setAttribute("stroke-dasharray", "3 3");
    hoverLine.setAttribute("opacity", "0.75");
    hoverGroup.appendChild(hoverLine);

    const hoverYLine = createSvgNode("line");
    hoverYLine.setAttribute("x1", String(pad.left));
    hoverYLine.setAttribute("x2", String(pad.left + plotW));
    hoverYLine.setAttribute("stroke", "#4a4a4a");
    hoverYLine.setAttribute("stroke-width", "1");
    hoverYLine.setAttribute("stroke-dasharray", "3 3");
    hoverYLine.setAttribute("opacity", "0.75");
    hoverGroup.appendChild(hoverYLine);

    const hoverPoint = createSvgNode("circle");
    hoverPoint.setAttribute("r", "4");
    hoverPoint.setAttribute("fill", "#ffffff");
    hoverPoint.setAttribute("stroke-width", "2");
    hoverGroup.appendChild(hoverPoint);
    svg.appendChild(hoverGroup);

    const hoverTip = runtimeDocument().createElement("div");
    hoverTip.className = "pulsar-plot-hover-tip";
    hoverTip.style.display = "none";
    el.appendChild(hoverTip);

    el.__pulsarPlotMeta = {
      xMin: xAxis.min,
      xMax: xAxis.max,
      yMin: yAxis.min,
      yMax: yAxis.max,
      dataXMin,
      dataXMax,
      xAxis,
      yAxis,
      defaultXAxis,
      defaultYAxis,
      sx,
      sy,
      pad,
      plotW,
      plotH,
      cursor,
      hoverSeries,
      hoverGroup,
      hoverLine,
      hoverYLine,
      hoverPoint,
      hoverTip,
    };
  }

  function renderAllPlot1d() {
    const plots = getGridPlots();
    for (const el of plots) {
      renderPlot1d(el);
    }
    return plots;
  }

  function getPlotTimelineBounds(plots) {
    let start = Infinity;
    let end = -Infinity;
    for (const el of (plots || [])) {
      const plot = parsePlotData(el);
      const xmin = finiteNumber(plot.data_x_min, finiteNumber(plot.x_min, NaN));
      const xmax = finiteNumber(plot.data_x_max, finiteNumber(plot.x_max, NaN));
      if (Number.isFinite(xmin)) start = Math.min(start, xmin);
      if (Number.isFinite(xmax)) end = Math.max(end, xmax);
    }
    if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
    if (Math.abs(end - start) <= 1e-12) end = start + 1;
    return { start, end };
  }
  function updatePlotCursors(rawTime, progress, activeAxisKey) {
    const plots = renderAllPlot1d();
    if (!plots.length) return;
    const t = Number.isFinite(Number(rawTime)) ? Number(rawTime) : 0;
    const progressValue = Number(progress);
    const normalizedProgress =
      progress === null ||
      progress === undefined ||
      !Number.isFinite(progressValue)
        ? null
        : Math.max(0, Math.min(1, progressValue));
    for (const el of plots) {
      const meta = el.__pulsarPlotMeta;
      if (!meta || !meta.cursor) continue;
      const plotAxisKey = String(el.getAttribute("data-plot-axis-key") || "");
      if (activeAxisKey && plotAxisKey !== String(activeAxisKey)) {
        meta.cursor.setAttribute("display", "none");
        continue;
      }
      const cursorValue = normalizedProgress === null
        ? t
        : meta.dataXMin + normalizedProgress * (meta.dataXMax - meta.dataXMin);
      const clampedValue = Math.max(meta.xMin, Math.min(meta.xMax, cursorValue));
      const px = meta.sx(clampedValue);
      if (!Number.isFinite(px)) {
        meta.cursor.setAttribute("display", "none");
        continue;
      }
      meta.cursor.removeAttribute("display");
      meta.cursor.setAttribute("x1", String(px));
      meta.cursor.setAttribute("x2", String(px));
    }
  }

  function hidePlotHover(el) {
    const meta = el && el.__pulsarPlotMeta;
    if (!meta) return;
    if (meta.hoverGroup) meta.hoverGroup.setAttribute("display", "none");
    if (meta.hoverTip) meta.hoverTip.style.display = "none";
  }

  function hideAllPlotHovers() {
    for (const el of getGridPlots()) {
      hidePlotHover(el);
    }
  }

  let plotViewDrag = null;
  let suppressPlotViewClick = false;
  let plotCtrlDown = false;
  let plotRenderTimer = null;
  let plotResizeObserver = null;
  let plotMutationObserver = null;
  let observedPlots = new Set();
  const PLOT_WHEEL_OPTIONS = { capture: true, passive: false };

  function nearestPointInSeries(points, x, y) {
    if (!points || !points.length) return null;
    let lo = 0;
    let hi = points.length;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (points[mid].px < x) lo = mid + 1;
      else hi = mid;
    }

    let best = null;
    const start = Math.max(0, lo - 4);
    const end = Math.min(points.length - 1, lo + 4);
    for (let i = start; i <= end; i += 1) {
      const p = points[i];
      const dx = p.px - x;
      const dy = p.py - y;
      const score = (dx * dx) + (dy * dy);
      if (!best || score < best.score) {
        best = { point: p, score };
      }
    }
    return best;
  }

  function nearestPlotHoverPoint(meta, x, y) {
    let best = null;
    for (const item of (meta.hoverSeries || [])) {
      const candidate = nearestPointInSeries(item.points || [], x, y);
      if (candidate && (!best || candidate.score < best.score)) {
        best = candidate;
      }
    }
    return best ? best.point : null;
  }

  function updatePlotHover(el, event) {
    if (!el || !event) return;
    renderPlot1d(el);
    const meta = el.__pulsarPlotMeta;
    const ctrlActive = !!(event.ctrlKey || plotCtrlDown) && !event.shiftKey;
    if (!meta || !meta.hoverGroup || !meta.hoverTip || !ctrlActive) {
      hidePlotHover(el);
      return;
    }

    const rect = el.getBoundingClientRect();
    const x = Number(event.clientX) - rect.left;
    const y = Number(event.clientY) - rect.top;
    const left = meta.pad.left;
    const right = meta.pad.left + meta.plotW;
    const top = meta.pad.top;
    const bottom = meta.pad.top + meta.plotH;
    if (!Number.isFinite(x) || !Number.isFinite(y) || x < left || x > right || y < top || y > bottom) {
      hidePlotHover(el);
      return;
    }

    const point = nearestPlotHoverPoint(meta, x, y);
    if (!point) {
      hidePlotHover(el);
      return;
    }

    meta.hoverLine.setAttribute("x1", String(point.px));
    meta.hoverLine.setAttribute("x2", String(point.px));
    if (meta.hoverYLine) {
      meta.hoverYLine.setAttribute("y1", String(point.py));
      meta.hoverYLine.setAttribute("y2", String(point.py));
    }
    meta.hoverPoint.setAttribute("cx", String(point.px));
    meta.hoverPoint.setAttribute("cy", String(point.py));
    meta.hoverPoint.setAttribute("stroke", point.color || "#1565c0");
    meta.hoverGroup.removeAttribute("display");

    const lines = [];
    if (point.pointLabel) {
      lines.push(point.pointLabel);
    } else if ((meta.hoverSeries || []).length > 1 && point.sourceLabel) {
      lines.push(point.sourceLabel);
    }
    lines.push("x: " + formatPlotHoverValue(point.x));
    lines.push("y: " + formatPlotHoverValue(point.y));
    meta.hoverTip.textContent = lines.join("\n");
    meta.hoverTip.style.display = "block";
    meta.hoverTip.style.left = "0px";
    meta.hoverTip.style.top = "0px";
    meta.hoverTip.style.borderColor = point.color || "#1565c0";

    const tipW = meta.hoverTip.offsetWidth || 90;
    const tipH = meta.hoverTip.offsetHeight || 42;
    let tipX = point.px + 8;
    let tipY = point.py - tipH - 8;
    if (tipX + tipW > rect.width - 4) tipX = point.px - tipW - 8;
    if (tipY < 4) tipY = point.py + 8;
    if (tipY + tipH > rect.height - 4) tipY = rect.height - tipH - 4;
    if (tipX < 4) tipX = 4;
    meta.hoverTip.style.left = String(Math.round(tipX)) + "px";
    meta.hoverTip.style.top = String(Math.round(tipY)) + "px";
  }

  function plotElementFromEvent(event) {
    const target = event && event.target;
    const plot = target && target.closest ? target.closest(".pulsar-plot1d") : null;
    return plot && runtimeRoot && runtimeRoot.contains(plot) ? plot : null;
  }

  function releasePlotPointerCapture(drag) {
    if (!drag || !drag.el || drag.pointerId === undefined) return;
    try {
      if (!drag.el.hasPointerCapture || drag.el.hasPointerCapture(drag.pointerId)) {
        drag.el.releasePointerCapture(drag.pointerId);
      }
    } catch (_) {
      // The pointer may already have been released by the browser.
    }
  }

  function beginPlotViewDrag(event, el, mode) {
    renderPlot1d(el);
    const meta = el.__pulsarPlotMeta;
    if (!meta || !meta.xAxis || !meta.yAxis) return;
    finishPlotViewDrag();
    const point = plotLocalPoint(el, event);
    plotViewDrag = {
      el,
      mode,
      startX: Number(event.clientX) || 0,
      startY: Number(event.clientY) || 0,
      pointerId: event.pointerId,
      moved: false,
      xAxis: meta.xAxis,
      yAxis: meta.yAxis,
      plotW: Math.max(1, meta.plotW),
      plotH: Math.max(1, meta.plotH),
      centerX: plotAxisTForLocalPoint(meta.xAxis, meta, point, "x"),
      centerY: plotAxisTForLocalPoint(meta.yAxis, meta, point, "y"),
    };
    el.classList.add(mode === "zoom" ? "is-zooming" : "is-panning");
    runtimeBody().classList.add(
      mode === "zoom" ? "pulsar-plot-zooming" : "pulsar-plot-panning"
    );
    hidePlotHover(el);
    try {
      el.setPointerCapture(event.pointerId);
    } catch (_) {
      // Pointer capture is best-effort for older browser implementations.
    }
    event.preventDefault();
    event.stopPropagation();
  }

  function updatePlotViewDrag(event) {
    if (!plotViewDrag) return;
    if (
      plotViewDrag.pointerId !== undefined &&
      event.pointerId !== plotViewDrag.pointerId
    ) {
      return;
    }
    const drag = plotViewDrag;
    const dx = (Number(event.clientX) || 0) - drag.startX;
    const dy = (Number(event.clientY) || 0) - drag.startY;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
      drag.moved = true;
    }

    let nextXAxis = null;
    let nextYAxis = null;
    if (drag.mode === "pan") {
      const xSpan = drag.xAxis.tMax - drag.xAxis.tMin;
      const ySpan = drag.yAxis.tMax - drag.yAxis.tMin;
      const nextXMin = drag.xAxis.tMin - (dx / drag.plotW) * xSpan;
      const nextXMax = drag.xAxis.tMax - (dx / drag.plotW) * xSpan;
      const nextYMin = drag.yAxis.tMin + (dy / drag.plotH) * ySpan;
      const nextYMax = drag.yAxis.tMax + (dy / drag.plotH) * ySpan;
      nextXAxis = plotAxisFromTransformRange(drag.xAxis, nextXMin, nextXMax);
      nextYAxis = plotAxisFromTransformRange(drag.yAxis, nextYMin, nextYMax);
    } else {
      const rangeFactor = Math.exp(dy * 0.01);
      nextXAxis = zoomPlotAxisAround(drag.xAxis, drag.centerX, rangeFactor);
      nextYAxis = zoomPlotAxisAround(drag.yAxis, drag.centerY, rangeFactor);
    }

    if (nextXAxis && nextYAxis) {
      setPlotViewStateFromAxes(drag.el, nextXAxis, nextYAxis);
      rerenderPlotView(drag.el);
    }
    event.preventDefault();
    event.stopPropagation();
  }

  function finishPlotViewDrag(event) {
    if (!plotViewDrag) return;
    const drag = plotViewDrag;
    plotViewDrag = null;
    drag.el.classList.remove("is-panning", "is-zooming");
    runtimeBody().classList.remove("pulsar-plot-panning", "pulsar-plot-zooming");
    suppressPlotViewClick = !!drag.moved;
    releasePlotPointerCapture(drag);
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onPlotKeyDown(event) {
    if (event && event.key === "Control") {
      plotCtrlDown = true;
    }
  }

  function onPlotKeyUp(event) {
    if (event && event.key === "Control") {
      plotCtrlDown = false;
      hideAllPlotHovers();
    }
  }

  function onPlotWindowBlur() {
    plotCtrlDown = false;
    hideAllPlotHovers();
    finishPlotViewDrag();
  }

  function onPlotPointerMove(event) {
    if (plotViewDrag) {
      updatePlotViewDrag(event);
      return;
    }
    const el = plotElementFromEvent(event);
    if (!el) return;
    const ctrlActive = !!(event.ctrlKey || plotCtrlDown) && !event.shiftKey;
    if (!ctrlActive) {
      hidePlotHover(el);
      return;
    }
    updatePlotHover(el, event);
  }

  function onPlotPointerDown(event) {
    const el = plotElementFromEvent(event);
    if (!el) return;
    const ctrlActive = !!(event.ctrlKey || plotCtrlDown);
    const isShiftPan = event.button === 0 && event.shiftKey && !ctrlActive;
    const isMiddleZoom = event.button === 1;
    if (isShiftPan || isMiddleZoom) {
      beginPlotViewDrag(event, el, isMiddleZoom ? "zoom" : "pan");
      return;
    }
    if (event.ctrlKey && event.button === 0) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onPlotPointerEnd(event) {
    if (
      plotViewDrag &&
      (plotViewDrag.pointerId === undefined ||
        event.pointerId === plotViewDrag.pointerId)
    ) {
      finishPlotViewDrag(event);
    }
  }

  function onPlotLostPointerCapture(event) {
    if (plotViewDrag && event.target === plotViewDrag.el) {
      finishPlotViewDrag();
    }
  }

  function onPlotWheel(event) {
    const el = plotElementFromEvent(event);
    if (!el) return;
    const rangeFactor = Math.exp((Number(event.deltaY) || 0) * 0.0015);
    zoomPlotViewAt(el, event, rangeFactor);
    hidePlotHover(el);
    event.preventDefault();
    event.stopPropagation();
  }

  function onPlotDoubleClick(event) {
    const el = plotElementFromEvent(event);
    if (!el) return;
    resetPlotView(el);
    event.preventDefault();
    event.stopPropagation();
  }

  function onPlotAuxClick(event) {
    const el = plotElementFromEvent(event);
    if (el && event.button === 1) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onPlotClick(event) {
    if (!suppressPlotViewClick) return;
    suppressPlotViewClick = false;
    const el = plotElementFromEvent(event);
    if (!el) return;
    event.preventDefault();
    event.stopPropagation();
  }

  function onPlotContextMenu(event) {
    const el = plotElementFromEvent(event);
    if (el && event.ctrlKey) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onPlotPointerOut(event) {
    const el = plotElementFromEvent(event);
    if (el && (!event.relatedTarget || !el.contains(event.relatedTarget))) {
      hidePlotHover(el);
    }
  }

  function scheduleRenderAllPlot1d() {
    if (!runtimeRoot) return;
    const ownerWindow = runtimeWindow();
    if (plotRenderTimer) return;
    plotRenderTimer = ownerWindow.setTimeout(function() {
      plotRenderTimer = null;
      if (!runtimeRoot) return;
      renderAllPlot1d();
      requestCursorRefresh();
    }, 30);
  }

  function observePlot1dSizes() {
    if (!plotResizeObserver) return;
    const currentPlots = new Set(getGridPlots());
    for (const el of observedPlots) {
      if (!currentPlots.has(el)) {
        plotResizeObserver.unobserve(el);
        observedPlots.delete(el);
      }
    }
    for (const el of currentPlots) {
      if (!observedPlots.has(el)) {
        plotResizeObserver.observe(el);
        observedPlots.add(el);
      }
    }
  }

  function mountPlotRuntime(root, options) {
    if (!root) return;
    if (root === runtimeRoot) {
      onCursorRefresh =
        options && typeof options.onCursorRefresh === "function"
          ? options.onCursorRefresh
          : null;
      return;
    }
    if (runtimeRoot) unmountPlotRuntime(runtimeRoot);

    runtimeRoot = root;
    onCursorRefresh =
      options && typeof options.onCursorRefresh === "function"
        ? options.onCursorRefresh
        : null;
    plotCtrlDown = false;
    suppressPlotViewClick = false;
    root.setAttribute("data-pulsar-plot-runtime-owner", "mounted");
    root.addEventListener("pointermove", onPlotPointerMove);
    root.addEventListener("pointerdown", onPlotPointerDown, true);
    root.addEventListener("pointerup", onPlotPointerEnd, true);
    root.addEventListener("pointercancel", onPlotPointerEnd, true);
    root.addEventListener("lostpointercapture", onPlotLostPointerCapture, true);
    root.addEventListener("wheel", onPlotWheel, PLOT_WHEEL_OPTIONS);
    root.addEventListener("dblclick", onPlotDoubleClick, true);
    root.addEventListener("auxclick", onPlotAuxClick, true);
    root.addEventListener("click", onPlotClick, true);
    root.addEventListener("contextmenu", onPlotContextMenu, true);
    root.addEventListener("pointerout", onPlotPointerOut);
    const ownerWindow = runtimeWindow();
    ownerWindow.addEventListener("keydown", onPlotKeyDown);
    ownerWindow.addEventListener("keyup", onPlotKeyUp);
    ownerWindow.addEventListener("blur", onPlotWindowBlur);
    ownerWindow.addEventListener("resize", scheduleRenderAllPlot1d);

    observedPlots = new Set();
    if (ownerWindow.ResizeObserver) {
      plotResizeObserver = new ownerWindow.ResizeObserver(scheduleRenderAllPlot1d);
    }
    plotMutationObserver = new ownerWindow.MutationObserver(function() {
      observePlot1dSizes();
      scheduleRenderAllPlot1d();
    });
    plotMutationObserver.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        "data-plot",
        "data-plot-settings",
        "data-canvas-w",
        "data-canvas-h",
        "data-canvas-revision",
        "data-layout-mode",
        "data-grid-sizing-mode",
        "data-grid-column-sizes",
        "data-grid-row-sizes",
        "data-grid-column-weights",
        "data-grid-row-weights",
      ],
    });
    observePlot1dSizes();
    scheduleRenderAllPlot1d();
  }

  function unmountPlotRuntime(root) {
    if (!root || root !== runtimeRoot) return;
    finishPlotViewDrag();
    suppressPlotViewClick = false;
    plotCtrlDown = false;
    root.removeEventListener("pointermove", onPlotPointerMove);
    root.removeEventListener("pointerdown", onPlotPointerDown, true);
    root.removeEventListener("pointerup", onPlotPointerEnd, true);
    root.removeEventListener("pointercancel", onPlotPointerEnd, true);
    root.removeEventListener("lostpointercapture", onPlotLostPointerCapture, true);
    root.removeEventListener("wheel", onPlotWheel, PLOT_WHEEL_OPTIONS);
    root.removeEventListener("dblclick", onPlotDoubleClick, true);
    root.removeEventListener("auxclick", onPlotAuxClick, true);
    root.removeEventListener("click", onPlotClick, true);
    root.removeEventListener("contextmenu", onPlotContextMenu, true);
    root.removeEventListener("pointerout", onPlotPointerOut);
    const ownerWindow = runtimeWindow();
    ownerWindow.removeEventListener("keydown", onPlotKeyDown);
    ownerWindow.removeEventListener("keyup", onPlotKeyUp);
    ownerWindow.removeEventListener("blur", onPlotWindowBlur);
    ownerWindow.removeEventListener("resize", scheduleRenderAllPlot1d);
    if (plotMutationObserver) {
      plotMutationObserver.disconnect();
      plotMutationObserver = null;
    }
    if (plotResizeObserver) {
      plotResizeObserver.disconnect();
      plotResizeObserver = null;
    }
    observedPlots.clear();
    if (plotRenderTimer) {
      ownerWindow.clearTimeout(plotRenderTimer);
      plotRenderTimer = null;
    }
    hideAllPlotHovers();
    runtimeBody().classList.remove("pulsar-plot-panning", "pulsar-plot-zooming");
    for (const el of root.querySelectorAll(
      ".pulsar-plot1d.is-panning, .pulsar-plot1d.is-zooming"
    )) {
      el.classList.remove("is-panning", "is-zooming");
    }
    root.removeAttribute("data-pulsar-plot-runtime-owner");
    onCursorRefresh = null;
    runtimeRoot = null;
  }

  function collectPlotTimeValues(plots) {
    const values = [];
    for (const el of (plots || [])) {
      const plot = parsePlotData(el);
      const xLabel = String(plot.x_label || "").trim().toLowerCase();
      if (xLabel && xLabel !== "time" && xLabel !== "physical time") continue;
      if (!xLabel) continue;
      const series = Array.isArray(plot.series) ? plot.series : [];
      for (const item of series) {
        const xs = Array.isArray(item && item.x) ? item.x : [];
        for (const raw of xs) {
          const value = Number(raw);
          if (Number.isFinite(value)) values.push(value);
        }
      }
    }
    return values;
  }

  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  const runtime = runtimes.plot || window.pulsarPlotRuntime || {};
  runtime.mount = mountPlotRuntime;
  runtime.unmount = unmountPlotRuntime;
  runtime.getPlots = getGridPlots;
  runtime.collectTimelineValues = collectPlotTimeValues;
  runtime.getTimelineBounds = getPlotTimelineBounds;
  runtime.renderAll = renderAllPlot1d;
  runtime.updateCursors = updatePlotCursors;
  runtime.resetViewForCellIndex = resetPlotViewForCellIndex;
  runtime.scheduleRender = scheduleRenderAllPlot1d;
  runtimes.plot = runtime;
  window.pulsarPlotRuntime = runtime;
})();
