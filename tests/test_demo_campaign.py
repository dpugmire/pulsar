import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from db import CampaignDb
from ingest_campaign import (
    _load_activity_provenance_index,
    _load_unified_representation_index,
    _load_visualization_api_index,
    parse_campaign,
)
from plugin_runtime import render_plugin_tile
from pulsar.demo_campaign import (
    DEMO_SOURCES,
    DEMO_VARIABLES_1D,
    DEMO_VARIABLES_2D,
    DEMO_VARIABLES_SCALAR,
    DemoConfig,
    analytical_step,
    demo_sources,
    generate_demo_campaign,
    temporary_demo_campaign,
)
from sqlite_store import open_sqlite_collection


def _require_unified_demo_api():
    hpc_campaign = pytest.importorskip("hpc_campaign")
    required = (
        "add_variable",
        "add_image_sequence",
        "add_activity",
        "data",
        "set_schema",
    )
    missing = [name for name in required if not hasattr(hpc_campaign.Manager, name)]
    if missing:
        pytest.skip(
            "installed hpc-campaign does not provide unified demo API "
            f"(missing: {', '.join(missing)})"
        )


def test_analytical_fields_are_deterministic_and_time_varying():
    config = DemoConfig(steps=4, samples_1d=24, shape_2d=(10, 12))
    first = analytical_step(DEMO_SOURCES[0], 0, config)
    again = analytical_step(DEMO_SOURCES[0], 0, config)
    later = analytical_step(DEMO_SOURCES[0], 1, config)

    assert set(first) == set(
        (*DEMO_VARIABLES_1D, *DEMO_VARIABLES_SCALAR, *DEMO_VARIABLES_2D)
    )
    for name in DEMO_VARIABLES_1D:
        assert first[name].shape == (24,)
    for name in DEMO_VARIABLES_SCALAR:
        assert first[name].shape == ()
    for name in DEMO_VARIABLES_2D:
        assert first[name].shape == (10, 12)
    for name, values in first.items():
        assert values.dtype == np.float32
        assert np.all(np.isfinite(values))
        np.testing.assert_array_equal(values, again[name])
        assert not np.array_equal(values, later[name])


def test_scalar_moments_track_pulse_position_and_damped_energy():
    config = DemoConfig(steps=8, samples_1d=256, shape_2d=(8, 8))
    source = DEMO_SOURCES[0]
    first = analytical_step(source, 0, config)
    later = analytical_step(source, 1, config)

    assert float(first["scalar/moving_pulse_position"]) == pytest.approx(
        0.2, abs=1e-3
    )
    assert float(later["scalar/moving_pulse_position"]) == pytest.approx(
        0.325, abs=1e-3
    )
    assert float(first["scalar/damped_mode_energy"]) == pytest.approx(
        float(np.mean(first["damped_mode_1d"] ** 2)), rel=1e-6
    )
    assert float(later["scalar/damped_mode_energy"]) < float(
        first["scalar/damped_mode_energy"]
    )


def test_source_parameter_sets_produce_distinct_fields():
    config = DemoConfig(steps=3, samples_1d=16, shape_2d=(8, 8))
    baseline = analytical_step(DEMO_SOURCES[0], 1, config)
    for source in DEMO_SOURCES[1:]:
        candidate = analytical_step(source, 1, config)
        assert any(
            not np.array_equal(baseline[name], candidate[name])
            for name in baseline
        )


def test_demo_config_rejects_degenerate_dimensions():
    with pytest.raises(ValueError, match="steps"):
        DemoConfig(steps=1).validate()
    with pytest.raises(ValueError, match="1D"):
        DemoConfig(samples_1d=1).validate()
    with pytest.raises(ValueError, match="2D"):
        DemoConfig(shape_2d=(8, 1)).validate()
    with pytest.raises(ValueError, match="source count"):
        DemoConfig(source_count=0).validate()
    with pytest.raises(ValueError, match="source count"):
        DemoConfig(source_count=50).validate()


