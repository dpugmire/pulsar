import copy
import unittest
from types import SimpleNamespace

from application import PulsarApplication
from pulsar.backends import BackendStatus, LocalCampaignBackend
from pulsar.controllers import attach_controllers
from pulsar.state import init_state

VARIABLE_NAVIGATION = [
    {
        "id": "variable-group:0D",
        "kind": "variable-group",
        "label": "0D",
        "resource": None,
        "children": [
            {
                "id": "variable:energy",
                "kind": "variable",
                "label": "energy",
                "resource": {
                    "variable_id": "energy",
                    "name": "energy",
                    "label": "energy",
                    "path": "energy",
                    "source_dataset": "run/output.bp",
                },
                "children": [],
                "has_children": False,
                "count": None,
            }
        ],
        "has_children": True,
        "count": 1,
    }
]

SOURCE_SUMMARY = {
    "variable_id": "energy",
    "num_sources": 0,
    "global_min": 1.0,
    "global_max": 4.0,
    "mean_min": 1.5,
    "mean_max": 3.5,
    "median_min": 1.5,
    "median_max": 3.5,
    "sources": [],
    "source_representation": {
        "id": "source",
        "label": "Source coefficients",
        "kind": "source",
        "data_model": "m3dc1_element_basis_coefficients",
        "shape": "27894 × 20",
        "num_frames": 51,
        "global_min": -5.6e9,
        "global_max": 1.3e10,
        "mean_min": -5.6e9,
        "mean_max": 1.3e10,
        "median_min": -5.6e9,
        "median_max": 1.3e10,
    },
    "derived_representations": [
        {
            "id": "scalar_field",
            "label": "Derived scalar field",
            "kind": "derived",
            "data_model": "m3dc1_regular_rz_grid",
            "source_data_model": "m3dc1_element_basis_coefficients",
            "shape": "256 × 256",
            "axes": "R × Z",
            "num_frames": 51,
            "global_min": -0.02,
            "global_max": 3.56,
            "mean_min": -0.01,
            "mean_max": 3.0,
            "median_min": -0.01,
            "median_max": 3.1,
        }
    ],
}


def source_summary_with_one_source():
    summary = copy.deepcopy(SOURCE_SUMMARY)
    summary.update(
        {
            "num_sources": 1,
            "sources": [
                {
                    "label": "run/output",
                    "variable_id": "energy",
                    "variable_name": "energy",
                    "variable_type": "variable",
                    "variable_path": "run/output.bp/energy",
                    "source_dataset": "run/output.bp",
                    "source_datasets": ["run/output.bp"],
                    "files": ["output.bp"],
                    "producer": "run",
                    "casename": "case-a",
                    "file": "output.bp",
                    "num_timesteps": 34,
                    "minimum": 1,
                    "maximum": 4,
                }
            ],
        }
    )
    return summary


class RecordingCampaignDb:
    def __init__(self):
        self.ok = True
        self.last_error = ""
        self.variable_calls = []
        self.file_calls = []
        self.source_summary_calls = []
        self.source_lookup_calls = []
        self.source_restriction_calls = []

    def grouped_variable_names(self, **kwargs):
        self.variable_calls.append(kwargs)
        return [
            {
                "name": "0D",
                "variables": [
                    {
                        "id": "energy",
                        "name": "energy",
                        "label": "energy",
                        "path": "energy",
                        "source_dataset": "run/output.bp",
                    }
                ],
            }
        ]

    def grouped_variables_by_source_dataset(self, **kwargs):
        self.file_calls.append(kwargs)
        return [
            {
                "name": "run/output",
                "source_dataset": "run/output.bp",
                "file_count": 3,
                "variables": [
                    {
                        "id": "energy",
                        "name": "energy",
                        "label": "energy",
                        "path": "energy",
                        "source_dataset": "run/output.bp",
                    }
                ],
            }
        ]

    def variable_min_max_summary(self, variable_id, **kwargs):
        self.source_summary_calls.append((variable_id, kwargs))
        return {
            "variable": variable_id,
            "num_sources": 1,
            "global_min": "1",
            "global_max": 4,
            "mean_min": 1.5,
            "mean_max": 3.5,
            "median_min": 1.5,
            "median_max": 3.5,
            "source_representation": {
                "id": "source",
                "label": "Source coefficients",
                "kind": "source",
                "data_model": "m3dc1_element_basis_coefficients",
                "shape": "27894 × 20",
                "num_frames": "51",
                "num_sources": "1",
                "global_min": "-5.6e9",
                "global_max": "1.3e10",
                "mean_min": "-5.6e9",
                "mean_max": "1.3e10",
                "median_min": "-5.6e9",
                "median_max": "1.3e10",
            },
            "derived_representations": [
                {
                    "id": "scalar_field",
                    "label": "Derived scalar field",
                    "kind": "derived",
                    "data_model": "m3dc1_regular_rz_grid",
                    "source_data_model": (
                        "m3dc1_element_basis_coefficients"
                    ),
                    "shape": "256 × 256",
                    "axes": "R × Z",
                    "num_frames": "51",
                    "num_sources": "1",
                    "global_min": "-0.02",
                    "global_max": "3.56",
                    "mean_min": "-0.01",
                    "mean_max": "3.0",
                    "median_min": "-0.01",
                    "median_max": "3.1",
                }
            ],
            "sources": [
                {
                    "source_label": "run/output",
                    "variable_id": variable_id,
                    "variable_name": "energy",
                    "variable_type": "variable",
                    "variable_path": "energy",
                    "source_dataset": "run/output.bp",
                    "source_datasets": ["run/output.bp"],
                    "files": ["output.bp"],
                    "producer": "run",
                    "casename": "case-a",
                    "file": "output.bp",
                    "num_timesteps": 34,
                    "min": "1",
                    "max": 4,
                }
            ],
        }

    def source_for_visualization(
        self, variable_id, visualization_name, **kwargs
    ):
        self.source_lookup_calls.append((variable_id, visualization_name, kwargs))
        return {
            "source_label": "run/output",
            "variable_id": variable_id,
            "source_dataset": "run/output.bp",
            "producer": "run",
            "casename": "case-a",
            "file": "output.bp",
            "visualization_name": visualization_name,
        }

    def source_restriction_summary(self, queries):
        self.source_restriction_calls.append(queries)
        return {"filter": {"producer": "run"}, "count": 2}


