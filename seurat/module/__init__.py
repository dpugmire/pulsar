"""Web assets served by the Seurat Trame application."""

from pathlib import Path


__all__ = ["scripts", "serve", "styles", "vue_use"]

# Browser assets are cached under this namespace. Bump it whenever an existing
# JavaScript or stylesheet asset changes so a normal reload cannot reuse stale code.
BASE_URL = "seurat_0_1_10"

serve = {
    BASE_URL: str(Path(__file__).with_name("serve").resolve()),
}
scripts = [
    f"{BASE_URL}/seurat.js",
    f"{BASE_URL}/seurat-media-runtime.js",
    f"{BASE_URL}/seurat-plot-runtime.js",
    f"{BASE_URL}/seurat-timeline-runtime.js",
    f"{BASE_URL}/seurat-grid-runtime.js",
    f"{BASE_URL}/seurat-canvas-layout.js",
    f"{BASE_URL}/seurat-canvas-runtime.js",
    f"{BASE_URL}/seurat-interaction-runtime.js",
    f"{BASE_URL}/seurat-resize-runtime.js",
    f"{BASE_URL}/seurat-history-runtime.js",
]
styles = [
    f"{BASE_URL}/seurat.css",
]
vue_use = [
    "seuratGridRuntime",
    "seuratCanvasRuntime",
    "seuratInteractionRuntime",
    "seuratResizeRuntime",
    "seuratHistoryRuntime",
]
