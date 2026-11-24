// Run with: node --test tests/test_campaign_drag_runtime.js
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { runInNewContext } = require("node:vm");
const { test } = require("node:test");

const source = readFileSync(
  new URL("../pulsar/module/serve/pulsar-interaction-runtime.js", `file://${__filename}`),
  "utf8"
);

function element() {
  const attributes = new Map();
  const classes = new Set();
  return {
    style: { opacity: "" }, children: [], textContent: "Guide",
    classList: {
      add: (name) => classes.add(name), remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
    listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
    removeEventListener(name) { delete this.listeners[name]; },
    setAttribute(name, value) { attributes.set(name, value); },
    getAttribute: (name) => attributes.get(name) ?? null,
    removeAttribute: (name) => attributes.delete(name),
    appendChild(child) { this.children.push(child); child.parent = this; },
    remove() { this.parent.children = this.parent.children.filter((c) => c !== this); },
    closest: () => null,
    querySelector: () => null, querySelectorAll: () => [], contains: () => true,
    getBoundingClientRect: () => ({ width: 180, height: 54 }),
    setPointerCapture(id) { this.captured = id; },
    hasPointerCapture(id) { return this.captured === id; },
    releasePointerCapture() { this.captured = null; },
  };
}

function harness(native = false) {
  const root = element(), card = element(), cell = element(), body = element();
  card.closest = (selector) => selector === ".pulsar-draggable-campaign-visualization" ? card : null;
  card.setAttribute("data-visualization-id", "guide");
  card.setAttribute("data-preview-url", "/preview/guide");
  card.setAttribute("draggable", String(native));
  cell.closest = (selector) => selector === ".pulsar-dropcell" ? cell : null;
  cell.setAttribute("data-cell-index", "2");
  const triggers = [], timers = [];
  const window = Object.assign(element(), {
    innerWidth: 800, innerHeight: 600,
    requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    setTimeout: (callback) => timers.push(callback),
    trame: { trigger: (...args) => triggers.push(args) },
  });
  const document = { body, createElement: element, elementFromPoint: () => cell };
  runInNewContext(source, { window, document });
  const runtime = window.pulsarInteractionRuntime;
  runtime.mount(root);
  function send(target, type, values = {}) {
    const event = {
      type, target: card, button: 0, pointerId: 1, clientX: 790, clientY: 590,
      preventDefault() { this.prevented = true; },
      stopPropagation() {}, stopImmediatePropagation() {}, ...values,
    };
    target.listeners[type]?.(event);
    return event;
  }
  function start() {
    send(root, "pointerdown", { clientX: 10, clientY: 10 });
    send(root, "pointermove");
  }
  return { root, card, cell, body, window, triggers, timers, runtime, send, start };
}

test("pointer preview follows the drag, stays in the viewport, and drops once", () => {
  const h = harness();
  h.start();
  assert.equal(h.card.captured, 1);
  const preview = h.body.children[0];
  assert.equal(preview.style.left, "616px");
  assert.equal(preview.style.top, "542px");
  assert.equal(h.send(h.root, "selectstart").prevented, true);
  h.send(h.root, "pointerup");
  assert.equal(h.body.children.length, 0);
  assert.equal(h.card.captured, null);
  assert.equal(h.card.style.opacity, "");
  assert.equal(h.triggers.length, 1);
  assert.equal(h.triggers[0][0], "assign_campaign_visualization_to_grid_cell_trigger");
  assert.deepEqual(Array.from(h.triggers[0][1]), ["guide", "2"]);
  assert.equal(h.send(h.root, "click").prevented, true);
});

for (const reason of ["pointercancel", "lostpointercapture", "blur", "Escape", "unmount"]) {
  test(`${reason} cleans the drag without inserting a tile`, () => {
    const h = harness();
    h.start();
    if (reason === "unmount") h.runtime.unmount(h.root);
    else if (reason === "blur") h.send(h.window, "blur");
    else if (reason === "Escape") h.send(h.window, "keydown", { key: "Escape" });
    else h.send(h.root, reason);
    assert.equal(h.body.children.length, 0);
    assert.equal(h.card.captured, null);
    assert.equal(h.body.classList.contains("pulsar-campaign-visualization-dragging"), false);
    assert.equal(h.triggers.length, 0);
  });
}

test("failed thumbnails fall back to the title; ordinary clicks remain available", () => {
  const h = harness();
  h.send(h.root, "pointerdown");
  h.send(h.root, "pointerup");
  assert.equal(h.send(h.root, "click").prevented, undefined);
  h.start();
  const preview = h.body.children[0];
  preview.children[0].listeners.error();
  assert.equal(preview.children.length, 1);
  assert.equal(preview.children[0].textContent, "Guide");
});

test("native freeform drag does not also start a pointer drag", () => {
  const h = harness(true);
  h.start();
  assert.equal(h.card.captured, undefined);
  assert.equal(h.body.children.length, 0);
  assert.equal(h.send(h.root, "selectstart").prevented, undefined);
});