class FakeCatalogBackend:
    def __init__(
        self,
        navigation=None,
        status=None,
        source_summary=None,
        source=None,
        source_restriction=None,
    ):
        self.navigation = navigation or []
        self.status = status or BackendStatus(ok=True)
        self.source_summary = source_summary or dict(SOURCE_SUMMARY)
        self.source = source
        self.source_restriction = source_restriction or {"query": {}, "count": 0}
        self.requests = []
        self.source_summary_requests = []
        self.source_lookup_requests = []
        self.source_restriction_requests = []

    def get_navigation(self, request):
        self.requests.append(request)
        return self.navigation

    def get_status(self):
        return self.status

    def get_source_summary(self, request):
        self.source_summary_requests.append(request)
        return self.source_summary

    def find_source(self, request):
        self.source_lookup_requests.append(request)
        return self.source

    def resolve_source_restriction(self, request):
        self.source_restriction_requests.append(request)
        return self.source_restriction


class RecordingEvent:
    def __init__(self):
        self.callbacks = []

    def add(self, callback):
        self.callbacks.append(callback)


class RecordingController:
    def __init__(self):
        self.actions = {}
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

    def change(self, *_names):
        def register(callback):
            for name in _names:
                self.change_callbacks.setdefault(name, []).append(callback)
            return callback

        return register


class LocalCampaignBackendTests(unittest.TestCase):
    def test_variable_navigation_normalizes_local_groups(self):
        db = RecordingCampaignDb()
        backend = LocalCampaignBackend(db)

        navigation = backend.get_navigation(
            {
                "view": "variables",
                "query": {"producer": "run"},
                "only_visualized": True,
            }
        )

        self.assertEqual(navigation, VARIABLE_NAVIGATION)
        self.assertEqual(
            db.variable_calls,
            [
                {
                    "extra_filter": {"producer": "run"},
                    "only_visualized": True,
                }
            ],
        )

    def test_file_navigation_preserves_group_metadata(self):
        db = RecordingCampaignDb()
        backend = LocalCampaignBackend(db)

        navigation = backend.get_navigation(
            {"view": "files", "query": {}, "only_visualized": False}
        )

        self.assertEqual(
            db.file_calls,
            [{"extra_filter": None, "only_visualized": False}],
        )
        self.assertEqual(navigation[0]["id"], "file:run/output")
        self.assertEqual(navigation[0]["resource"]["file_count"], 3)
        self.assertEqual(
            navigation[0]["children"][0]["resource"]["source_dataset"],
            "run/output.bp",
        )

    def test_status_hides_campaign_db_implementation(self):
        db = RecordingCampaignDb()
        db.ok = False
        db.last_error = "sidecar unavailable"

        self.assertEqual(
            LocalCampaignBackend(db).get_status(),
            BackendStatus(ok=False, error="sidecar unavailable"),
        )

    def test_source_summary_normalizes_rows_and_assigns_stable_opaque_ids(self):
        db = RecordingCampaignDb()
        backend = LocalCampaignBackend(db)
        request = {"variable_id": "energy", "query": {"producer": "run"}}

        first = backend.get_source_summary(request)
        second = backend.get_source_summary(request)
        other_variable = backend.get_source_summary(
            {"variable_id": "temperature", "query": {"producer": "run"}}
        )

        self.assertEqual(first["variable_id"], "energy")
        self.assertEqual(first["global_min"], 1.0)
        self.assertEqual(first["sources"][0]["minimum"], 1.0)
        self.assertEqual(first["sources"][0]["maximum"], 4.0)
        self.assertEqual(first["sources"][0]["label"], "run/output")
        self.assertEqual(first["sources"][0]["num_timesteps"], 34)
        self.assertEqual(
            first["source_representation"]["data_model"],
            "m3dc1_element_basis_coefficients",
        )
        self.assertEqual(
            first["source_representation"]["global_min"],
            -5.6e9,
        )
        self.assertEqual(
            first["derived_representations"][0]["data_model"],
            "m3dc1_regular_rz_grid",
        )
        self.assertEqual(
            first["derived_representations"][0]["global_max"],
            3.56,
        )
        self.assertTrue(
            first["sources"][0]["id"].startswith("local-source:v1:")
        )
        self.assertEqual(
            first["sources"][0]["id"],
            second["sources"][0]["id"],
        )
        self.assertEqual(
            first["sources"][0]["id"],
            other_variable["sources"][0]["id"],
        )
        self.assertEqual(
            db.source_summary_calls,
            [
                ("energy", {"extra_filter": {"producer": "run"}}),
                ("energy", {"extra_filter": {"producer": "run"}}),
                ("temperature", {"extra_filter": {"producer": "run"}}),
            ],
        )

    def test_source_lookup_uses_the_same_stable_identity(self):
        db = RecordingCampaignDb()
        backend = LocalCampaignBackend(db)

        source = backend.find_source(
            {
                "variable_id": "energy",
                "visualization_name": "timeseries",
                "query": {"producer": "run"},
            }
        )
        summary_source = backend.get_source_summary(
            {"variable_id": "energy", "query": {}}
        )["sources"][0]

        self.assertIsNotNone(source)
        self.assertEqual(source["id"], summary_source["id"])
        self.assertEqual(
            db.source_lookup_calls,
            [
                (
                    "energy",
                    "timeseries",
                    {"extra_filter": {"producer": "run"}},
                )
            ],
        )

    def test_source_restriction_hides_local_result_shape(self):
        db = RecordingCampaignDb()
        backend = LocalCampaignBackend(db)
        queries = [{"producer": "run"}]

        result = backend.resolve_source_restriction({"queries": queries})

        self.assertEqual(result, {"query": {"producer": "run"}, "count": 2})
        self.assertEqual(db.source_restriction_calls, [queries])


