"""Web assets served by the Pulsar Trame application."""

from pathlib import Path


__all__ = ["scripts", "serve", "styles", "vue_use"]

# Browser assets are cached under this namespace. Bump it whenever an existing
# JavaScript or stylesheet asset changes so a normal reload cannot reuse stale code.
BASE_URL = "pulsar_0_1_11"

serve = {
    BASE_URL: str(Path(__file__).with_name("serve").resolve()),
}
scripts = [
    f"{BASE_URL}/pulsar.js",
    f"{BASE_URL}/pulsar-media-runtime.js",
    f"{BASE_URL}/pulsar-plot-runtime.js",
    f"{BASE_URL}/pulsar-timeline-runtime.js",
    f"{BASE_URL}/pulsar-grid-runtime.js",
    f"{BASE_URL}/pulsar-canvas-layout.js",
    f"{BASE_URL}/pulsar-canvas-runtime.js",
    f"{BASE_URL}/pulsar-interaction-runtime.js",
    f"{BASE_URL}/pulsar-resize-runtime.js",
    f"{BASE_URL}/pulsar-history-runtime.js",
]
styles = [
    f"{BASE_URL}/pulsar.css",
]
vue_use = [
    "pulsarGridRuntime",
    "pulsarCanvasRuntime",
    "pulsarInteractionRuntime",
    "pulsarResizeRuntime",
    "pulsarHistoryRuntime",
]