def test_demo_sources_preserve_defaults_and_add_deterministic_variants():
    assert demo_sources(3) == DEMO_SOURCES[:3]
    assert demo_sources(5) == DEMO_SOURCES

    expanded = demo_sources(8)
    assert expanded[:5] == DEMO_SOURCES
    assert [source.name for source in expanded[5:]] == [
        "variant_06",
        "variant_07",
        "variant_08",
    ]
    assert len({source.name for source in demo_sources(49)}) == 49


def test_generated_demo_archive_and_ingestion(tmp_path: Path):
    _require_unified_demo_api()
    config = DemoConfig(
        steps=3,
        samples_1d=16,
        shape_2d=(8, 10),
        source_count=7,
    )
    demo = generate_demo_campaign(tmp_path, config=config)

    assert demo.campaign_path.is_file()
    assert sorted(path.name for path in (tmp_path / "sources").glob("*.bp")) == [
        f"{source.name}.bp"
        for source in sorted(demo_sources(7), key=lambda item: item.name)
    ]

    con = sqlite3.connect(demo.campaign_path)
    try:
        source_count = con.execute(
            "select count(*) from dataset where name like 'sources/%.bp' and deltime = 0"
        ).fetchone()[0]
        variable_count = con.execute(
            "select count(*) from logical_variable"
        ).fetchone()[0]
        chunk_count = con.execute(
            "select count(*) from variable_chunk"
        ).fetchone()[0]
    finally:
        con.close()

    assert source_count == 7
    assert variable_count == 98
    assert chunk_count == 126

    representation_index = _load_unified_representation_index(
        str(demo.campaign_path)
    )
    assert len(representation_index) == 126
    assert {
        entry["item_type"] for entry in representation_index.values()
    } == {"IMAGE", "SCALAR_FIELD"}

    collection = open_sqlite_collection(
        str(demo.campaign_path),
        db_path=str(demo.sidecar_path),
    )
    try:
        parse_campaign(str(demo.campaign_path), collection)
        db = CampaignDb(collection)
        assert set(db.distinct_variable_names()) == set(
            (*DEMO_VARIABLES_1D, *DEMO_VARIABLES_SCALAR, *DEMO_VARIABLES_2D)
        )
        for variable_name in (
            *DEMO_VARIABLES_1D,
            *DEMO_VARIABLES_SCALAR,
            *DEMO_VARIABLES_2D,
        ):
            assert len(db.variable_min_max_summary(variable_name)["sources"]) == 7

        groups = {
            group["name"]: [variable["id"] for variable in group["variables"]]
            for group in db.grouped_variable_names()
        }
        assert groups["Scalar Time Series"] == sorted(DEMO_VARIABLES_SCALAR)

        profile_candidate = db.scalar_plot_candidate(
            "traveling_wave_1d",
            source_filter={"source_dataset": "sources/baseline.bp"},
        )
        assert profile_candidate
        profile_tile = render_plugin_tile(
            str(demo.campaign_path),
            "profile_timeseries",
            profile_candidate,
        )
        assert profile_tile["media_type"] == "plot1d"
        assert profile_tile["plot"]["x_label"] == "adios_step"
        assert len(profile_tile["plot"]["series"]) == 5

        scalar_candidate = db.scalar_plot_candidate(
            "scalar/moving_pulse_position",
            source_filter={"source_dataset": "sources/baseline.bp"},
        )
        assert scalar_candidate
        scalar_tile = render_plugin_tile(
            str(demo.campaign_path),
            "profile_timeseries",
            scalar_candidate,
        )
        assert scalar_tile["media_type"] == "plot1d"
        assert scalar_tile["plot"]["x_label"] == "adios_step"
        assert len(scalar_tile["plot"]["series"]) == 1
        assert all(len(series["y"]) == 3 for series in scalar_tile["plot"]["series"])

        for variable_name in DEMO_VARIABLES_2D:
            assert db.distinct_visualization_names_for_variable(variable_name) == [
                "heatmap",
                "scalar_field",
            ]
            scalar_docs = list(
                collection.find(
                    {
                        "variable_id": variable_name,
                        "variable_type": "scalarField",
                    }
                )
            )
            assert len(scalar_docs) == 21
            assert {doc["frame_index"] for doc in scalar_docs} == {0, 1, 2}
            assert all(doc["association_source"] == "unified-variable" for doc in scalar_docs)

        image_frames, image_total, image_indices, _, _ = (
            db.get_movie_frames_for_stream(
                "moving_blob_2d",
                "heatmap",
                "",
                "",
                source_dataset="sources/baseline.bp",
            )
        )
        assert image_total == 3
        assert image_indices == [0, 1, 2]
        assert all(frame.startswith(b"\x89PNG\r\n\x1a\n") for frame in image_frames)

        scalar_frames, total, frame_indices, time_values, time_mode = (
            db.get_movie_frames_for_stream(
                "moving_blob_2d",
                "scalar_field",
                "",
                "",
                source_dataset="sources/baseline.bp",
            )
        )
        assert total == 3
        assert frame_indices == [0, 1, 2]
        assert time_values == [0.0, 1.0, 2.0]
        assert time_mode == "timestep"
        assert all(frame.startswith(b"\x89PNG\r\n\x1a\n") for frame in scalar_frames)
    finally:
        collection.close()


