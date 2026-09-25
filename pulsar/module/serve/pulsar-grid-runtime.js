(function registerPulsarGridRuntime() {
  const pulsar = window.pulsar = window.pulsar || {};
  const runtimes = pulsar.runtimes = pulsar.runtimes || {};
  const runtime = runtimes.grid || window.pulsarGridRuntime || {};

  runtime.install = function install(app) {
    app.component("pulsar-grid-runtime", {
      mounted() {
        const root = this.$el.closest(".pulsar-content-column");
        if (root && runtime.mount) {
          runtime.mount(root);
        }
      },
      beforeUnmount() {
        const root = this.$el.closest(".pulsar-content-column");
        if (root && runtime.unmount) {
          runtime.unmount(root);
        }
      },
      template: '<span hidden data-pulsar-grid-runtime="mounted"></span>',
    });
  };

  runtimes.grid = runtime;
  window.pulsarGridRuntime = runtime;
})();
