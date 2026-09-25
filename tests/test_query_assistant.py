import asyncio
import inspect
import json
import unittest
import urllib.error
from unittest.mock import patch
from types import SimpleNamespace

from pulsar.backends import BackendStatus
from pulsar.controllers import attach_controllers
from pulsar.query_assistant import (
    ChatCompletionsQueryTranslator,
    QueryAssistantError,
    QuerySourceFilterContext,
    QueryTranslationRequest,
    make_chat_completions_query_translator,
    parse_query_proposal,
)
from pulsar.state import init_state
from pulsar.viewer_actions import (
    CatalogCondition,
    CatalogQueryAction,
    SourceRank,
    VisualizationAddAction,
    ViewerActionProposal,
)
from trame_server.controller import Controller


VARIABLE_NAVIGATION = [
    {
        "id": "variable-group:0D",
        "kind": "variable-group",
        "label": "0D",
        "resource": None,
        "children": [
            {
                "id": "variable:temperature",
                "kind": "variable",
                "label": "Temperature",
                "resource": {
                    "variable_id": "temperature",
                    "name": "temperature",
                    "label": "Temperature",
                    "path": "run/scalars.bp/temperature",
                    "source_dataset": "run/scalars.bp",
                },
                "children": [],
                "has_children": False,
                "count": None,
            },
            {
                "id": "variable:valid",
                "kind": "variable",
                "label": "Valid",
                "resource": {
                    "variable_id": "valid",
                    "name": "valid",
                    "label": "Valid",
                    "path": "run/scalars.bp/valid",
                    "source_dataset": "run/scalars.bp",
                },
                "children": [],
                "has_children": False,
                "count": None,
            },
            {
                "id": "variable:pressure",
                "kind": "variable",
                "label": "Pressure",
                "resource": {
                    "variable_id": "pressure",
                    "name": "pressure",
                    "label": "Pressure",
                    "path": "run/scalars.bp/pressure",
                    "source_dataset": "run/scalars.bp",
                },
                "children": [],
                "has_children": False,
                "count": None,
            },
        ],
        "has_children": True,
        "count": 2,
    }
]


class RecordingEvent:
    def __init__(self):
        self.callbacks = []

    def add(self, callback):
        self.callbacks.append(callback)


class RecordingController:
    def __init__(self):
        self.actions = {}
        self.set_actions = set()
        self.triggers = {}
        self.on_server_ready = RecordingEvent()

    def add(self, name):
        def register(callback):
            self.actions[name] = callback
            return callback

        return register

    def set(self, name, clear=False):
        if clear:
            self.actions.pop(name, None)
        self.set_actions.add(name)
        return self.add(name)

    def trigger(self, name):
        def register(callback):
            self.triggers[name] = callback
            return callback

        return register