def test_legacy_visualization_api_archive_is_supported(tmp_path: Path):
    campaign_path = tmp_path / "legacy.aca"
    con = sqlite3.connect(campaign_path)
    try:
        con.executescript(
            """
            create table dataset(
                rowid integer primary key,
                uuid text,
                name text,
                fileformat text,
                deltime integer
            );
            create table visualization_sequence(
                visid integer primary key,
                name text,
                vistype text,
                metadata text
            );
            create table visualization_item(
                visid integer,
                item_order integer,
                item_type text,
                item_uuid text,
                metadata text
            );
            create table visualization_variable(
                visid integer,
                datasetid integer,
                variable_name text,
                role text
            );
            """
        )
        con.execute(
            "insert into dataset(rowid, uuid, name, fileformat, deltime) values (?, ?, ?, ?, ?)",
            (1, "source-uuid", "run/output.bp", "BP", 0),
        )
        con.execute(
            "insert into dataset(rowid, uuid, name, fileformat, deltime) values (?, ?, ?, ?, ?)",
            (2, "item-uuid", "visualizations/pressure/image.0000.png", "IMAGE", 0),
        )
        con.execute(
            "insert into visualization_sequence(visid, name, vistype, metadata) values (?, ?, ?, ?)",
            (1, "pressure/heatmap", "field_2d", "{}"),
        )
        con.execute(
            "insert into visualization_item(visid, item_order, item_type, item_uuid, metadata) values (?, ?, ?, ?, ?)",
            (1, 0, "IMAGE", "item-uuid", "{}"),
        )
        con.execute(
            "insert into visualization_variable(visid, datasetid, variable_name, role) values (?, ?, ?, ?)",
            (1, 1, "pressure", "color-by"),
        )
        con.commit()
    finally:
        con.close()

    assert _load_unified_representation_index(str(campaign_path)) == {}
    visualization_index = _load_visualization_api_index(str(campaign_path))
    assert list(visualization_index) == ["visualizations/pressure/image.0000.png"]
    entry = visualization_index["visualizations/pressure/image.0000.png"]
    assert entry["sequence_name"] == "pressure/heatmap"
    assert entry["visualization_name"] == "heatmap"
    assert entry["visualization_kind"] == "field_2d"
    assert entry["item_type"] == "IMAGE"
    assert entry["display_variables"] == [
        {
            "name": "pressure",
            "roles": ["color-by"],
            "source_dataset": "run/output.bp",
        }
    ]


