import unittest

from query_parser import python_query_to_filters
from pulsar.viewer_actions import (
    CatalogCondition,
    CatalogQueryAction,
    SourceRank,
    VisualizationAddAction,
    ViewerActionValidationError,
    compile_catalog_query,
    compile_source_filter_query,
    parse_catalog_query_action,
    parse_viewer_action,
    parse_visualization_add_action,
    summarize_catalog_query,
    summarize_visualization_add,
    viewer_action_plan_to_dict,
)


def disabled_rank_payload():
    return {
        "enabled": False,
        "variable_id": "",
        "field": "",
        "direction": "",
        "limit": 1,
        "include_ties": True,
    }


class ViewerActionTests(unittest.TestCase):
    def test_source_threshold_action_compiles_to_existing_query_path(self):
        action = parse_catalog_query_action(
            {
                "type": "catalog.query",
                "arguments": {
                    "select": "sources",
                    "result_variable_id": "pressure",
                    "conditions": [
                        {"field": "maximum", "operator": "gt", "value": 5.0}
                    ],
                    "source_conditions": [],
                    "rank": disabled_rank_payload(),
                },
            }
        )

        query_text = compile_catalog_query(action)
        query_filter, source_filters = python_query_to_filters(query_text)

        self.assertEqual(
            query_text,
            'source(id == "pressure" and max > 5.0)',
        )
        self.assertEqual(query_filter, {})
        self.assertEqual(
            source_filters,
            [
                {
                    "$and": [
                        {"variable_id": "pressure"},
                        {"max": {"$gt": 5.0}},
                    ]
                }
            ],
        )

    def test_ranked_action_materializes_a_resolved_source_condition(self):
        action = CatalogQueryAction(
            action_type="catalog.query",
            select="variables",
            result_variable_id="temperature",
            rank=SourceRank(
                enabled=True,
                variable_id="pressure",
                field="maximum",
                direction="descending",
            ),
        )

        query_text = compile_catalog_query(action, rank_value=27.5)

        self.assertEqual(
            query_text,
            'id == "temperature" and '
            'source(id == "pressure" and max == 27.5)',
        )
        self.assertIn(
            "largest source maximum",
            summarize_catalog_query(action, rank_value=27.5),
        )

    def test_source_filter_materializes_current_variable_conditions_directly(self):
        action = CatalogQueryAction(
            action_type="catalog.query",
            select="sources",
            result_variable_id="pressure",
            conditions=(
                CatalogCondition("maximum", "gt", 5.0),
                CatalogCondition("source_dataset", "contains", "128"),
            ),
        )

        self.assertEqual(
            compile_source_filter_query(action),
            'max > 5.0 and contains(source_dataset, "128")',
        )

    def test_source_filter_keeps_cross_variable_conditions_as_restrictions(self):
        action = CatalogQueryAction(
            action_type="catalog.query",
            select="sources",
            result_variable_id="pressure",
            source_conditions=(
                CatalogCondition("variable_id", "eq", "valid"),
                CatalogCondition("minimum", "eq", 1),
            ),
        )

        self.assertEqual(
            compile_source_filter_query(action),
            'source(variable_id == "valid" and min == 1)',
        )

    def test_condition_types_and_phase_one_rank_limits_are_validated(self):
        with self.assertRaisesRegex(
            ViewerActionValidationError,
            "maximum requires a numeric value",
        ):
            parse_catalog_query_action(
                {
                    "type": "catalog.query",
                    "arguments": {
                        "select": "variables",
                        "result_variable_id": "pressure",
                        "conditions": [
                            {
                                "field": "maximum",
                                "operator": "gt",
                                "value": "five",
                            }
                        ],
                        "source_conditions": [],
                        "rank": disabled_rank_payload(),
                    },
                }
            )

        with self.assertRaisesRegex(
            ViewerActionValidationError,
            "supports limit 1",
        ):
            parse_catalog_query_action(
                {
                    "type": "catalog.query",
                    "arguments": {
                        "select": "sources",
                        "result_variable_id": "pressure",
                        "conditions": [],
                        "source_conditions": [],
                        "rank": {
                            "enabled": True,
                            "variable_id": "pressure",
                            "field": "maximum",
                            "direction": "descending",
                            "limit": 2,
                            "include_ties": True,
                        },
                    },
                }
            )

    def test_contains_is_restricted_to_text_fields(self):
        with self.assertRaisesRegex(
            ViewerActionValidationError,
            "contains is only valid for text fields",
        ):
            parse_catalog_query_action(
                {
                    "type": "catalog.query",
                    "arguments": {
                        "select": "variables",
                        "result_variable_id": "pressure",
                        "conditions": [
                            {
                                "field": "maximum",
                                "operator": "contains",
                                "value": 5,
                            }
                        ],
                        "source_conditions": [],
                        "rank": disabled_rank_payload(),
                    },
                }
            )

    def test_direct_condition_objects_compile_without_provider_data(self):
        action = CatalogQueryAction(
            action_type="catalog.query",
            select="variables",
            result_variable_id="pressure",
            conditions=(CatalogCondition("minimum", "gte", 0),),
        )

        self.assertEqual(
            compile_catalog_query(action),
            'id == "pressure" and min >= 0',
        )

    def test_action_plan_serialization_carries_schema_version(self):
        action = CatalogQueryAction(
            action_type="catalog.query",
            select="variables",
            result_variable_id="pressure",
        )

        plan = viewer_action_plan_to_dict((action,))

        self.assertEqual(plan["version"], 1)
        self.assertEqual(plan["actions"][0]["type"], "catalog.query")
        self.assertEqual(
            plan["actions"][0]["arguments"]["result_variable_id"],
            "pressure",
        )

    def test_visualization_add_action_is_validated_and_serialized(self):
        action = parse_visualization_add_action(
            {
                "type": "visualization.add",
                "arguments": {
                    "variable_id": "pressure",
                    "target": "active_cell",
                },
            }
        )

        self.assertEqual(
            action,
            VisualizationAddAction(
                action_type="visualization.add",
                variable_id="pressure",
                target="active_cell",
            ),
        )
        self.assertEqual(
            parse_viewer_action(viewer_action_plan_to_dict((action,))["actions"][0]),
            action,
        )
        self.assertIn(
            "grid cell 2",
            summarize_visualization_add(
                action,
                cell_index=1,
                visualization_name="heatmap",
            ),
        )

    def test_visualization_add_rejects_unsupported_arguments_and_targets(self):
        with self.assertRaisesRegex(
            ViewerActionValidationError,
            "unsupported fields: visualization_name",
        ):
            parse_visualization_add_action(
                {
                    "type": "visualization.add",
                    "arguments": {
                        "variable_id": "pressure",
                        "target": "active_cell",
                        "visualization_name": "heatmap",
                    },
                }
            )

        with self.assertRaisesRegex(
            ViewerActionValidationError,
            "Unsupported visualization target",
        ):
            parse_visualization_add_action(
                {
                    "type": "visualization.add",
                    "arguments": {
                        "variable_id": "pressure",
                        "target": "cell_3",
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
