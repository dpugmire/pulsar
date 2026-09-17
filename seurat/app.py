"""Seurat's Trame application composition root."""

import argparse
import atexit
from pathlib import Path

from trame.app import TrameApp

from config import (
    SEURAT_LLM_API_KEY,
    SEURAT_LLM_BASE_URL,
    SEURAT_LLM_MODEL,
    SEURAT_LLM_TIMEOUT_SECONDS,
    SEURAT_INTERACTION_LOG_DIR,
    SEURAT_INTERACTION_LOG_MAX_MB,
)
from controllers import attach_controllers
from db import CampaignDb
from ingest_campaign import parse_campaign
from sqlite_store import open_sqlite_collection
from ui import build_ui

from . import module as seurat_module
from .backends import LocalCampaignBackend
from .demo_campaign import (
    DEFAULT_DEMO_SOURCE_COUNT,
    MAX_DEMO_SOURCE_COUNT,
    DemoConfig,
    DemoDependencyError,
    temporary_demo_campaign,
)
from .learning import InteractionLog
from .plot_options_assistant import make_chat_completions_plot_options_translator
from .query_assistant import make_chat_completions_query_translator
from .state import init_state


def _expanded_path(path):
    return str(Path(path).expanduser()) if path else ""


def _demo_source_count(value):
    count = int(value)
    if not 1 <= count <= MAX_DEMO_SOURCE_COUNT:
        raise argparse.ArgumentTypeError(
            f"demo source count must be between 1 and {MAX_DEMO_SOURCE_COUNT}"
        )
    return count


class SeuratApp(TrameApp):
    """Own and connect the server, data model, controllers, and UI."""

    def __init__(
        self,
        campaign_path,
        image_association_schema_path="",
        campaign_schema_path="",
        server=None,
        collection=None,
        db=None,
        query_translator=None,
        plot_options_translator=None,
        interaction_log=None,
        controller_attacher=attach_controllers,
        ui_builder=build_ui,
    ):
        super().__init__(server, client_type="vue3")
        self.server.enable_module(seurat_module)

        self.campaign_path = _expanded_path(campaign_path)
        self.image_association_schema_path = _expanded_path(
            image_association_schema_path
        )
        self.campaign_schema_path = _expanded_path(campaign_schema_path)

        self.collection = collection or open_sqlite_collection(self.campaign_path)
        print(f"Seurat sidecar DB: {self.collection.path}")

        self.db = db or CampaignDb(self.collection)
        close_db = getattr(self.db, "close", None)
        if callable(close_db):
            atexit.register(close_db)
        self.backend = LocalCampaignBackend(self.db)
        self.interaction_log = (
            interaction_log
            if interaction_log is not None
            else InteractionLog(
                SEURAT_INTERACTION_LOG_DIR,
                campaign_path=self.campaign_path,
                max_megabytes=SEURAT_INTERACTION_LOG_MAX_MB,
            )
        )
        close_interaction_log = getattr(self.interaction_log, "close", None)
        if bool(getattr(self.interaction_log, "enabled", False)) and callable(
            close_interaction_log
        ):
            atexit.register(close_interaction_log)
        self.query_translator = (
            query_translator
            or make_chat_completions_query_translator(
                model=SEURAT_LLM_MODEL,
                base_url=SEURAT_LLM_BASE_URL,
                api_key=SEURAT_LLM_API_KEY,
                timeout_seconds=SEURAT_LLM_TIMEOUT_SECONDS,
            )
        )
        self.plot_options_translator = (
            plot_options_translator
            or make_chat_completions_plot_options_translator(
                model=SEURAT_LLM_MODEL,
                base_url=SEURAT_LLM_BASE_URL,
                api_key=SEURAT_LLM_API_KEY,
                timeout_seconds=SEURAT_LLM_TIMEOUT_SECONDS,
            )
        )
        init_state(self.state, self.db)

        self.refresh_variable_list = controller_attacher(
            server=self.server,
            backend=self.backend,
            db=self.db,
            collection=self.collection,
            parse_campaign=parse_campaign,
            campaign_path=self.campaign_path,
            image_association_schema_path=self.image_association_schema_path,
            campaign_schema_path=self.campaign_schema_path,
            query_translator=self.query_translator,
            plot_options_translator=self.plot_options_translator,
            interaction_log=self.interaction_log,
        )
        self.ui = ui_builder(
            self.server,
            self.refresh_variable_list,
            campaign_name=Path(self.campaign_path).name,
        )


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "campaign_path",
        nargs="?",
        help="Path to .aca campaign file",
    )
    parser.add_argument(
        "--demo",
        nargs="?",
        const=DEFAULT_DEMO_SOURCE_COUNT,
        type=_demo_source_count,
        metavar="SOURCE_COUNT",
        help=(
            "Generate an ephemeral synthetic campaign with SOURCE_COUNT sources "
            f"(default: {DEFAULT_DEMO_SOURCE_COUNT}, maximum: {MAX_DEMO_SOURCE_COUNT})."
        ),
    )
    parser.add_argument(
        "--image-association-schema",
        default="",
        help="Optional path to image association schema text/YAML file.",
    )
    parser.add_argument(
        "--campaign-schema",
        default="",
        help="Optional path to campaign schema YAML; overrides embedded schema.yaml.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.campaign_path) == bool(args.demo):
        parser.error("provide exactly one of campaign_path or --demo")
    if args.demo and (args.image_association_schema or args.campaign_schema):
        parser.error("--demo cannot be combined with external schema options")

    if args.demo:
        try:
            with temporary_demo_campaign(
                config=DemoConfig(source_count=args.demo)
            ) as demo:
                collection = open_sqlite_collection(
                    str(demo.campaign_path),
                    db_path=str(demo.sidecar_path),
                )
                try:
                    app = SeuratApp(
                        campaign_path=str(demo.campaign_path),
                        collection=collection,
                    )
                    app.server.start()
                finally:
                    collection.close()
            return
        except DemoDependencyError as exc:
            parser.error(str(exc))

    app = SeuratApp(
        campaign_path=args.campaign_path,
        image_association_schema_path=args.image_association_schema,
        campaign_schema_path=args.campaign_schema,
    )
    app.server.start()