def test_prov_json_activity_provenance_links_analysis_variables_to_output(tmp_path: Path):
    campaign_path = tmp_path / "prov-json.aca"
    con = sqlite3.connect(campaign_path)
    try:
        con.execute(
            """
            create table provenance_document(
                uuid text primary key,
                name text not null unique,
                format text not null,
                content text not null,
                sha256 text not null,
                active integer not null,
                modtime integer not null
            )
            """
        )
        content = {
            "activity": {
                "hpcid:activity_gradient": {
                    "prov:type": {"$": "hpc:QuantityOfInterest", "type": "xsd:QName"}
                },
                "hpcid:activity_divergence": {
                    "prov:type": {"$": "hpc:QuantityOfInterest", "type": "xsd:QName"}
                },
            },
            "entity": {
                "hpcid:variable_grad": {
                    "prov:type": {"$": "hpc:LogicalVariable", "type": "xsd:QName"},
                    "hpc:datasetName": "hll_128/analysis.bp",
                    "hpc:variable": "grad_rho_abs",
                    "hpc:variableDefinition": "density_gradient_magnitude",
                },
                "hpcid:variable_div": {
                    "prov:type": {"$": "hpc:LogicalVariable", "type": "xsd:QName"},
                    "hpc:datasetName": "hll_128/analysis.bp",
                    "hpc:variable": "div_b",
                    "hpc:variableDefinition": "magnetic_field_divergence",
                },
                "hpcid:variable_rho": {
                    "prov:type": {"$": "hpc:LogicalVariable", "type": "xsd:QName"},
                    "hpc:datasetName": "hll_128/output.bp",
                    "hpc:variable": "rho",
                    "hpc:variableDefinition": "density",
                },
                "hpcid:variable_bx": {
                    "prov:type": {"$": "hpc:LogicalVariable", "type": "xsd:QName"},
                    "hpc:datasetName": "hll_128/output.bp",
                    "hpc:variable": "bx",
                    "hpc:variableDefinition": "magnetic_x",
                },
                "hpcid:variable_by": {
                    "prov:type": {"$": "hpc:LogicalVariable", "type": "xsd:QName"},
                    "hpc:datasetName": "hll_128/output.bp",
                    "hpc:variable": "by",
                    "hpc:variableDefinition": "magnetic_y",
                },
                "hpcid:plan_gradient": {
                    "prov:type": [
                        {"$": "prov:Plan", "type": "xsd:QName"},
                        {"$": "hpc:ActionSpecification", "type": "xsd:QName"},
                    ],
                    "prov:value": json.dumps(
                        {
                            "operation": "gradient_magnitude",
                            "script_dataset": "plans/adios_derived_variables.py",
                        }
                    ),
                },
                "hpcid:plan_divergence": {
                    "prov:type": [
                        {"$": "prov:Plan", "type": "xsd:QName"},
                        {"$": "hpc:ActionSpecification", "type": "xsd:QName"},
                    ],
                    "prov:value": json.dumps(
                        {
                            "operation": "divergence",
                            "script_dataset": "plans/adios_derived_variables.py",
                        }
                    ),
                },
                "hpcid:workflow_gradient": {
                    "prov:type": {"$": "prov:Plan", "type": "xsd:QName"},
                    "prov:label": "MHD derived-variable workflow",
                    "prov:location": (
                        "https://github.com/example/repo/blob/abc123/"
                        "scripts/adios_derived_variables.py"
                    ),
                    "prov:value": json.dumps(
                        {
                            "schema_version": 1,
                            "workflow": "derived_variables",
                            "implementation_dataset": (
                                "plans/adios_derived_variables.py"
                            ),
                            "selection": {
                                "datasets": ["hll_128/analysis.bp"]
                            },
                            "parameters": {
                                "discretization": "numpy.gradient"
                            },
                        }
                    ),
                },
            },
            "agent": {
                "hpcid:agent_numpy": {
                    "prov:type": {
                        "$": "prov:SoftwareAgent",
                        "type": "xsd:QName",
                    },
                    "prov:label": "NumPy",
                    "hpc:version": "2.0.0",
                }
            },
            "used": {
                "hpcid:usage_gradient_action_specification": {
                    "prov:activity": "hpcid:activity_gradient",
                    "prov:entity": "hpcid:plan_gradient",
                    "prov:role": {"$": "hpc:action_specification", "type": "xsd:QName"},
                },
                "hpcid:usage_gradient_density": {
                    "prov:activity": "hpcid:activity_gradient",
                    "prov:entity": "hpcid:variable_rho",
                    "prov:role": {"$": "hpc:density", "type": "xsd:QName"},
                },
                "hpcid:usage_divergence_action_specification": {
                    "prov:activity": "hpcid:activity_divergence",
                    "prov:entity": "hpcid:plan_divergence",
                    "prov:role": {"$": "hpc:action_specification", "type": "xsd:QName"},
                },
                "hpcid:usage_divergence_magnetic_x": {
                    "prov:activity": "hpcid:activity_divergence",
                    "prov:entity": "hpcid:variable_bx",
                    "prov:role": {"$": "hpc:magnetic_x", "type": "xsd:QName"},
                },
                "hpcid:usage_divergence_magnetic_y": {
                    "prov:activity": "hpcid:activity_divergence",
                    "prov:entity": "hpcid:variable_by",
                    "prov:role": {"$": "hpc:magnetic_y", "type": "xsd:QName"},
                },
            },
            "wasDerivedFrom": {
                "hpcid:derivation_gradient_density": {
                    "prov:activity": "hpcid:activity_gradient",
                    "prov:generatedEntity": "hpcid:variable_grad",
                    "prov:usage": "hpcid:usage_gradient_density",
                    "prov:usedEntity": "hpcid:variable_rho",
                },
                "hpcid:derivation_divergence_magnetic_x": {
                    "prov:activity": "hpcid:activity_divergence",
                    "prov:generatedEntity": "hpcid:variable_div",
                    "prov:usage": "hpcid:usage_divergence_magnetic_x",
                    "prov:usedEntity": "hpcid:variable_bx",
                },
                "hpcid:derivation_divergence_magnetic_y": {
                    "prov:activity": "hpcid:activity_divergence",
                    "prov:generatedEntity": "hpcid:variable_div",
                    "prov:usage": "hpcid:usage_divergence_magnetic_y",
                    "prov:usedEntity": "hpcid:variable_by",
                },
            },
            "wasAssociatedWith": {
                "hpcid:association_gradient": {
                    "prov:activity": "hpcid:activity_gradient",
                    "prov:agent": "hpcid:agent_numpy",
                    "prov:plan": "hpcid:workflow_gradient",
                },
                "hpcid:association_divergence": {
                    "prov:activity": "hpcid:activity_divergence",
                    "prov:agent": "hpcid:agent_numpy",
                    "prov:plan": "hpcid:workflow_gradient",
                }
            },
        }
        con.execute(
            """
            insert into provenance_document(
                uuid, name, format, content, sha256, active, modtime
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "prov-doc",
                "campaign-provenance",
                "prov-json",
                json.dumps(content),
                "sha",
                1,
                1,
            ),
        )
        con.commit()
    finally:
        con.close()

    index = _load_activity_provenance_index(str(campaign_path))

    gradient_entry = index[("hll_128/analysis.bp", "grad_rho_abs")]
    assert gradient_entry == {
        "activity_uuid": "gradient",
        "activity_kind": "quantity_of_interest",
        "activity_operation": "gradient_magnitude",
        "activity_metadata": {
            "operation": "gradient_magnitude",
            "script_dataset": "plans/adios_derived_variables.py",
        },
        "output_role": "",
        "output_definition": "density_gradient_magnitude",
        "inputs": [
            {
                "name": "rho",
                "source_dataset": "hll_128/output.bp",
                "definition": "density",
                "roles": ["density"],
            }
        ],
        "workflow_plan": {
            "id": "hpcid:workflow_gradient",
            "label": "MHD derived-variable workflow",
            "location": (
                "https://github.com/example/repo/blob/abc123/"
                "scripts/adios_derived_variables.py"
            ),
            "details": {
                "schema_version": 1,
                "workflow": "derived_variables",
                "implementation_dataset": "plans/adios_derived_variables.py",
                "selection": {"datasets": ["hll_128/analysis.bp"]},
                "parameters": {"discretization": "numpy.gradient"},
            },
        },
        "activity_agent": {
            "id": "hpcid:agent_numpy",
            "label": "NumPy",
            "type": "SoftwareAgent",
            "version": "2.0.0",
        },
    }
    assert index[("hll_128/analysis.bp", "div_b")]["inputs"] == [
        {
            "name": "bx",
            "source_dataset": "hll_128/output.bp",
            "definition": "magnetic_x",
            "roles": ["magnetic_x"],
        },
        {
            "name": "by",
            "source_dataset": "hll_128/output.bp",
            "definition": "magnetic_y",
            "roles": ["magnetic_y"],
        },
    ]
    assert index[("hll_128/analysis.bp", "div_b")]["activity_metadata"] == {
        "operation": "divergence",
        "script_dataset": "plans/adios_derived_variables.py",
    }


def test_prov_json_visualization_provenance_resolves_sequence_manifest(tmp_path: Path):
    campaign_path = tmp_path / "visualization-prov-json.aca"
    manifest_name = "run/provenance/visualizations/pressure.json"
    sequence_name = "run/output.bp/visualizations/pressure_heatmap"
    con = sqlite3.connect(campaign_path)
    try:
        con.executescript(
            """
            create table provenance_document(
                uuid text primary key,
                name text not null unique,
                format text not null,
                content text not null,
                sha256 text not null,
                active integer not null,
                modtime integer not null
            );
            create table dataset(
                rowid integer primary key,
                name text not null,
                fileformat text not null,
                deltime integer not null
            );
            create table replica(
                rowid integer primary key,
                datasetid integer not null,
                keyid integer not null,
                deltime integer not null
            );
            create table repfiles(
                replicaid integer not null,
                fileid integer not null
            );
            create table file(
                fileid integer primary key,
                compression integer not null,
                data blob not null
            );
            """
        )
        content = {
            "activity": {
                "hpcid:activity_visualization": {
                    "prov:type": {
                        "$": "hpc:Visualization",
                        "type": "xsd:QName",
                    }
                }
            },
            "entity": {
                "hpcid:visualization_output": {
                    "prov:type": {
                        "$": "hpc:LogicalVariable",
                        "type": "xsd:QName",
                    },
                    "hpc:datasetName": manifest_name,
                    "hpc:variable": "image_sequence",
                    "hpc:variableDefinition": "pressure_visualization",
                },
                "hpcid:pressure": {
                    "prov:type": {
                        "$": "hpc:LogicalVariable",
                        "type": "xsd:QName",
                    },
                    "hpc:datasetName": "run/output.bp",
                    "hpc:variable": "pressure",
                    "hpc:variableDefinition": "pressure",
                },
                "hpcid:visualization_action": {
                    "prov:type": [
                        {"$": "prov:Plan", "type": "xsd:QName"},
                        {
                            "$": "hpc:ActionSpecification",
                            "type": "xsd:QName",
                        },
                    ],
                    "prov:value": json.dumps(
                        {
                            "visualization_type": "heatmap",
                            "steps": [0, 1],
                            "rendering_parameters": {"dpi": 120},
                            "sequence_manifest": manifest_name,
                            "script_dataset": (
                                "plans/render_adios_visualizations_to_campaign.py"
                            ),
                        }
                    ),
                },
                "hpcid:visualization_workflow": {
                    "prov:type": {"$": "prov:Plan", "type": "xsd:QName"},
                    "prov:label": "MHD visualization workflow",
                    "prov:location": (
                        "plans/render_adios_visualizations_to_campaign.py"
                    ),
                    "prov:value": json.dumps(
                        {
                            "schema_version": 1,
                            "workflow": "render_visualizations",
                            "implementation_dataset": (
                                "plans/render_adios_visualizations_to_campaign.py"
                            ),
                            "selection": {"variables": ["pressure"]},
                            "parameters": {"visualization_type": "heatmap"},
                            "output_policy": {"replace": True},
                        }
                    ),
                },
            },
            "agent": {
                "hpcid:agent_matplotlib": {
                    "prov:type": {
                        "$": "prov:SoftwareAgent",
                        "type": "xsd:QName",
                    },
                    "prov:label": "Matplotlib",
                    "hpc:version": "3.10.0",
                }
            },
            "used": {
                "hpcid:usage_visualization_action": {
                    "prov:activity": "hpcid:activity_visualization",
                    "prov:entity": "hpcid:visualization_action",
                    "prov:role": {
                        "$": "hpc:action_specification",
                        "type": "xsd:QName",
                    },
                },
                "hpcid:usage_pressure": {
                    "prov:activity": "hpcid:activity_visualization",
                    "prov:entity": "hpcid:pressure",
                    "prov:role": {"$": "hpc:color", "type": "xsd:QName"},
                },
            },
            "wasDerivedFrom": {
                "hpcid:derivation_visualization": {
                    "prov:activity": "hpcid:activity_visualization",
                    "prov:generatedEntity": "hpcid:visualization_output",
                    "prov:usage": "hpcid:usage_pressure",
                    "prov:usedEntity": "hpcid:pressure",
                }
            },
            "wasAssociatedWith": {
                "hpcid:association_visualization": {
                    "prov:activity": "hpcid:activity_visualization",
                    "prov:agent": "hpcid:agent_matplotlib",
                    "prov:plan": "hpcid:visualization_workflow",
                }
            },
        }
        con.execute(
            """
            insert into provenance_document(
                uuid, name, format, content, sha256, active, modtime
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "visualization-prov-doc",
                "visualization-provenance",
                "prov-json",
                json.dumps(content),
                "sha",
                1,
                1,
            ),
        )
        con.execute(
            "insert into dataset(rowid, name, fileformat, deltime) values (?, ?, ?, ?)",
            (1, manifest_name, "TEXT", 0),
        )
        con.execute(
            "insert into replica(rowid, datasetid, keyid, deltime) values (?, ?, ?, ?)",
            (1, 1, 0, 0),
        )
        con.execute(
            "insert into repfiles(replicaid, fileid) values (?, ?)",
            (1, 1),
        )
        con.execute(
            "insert into file(fileid, compression, data) values (?, ?, ?)",
            (1, 0, json.dumps({"sequence_name": sequence_name}).encode()),
        )
        con.commit()
    finally:
        con.close()

    entry = _load_activity_provenance_index(str(campaign_path))[
        (manifest_name, "image_sequence")
    ]

    assert entry["activity_kind"] == "visualization"
    assert entry["activity_operation"] == "heatmap"
    assert entry["visualization_sequence"] == sequence_name
    assert entry["workflow_plan"]["details"]["workflow"] == (
        "render_visualizations"
    )
    assert "activities" not in entry["workflow_plan"]
    assert entry["activity_agent"] == {
        "id": "hpcid:agent_matplotlib",
        "label": "Matplotlib",
        "type": "SoftwareAgent",
        "version": "3.10.0",
    }


def test_temporary_demo_campaign_removes_generated_files():
    _require_unified_demo_api()
    config = DemoConfig(steps=2, samples_1d=8, shape_2d=(4, 4))
    with temporary_demo_campaign(config=config) as demo:
        root = demo.root
        assert demo.campaign_path.exists()
    assert not root.exists()