class BackendInjectionTests(unittest.TestCase):
    @staticmethod
    def provenance_node_shapes(nodes):
        return [
            {key: node[key] for key in ("id", "kind", "label", "shape")}
            for node in nodes
        ]

    def test_application_delegates_to_explicit_backend(self):
        source = {"id": "remote-source:7", "label": "run/output"}
        backend = FakeCatalogBackend(
            VARIABLE_NAVIGATION,
            BackendStatus(ok=False, error="remote unavailable"),
            source=source,
            source_restriction={"query": {"producer": "run"}, "count": 2},
        )
        application = PulsarApplication(backend=backend)
        request = {"view": "variables", "query": {}, "only_visualized": False}

        self.assertIs(application.get_navigation(request), VARIABLE_NAVIGATION)
        self.assertEqual(backend.requests, [request])
        self.assertEqual(
            application.get_backend_status(),
            BackendStatus(ok=False, error="remote unavailable"),
        )
        source_request = {"variable_id": "energy", "query": {}}
        self.assertEqual(application.get_source_summary(source_request), SOURCE_SUMMARY)
        self.assertEqual(backend.source_summary_requests, [source_request])
        lookup_request = {
            "variable_id": "energy",
            "visualization_name": "timeseries",
            "query": {},
        }
        self.assertIs(application.find_source(lookup_request), source)
        self.assertEqual(backend.source_lookup_requests, [lookup_request])
        restriction_request = {"queries": [{"producer": "run"}]}
        self.assertEqual(
            application.resolve_source_restriction(restriction_request),
            {"query": {"producer": "run"}, "count": 2},
        )
        self.assertEqual(
            backend.source_restriction_requests,
            [restriction_request],
        )

    def test_controller_catalog_refresh_uses_injected_backend(self):
        backend = FakeCatalogBackend(VARIABLE_NAVIGATION)
        state = RecordingState(
            queryFilter={},
            querySourceRestrictionFilter={},
            showOnlyVisualizedVars=False,
            variablePaneView="variables",
            variableGroupCollapsed={},
            variableGroupCollapsedByView={"variables": {}, "files": {}},
        )
        server = SimpleNamespace(state=state, controller=RecordingController())
        db = SimpleNamespace(ok=False, last_error="must not drive catalog refresh")

        refresh = attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        refresh()

        self.assertEqual(state.variableNames, ["energy"])
        self.assertEqual(state.variableLabelsById, {"energy": "energy"})
        self.assertTrue(state.dbOk)
        self.assertEqual(state.dbStatus, "Connected")
        self.assertEqual(
            backend.requests,
            [
                {
                    "view": "variables",
                    "query": {},
                    "only_visualized": False,
                    "parent_id": None,
                }
            ],
        )

    def test_controller_source_panel_uses_injected_backend(self):
        backend = FakeCatalogBackend(source_summary=dict(SOURCE_SUMMARY))
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        init_state(state, db)
        state.variableLabelsById = {"energy": "Energy"}
        server = SimpleNamespace(state=state, controller=RecordingController())

        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        state.change_callbacks["selectedVar"][0]("energy")

        self.assertEqual(
            backend.source_summary_requests,
            [{"variable_id": "energy", "query": {}}],
        )
        self.assertEqual(state.detailsSelectedVarId, "energy")
        self.assertEqual(state.detailsNumSources, 0)
        self.assertEqual(state.detailsGlobalMin, "1")
        self.assertEqual(state.detailsGlobalMax, "4")
        self.assertEqual(
            state.detailsSourceRepresentation["label"],
            "Source coefficients",
        )
        self.assertEqual(
            state.detailsDerivedRepresentations[0]["label"],
            "Derived scalar field",
        )
        self.assertEqual(
            state.detailsDerivedRepresentations[0]["global_max"],
            "3.56",
        )

    def test_controller_details_show_variable_provenance_for_selected_source(self):
        backend = FakeCatalogBackend(source_summary=source_summary_with_one_source())
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        init_state(state, db)
        state.variableLabelsById = {"energy": "Energy"}
        server = SimpleNamespace(state=state, controller=RecordingController())

        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        state.change_callbacks["selectedVar"][0]("energy")

        self.assertEqual(state.detailsProvenanceKind, "variable")
        self.assertEqual(state.detailsProvenanceChain, "Energy --> run/output")
        self.assertEqual(state.detailsProvenanceCompact, "Energy : run/output")
        self.assertEqual(
            self.provenance_node_shapes(state.detailsProvenanceNodes),
            [
                {
                    "id": "variable",
                    "kind": "variable",
                    "label": "Energy",
                    "shape": "box",
                },
                {
                    "id": "source",
                    "kind": "source",
                    "label": "run/output",
                    "shape": "cylinder",
                },
            ],
        )
        self.assertFalse(state.detailsProvenanceNodes[0]["expanded"])

        server.controller.actions["toggle_provenance_node_details"]("variable")
        self.assertEqual(state.detailsProvenanceExpanded, {"variable": True})
        self.assertTrue(state.detailsProvenanceNodes[0]["expanded"])
        self.assertTrue(state.detailsProvenanceGraph[0]["entity"]["expanded"])
        self.assertFalse(state.detailsProvenanceNodes[1]["expanded"])

        server.controller.actions["toggle_provenance_node_details"]("variable")
        self.assertEqual(state.detailsProvenanceExpanded, {"variable": False})
        self.assertFalse(state.detailsProvenanceNodes[0]["expanded"])
        self.assertFalse(state.detailsProvenanceGraph[0]["entity"]["expanded"])

    def test_controller_details_show_visualization_provenance_in_visualization_context(self):
        backend = FakeCatalogBackend(source_summary=source_summary_with_one_source())
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        db.distinct_visualization_names_for_variable = (
            lambda *_args, **_kwargs: ["contour", "heatmap"]
        )

        def first_movie_tile(*_args, **kwargs):
            vis = (
                "heatmap"
                if "heatmap" in repr(kwargs.get("extra_filter"))
                else "contour"
            )
            return [
                {
                    "variable_id": "energy",
                    "variable_name": "Energy",
                    "visualization_name": vis,
                    "visualization_kind": "scalar_field",
                    "source_dataset": "run/output.bp",
                    "status": "ok",
                    "visualization_activity_provenance": {
                        "activity_kind": "visualization",
                        "activity_operation": "scalar_field",
                        "activity_metadata": {
                            "steps": [0, 1],
                            "rendering_parameters": {"dpi": 120},
                        },
                        "workflow_plan": {
                            "label": "MHD visualization workflow",
                            "location": (
                                "plans/render_adios_visualizations_to_campaign.py"
                            ),
                            "details": {
                                "workflow": "render_visualizations",
                                "implementation_dataset": (
                                    "plans/"
                                    "render_adios_visualizations_to_campaign.py"
                                ),
                                "selection": {"variables": ["Energy"]},
                                "parameters": {
                                    "visualization_type": "scalar_field"
                                },
                                "output_policy": {"replace": True},
                            },
                        },
                        "activity_agent": {
                            "label": "Matplotlib",
                            "type": "SoftwareAgent",
                            "version": "3.10.0",
                        },
                    },
                }
            ]

        db.get_first_movie_tiles_for_variable = first_movie_tile
        init_state(state, db)
        state.variableLabelsById = {"energy": "Energy"}
        server = SimpleNamespace(state=state, controller=RecordingController())

        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        state.change_callbacks["selectedVar"][0]("energy")

        self.assertEqual(state.detailsProvenanceKind, "variable")
        self.assertEqual(state.detailsProvenanceChain, "Energy --> run/output")
        self.assertEqual(state.detailsProvenanceCompact, "Energy : run/output")

        owner = server.controller.actions["pick_var"].__self__
        owner.update_selected_var_panels(
            "energy",
            include_visualization_provenance=True,
            preferred_visualization="heatmap",
        )

        self.assertEqual(state.detailsProvenanceKind, "visualization")
        self.assertEqual(
            state.detailsProvenanceChain,
            "heatmap --> visualization: scalar_field --> Energy --> run/output",
        )
        self.assertEqual(
            state.detailsProvenanceCompact,
            "heatmap = scalar_field(Energy) : run/output",
        )
        self.assertEqual(
            self.provenance_node_shapes(state.detailsProvenanceNodes),
            [
                {
                    "id": "visualization",
                    "kind": "visualization",
                    "label": "heatmap",
                    "shape": "box",
                },
                {
                    "id": "activity",
                    "kind": "activity",
                    "label": "visualization: scalar_field",
                    "shape": "box",
                },
                {
                    "id": "input-0",
                    "kind": "variable",
                    "label": "Energy",
                    "shape": "box",
                },
                {
                    "id": "source",
                    "kind": "source",
                    "label": "run/output",
                    "shape": "cylinder",
                },
            ],
        )
        self.assertEqual(
            [segment["type"] for segment in state.detailsProvenanceGraph],
            ["node", "arrow", "plan_group", "branches"],
        )
        plan_segment = state.detailsProvenanceGraph[2]
        self.assertEqual(
            plan_segment["selected_action"]["node"]["label"],
            "visualization: scalar_field",
        )
        self.assertEqual(
            plan_segment["plan"]["label"],
            "MHD visualization workflow",
        )
        self.assertEqual(
            plan_segment["selected_action"]["agent"]["label"],
            "Matplotlib",
        )
        visualization_details = state.detailsProvenanceNodes[1]["details"]
        self.assertEqual(
            next(row for row in visualization_details if row["label"] == "Steps")[
                "value"
            ],
            "[0, 1]",
        )

        plugin_tile = {
            "variable_id": "energy",
            "variable_name": "Energy",
            "visualization_name": "plugin:profile_timeseries",
            "selected_visualization": "plugin:profile_timeseries",
            "display_title": "Energy profile time series",
            "media_type": "plot1d",
            "source_dataset": "run/output.bp",
            "status": "ok",
            "visualization_variables": [
                {
                    "name": "Energy",
                    "variable_id": "energy",
                    "source_dataset": "run/output.bp",
                    "roles": ["source"],
                }
            ],
            "visualization_activity_provenance": {
                "activity_kind": "visualization",
                "activity_operation": "profile_timeseries",
                "workflow_plan": {
                    "label": "Scalar/profile time series workflow"
                },
                "activity_agent": {
                    "label": "Scalar/profile time series",
                    "type": "SoftwareAgent",
                    "version": "1.0",
                },
            },
        }
        state.gridCells = [plugin_tile]
        state.activeGridCell = 0
        owner.update_selected_var_panels(
            "energy",
            include_visualization_provenance=True,
            preferred_visualization="plugin:profile_timeseries",
        )

        self.assertEqual(
            state.detailsProvenanceChain,
            "1D plot --> visualization: profile_timeseries --> Energy --> run/output",
        )
        self.assertEqual(
            state.detailsProvenanceCompact,
            "1D plot = profile_timeseries(Energy) : run/output.bp",
        )
        output_node = state.detailsProvenanceNodes[0]
        self.assertEqual(output_node["label"], "plugin:profile_timeseries")
        self.assertEqual(output_node["display_label"], "1D plot")
        self.assertEqual(
            output_node["secondary_label"],
            "Energy profile time series",
        )
        plugin_plan = state.detailsProvenanceGraph[2]
        self.assertEqual(plugin_plan["type"], "plan_group")
        self.assertEqual(
            plugin_plan["plan"]["label"],
            "Scalar/profile time series workflow",
        )
        self.assertEqual(
            plugin_plan["selected_action"]["agent"]["label"],
            "Scalar/profile time series",
        )

    def test_controller_details_show_streamline_activity_inputs(self):
        backend = FakeCatalogBackend(source_summary=source_summary_with_one_source())
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        db.distinct_visualization_names_for_variable = (
            lambda *_args, **_kwargs: ["velocity_streamlines"]
        )
        db.get_first_movie_tiles_for_variable = lambda *_args, **_kwargs: [
            {
                "variable_id": "vx",
                "variable_name": "vx",
                "visualization_name": "velocity_streamlines",
                "source_dataset": "run/output.bp",
                "status": "ok",
                "visualization_sequence_metadata": {
                    "visualization_type": "streamlines",
                },
                "visualization_variables": [
                    {"name": "vx", "roles": ["streamline_0"]},
                    {"name": "vy", "roles": ["streamline_1"]},
                    {"name": "speed", "roles": ["color"]},
                ],
            }
        ]
        init_state(state, db)
        state.variableLabelsById = {"energy": "velocity"}
        server = SimpleNamespace(state=state, controller=RecordingController())

        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        owner = server.controller.actions["pick_var"].__self__
        owner.update_selected_var_panels(
            "energy",
            include_visualization_provenance=True,
        )

        self.assertEqual(state.detailsProvenanceKind, "visualization")
        self.assertEqual(
            state.detailsProvenanceChain,
            "velocity_streamlines --> visualization: streamlines --> vx + vy + speed --> run/output",
        )
        self.assertEqual(
            state.detailsProvenanceCompact,
            "velocity_streamlines = streamlines(vx + vy + speed) : run/output",
        )
        self.assertEqual(
            [node["kind"] for node in state.detailsProvenanceNodes],
            ["visualization", "activity", "variables", "source"],
        )
        action_details = state.detailsProvenanceNodes[1]["details"]
        action_labels = [row["label"] for row in action_details]
        input_detail = next(row for row in action_details if row["label"] == "Inputs")
        self.assertEqual(input_detail["kind"], "input_table")
        self.assertNotIn("run/output", str(input_detail["rows"]))
        self.assertEqual(
            input_detail["rows"],
            [
                {"variable": "vx", "role": "streamline-x"},
                {"variable": "vy", "role": "streamline-y"},
                {"variable": "speed", "role": "color-by"},
            ],
        )
        self.assertNotIn("Input roles", action_labels)
        self.assertEqual(state.detailsProvenanceNodes[2]["shape"], "group")
        self.assertEqual(
            [item["label"] for item in state.detailsProvenanceNodes[2]["items"]],
            ["vx", "vy", "speed"],
        )
        for item in state.detailsProvenanceNodes[2]["items"]:
            self.assertNotIn(
                "Roles",
                [row["label"] for row in item.get("details", [])],
            )
        self.assertEqual(
            [segment["type"] for segment in state.detailsProvenanceGraph],
            ["node", "arrow", "node", "branches"],
        )
        branch_segment = state.detailsProvenanceGraph[-1]
        self.assertEqual(
            [branch["input"]["label"] for branch in branch_segment["branches"]],
            ["vx", "vy", "speed"],
        )
        self.assertEqual(branch_segment["shared_source"]["label"], "run/output")

    def test_controller_details_show_derived_activity_provenance(self):
        summary = source_summary_with_one_source()
        summary["variable_id"] = "div_b"
        source = summary["sources"][0]
        source.update(
            {
                "variable_id": "div_b",
                "variable_name": "div_b",
                "variable_path": "run/analysis.bp/div_b",
                "source_dataset": "run/analysis.bp",
                "activity_provenance": {
                    "activity_uuid": "divergence",
                    "activity_kind": "quantity_of_interest",
                    "activity_operation": "divergence",
                    "workflow_plan": {
                        "label": "MHD derived-variable workflow",
                        "location": "plans/adios_derived_variables.py",
                        "details": {
                            "workflow": "derived_variables",
                            "implementation_dataset": (
                                "plans/adios_derived_variables.py"
                            ),
                            "selection": {
                                "datasets": ["run/analysis.bp"]
                            },
                            "parameters": {
                                "discretization": "numpy.gradient"
                            },
                        },
                        "activities": [
                            {
                                "id": "divergence",
                                "activity_kind": "quantity_of_interest",
                                "activity_operation": "divergence",
                                "activity_agent": {
                                    "label": "NumPy",
                                    "type": "SoftwareAgent",
                                    "version": "2.0.0",
                                },
                                "inputs": [
                                    {
                                        "name": "bx",
                                        "roles": ["magnetic_x"],
                                    },
                                    {
                                        "name": "by",
                                        "roles": ["magnetic_y"],
                                    },
                                ],
                                "outputs": [
                                    {
                                        "dataset": "run/analysis.bp",
                                        "variable": "div_b",
                                    }
                                ],
                            },
                            {
                                "id": "gradient",
                                "activity_kind": "quantity_of_interest",
                                "activity_operation": "gradient_magnitude",
                                "activity_metadata": {
                                    "script_dataset": (
                                        "plans/adios_derived_variables.py"
                                    )
                                },
                                "activity_agent": {
                                    "label": "NumPy",
                                    "type": "SoftwareAgent",
                                    "version": "2.0.0",
                                },
                                "inputs": [
                                    {
                                        "name": "rho",
                                        "roles": ["density"],
                                    }
                                ],
                                "outputs": [
                                    {
                                        "dataset": "run/analysis.bp",
                                        "variable": "grad_rho_abs",
                                    }
                                ],
                            },
                        ],
                    },
                    "activity_agent": {
                        "label": "NumPy",
                        "type": "SoftwareAgent",
                        "version": "2.0.0",
                    },
                    "inputs": [
                        {"name": "bx", "roles": ["magnetic_x"]},
                        {"name": "by", "roles": ["magnetic_y"]},
                    ],
                },
            }
        )
        backend = FakeCatalogBackend(source_summary=summary)
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        init_state(state, db)
        state.variableLabelsById = {"div_b": "div_b"}
        server = SimpleNamespace(state=state, controller=RecordingController())

        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        state.change_callbacks["selectedVar"][0]("div_b")

        self.assertEqual(state.detailsProvenanceKind, "activity")
        self.assertEqual(
            state.detailsProvenanceChain,
            "div_b --> derived: divergence --> bx + by --> run/output",
        )
        self.assertEqual(
            state.detailsProvenanceCompact,
            "div_b = divergence(bx + by) : run/output",
        )
        self.assertEqual(
            [node["kind"] for node in state.detailsProvenanceNodes],
            ["variable", "activity", "variables", "source"],
        )
        self.assertEqual(state.detailsProvenanceNodes[1]["shape"], "box")
        action_details = state.detailsProvenanceNodes[1]["details"]
        action_labels = [row["label"] for row in action_details]
        input_detail = next(row for row in action_details if row["label"] == "Inputs")
        self.assertEqual(input_detail["kind"], "input_table")
        self.assertNotIn("run/output", str(input_detail["rows"]))
        self.assertEqual(
            input_detail["rows"],
            [
                {"variable": "bx", "role": "magnetic-x"},
                {"variable": "by", "role": "magnetic-y"},
            ],
        )
        self.assertNotIn("Input roles", action_labels)
        self.assertEqual(state.detailsProvenanceNodes[2]["shape"], "group")
        for item in state.detailsProvenanceNodes[2]["items"]:
            self.assertNotIn(
                "Roles",
                [row["label"] for row in item.get("details", [])],
            )
        self.assertEqual(
            [segment["type"] for segment in state.detailsProvenanceGraph],
            ["node", "arrow", "plan_group", "branches"],
        )
        plan_segment = state.detailsProvenanceGraph[2]
        self.assertEqual(
            plan_segment["selected_action"]["node"]["label"],
            "derived: divergence",
        )
        self.assertEqual(
            plan_segment["selected_action"]["agent"]["label"],
            "NumPy",
        )
        self.assertNotIn("other_actions", plan_segment)
        self.assertNotIn("gradient_magnitude", str(plan_segment))
        plan_node = plan_segment["plan"]
        self.assertEqual(plan_node["kind"], "plan")
        self.assertEqual(plan_node["label"], "MHD derived-variable workflow")
        self.assertEqual(
            {row["label"]: row["value"] for row in plan_node["details"]},
            {
                "Workflow": "derived_variables",
                "Implementation": "plans/adios_derived_variables.py",
                "Location": "plans/adios_derived_variables.py",
                "Selection": '{"datasets": ["run/analysis.bp"]}',
                "Parameters": '{"discretization": "numpy.gradient"}',
            },
        )
        agent_node = plan_segment["selected_action"]["agent"]
        self.assertEqual(agent_node["kind"], "agent")
        self.assertEqual(agent_node["label"], "NumPy")
        self.assertEqual(
            {row["label"]: row["value"] for row in agent_node["details"]},
            {"Type": "SoftwareAgent", "Version": "2.0.0"},
        )

        server.controller.actions["toggle_provenance_node_details"](
            "activity-plan"
        )
        plan_segment = state.detailsProvenanceGraph[2]
        self.assertTrue(plan_segment["plan"]["expanded"])

    def test_controller_visualization_extends_analysis_provenance_to_output_source(self):
        summary = source_summary_with_one_source()
        summary["variable_id"] = "grad_rho_abs"
        source = summary["sources"][0]
        source.update(
            {
                "source_label": "hll_128/analysis.bp",
                "variable_id": "grad_rho_abs",
                "variable_name": "grad_rho_abs",
                "variable_path": "hll_128/analysis.bp/grad_rho_abs",
                "source_dataset": "hll_128/analysis.bp",
                "file": "analysis.bp",
                "activity_provenance": {
                    "activity_kind": "quantity_of_interest",
                    "activity_operation": "gradient_magnitude",
                    "inputs": [
                        {
                            "name": "rho",
                            "roles": ["density"],
                            "source_dataset": "hll_128/output.bp",
                        },
                    ],
                },
            }
        )
        backend = FakeCatalogBackend(source_summary=summary)
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        db.distinct_visualization_names_for_variable = (
            lambda *_args, **_kwargs: ["grad_rho_abs_heatmap"]
        )
        db.get_first_movie_tiles_for_variable = lambda *_args, **_kwargs: [
            {
                "variable_id": "grad_rho_abs",
                "variable_name": "grad_rho_abs",
                "visualization_name": "grad_rho_abs_heatmap",
                "source_dataset": "hll_128/analysis.bp",
                "status": "ok",
                "visualization_sequence_metadata": {
                    "visualization_type": "heatmap",
                },
                "visualization_variables": [
                    {
                        "name": "grad_rho_abs",
                        "roles": ["color-by"],
                        "source_dataset": "hll_128/analysis.bp",
                    },
                ],
            }
        ]
        init_state(state, db)
        state.variableLabelsById = {"grad_rho_abs": "grad_rho_abs"}
        server = SimpleNamespace(state=state, controller=RecordingController())

        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        state.change_callbacks["selectedVar"][0]("grad_rho_abs")

        self.assertEqual(
            state.detailsProvenanceChain,
            "grad_rho_abs --> derived: gradient_magnitude --> rho --> hll_128/output.bp",
        )
        self.assertEqual(
            state.detailsProvenanceCompact,
            "grad_rho_abs = gradient_magnitude(rho) : hll_128/output.bp",
        )

        owner = server.controller.actions["pick_var"].__self__
        owner.update_selected_var_panels(
            "grad_rho_abs",
            include_visualization_provenance=True,
            preferred_visualization="grad_rho_abs_heatmap",
        )

        self.assertEqual(state.detailsProvenanceKind, "visualization")
        self.assertEqual(
            state.detailsProvenanceChain,
            "grad_rho_abs_heatmap --> visualization: heatmap --> grad_rho_abs --> derived: gradient_magnitude --> rho --> hll_128/output.bp",
        )
        self.assertEqual(
            state.detailsProvenanceCompact,
            "grad_rho_abs_heatmap = heatmap(grad_rho_abs = gradient_magnitude(rho)) : hll_128/output.bp",
        )
        self.assertEqual(
            [node["kind"] for node in state.detailsProvenanceNodes],
            [
                "visualization",
                "activity",
                "variable",
                "source",
                "activity",
                "variable",
                "source",
            ],
        )
        visualization_details = state.detailsProvenanceNodes[1]["details"]
        visualization_input_detail = next(
            row for row in visualization_details if row["label"] == "Inputs"
        )
        self.assertEqual(visualization_input_detail["kind"], "input_table")
        self.assertEqual(
            visualization_input_detail["rows"],
            [{"variable": "grad_rho_abs", "role": "color-by"}],
        )
        self.assertNotIn("hll_128/analysis.bp", str(visualization_input_detail["rows"]))
        self.assertNotIn(
            "Input roles",
            [row["label"] for row in visualization_details],
        )
        derived_details = state.detailsProvenanceNodes[4]["details"]
        derived_input_detail = next(
            row for row in derived_details if row["label"] == "Inputs"
        )
        self.assertEqual(derived_input_detail["kind"], "input_table")
        self.assertEqual(
            derived_input_detail["rows"],
            [{"variable": "rho", "role": "density"}],
        )
        self.assertNotIn("hll_128/output.bp", str(derived_input_detail["rows"]))
        self.assertNotIn("Input roles", [row["label"] for row in derived_details])
        self.assertNotIn(
            "Roles",
            [row["label"] for row in state.detailsProvenanceNodes[2]["details"]],
        )
        self.assertNotIn(
            "Roles",
            [row["label"] for row in state.detailsProvenanceNodes[5]["details"]],
        )
        self.assertEqual(
            state.detailsProvenanceNodes[-1]["label"],
            "hll_128/output.bp",
        )
        self.assertEqual(
            [segment["type"] for segment in state.detailsProvenanceGraph],
            [
                "node",
                "arrow",
                "node",
                "arrow",
                "entity_source",
                "arrow",
                "node",
                "branches",
            ],
        )
        self.assertEqual(
            [
                segment.get("relation", "")
                for segment in state.detailsProvenanceGraph
                if segment["type"] in {"arrow", "branches"}
            ],
            ["", "uses", "", "uses"],
        )
        self.assertEqual(
            state.detailsProvenanceNodes[0]["display_label"],
            "Grad rho abs heatmap",
        )
        self.assertEqual(
            state.detailsProvenanceNodes[1]["display_label"],
            "Heatmap",
        )
        self.assertEqual(
            state.detailsProvenanceNodes[4]["display_label"],
            "Gradient magnitude",
        )
        visualization_input_segment = state.detailsProvenanceGraph[4]
        self.assertEqual(
            visualization_input_segment["entity"]["label"],
            "grad_rho_abs",
        )
        self.assertEqual(
            visualization_input_segment["source"]["label"],
            "hll_128/analysis.bp",
        )
        self.assertEqual(
            state.detailsProvenanceGraph[-1]["branches"][0]["source"]["label"],
            "hll_128/output.bp",
        )

    def test_controller_source_restriction_uses_injected_backend(self):
        backend = FakeCatalogBackend(
            source_restriction={"query": {"producer": "run"}, "count": 2}
        )
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        init_state(state, db)
        state.queryText = "source(producer == 'run')"
        server = SimpleNamespace(state=state, controller=RecordingController())

        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )
        server.controller.actions["run_query"]()

        self.assertEqual(
            backend.source_restriction_requests,
            [{"queries": [{"producer": "run"}]}],
        )
        self.assertEqual(state.querySourceRestrictionFilter, {"producer": "run"})
        self.assertEqual(state.querySourceRestrictionCount, 2)
        self.assertEqual(state.queryStatus, "Query OK · 2 source runs")

    def test_invalid_query_preserves_the_previous_active_filter(self):
        backend = FakeCatalogBackend(VARIABLE_NAVIGATION)
        state = RecordingState()
        db = SimpleNamespace(ok=True, last_error="")
        init_state(state, db)
        state.queryText = "var == 'energy'"
        server = SimpleNamespace(state=state, controller=RecordingController())
        attach_controllers(
            server=server,
            backend=backend,
            db=db,
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )

        self.assertTrue(server.controller.actions["run_query"]())
        self.assertEqual(state.queryFilter, {"variable_name": "energy"})
        self.assertEqual(state.queryViewLabel, "var == 'energy'")
        state.activeViewerActionPlan = {"type": "catalog.query"}
        state.activeNaturalLanguageQuery = "show energy"

        state.queryText = "var =="
        self.assertFalse(server.controller.actions["run_query"]())

        self.assertEqual(state.queryFilter, {"variable_name": "energy"})
        self.assertEqual(state.queryViewLabel, "var == 'energy'")
        self.assertEqual(
            state.activeViewerActionPlan,
            {"type": "catalog.query"},
        )
        self.assertEqual(state.activeNaturalLanguageQuery, "show energy")
        self.assertEqual(
            state.queryStatus,
            "Query ERROR · active query unchanged",
        )


if __name__ == "__main__":
    unittest.main()