class RecordingState(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.change_callbacks = {}
        self.flush_count = 0

    def change(self, *_names):
        def register(callback):
            for name in _names:
                self.change_callbacks.setdefault(name, []).append(callback)
            return callback

        return register

    def flush(self):
        self.flush_count += 1


class FakeBackend:
    def __init__(self, source_summaries=None):
        self.navigation_requests = []
        self.source_summaries = dict(source_summaries or {})

    def get_navigation(self, request):
        self.navigation_requests.append(request)
        return VARIABLE_NAVIGATION

    def get_status(self):
        return BackendStatus(ok=True)

    def get_source_summary(self, request):
        variable_id = request.get("variable_id", "")
        if variable_id in self.source_summaries:
            return self.source_summaries[variable_id]
        return {
            "variable_id": variable_id,
            "num_sources": 0,
            "global_min": None,
            "global_max": None,
            "mean_min": None,
            "mean_max": None,
            "median_min": None,
            "median_max": None,
            "sources": [],
        }

    def find_source(self, request):
        return None

    def resolve_source_restriction(self, request):
        return {"query": {"source_dataset": "run/scalars.bp"}, "count": 1}


class FakeVisualizationDB:
    ok = True
    last_error = ""

    def __init__(self, visualization_names=None, scalar_candidate=None):
        self.visualization_names = list(visualization_names or [])
        self._scalar_candidate = dict(scalar_candidate or {})
        self.visualization_queries = []
        self.tile_queries = []

    def distinct_visualization_names_for_variable(self, variable_id, extra_filter=None):
        self.visualization_queries.append((variable_id, extra_filter))
        return list(self.visualization_names)

    def scalar_plot_candidate(self, variable_id, **kwargs):
        return dict(self._scalar_candidate)

    def get_first_movie_tiles_for_variable(self, variable_id, **kwargs):
        self.tile_queries.append((variable_id, kwargs))
        if not self.visualization_names:
            return []
        return [
            {
                "variable_id": variable_id,
                "variable_name": variable_id,
                "visualization_name": self.visualization_names[0],
                "selected_visualization": self.visualization_names[0],
                "media_type": "plot1d",
                "plot": {"series": []},
                "status": "ready",
            }
        ]


class FakeTranslator:
    description = "Fake translator"
    timeout_seconds = 2.0

    def __init__(self, proposal):
        self.proposal = proposal
        self.requests = []

    def translate(self, request):
        self.requests.append(request)
        return self.proposal


def make_controller(translator, backend=None, db=None):
    state = RecordingState()
    db = db or SimpleNamespace(ok=True, last_error="")
    init_state(state, db)
    state.gridLayoutMode = "uniform"
    server = SimpleNamespace(state=state, controller=RecordingController())
    backend = backend or FakeBackend()
    attach_controllers(
        server=server,
        backend=backend,
        db=db,
        collection=SimpleNamespace(),
        parse_campaign=lambda *_args, **_kwargs: None,
        campaign_path="/campaign/example.aca",
        query_translator=translator,
    )
    return state, server.controller, backend


def disabled_rank():
    return SourceRank()


def action_proposal(action, explanation="Select campaign metadata."):
    return ViewerActionProposal(
        status="proposal",
        actions=(action,),
        explanation=explanation,
    )


def variable_action(variable_id="temperature"):
    return CatalogQueryAction(
        action_type="catalog.query",
        select="variables",
        result_variable_id=variable_id,
        rank=disabled_rank(),
    )


def visualization_action(variable_id="temperature"):
    return VisualizationAddAction(
        action_type="visualization.add",
        variable_id=variable_id,
        target="active_cell",
    )


class QueryProposalTests(unittest.TestCase):
    def test_provider_envelope_is_validated(self):
        proposal = parse_query_proposal(
            {
                "version": 1,
                "status": "proposal",
                "actions": [
                    {
                        "type": "catalog.query",
                        "arguments": {
                            "select": "variables",
                            "result_variable_id": "temperature",
                            "conditions": [],
                            "source_conditions": [],
                            "rank": {
                                "enabled": False,
                                "variable_id": "",
                                "field": "",
                                "direction": "",
                                "limit": 1,
                                "include_ties": True,
                            },
                        },
                    }
                ],
                "explanation": "Select temperature.",
                "assumptions": ["Temperature means the exact variable name."],
                "clarification": "",
            }
        )

        self.assertEqual(proposal.actions[0].result_variable_id, "temperature")
        self.assertEqual(len(proposal.assumptions), 1)

    def test_provider_envelope_rejects_unknown_schema_version(self):
        with self.assertRaisesRegex(
            QueryAssistantError,
            "Unsupported viewer action schema version: 2",
        ):
            parse_query_proposal(
                {
                    "version": 2,
                    "status": "needs_clarification",
                    "actions": [],
                    "explanation": "A newer schema was returned.",
                    "assumptions": [],
                    "clarification": "Use a compatible provider.",
                }
            )

    def test_clarification_cannot_smuggle_a_query(self):
        with self.assertRaisesRegex(
            QueryAssistantError,
            "clarification must not contain viewer actions",
        ):
            parse_query_proposal(
                {
                    "version": 1,
                    "status": "needs_clarification",
                    "actions": [
                        {
                            "type": "catalog.query",
                            "arguments": {
                                "select": "variables",
                                "result_variable_id": "temperature",
                                "conditions": [],
                                "source_conditions": [],
                                "rank": {
                                    "enabled": False,
                                    "variable_id": "",
                                    "field": "",
                                    "direction": "",
                                    "limit": 1,
                                    "include_ties": True,
                                },
                            },
                        }
                    ],
                    "explanation": "The variable is ambiguous.",
                    "assumptions": [],
                    "clarification": "Which temperature variable?",
                }
            )

    def test_unconfigured_chat_translator_is_disabled(self):
        self.assertIsNone(
            make_chat_completions_query_translator(
                model="",
                base_url="http://localhost:11434/v1",
            )
        )

    def test_chat_completions_translator_uses_configured_endpoint(self):
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "version": 1,
                                "status": "proposal",
                                "actions": [
                                    {
                                        "type": "catalog.query",
                                        "arguments": {
                                            "select": "variables",
                                            "result_variable_id": "temperature",
                                            "conditions": [],
                                            "source_conditions": [],
                                            "rank": {
                                                "enabled": False,
                                                "variable_id": "",
                                                "field": "",
                                                "direction": "",
                                                "limit": 1,
                                                "include_ties": True,
                                            },
                                        },
                                    }
                                ],
                                "explanation": "Select temperature.",
                                "assumptions": [],
                                "clarification": "",
                            }
                        )
                    }
                }
            ]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, *_args):
                return json.dumps(response_payload).encode("utf-8")

        translator = ChatCompletionsQueryTranslator(
            model="gpt-oss:20b",
            base_url="http://localhost:11434/v1/",
            api_key="ollama",
        )
        request = QueryTranslationRequest(
            request_text="Show temperature",
            variables=(),
            source_datasets=(),
            selected_variable_id="pressure",
            target="source_filter",
            context_truncated=False,
            source_filter_context=QuerySourceFilterContext(
                row_count=3,
                visible_row_count=2,
                source_datasets=("run/a.bp", "run/b.bp"),
                producers=("xgc",),
                casenames=("case-a",),
                files=("restart.bp",),
                minimum_range=(-1.0, 0.5),
                maximum_range=(2.0, 9.0),
            ),
        )
        with patch(
            "pulsar.query_assistant.urllib.request.urlopen",
            return_value=FakeResponse(),
        ) as urlopen:
            proposal = translator.translate(request)

        http_request = urlopen.call_args.args[0]
        self.assertEqual(
            http_request.full_url,
            "http://localhost:11434/v1/chat/completions",
        )
        self.assertEqual(
            http_request.get_header("Authorization"),
            "Bearer ollama",
        )
        sent_payload = json.loads(http_request.data)
        self.assertEqual(sent_payload["model"], "gpt-oss:20b")
        self.assertEqual(
            sent_payload["response_format"]["type"],
            "json_schema",
        )
        self.assertEqual(
            sent_payload["response_format"]["json_schema"]["schema"][
                "properties"
            ]["version"]["enum"],
            [1],
        )
        system_message = sent_payload["messages"][0]["content"]
        self.assertIn(
            "Numeric values explicitly supplied by the user are authoritative",
            system_message,
        )
        self.assertIn(
            '"largest max" means field maximum',
            system_message,
        )
        self.assertIn("min between A and B", system_message)
        self.assertIn("visualization: visualization.add", system_message)
        sent_context = json.loads(sent_payload["messages"][1]["content"])
        self.assertEqual(
            sent_context["campaign_context"]["target"],
            "source_filter",
        )
        self.assertEqual(
            sent_context["campaign_context"]["source_filter"]["row_count"],
            3,
        )
        self.assertEqual(
            sent_context["campaign_context"]["source_filter"]["examples"][
                "source_datasets"
            ],
            ["run/a.bp", "run/b.bp"],
        )
        self.assertEqual(
            sent_context["campaign_context"]["source_filter"]["ranges"][
                "maximum"
            ],
            {"min": 2.0, "max": 9.0},
        )
        self.assertEqual(proposal.actions[0].result_variable_id, "temperature")

    def test_visualization_proposal_is_parsed_from_provider_envelope(self):
        proposal = parse_query_proposal(
            {
                "version": 1,
                "status": "proposal",
                "actions": [
                    {
                        "type": "visualization.add",
                        "arguments": {
                            "variable_id": "pressure",
                            "target": "active_cell",
                        },
                    }
                ],
                "explanation": "Add pressure to the active cell.",
                "assumptions": [],
                "clarification": "",
            }
        )

        self.assertEqual(proposal.actions[0], visualization_action("pressure"))

    def test_chat_completions_falls_back_when_json_schema_is_rejected(self):
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "version": 1,
                                "status": "needs_clarification",
                                "actions": [],
                                "explanation": "A variable is required.",
                                "assumptions": [],
                                "clarification": "Which variable?",
                            }
                        )
                    }
                }
            ]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, *_args):
                return json.dumps(response_payload).encode("utf-8")

        translator = ChatCompletionsQueryTranslator(
            model="compatible-model",
            base_url="http://localhost:9000/v1",
        )
        request = SimpleNamespace(
            request_text="Show a variable",
            variables=(),
            source_datasets=(),
            selected_variable_id="",
            context_truncated=False,
        )
        unsupported_error = urllib.error.HTTPError(
            "http://localhost:9000/v1/chat/completions",
            400,
            "Unsupported response_format",
            {},
            None,
        )
        with patch(
            "pulsar.query_assistant.urllib.request.urlopen",
            side_effect=[unsupported_error, FakeResponse()],
        ) as urlopen:
            proposal = translator.translate(request)

        self.assertEqual(urlopen.call_count, 2)
        structured_payload = json.loads(urlopen.call_args_list[0].args[0].data)
        fallback_payload = json.loads(urlopen.call_args_list[1].args[0].data)
        self.assertIn("response_format", structured_payload)
        self.assertNotIn("response_format", fallback_payload)
        self.assertEqual(proposal.status, "needs_clarification")


