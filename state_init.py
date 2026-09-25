from typing import Optional

from pulsar.state import clear_details, clear_right_panes, init_state


__all__ = ["clear_details", "clear_right_panes", "fmt", "init_state"]


def fmt(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{value:.6g}"
    except Exception:
        return str(value)
