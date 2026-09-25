"""Explicit ownership and initialization of Pulsar's client state."""

from . import (
    catalog,
    context_menu,
    grid,
    history,
    query_assistant,
    sources,
    visualization,
    workspace,
)


STATE_SECTIONS = (
    ("catalog", catalog.defaults),
    ("query_assistant", query_assistant.defaults),
    ("sources", sources.defaults),
    ("visualization", visualization.defaults),
    ("grid", grid.defaults),
    ("context_menu", context_menu.defaults),
    ("workspace", workspace.defaults),
    ("history", history.defaults),
)


def _apply(state, values) -> None:
    for name, value in values.items():
        setattr(state, name, value)


def init_state(state, db) -> None:
    _apply(
        state,
        {
            "dbOk": db.ok,
            "dbStatus": "Connected" if db.ok else f"DB error: {db.last_error}",
        },
    )
    for _name, defaults in STATE_SECTIONS:
        _apply(state, defaults())


def clear_details(state) -> None:
    _apply(state, sources.details_defaults())


def clear_right_panes(state) -> None:
    clear_details(state)
    _apply(state, sources.media_defaults())
    _apply(state, context_menu.right_pane_reset_defaults())
    _apply(state, visualization.right_pane_reset_defaults())
