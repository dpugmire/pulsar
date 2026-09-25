(function registerPulsarCanvasLayout() {
  const COLUMNS = 24;
  const ROW_HEIGHT = 24;
  const DEAD_ZONE = 0.55;
  const MINIMUMS = {
    field: [2, 3],
    plot: [2, 3],
    kpi: [4, 3],
    stats: [5, 4],
  };

  function number(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function tileType(value) {
    const kind = String(value || "plot").toLowerCase();
    return MINIMUMS[kind] ? kind : "plot";
  }

  function minimumSize(kind) {
    return MINIMUMS[tileType(kind)].slice();
  }

  function copy(item) {
    return {
      tile_id: String(item.tile_id || ""),
      tile_type: tileType(item.tile_type),
      x: number(item.x, 0),
      y: number(item.y, 0),
      w: number(item.w, 4),
      h: number(item.h, 3),
    };
  }

  function normalize(item, snap, columns) {
    const result = copy(item);
    const limit = number(columns, COLUMNS);
    const minimum = minimumSize(result.tile_type);
    const round = snap === false ? (value) => Math.round(value * 10000) / 10000 : Math.round;
    result.w = Math.min(limit, Math.max(minimum[0], round(result.w)));
    result.h = Math.max(minimum[1], round(result.h));
    result.x = Math.max(0, Math.min(round(result.x), limit - result.w));
    result.y = Math.max(0, round(result.y));
    return result;
  }

  function overlaps(first, second) {
    return (
      first.x < second.x + second.w &&
      first.x + first.w > second.x &&
      first.y < second.y + second.h &&
      first.y + first.h > second.y
    );
  }

  function verticallyOverlaps(first, second) {
    return first.y < second.y + second.h && first.y + first.h > second.y;
  }

  function stickySnap(value, current, deadZone) {
    if (current === null || current === undefined) return Math.round(value);
    if (Math.abs(value - current) < number(deadZone, DEAD_ZONE)) {
      return Math.round(current);
    }
    return Math.round(value);
  }

  function fitRectangle(anchorX, anchorY, desiredW, desiredH, others, columns) {
    const limit = number(columns, COLUMNS);
    let best = { x: anchorX, y: anchorY, w: 0, h: 0 };
    let bestArea = -1;
    let runningWidth = Infinity;
    for (let height = 1; height <= desiredH; height += 1) {
      const row = anchorY + height - 1;
      let freeWidth = Math.min(desiredW, limit - anchorX);
      for (const other of others) {
        if (other.y <= row && row < other.y + other.h) {
          if (other.x <= anchorX && anchorX < other.x + other.w) freeWidth = 0;
          else if (other.x > anchorX) freeWidth = Math.min(freeWidth, other.x - anchorX);
        }
      }
      runningWidth = Math.min(runningWidth, Math.max(0, freeWidth));
      const area = height * runningWidth;
      if (runningWidth > 0 && (area > bestArea || (area === bestArea && height > best.h))) {
        best = { x: anchorX, y: anchorY, w: runningWidth, h: height };
        bestArea = area;
      }
    }
    return best;
  }

  function nearestFree(target, others, columns, radiusLimit) {
    const base = copy(target);
    const limit = number(columns, COLUMNS);
    const maximumRadius = number(radiusLimit, 120);
    const fits = (x, y) => {
      const candidate = Object.assign({}, base, { x, y });
      return x >= 0 && y >= 0 && x + candidate.w <= limit && !others.some((item) => overlaps(candidate, item));
    };
    const startX = Math.round(base.x);
    const startY = Math.round(base.y);
    if (fits(startX, startY)) return Object.assign({}, base, { x: startX, y: startY });
    for (let radius = 1; radius <= maximumRadius; radius += 1) {
      for (let dy = -radius; dy <= radius; dy += 1) {
        for (let dx = -radius; dx <= radius; dx += 1) {
          if (Math.abs(dx) + Math.abs(dy) !== radius) continue;
          if (fits(startX + dx, startY + dy)) {
            return Object.assign({}, base, { x: startX + dx, y: startY + dy });
          }
        }
      }
    }
    return base;
  }

  function verticalPush(items, priorityId) {
    const result = items.map(copy);
    const priority = result.find((item) => item.tile_id === priorityId);
    if (!priority) return result;
    const placed = [priority];
    const rest = result
      .filter((item) => item !== priority)
      .sort((a, b) => a.y - b.y || a.x - b.x);
    for (const item of rest) {
      let guard = 0;
      while (guard < 1000) {
        const collisions = placed.filter((other) => overlaps(item, other));
        if (!collisions.length) break;
        item.y = Math.max(...collisions.map((other) => other.y + other.h));
        guard += 1;
      }
      placed.push(item);
    }
    const order = new Map(items.map((item, index) => [String(item.tile_id), index]));
    return result.sort((a, b) => order.get(a.tile_id) - order.get(b.tile_id));
  }

  function horizontalResizePush(items, priorityId, originalRight, columns) {
    const source = items.map(copy);
    const priority = source.find((item) => item.tile_id === priorityId);
    if (!priority) return source;
    const limit = number(columns, COLUMNS);
    const originalWidth = Math.max(
      minimumSize(priority.tile_type)[0],
      number(originalRight, priority.x + priority.w) - priority.x
    );
    let targetWidth = Math.max(originalWidth, priority.w);
    const order = new Map(items.map((item, index) => [String(item.tile_id), index]));

    const resolve = (width) => {
      const result = source.map(copy);
      const resized = result.find((item) => item.tile_id === priorityId);
      resized.w = width;
      const placed = [resized];
      const movable = result
        .filter((item) => item !== resized && item.x >= originalRight)
        .sort((a, b) => a.x - b.x || a.y - b.y);
      for (const item of movable) {
        let guard = 0;
        while (guard < movable.length + 1) {
          const collisions = placed.filter(
            (other) => verticallyOverlaps(item, other) && overlaps(item, other)
          );
          if (!collisions.length) break;
          const nextX = Math.max(item.x, ...collisions.map((other) => other.x + other.w));
          if (nextX <= item.x + 1e-9) break;
          item.x = nextX;
          guard += 1;
        }
        placed.push(item);
      }
      const overflow = Math.max(
        0,
        ...movable.map((item) => item.x + item.w - limit)
      );
      return {
        items: result.sort((a, b) => order.get(a.tile_id) - order.get(b.tile_id)),
        overflow,
      };
    };

    let resolved = { items: source, overflow: 0 };
    for (let attempt = 0; attempt < 4; attempt += 1) {
      resolved = resolve(targetWidth);
      if (resolved.overflow <= 1e-9) return resolved.items;
      const adjustedWidth = Math.max(originalWidth, targetWidth - resolved.overflow);
      if (adjustedWidth >= targetWidth - 1e-9) break;
      targetWidth = adjustedWidth;
    }
    return resolve(originalWidth).items;
  }

  function hasFarSideTile(items, draggedId, orientation, seam, tile) {
    if (orientation === "row") {
      return items.some((item) => item.tile_id !== draggedId && item.y === seam && item.x < tile.x + tile.w && item.x + item.w > tile.x);
    }
    return items.some((item) => item.tile_id !== draggedId && item.x === seam && item.y < tile.y + tile.h && item.y + item.h > tile.y);
  }

  function insertionZone(items, draggedId, pointerX, pointerY, options) {
    const epsilon = 1e-9;
    const xTolerance = Math.max(0, number(options && options.xTolerance, 0));
    const yTolerance = Math.max(0, number(options && options.yTolerance, 0));
    const others = items.filter((item) => item.tile_id !== draggedId);
    const shared = [];

    for (const left of others) {
      const seam = left.x + left.w;
      for (const right of others) {
        if (left === right || Math.abs(seam - right.x) > epsilon) continue;
        const overlapStart = Math.max(left.y, right.y);
        const overlapEnd = Math.min(left.y + left.h, right.y + right.h);
        const distance = Math.abs(pointerX - seam);
        if (
          overlapEnd - overlapStart > epsilon &&
          distance <= xTolerance + epsilon &&
          pointerY >= overlapStart - epsilon &&
          pointerY <= overlapEnd + epsilon
        ) {
          shared.push({
            distance: distance / Math.max(xTolerance, epsilon),
            priority: 0,
            zone: {
              orientation: "column",
              seam,
              anchor_x: right.x,
              anchor_y: right.y,
              edge: "shared",
            },
          });
        }
      }
    }

    for (const top of others) {
      const seam = top.y + top.h;
      for (const bottom of others) {
        if (top === bottom || Math.abs(seam - bottom.y) > epsilon) continue;
        const overlapStart = Math.max(top.x, bottom.x);
        const overlapEnd = Math.min(top.x + top.w, bottom.x + bottom.w);
        const distance = Math.abs(pointerY - seam);
        if (
          overlapEnd - overlapStart > epsilon &&
          distance <= yTolerance + epsilon &&
          pointerX >= overlapStart - epsilon &&
          pointerX <= overlapEnd + epsilon
        ) {
          shared.push({
            distance: distance / Math.max(yTolerance, epsilon),
            priority: 1,
            zone: {
              orientation: "row",
              seam,
              anchor_x: bottom.x,
              anchor_y: bottom.y,
              edge: "shared",
            },
          });
        }
      }
    }

    if (shared.length) {
      shared.sort((a, b) => a.distance - b.distance || a.priority - b.priority);
      return shared[0].zone;
    }

    for (const tile of items) {
      if (tile.tile_id === draggedId) continue;
      if (pointerX < tile.x || pointerX >= tile.x + tile.w || pointerY < tile.y || pointerY >= tile.y + tile.h) continue;
      const fractions = [
        { edge: "left", value: (pointerX - tile.x) / tile.w },
        { edge: "right", value: (tile.x + tile.w - pointerX) / tile.w },
        { edge: "top", value: (pointerY - tile.y) / tile.h },
        { edge: "bottom", value: (tile.y + tile.h - pointerY) / tile.h },
      ].sort((a, b) => a.value - b.value);
      const edge = fractions[0].edge;
      if (edge === "top") return { orientation: "row", seam: tile.y, anchor_x: tile.x, anchor_y: tile.y, edge };
      if (edge === "bottom") {
        const seam = tile.y + tile.h;
        return hasFarSideTile(items, draggedId, "row", seam, tile)
          ? { orientation: "row", seam, anchor_x: tile.x, anchor_y: tile.y, edge }
          : null;
      }
      if (edge === "left") return { orientation: "column", seam: tile.x, anchor_x: tile.x, anchor_y: tile.y, edge };
      const seam = tile.x + tile.w;
      return hasFarSideTile(items, draggedId, "column", seam, tile)
        ? { orientation: "column", seam, anchor_x: tile.x, anchor_y: tile.y, edge }
        : null;
    }
    return null;
  }

  function connectedColumnMoveSet(items, seam, anchorY, height, excludedId) {
    const candidates = items.filter((item) => item.tile_id !== excludedId && item.x >= seam);
    const moved = candidates.filter((item) => item.y < anchorY + height && item.y + item.h > anchorY);
    const ids = new Set(moved.map((item) => item.tile_id));
    let changed = true;
    while (changed) {
      changed = false;
      for (const candidate of candidates) {
        if (ids.has(candidate.tile_id)) continue;
        if (moved.some((member) => verticallyOverlaps(candidate, member) && candidate.x >= member.x)) {
          moved.push(candidate);
          ids.add(candidate.tile_id);
          changed = true;
        }
      }
    }
    return moved.map((item) => item.tile_id);
  }

  function columnInsertionSize(dragged, moveItems, seam, columns) {
    const limit = number(columns, COLUMNS);
    const maxRight = moveItems.length ? Math.max(...moveItems.map((item) => item.x + item.w)) : seam;
    if (limit - maxRight >= dragged.w) return { w: dragged.w, h: dragged.h, mode: "push" };
    if (!moveItems.length) return null;
    const remaining = limit - seam;
    const minimumScale = Math.max(...moveItems.map((item) => minimumSize(item.tile_type)[0] / item.w));
    const widthCap = Math.floor(remaining * (1 - minimumScale));
    const minimum = minimumSize(dragged.tile_type);
    if (widthCap < minimum[0]) return null;
    const width = Math.min(dragged.w, widthCap);
    const height = width < dragged.w ? Math.max(minimum[1], Math.round((dragged.h * width) / dragged.w)) : dragged.h;
    return { w: width, h: height, mode: "shrink" };
  }

  function applyColumnInsertion(items, options) {
    const result = items.map(copy);
    const dragged = result.find((item) => item.tile_id === options.draggedId);
    if (!dragged) return result;
    Object.assign(dragged, { x: options.seam, y: options.anchorY, w: options.width, h: options.height });
    const selected = new Set(options.moveIds || []);
    if (options.mode === "shrink") {
      const remaining = number(options.columns, COLUMNS) - options.seam;
      const scale = (remaining - options.width) / remaining;
      const transform = (value) => options.seam + options.width + (value - options.seam) * scale;
      for (const item of result) {
        if (!selected.has(item.tile_id)) continue;
        const newX = Math.round(transform(item.x));
        const newRight = Math.round(transform(item.x + item.w));
        item.x = newX;
        item.w = Math.max(minimumSize(item.tile_type)[0], newRight - newX);
      }
    } else {
      for (const item of result) if (selected.has(item.tile_id)) item.x += options.width;
    }
    return verticalPush(result, options.draggedId);
  }

  window.pulsarCanvasLayout = {
    COLUMNS,
    ROW_HEIGHT,
    DEAD_ZONE,
    minimumSize,
    normalize,
    overlaps,
    stickySnap,
    fitRectangle,
    nearestFree,
    verticalPush,
    horizontalResizePush,
    insertionZone,
    connectedColumnMoveSet,
    columnInsertionSize,
    applyColumnInsertion,
  };
})();
