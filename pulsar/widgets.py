"""Pulsar client widgets registered by the Trame web module."""

from trame_client.widgets.core import AbstractElement


class GridRuntime(AbstractElement):
    """Lifecycle owner for browser-only grid and timeline interactions."""

    def __init__(self, children=None, **kwargs):
        super().__init__("pulsar-grid-runtime", children, **kwargs)


class InteractionRuntime(AbstractElement):
    """Lifecycle owner for catalog/grid drag-and-drop and context menus."""

    def __init__(self, children=None, **kwargs):
        super().__init__("pulsar-interaction-runtime", children, **kwargs)


class CanvasRuntime(AbstractElement):
    """Lifecycle owner for freeform canvas placement and resizing."""

    def __init__(self, children=None, **kwargs):
        super().__init__("pulsar-canvas-runtime", children, **kwargs)


class ResizeRuntime(AbstractElement):
    """Lifecycle owner for variable-panel and grid-track resizing."""

    def __init__(self, children=None, **kwargs):
        super().__init__("pulsar-resize-runtime", children, **kwargs)


class HistoryRuntime(AbstractElement):
    """Lifecycle owner for workspace undo/redo keyboard shortcuts."""

    def __init__(self, children=None, **kwargs):
        super().__init__("pulsar-history-runtime", children, **kwargs)
