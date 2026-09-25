(function registerPulsarHistoryRuntime() {
  const mountedRoots = new WeakMap();

  function trameTrigger(name) {
    if (window.trame && window.trame.trigger) window.trame.trigger(name, []);
  }

  function isEditable(target) {
    if (!target || !target.closest) return false;
    // Range controls retain focus after timeline scrubbing, but they do not
    // have a native text-edit history that workspace undo must preserve.
    if (target.closest("input[type='range']")) return false;
    return !!target.closest(
      "input, textarea, select, [contenteditable='true'], [contenteditable='']"
    );
  }

  function mount(root) {
    if (!root || mountedRoots.has(root)) return;
    const onKeyDown = (event) => {
      if (!event || event.defaultPrevented || event.altKey || isEditable(event.target)) {
        return;
      }
      const modifier = event.ctrlKey || event.metaKey;
      if (!modifier) return;
      const key = String(event.key || "").toLowerCase();
      const redo = (key === "z" && event.shiftKey) || (key === "y" && !event.shiftKey);
      const undo = key === "z" && !event.shiftKey;
      if (!undo && !redo) return;
      event.preventDefault();
      trameTrigger(redo ? "redo_workspace_trigger" : "undo_workspace_trigger");
    };
    const ownerWindow = root.ownerDocument && root.ownerDocument.defaultView;
    if (!ownerWindow) return;
    ownerWindow.addEventListener("keydown", onKeyDown, true);
    mountedRoots.set(root, { onKeyDown, ownerWindow });
    root.setAttribute("data-pulsar-history-runtime-owner", "mounted");
  }

  function unmount(root) {
    const mounted = root && mountedRoots.get(root);
    if (!root || !mounted) return;
    mounted.ownerWindow.removeEventListener("keydown", mounted.onKeyDown, true);
    mountedRoots.delete(root);
    root.removeAttribute("data-pulsar-history-runtime-owner");
  }

  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  const runtime = runtimes.history || window.pulsarHistoryRuntime || {};
  runtime.mount = mount;
  runtime.unmount = unmount;
  runtime.install = function install(app) {
    app.component("pulsar-history-runtime", {
      mounted() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.mount(root);
      },
      beforeUnmount() {
        const root = this.$el.closest(".v-application");
        if (root) runtime.unmount(root);
      },
      template: '<span hidden data-pulsar-history-runtime="mounted"></span>',
    });
  };

  runtimes.history = runtime;
  window.pulsarHistoryRuntime = runtime;
})();
