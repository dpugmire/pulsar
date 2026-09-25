"""Explicit runtime dependencies shared by Pulsar controller adapters."""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from pulsar.backends import PulsarBackend
from pulsar.plot_options_assistant import PlotOptionsTranslator
from pulsar.query_assistant import QueryTranslator


@dataclass(frozen=True)
class ControllerContext:
    server: Any
    backend: PulsarBackend
    db: Any
    collection: Any
    parse_campaign: Callable[..., Any]
    campaign_path: str
    image_association_schema_path: str = ""
    campaign_schema_path: str = ""
    query_translator: Optional[QueryTranslator] = None
    plot_options_translator: Optional[PlotOptionsTranslator] = None
    interaction_log: Optional[Any] = None