class QueryAssistantControllerTests(unittest.TestCase):
    def test_manual_source_filter_path_remains_available(self):
        state, controller, _backend = make_controller(
            FakeTranslator(action_proposal(variable_action()))
        )
        state.sourceRowsAll = [
            {"_key": "low", "max_value": 2.0},
            {"_key": "high", "max_value": 9.0},
        ]
        state.sourceRows = list(state.sourceRowsAll)
        state.sourceFilterDraftText = "max > 5"

        controller.actions["apply_source_dialog_filter"]()

        self.assertEqual(state.sourceFilterText, "max > 5")
        self.assertEqual(
            [row["_key"] for row in state.sourceRows],
            ["high"],
        )

    def test_async_translation_action_is_registered_as_a_direct_callback(self):
        _state, controller, _backend = make_controller(
            FakeTranslator(action_proposal(variable_action()))
        )

        self.assertEqual(
            controller.set_actions,
            {
                "translate_query_request",
                "translate_scalar_field_options_request",
            },
        )

    def test_real_trame_controller_exposes_an_awaitable_action(self):
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        init_state(state, db)
        server = SimpleNamespace(state=state, controller=Controller())
        attach_controllers(
            server=server,
            backend=FakeBackend(),
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
            query_translator=FakeTranslator(action_proposal(variable_action())),
        )

        result = server.controller.translate_query_request()
        self.assertTrue(inspect.isawaitable(result))
        result.close()

    def test_translation_is_reviewed_before_explicit_apply(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="variables",
                    result_variable_id="temperature",
                    source_conditions=(
                        CatalogCondition("variable_id", "eq", "valid"),
                        CatalogCondition("minimum", "eq", 1),
                    ),
                    rank=disabled_rank(),
                ),
                explanation="Select temperature from valid runs.",
            )
        )
        state, controller, _backend = make_controller(translator)
        state.queryAssistantRequestText = (
            "Show temperature from runs where valid equals one"
        )

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(state.queryText, "")
        self.assertEqual(
            state.queryAssistantProposalText,
            'id == "temperature" and '
            'source(variable_id == "valid" and min == 1)',
        )
        self.assertEqual(state.queryAssistantVariableCount, 3)
        self.assertEqual(state.queryAssistantSourceCount, 1)
        self.assertEqual(state.queryAssistantProvider, "Fake translator")
        self.assertEqual(state.flush_count, 1)
        self.assertEqual(
            [item.variable_id for item in translator.requests[0].variables],
            ["pressure", "temperature", "valid"],
        )
        self.assertEqual(
            translator.requests[0].source_datasets,
            ("run/scalars.bp",),
        )

        self.assertTrue(controller.actions["apply_query_proposal"]())
        self.assertEqual(state.queryText, state.queryAssistantProposalText)
        self.assertFalse(state.showQueryAssistant)

    def test_invalid_provider_action_does_not_replace_active_query(self):
        translator = FakeTranslator(
            action_proposal(
                variable_action("not-in-campaign"),
                explanation="Invalid provider output.",
            )
        )
        state, controller, _backend = make_controller(translator)
        state.queryText = "var == 'valid'"
        state.queryFilter = {"variable_name": "valid"}
        state.queryViewLabel = "var == 'valid'"
        state.queryAssistantRequestText = "Do something unsafe"

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertFalse(result)
        self.assertEqual(state.queryText, "var == 'valid'")
        self.assertEqual(state.queryFilter, {"variable_name": "valid"})
        self.assertEqual(state.queryViewLabel, "var == 'valid'")
        self.assertEqual(state.queryAssistantStatus, "")
        self.assertTrue(state.queryAssistantError)

    def test_largest_max_is_resolved_from_local_source_metadata(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="",
                    rank=SourceRank(
                        enabled=True,
                        variable_id="",
                        field="maximum",
                        direction="descending",
                    ),
                ),
                explanation="Rank pressure sources by their maximum.",
            )
        )
        backend = FakeBackend(
            source_summaries={
                "pressure": {
                    "variable_id": "pressure",
                    "num_sources": 3,
                    "global_min": 0.0,
                    "global_max": 9.0,
                    "mean_min": 0.0,
                    "mean_max": 6.0,
                    "median_min": 0.0,
                    "median_max": 9.0,
                    "sources": [
                        {"source_dataset": "run/a.bp", "maximum": 2.0},
                        {"source_dataset": "run/b.bp", "maximum": 9.0},
                        {"source_dataset": "run/c.bp", "maximum": 9.0},
                    ],
                }
            }
        )
        state, controller, _backend = make_controller(translator, backend)
        state.selectedVar = "pressure"
        state.queryAssistantRequestText = "largest max"

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(
            state.queryAssistantProposalText,
            'source(id == "pressure" and max == 9.0)',
        )
        self.assertEqual(state.queryAssistantRankValue, 9.0)
        self.assertEqual(state.queryAssistantTieCount, 2)
        self.assertIn("largest source maximum", state.queryAssistantProposalSummary)
        self.assertIn("2 sources are tied", state.queryAssistantProposalSummary)
        self.assertEqual(
            state.queryAssistantActionPlan["actions"][0]["arguments"]["rank"][
                "variable_id"
            ],
            "pressure",
        )
        self.assertEqual(state.queryAssistantActionPlan["version"], 1)
        self.assertEqual(
            translator.requests[0].selected_variable_id,
            "pressure",
        )

        self.assertTrue(controller.actions["apply_query_proposal"]())
        self.assertEqual(state.queryText, state.queryAssistantProposalText)

    def test_source_dataset_substring_is_not_validated_as_an_exact_name(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    conditions=(
                        CatalogCondition("maximum", "gt", 5.0),
                    ),
                    source_conditions=(
                        CatalogCondition(
                            "source_dataset",
                            "contains",
                            "scalars",
                        ),
                    ),
                    rank=disabled_rank(),
                )
            )
        )
        state, controller, _backend = make_controller(translator)
        state.queryAssistantRequestText = (
            "sources where pressure max is > 5.0 and source dataset name "
            'contains "scalars"'
        )

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(state.queryAssistantError, "")
        self.assertEqual(
            state.queryAssistantProposalText,
            'source(id == "pressure" and max > 5.0 and '
            'contains(source_dataset, "scalars"))',
        )

    def test_source_dialog_assistant_previews_and_applies_only_source_rows(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    conditions=(CatalogCondition("maximum", "gt", 5.0),),
                    source_conditions=(
                        CatalogCondition(
                            "source_dataset",
                            "contains",
                            "scalars",
                        ),
                    ),
                    rank=disabled_rank(),
                )
            )
        )
        state, controller, _backend = make_controller(translator)
        state.detailsSelectedVarId = "pressure"
        state.selectedVar = "pressure"
        state.showSourcesModal = True
        state.queryText = 'id == "temperature"'
        state.sourceRowsAll = [
            {
                "_key": "matching",
                "variable_id": "pressure",
                "source_dataset": "run/scalars.bp",
                "max_value": 9.0,
            },
            {
                "_key": "other",
                "variable_id": "pressure",
                "source_dataset": "run/other.bp",
                "max_value": 12.0,
            },
        ]
        state.sourceRows = list(state.sourceRowsAll)
        state.sourceFilterDraftText = (
            "max > 5 and source dataset contains scalars"
        )

        self.assertTrue(controller.actions["open_source_query_assistant"]())
        self.assertEqual(state.queryAssistantTarget, "source_filter")
        self.assertEqual(
            state.queryAssistantRequestText,
            "max > 5 and source dataset contains scalars",
        )

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(translator.requests[0].target, "source_filter")
        self.assertEqual(translator.requests[0].selected_variable_id, "pressure")
        self.assertEqual(state.queryAssistantStatus, "Valid · 1 source row")
        self.assertEqual(state.queryAssistantSourceCount, 1)
        self.assertEqual(state.queryText, 'id == "temperature"')

        self.assertTrue(controller.actions["apply_query_proposal"]())
        self.assertEqual(
            state.sourceFilterText,
            'max > 5.0 and contains(source_dataset, "scalars")',
        )
        self.assertEqual(
            [row["_key"] for row in state.sourceRows],
            ["matching"],
        )
        self.assertEqual(state.queryText, 'id == "temperature"')
        self.assertTrue(state.showSourcesModal)
        self.assertFalse(state.showQueryAssistant)
        self.assertIn(
            "Preview: 1 matching source row.",
            state.queryAssistantProposalSummary,
        )

    def test_source_filter_request_includes_source_row_context(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    conditions=(CatalogCondition("maximum", "gt", 0.0),),
                    rank=disabled_rank(),
                )
            )
        )
        state, controller, _backend = make_controller(translator)
        state.detailsSelectedVarId = "pressure"
        state.selectedVar = "pressure"
        state.sourceRowsAll = [
            {
                "_key": "a",
                "source_dataset": "run/b.bp",
                "producer": "xgc",
                "casename": "case-b",
                "file": "restart-b.bp",
                "min_value": -2.0,
                "max_value": 9.0,
            },
            {
                "_key": "b",
                "source_dataset": "run/a.bp",
                "producer": "xgc",
                "casename": "case-a",
                "file": "restart-a.bp",
                "min_value": 0.5,
                "max_value": 4.0,
            },
        ]
        state.sourceRows = [state.sourceRowsAll[0]]
        state.sourceFilterDraftText = "max > 0"

        controller.actions["open_source_query_assistant"]()
        self.assertTrue(asyncio.run(controller.actions["translate_query_request"]()))

        context = translator.requests[0].source_filter_context
        self.assertIsNotNone(context)
        self.assertEqual(context.row_count, 2)
        self.assertEqual(context.visible_row_count, 1)
        self.assertEqual(context.source_datasets, ("run/a.bp", "run/b.bp"))
        self.assertEqual(context.producers, ("xgc",))
        self.assertEqual(context.casenames, ("case-a", "case-b"))
        self.assertEqual(context.files, ("restart-a.bp", "restart-b.bp"))
        self.assertEqual(context.minimum_range, (-2.0, 0.5))
        self.assertEqual(context.maximum_range, (4.0, 9.0))

    def test_source_dialog_ranking_uses_current_source_rows(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    rank=SourceRank(
                        enabled=True,
                        variable_id="pressure",
                        field="maximum",
                        direction="descending",
                    ),
                )
            )
        )
        backend = FakeBackend(
            source_summaries={
                "pressure": {
                    "sources": [
                        {"source_dataset": "outside", "maximum": 100.0}
                    ]
                }
            }
        )
        state, controller, _backend = make_controller(translator, backend)
        state.detailsSelectedVarId = "pressure"
        state.selectedVar = "pressure"
        state.sourceRowsAll = [
            {
                "_key": "a",
                "variable_id": "pressure",
                "source_dataset": "run/scalars.bp",
                "max_value": 2.0,
            },
            {
                "_key": "b",
                "variable_id": "pressure",
                "source_dataset": "run/scalars.bp",
                "max_value": 9.0,
            },
        ]
        state.sourceRows = list(state.sourceRowsAll)
        state.sourceFilterDraftText = "largest max"

        controller.actions["open_source_query_assistant"]()
        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(state.queryAssistantRankValue, 9.0)
        self.assertEqual(
            state.queryAssistantProposalText,
            "max == 9.0",
        )

    def test_source_dialog_minimum_range_preview_counts_matching_rows(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    conditions=(
                        CatalogCondition("minimum", "gte", 0.0),
                        CatalogCondition("minimum", "lte", 1.0),
                    ),
                    rank=disabled_rank(),
                )
            )
        )
        state, controller, _backend = make_controller(translator)
        state.detailsSelectedVarId = "pressure"
        state.selectedVar = "pressure"
        state.sourceRowsAll = [
            {"_key": "low", "min_value": -1.0, "max_value": 2.0},
            {"_key": "match", "min_value": 0.5, "max_value": 3.0},
            {"_key": "high", "min_value": 1.5, "max_value": 4.0},
        ]
        state.sourceRows = list(state.sourceRowsAll)
        state.sourceFilterDraftText = "min between 0 and 1"

        controller.actions["open_source_query_assistant"]()
        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(
            state.queryAssistantProposalText,
            "min >= 0.0 and min <= 1.0",
        )
        self.assertEqual(state.queryAssistantSourceCount, 1)
        self.assertIn(
            "Preview: 1 matching source row.",
            state.queryAssistantProposalSummary,
        )

    def test_exact_source_dataset_still_requires_a_campaign_name(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    source_conditions=(
                        CatalogCondition(
                            "source_dataset",
                            "eq",
                            "invented/output.bp",
                        ),
                    ),
                    rank=disabled_rank(),
                )
            )
        )
        state, controller, _backend = make_controller(translator)
        state.queryAssistantRequestText = "pressure from invented/output.bp"

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertFalse(result)
        self.assertEqual(
            state.queryAssistantError,
            "Action references an unknown source dataset.",
        )
        self.assertEqual(state.queryAssistantProposalText, "")

    def test_smallest_min_is_resolved_from_local_source_metadata(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    rank=SourceRank(
                        enabled=True,
                        variable_id="pressure",
                        field="minimum",
                        direction="ascending",
                    ),
                )
            )
        )
        backend = FakeBackend(
            source_summaries={
                "pressure": {
                    "sources": [
                        {"source_dataset": "run/a.bp", "minimum": -3.0},
                        {"source_dataset": "run/b.bp", "minimum": 1.0},
                    ]
                }
            }
        )
        state, controller, _backend = make_controller(translator, backend)
        state.queryAssistantRequestText = "pressure with smallest min"

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(state.queryAssistantRankValue, -3.0)
        self.assertEqual(
            state.queryAssistantProposalText,
            'source(id == "pressure" and min == -3.0)',
        )

    def test_rank_without_finite_metadata_is_not_proposed(self):
        translator = FakeTranslator(
            action_proposal(
                CatalogQueryAction(
                    action_type="catalog.query",
                    select="sources",
                    result_variable_id="pressure",
                    rank=SourceRank(
                        enabled=True,
                        variable_id="pressure",
                        field="maximum",
                        direction="descending",
                    ),
                )
            )
        )
        backend = FakeBackend(
            source_summaries={
                "pressure": {
                    "sources": [
                        {"source_dataset": "run/a.bp", "maximum": None},
                        {"source_dataset": "run/b.bp", "maximum": "nan"},
                    ]
                }
            }
        )
        state, controller, _backend = make_controller(translator, backend)
        state.queryAssistantRequestText = "pressure with largest max"

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertFalse(result)
        self.assertEqual(state.queryAssistantProposalText, "")
        self.assertIn(
            "No finite source maximum metadata is available for pressure",
            state.queryAssistantError,
        )

    def test_clarification_does_not_create_a_proposal(self):
        translator = FakeTranslator(
            ViewerActionProposal(
                status="needs_clarification",
                actions=(),
                explanation="More information is required.",
                clarification="Which temperature variable do you mean?",
            )
        )
        state, controller, _backend = make_controller(translator)
        state.queryAssistantRequestText = "Show temperature"

        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertFalse(result)
        self.assertEqual(state.queryAssistantProposalText, "")
        self.assertEqual(state.queryAssistantStatus, "Clarification needed")
        self.assertIn("Which temperature", state.queryAssistantClarification)

    def test_visualization_is_previewed_without_mutating_grid_until_apply(self):
        translator = FakeTranslator(
            action_proposal(
                visualization_action("pressure"),
                explanation="Add pressure to the active cell.",
            )
        )
        db = FakeVisualizationDB(["timeseries"])
        state, controller, _backend = make_controller(translator, db=db)
        state.activeGridCell = 0
        state.queryText = 'source(producer == "run-128")'
        state.queryFilter = {"producer": "run-128"}
        state.activeViewerActionPlan = {"preserve": "catalog query provenance"}
        original_cells = [dict(cell) for cell in state.gridCells]

        self.assertTrue(controller.actions["open_visualization_assistant"]())
        state.queryAssistantRequestText = "Plot pressure in the selected cell"
        result = asyncio.run(controller.actions["translate_query_request"]())

        self.assertTrue(result)
        self.assertEqual(translator.requests[0].target, "visualization")
        self.assertEqual(state.gridCells, original_cells)
        self.assertEqual(state.queryAssistantProposalText, "")
        self.assertEqual(state.queryAssistantVisualizationName, "timeseries")
        self.assertEqual(state.queryAssistantTargetCellIndex, 0)
        self.assertEqual(
            state.queryAssistantStatus,
            "Valid · pressure · grid cell 1",
        )
        self.assertIn("using timeseries", state.queryAssistantProposalSummary)
        self.assertEqual(
            state.queryAssistantActionPlan["actions"][0]["type"],
            "visualization.add",
        )

        self.assertTrue(controller.actions["apply_query_proposal"]())
        self.assertEqual(state.gridCells[0]["variable_id"], "pressure")
        self.assertEqual(
            state.gridCells[0]["selected_visualization"],
            "timeseries",
        )
        self.assertEqual(state.queryText, 'source(producer == "run-128")')
        self.assertEqual(state.queryFilter, {"producer": "run-128"})
        self.assertEqual(
            state.activeViewerActionPlan,
            {"preserve": "catalog query provenance"},
        )
        self.assertFalse(state.showQueryAssistant)

    def test_visualization_preview_respects_active_query_and_preserves_grid(self):
        translator = FakeTranslator(action_proposal(visualization_action("pressure")))
        db = FakeVisualizationDB(["timeseries"])
        state, controller, _backend = make_controller(translator, db=db)
        state.activeGridCell = 1
        state.queryFilter = {"producer": "matching-run"}
        original_cells = [dict(cell) for cell in state.gridCells]

        controller.actions["open_visualization_assistant"]()
        state.queryAssistantRequestText = "Show pressure"
        self.assertTrue(asyncio.run(controller.actions["translate_query_request"]()))

        variable_id, query_filter = db.visualization_queries[0]
        self.assertEqual(variable_id, "pressure")
        self.assertEqual(query_filter, {"producer": "matching-run"})
        self.assertEqual(state.gridCells, original_cells)

    def test_visualization_rejects_missing_cell_unknown_variable_and_wrong_action(self):
        db = FakeVisualizationDB(["timeseries"])
        translator = FakeTranslator(action_proposal(visualization_action("pressure")))
        state, controller, _backend = make_controller(translator, db=db)
        state.activeGridCell = -1
        controller.actions["open_visualization_assistant"]()
        state.queryAssistantRequestText = "Show pressure"

        self.assertFalse(asyncio.run(controller.actions["translate_query_request"]()))
        self.assertIn("Select a grid cell", state.queryAssistantError)

        translator.proposal = action_proposal(visualization_action("invented"))
        state.activeGridCell = 0
        self.assertFalse(asyncio.run(controller.actions["translate_query_request"]()))
        self.assertEqual(
            state.queryAssistantError,
            "Unknown campaign variable: invented",
        )

        translator.proposal = action_proposal(variable_action("pressure"))
        self.assertFalse(asyncio.run(controller.actions["translate_query_request"]()))
        self.assertIn("must propose visualization.add", state.queryAssistantError)

    def test_query_target_rejects_visualization_action(self):
        translator = FakeTranslator(action_proposal(visualization_action("pressure")))
        state, controller, _backend = make_controller(translator)
        state.queryAssistantTarget = "catalog"
        state.queryAssistantRequestText = "Show pressure"

        self.assertFalse(asyncio.run(controller.actions["translate_query_request"]()))
        self.assertEqual(
            state.queryAssistantError,
            "A query request must propose catalog.query.",
        )

    def test_visualization_uses_existing_scalar_generation_confirmation(self):
        translator = FakeTranslator(action_proposal(visualization_action("pressure")))
        db = FakeVisualizationDB(
            scalar_candidate={
                "variable_id": "pressure",
                "source_label": "run-128",
                "source_fields": {"source_dataset": "run-128/output.bp"},
            }
        )
        state, controller, _backend = make_controller(translator, db=db)
        state.activeGridCell = 0
        state.scalarPlotPolicy = "ask"
        original_cells = [dict(cell) for cell in state.gridCells]

        with patch("plugin_runtime.discover_plugins", return_value=[]):
            controller.actions["open_visualization_assistant"]()
            state.queryAssistantRequestText = "Plot pressure"
            self.assertTrue(
                asyncio.run(controller.actions["translate_query_request"]())
            )
            self.assertEqual(
                state.queryAssistantVisualizationName,
                "generated scalar plot",
            )
            self.assertEqual(state.gridCells, original_cells)

            self.assertTrue(controller.actions["apply_query_proposal"]())
        self.assertTrue(state.showScalarPlotDialog)
        self.assertEqual(state.pendingScalarPlotVariableId, "pressure")
        self.assertEqual(state.pendingScalarPlotCellIndex, 0)
        self.assertEqual(state.gridCells, original_cells)

    def test_visualization_rejects_disabled_scalar_generation(self):
        translator = FakeTranslator(action_proposal(visualization_action("pressure")))
        db = FakeVisualizationDB(scalar_candidate={"variable_id": "pressure"})
        state, controller, _backend = make_controller(translator, db=db)
        state.activeGridCell = 0
        state.scalarPlotPolicy = "never"
        original_cells = [dict(cell) for cell in state.gridCells]

        with patch("plugin_runtime.discover_plugins", return_value=[]):
            controller.actions["open_visualization_assistant"]()
            state.queryAssistantRequestText = "Plot pressure"
            self.assertFalse(
                asyncio.run(controller.actions["translate_query_request"]())
            )

        self.assertIn("scalar plot generation is disabled", state.queryAssistantError)
        self.assertEqual(state.gridCells, original_cells)


if __name__ == "__main__":
    unittest.main()
