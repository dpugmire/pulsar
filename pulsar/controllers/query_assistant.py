"""Natural-language viewer-action proposal and explicit-apply behavior."""

import asyncio
import math
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Tuple

from query_parser import and_filter
from pulsar.query_assistant import (
    MAX_ASSISTANT_REQUEST_LENGTH,
    MAX_CONTEXT_SOURCE_FILTER_VALUES,
    MAX_CONTEXT_SOURCES,
    MAX_CONTEXT_VARIABLES,
    QueryAssistantError,
    QueryContextVariable,
    QuerySourceFilterContext,
    QueryTranslationRequest,
)
from pulsar.viewer_actions import (
    CatalogQueryAction,
    VisualizationAddAction,
    ViewerActionProposal,
    compile_catalog_query,
    compile_source_filter_query,
    summarize_catalog_query,
    summarize_visualization_add,
    viewer_action_plan_to_dict,
)


class QueryAssistantControllerMixin:
    ACTION_BINDINGS = (
        ("open_query_assistant", "open_query_assistant"),
        ("open_source_query_assistant", "open_source_query_assistant"),
        ("open_visualization_assistant", "open_visualization_assistant"),
        ("close_query_assistant", "close_query_assistant"),
        ("translate_query_request", "translate_query_request"),
        ("validate_query_proposal", "validate_query_proposal"),
        ("apply_query_proposal", "apply_query_proposal"),
    )
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = ()
    HISTORY_ACTIONS = {
        "apply_query_proposal": "Apply assistant proposal",
    }
    HISTORY_TRIGGERS = {}

    def reset_query_assistant_proposal(self) -> None:
        self._query_assistant_action = None
        self._query_assistant_rank_value = None
        self._query_assistant_target_cell_index = None
        self.state.queryAssistantProposalText = ""
        self.state.queryAssistantProposalSummary = ""
        self.state.queryAssistantActionPlan = {}
        self.state.queryAssistantExplanation = ""
        self.state.queryAssistantAssumptions = []
        self.state.queryAssistantClarification = ""
        self.state.queryAssistantStatus = ""
        self.state.queryAssistantError = ""
        self.state.queryAssistantVariableCount = 0
        self.state.queryAssistantSourceCount = 0
        self.state.queryAssistantRankValue = None
        self.state.queryAssistantTieCount = 0
        self.state.queryAssistantValidatedText = ""
        self.state.queryAssistantTargetCellIndex = -1
        self.state.queryAssistantVisualizationName = ""

    def open_query_assistant(self, **_):
        if not self.query_translator:
            return False
        previous_target = str(self.state.queryAssistantTarget or "catalog")
        self.reset_query_assistant_proposal()
        self.state.queryAssistantTarget = "catalog"
        if previous_target != "catalog":
            self.state.queryAssistantRequestText = ""
        self.state.showQueryAssistant = True
        return True

    def open_source_query_assistant(self, **_):
        if not self.query_translator:
            return False
        selected_variable_id = str(
            getattr(self.state, "detailsSelectedVarId", "")
            or getattr(self.state, "selectedVar", "")
            or ""
        ).strip()
        if not selected_variable_id:
            self.state.sourceFilterError = "Select a variable first."
            return False

        self.reset_query_assistant_proposal()
        self.state.queryAssistantTarget = "source_filter"
        self.state.queryAssistantRequestText = str(
            self.state.sourceFilterDraftText or ""
        ).strip()
        self.state.showQueryAssistant = True
        return True

    def open_visualization_assistant(self, **_):
        if not self.query_translator:
            return False
        previous_target = str(self.state.queryAssistantTarget or "catalog")
        self.reset_query_assistant_proposal()
        self.state.queryAssistantTarget = "visualization"
        if previous_target != "visualization":
            self.state.queryAssistantRequestText = ""
        try:
            cell_index = int(self.state.activeGridCell)
        except (TypeError, ValueError):
            cell_index = -1
        if not self.is_valid_grid_index(cell_index):
            self.state.queryAssistantError = (
                "Select a grid cell before adding a visualization."
            )
        self.state.showQueryAssistant = True
        return True

    def close_query_assistant(self, **_):
        self._invalidate_query_assistant_request()
        self.state.queryAssistantBusy = False
        self.state.showQueryAssistant = False

    def _invalidate_query_assistant_request(self) -> int:
        request_id = int(
            getattr(self, "_query_assistant_request_id", 0) or 0
        ) + 1
        self._query_assistant_request_id = request_id
        return request_id

    def _flush_query_assistant_state(self) -> None:
        flush = getattr(self.state, "flush", None)
        if callable(flush):
            flush()

    def compile_query_assistant_action(self, action: CatalogQueryAction) -> str:
        rank_value = getattr(self, "_query_assistant_rank_value", None)
        if self.state.queryAssistantTarget == "source_filter":
            return compile_source_filter_query(
                action,
                rank_value=rank_value,
            )
        return compile_catalog_query(action, rank_value=rank_value)

    @staticmethod
    def _query_assistant_finite_float(value: Any):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _query_assistant_numeric_range(values: Iterable[Any]) -> Tuple[Any, Any]:
        finite = [
            QueryAssistantControllerMixin._query_assistant_finite_float(value)
            for value in values
        ]
        numbers = [value for value in finite if value is not None]
        if not numbers:
            return (None, None)
        return (min(numbers), max(numbers))

    @staticmethod
    def _query_assistant_context_values(
        values: Iterable[Any],
    ) -> Tuple[Tuple[str, ...], bool]:
        unique = sorted(
            {
                str(value or "").strip()
                for value in values
                if str(value or "").strip()
            },
            key=str.casefold,
        )
        return (
            tuple(unique[:MAX_CONTEXT_SOURCE_FILTER_VALUES]),
            len(unique) > MAX_CONTEXT_SOURCE_FILTER_VALUES,
        )

    def source_filter_translation_context(self) -> QuerySourceFilterContext:
        rows = list(self.all_source_rows())
        visible_rows = list(getattr(self.state, "sourceRows", []) or [])
        values = [self.source_filter_values(row) for row in rows]

        source_datasets, source_datasets_truncated = (
            self._query_assistant_context_values(
                value.get("source_dataset", "") for value in values
            )
        )
        producers, producers_truncated = self._query_assistant_context_values(
            value.get("producer", "") for value in values
        )
        casenames, casenames_truncated = self._query_assistant_context_values(
            value.get("casename", "") for value in values
        )
        files, files_truncated = self._query_assistant_context_values(
            value.get("file", "") for value in values
        )

        return QuerySourceFilterContext(
            row_count=len(rows),
            visible_row_count=len(visible_rows),
            source_datasets=source_datasets,
            producers=producers,
            casenames=casenames,
            files=files,
            minimum_range=self._query_assistant_numeric_range(
                value.get("min", None) for value in values
            ),
            maximum_range=self._query_assistant_numeric_range(
                value.get("max", None) for value in values
            ),
            context_truncated=(
                source_datasets_truncated
                or producers_truncated
                or casenames_truncated
                or files_truncated
            ),
        )

    def query_translation_request(self, request_text: str) -> QueryTranslationRequest:
        navigation = self.application.get_navigation(
            {
                "view": "files",
                "query": {},
                "only_visualized": False,
                "parent_id": None,
            }
        )
        by_id: Dict[str, QueryContextVariable] = {}
        source_datasets = set()
        for node in navigation:
            node_resource = node.get("resource") or {}
            node_source_dataset = str(
                node_resource.get("source_dataset", "") or ""
            ).strip()
            if node_source_dataset:
                source_datasets.add(node_source_dataset)
            for child in node.get("children", []) or []:
                if child.get("kind") != "variable":
                    continue
                resource = child.get("resource") or {}
                variable_id = str(resource.get("variable_id", "") or "").strip()
                source_dataset = str(
                    resource.get("source_dataset", "") or ""
                ).strip()
                if source_dataset:
                    source_datasets.add(source_dataset)
                if not variable_id or variable_id in by_id:
                    continue
                by_id[variable_id] = QueryContextVariable(
                    variable_id=variable_id,
                    name=str(resource.get("name", "") or ""),
                    label=str(
                        resource.get("label", "")
                        or child.get("label", "")
                        or variable_id
                    ),
                    path=str(resource.get("path", "") or ""),
                    source_dataset=source_dataset,
                )

        variables: List[QueryContextVariable] = sorted(
            by_id.values(),
            key=lambda item: (
                item.label.casefold(),
                item.variable_id.casefold(),
            ),
        )
        target = str(self.state.queryAssistantTarget or "catalog")
        if target == "source_filter":
            selected_variable_id = str(
                getattr(self.state, "detailsSelectedVarId", "")
                or getattr(self.state, "selectedVar", "")
                or ""
            )
        else:
            selected_variable_id = str(
                getattr(self.state, "selectedVar", "")
                or getattr(self.state, "detailsSelectedVarId", "")
                or ""
            )
        context_variables = variables[:MAX_CONTEXT_VARIABLES]
        if (
            selected_variable_id in by_id
            and selected_variable_id
            not in {item.variable_id for item in context_variables}
        ):
            context_variables = [
                by_id[selected_variable_id],
                *context_variables[: MAX_CONTEXT_VARIABLES - 1],
            ]
        return QueryTranslationRequest(
            request_text=request_text,
            variables=tuple(context_variables),
            source_datasets=tuple(
                sorted(source_datasets, key=str.casefold)[:MAX_CONTEXT_SOURCES]
            ),
            selected_variable_id=selected_variable_id,
            target=target,
            context_truncated=(
                len(variables) > MAX_CONTEXT_VARIABLES
                or len(source_datasets) > MAX_CONTEXT_SOURCES
            ),
            source_filter_context=(
                self.source_filter_translation_context()
                if target == "source_filter"
                else None
            ),
        )

    async def translate_query_request(self, **_):
        if not self.query_translator:
            self.state.queryAssistantError = "Query Assistant is not configured."
            return False

        request_text = str(
            self.state.queryAssistantRequestText or ""
        ).strip()
        if not request_text:
            self.state.queryAssistantError = "Enter a request to translate."
            return False
        if len(request_text) > MAX_ASSISTANT_REQUEST_LENGTH:
            self.state.queryAssistantError = (
                f"Requests are limited to {MAX_ASSISTANT_REQUEST_LENGTH} characters."
            )
            return False

        request_id = self._invalidate_query_assistant_request()
        self.reset_query_assistant_proposal()
        self.state.queryAssistantBusy = True
        self.state.queryAssistantStatus = "Translating request…"
        self._flush_query_assistant_state()

        try:
            translation_request = self.query_translation_request(request_text)
            timeout_seconds = max(
                1.0,
                float(self.query_translator.timeout_seconds),
            )
            proposal = await asyncio.wait_for(
                asyncio.to_thread(
                    self.query_translator.translate,
                    translation_request,
                ),
                timeout=timeout_seconds + 1.0,
            )
            if not isinstance(proposal, ViewerActionProposal):
                raise QueryAssistantError(
                    "Translator returned an invalid proposal object."
                )
            if proposal.status == "proposal":
                proposed_action = proposal.actions[0]
                if isinstance(proposed_action, CatalogQueryAction):
                    action, rank_value, tie_count = self.resolve_catalog_action(
                        proposed_action,
                        translation_request,
                    )
                    target_cell_index = None
                elif isinstance(proposed_action, VisualizationAddAction):
                    action, target_cell_index = self.resolve_visualization_action(
                        proposed_action,
                        translation_request,
                    )
                    rank_value = None
                    tie_count = 0
                else:
                    raise QueryAssistantError("Unsupported viewer action proposal.")
        except asyncio.TimeoutError:
            if request_id == self._query_assistant_request_id:
                self.state.queryAssistantError = "Query translation timed out."
                self.state.queryAssistantStatus = ""
            return False
        except Exception as e:
            if request_id == self._query_assistant_request_id:
                message = str(e) if isinstance(e, QueryAssistantError) else (
                    f"Query translation failed ({type(e).__name__})."
                )
                self.state.queryAssistantError = message
                self.state.queryAssistantStatus = ""
            return False
        finally:
            if request_id == self._query_assistant_request_id:
                self.state.queryAssistantBusy = False

        if request_id != self._query_assistant_request_id:
            return False

        self.state.queryAssistantExplanation = proposal.explanation
        self.state.queryAssistantAssumptions = list(proposal.assumptions)
        self.state.queryAssistantClarification = proposal.clarification
        if proposal.status == "needs_clarification":
            self.state.queryAssistantStatus = "Clarification needed"
            return False

        self._query_assistant_action = action
        self._query_assistant_rank_value = rank_value
        self._query_assistant_target_cell_index = target_cell_index
        self.state.queryAssistantActionPlan = viewer_action_plan_to_dict(
            (action,),
            version=proposal.version,
        )
        self.state.queryAssistantRankValue = rank_value
        self.state.queryAssistantTieCount = tie_count
        if isinstance(action, CatalogQueryAction):
            self.state.queryAssistantProposalText = (
                self.compile_query_assistant_action(action)
            )
            self.state.queryAssistantProposalSummary = summarize_catalog_query(
                action,
                rank_value=rank_value,
                tie_count=tie_count,
            )
        else:
            self.state.queryAssistantTargetCellIndex = target_cell_index
        return self.validate_query_proposal()

    def resolve_catalog_action(
        self,
        action: CatalogQueryAction,
        request: QueryTranslationRequest,
    ):
        if request.target == "visualization":
            raise QueryAssistantError(
                "A visualization request must propose visualization.add."
            )
        available_ids = {variable.variable_id for variable in request.variables}
        available_names = {variable.name for variable in request.variables}
        available_sources = set(request.source_datasets)

        result_variable_id = action.result_variable_id
        rank = action.rank
        rank_variable_id = rank.variable_id
        selected_variable_id = str(request.selected_variable_id or "")
        if request.target == "source_filter":
            if action.select != "sources":
                raise QueryAssistantError(
                    "A Source Filter action must select sources."
                )
            if not selected_variable_id:
                raise QueryAssistantError(
                    "Select a variable before filtering source rows."
                )
            if result_variable_id and result_variable_id != selected_variable_id:
                raise QueryAssistantError(
                    "A Source Filter action must return the selected variable."
                )
            result_variable_id = selected_variable_id
            referenced_variable_ids = {
                str(value)
                for condition in action.source_conditions
                if condition.field == "variable_id"
                for value in (
                    condition.value
                    if isinstance(condition.value, list)
                    else [condition.value]
                )
            }
            if not referenced_variable_ids or referenced_variable_ids == {
                selected_variable_id
            }:
                action = replace(
                    action,
                    conditions=(*action.conditions, *action.source_conditions),
                    source_conditions=(),
                )
        if rank.enabled and not rank_variable_id:
            rank_variable_id = result_variable_id or selected_variable_id
        if rank.enabled and not result_variable_id and action.select == "sources":
            result_variable_id = rank_variable_id

        if result_variable_id and result_variable_id not in available_ids:
            raise QueryAssistantError(
                f"Unknown campaign variable: {result_variable_id}"
            )
        if rank.enabled and not rank_variable_id:
            raise QueryAssistantError(
                "Select or name a variable before requesting a ranking."
            )
        if rank_variable_id and rank_variable_id not in available_ids:
            raise QueryAssistantError(
                f"Unknown ranking variable: {rank_variable_id}"
            )

        for condition in (*action.conditions, *action.source_conditions):
            if condition.operator not in {"eq", "in"}:
                continue
            values = (
                condition.value
                if isinstance(condition.value, list)
                else [condition.value]
            )
            if condition.field == "variable_id" and any(
                value not in available_ids for value in values
            ):
                raise QueryAssistantError("Action references an unknown variable ID.")
            if condition.field == "variable_name" and any(
                value not in available_names for value in values
            ):
                raise QueryAssistantError("Action references an unknown variable name.")
            if condition.field == "source_dataset" and any(
                value not in available_sources for value in values
            ):
                raise QueryAssistantError("Action references an unknown source dataset.")

        if result_variable_id != action.result_variable_id or (
            rank.enabled and rank_variable_id != rank.variable_id
        ):
            rank = replace(rank, variable_id=rank_variable_id)
            action = replace(
                action,
                result_variable_id=result_variable_id,
                rank=rank,
            )

        if not rank.enabled:
            return action, None, 0

        source_value_key = "minimum" if rank.field == "minimum" else "maximum"
        if (
            request.target == "source_filter"
            and rank.variable_id == selected_variable_id
        ):
            summary_sources = []
            row_value_key = "min_value" if rank.field == "minimum" else "max_value"
            row_fallback_key = "min" if rank.field == "minimum" else "max"
            for source_row in self.all_source_rows():
                summary_sources.append(
                    {
                        source_value_key: source_row.get(
                            row_value_key,
                            source_row.get(row_fallback_key),
                        )
                    }
                )
        else:
            summary = self.application.get_source_summary(
                {"variable_id": rank.variable_id, "query": {}}
            )
            summary_sources = summary.get("sources", []) or []
        values = []
        for source in summary_sources:
            raw_value = source.get(source_value_key)
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
        if not values:
            raise QueryAssistantError(
                f"No finite source {rank.field} metadata is available for "
                f"{rank.variable_id}."
            )
        rank_value = (
            max(values) if rank.direction == "descending" else min(values)
        )
        tie_count = sum(value == rank_value for value in values)
        return action, rank_value, tie_count

    def resolve_visualization_action(
        self,
        action: VisualizationAddAction,
        request: QueryTranslationRequest,
    ):
        if request.target != "visualization":
            raise QueryAssistantError(
                "A query request must propose catalog.query."
            )
        available_ids = {variable.variable_id for variable in request.variables}
        if action.variable_id not in available_ids:
            raise QueryAssistantError(
                f"Unknown campaign variable: {action.variable_id}"
            )
        try:
            cell_index = int(self.state.activeGridCell)
        except (TypeError, ValueError):
            cell_index = -1
        if not self.is_valid_grid_index(cell_index):
            raise QueryAssistantError(
                "Select a grid cell before adding a visualization."
            )
        return action, cell_index

    def visualization_add_preview(
        self,
        action: VisualizationAddAction,
        cell_index: int,
    ) -> str:
        if not self.is_valid_grid_index(cell_index):
            raise QueryAssistantError("The target grid cell is no longer available.")

        variable_id = action.variable_id
        source_filter = self.active_source_filter_for_variable(variable_id)
        query_filter = self.active_query_filter()
        active_filter = (
            and_filter(query_filter, source_filter)
            if query_filter and source_filter
            else (query_filter or source_filter or None)
        )
        try:
            visualization_names = self.visualization_names_with_plugins(
                variable_id,
                source_filter=source_filter or None,
                extra_filter=active_filter,
            )
        except Exception as e:
            raise QueryAssistantError(
                f"Could not inspect visualizations for {variable_id}: {e}"
            ) from e

        selected = self.choose_visualization_default(visualization_names)
        if selected:
            return selected

        try:
            scalar_candidate = self.db.scalar_plot_candidate(
                variable_id,
                source_filter=source_filter or None,
                extra_filter=query_filter,
            )
        except Exception as e:
            raise QueryAssistantError(
                f"Could not inspect raw scalar data for {variable_id}: {e}"
            ) from e
        if scalar_candidate:
            policy = str(self.state.scalarPlotPolicy or "always").strip().lower()
            if policy == "never":
                raise QueryAssistantError(
                    f"No stored visualization is available for {variable_id}, and "
                    "scalar plot generation is disabled."
                )
            return "generated scalar plot"

        raise QueryAssistantError(
            f"No visualization is available for {variable_id} under the active query."
        )

    def validate_visualization_proposal(
        self,
        action: VisualizationAddAction,
    ) -> bool:
        cell_index = getattr(self, "_query_assistant_target_cell_index", None)
        if not isinstance(cell_index, int):
            self.state.queryAssistantError = "There is no grid target to validate."
            self.state.queryAssistantStatus = ""
            return False
        try:
            visualization_name = self.visualization_add_preview(action, cell_index)
        except Exception as e:
            self.state.queryAssistantError = (
                str(e)
                if isinstance(e, QueryAssistantError)
                else f"{type(e).__name__}: {e}"
            )
            self.state.queryAssistantStatus = "Proposal is not valid"
            self.state.queryAssistantProposalSummary = ""
            self.state.queryAssistantVisualizationName = ""
            return False

        self.state.queryAssistantProposalText = ""
        self.state.queryAssistantValidatedText = ""
        self.state.queryAssistantVariableCount = 1
        self.state.queryAssistantSourceCount = 0
        self.state.queryAssistantTargetCellIndex = cell_index
        self.state.queryAssistantVisualizationName = visualization_name
        self.state.queryAssistantProposalSummary = summarize_visualization_add(
            action,
            cell_index=cell_index,
            visualization_name=visualization_name,
        )
        self.state.queryAssistantError = ""
        self.state.queryAssistantStatus = (
            f"Valid · {action.variable_id} · grid cell {cell_index + 1}"
        )
        return True

    def validate_query_proposal(self, **_):
        action = getattr(self, "_query_assistant_action", None)
        if isinstance(action, VisualizationAddAction):
            if self.state.queryAssistantTarget != "visualization":
                self.state.queryAssistantError = (
                    "A query request cannot apply a visualization action."
                )
                return False
            return self.validate_visualization_proposal(action)
        if not isinstance(action, CatalogQueryAction):
            self.state.queryAssistantError = "There is no viewer action to validate."
            self.state.queryAssistantStatus = ""
            self.state.queryAssistantValidatedText = ""
            return False

        try:
            proposal_text = self.compile_query_assistant_action(action)
            if self.state.queryAssistantTarget == "source_filter":
                source_rows = self.source_rows_matching_filter(proposal_text)
                evaluation = None
            else:
                evaluation = self.evaluate_query_text(proposal_text)
        except Exception as e:
            self.state.queryAssistantError = f"{type(e).__name__}: {e}"
            self.state.queryAssistantStatus = "Proposal is not valid"
            self.state.queryAssistantVariableCount = 0
            self.state.queryAssistantSourceCount = 0
            self.state.queryAssistantValidatedText = ""
            return False

        if self.state.queryAssistantTarget == "source_filter":
            variable_count = 1
            source_count = len(source_rows)
        else:
            variable_count = int(evaluation["variable_count"])
            source_count = int(evaluation["source_count"])
        self.state.queryAssistantVariableCount = variable_count
        self.state.queryAssistantSourceCount = source_count
        self.state.queryAssistantValidatedText = proposal_text
        self.state.queryAssistantProposalText = proposal_text
        self.state.queryAssistantError = ""
        if self.state.queryAssistantTarget == "source_filter":
            status = (
                f"Valid · {source_count} source row"
                f"{'s' if source_count != 1 else ''}"
            )
            rank_value = getattr(self, "_query_assistant_rank_value", None)
            tie_count = int(getattr(self.state, "queryAssistantTieCount", 0) or 0)
            self.state.queryAssistantProposalSummary = (
                summarize_catalog_query(
                    action,
                    rank_value=rank_value,
                    tie_count=tie_count,
                )
                + " Preview: "
                + f"{source_count} matching source row"
                + ("." if source_count == 1 else "s.")
            )
        else:
            status = (
                f"Valid · {variable_count} variable"
                f"{'s' if variable_count != 1 else ''}"
            )
            if evaluation["source_filters"]:
                status += (
                    f" · {source_count} source run"
                    f"{'s' if source_count != 1 else ''}"
                )
        self.state.queryAssistantStatus = status
        return True

    def apply_query_proposal(self, **_):
        if not self.validate_query_proposal():
            return False

        action = getattr(self, "_query_assistant_action", None)
        if isinstance(action, VisualizationAddAction):
            cell_index = getattr(self, "_query_assistant_target_cell_index", None)
            if not isinstance(cell_index, int):
                self.state.queryAssistantError = "There is no grid target to apply."
                return False
            self.record_query_applied(
                origin="query_assistant",
                target="visualization",
                action_plan=dict(self.state.queryAssistantActionPlan or {}),
            )
            self._interaction_assignment_source = "query_assistant"
            try:
                self.assign_var_to_grid_cell(cell_index, action.variable_id)
            finally:
                self._interaction_assignment_source = ""
            self.state.showQueryAssistant = False
            return True

        proposal_text = str(self.state.queryAssistantValidatedText or "").strip()
        if self.state.queryAssistantTarget == "source_filter":
            self.state.sourceFilterDraftText = proposal_text
            self.state.sourceFilterText = proposal_text
            self.state.sourceFilterError = ""
            self.apply_source_filter_and_sort()
            if self.state.sourceFilterError:
                self.state.queryAssistantError = self.state.sourceFilterError
                return False
            self.record_query_applied(
                origin="query_assistant",
                target="source_filter",
                action_plan=dict(self.state.queryAssistantActionPlan or {}),
            )
            self.state.showQueryAssistant = False
            return True

        self.state.queryText = proposal_text
        self._interaction_pending_query_origin = "query_assistant"
        self._interaction_pending_query_action_plan = dict(
            self.state.queryAssistantActionPlan or {}
        )
        try:
            if not self.run_query():
                self.state.queryAssistantError = self.state.queryError
                return False
        finally:
            self._interaction_pending_query_origin = ""
            self._interaction_pending_query_action_plan = None

        self.state.activeViewerActionPlan = dict(
            self.state.queryAssistantActionPlan or {}
        )
        self.state.activeNaturalLanguageQuery = str(
            self.state.queryAssistantRequestText or ""
        ).strip()
        self.state.queryViewLabel = self.state.activeNaturalLanguageQuery
        self.state.showQueryAssistant = False
        return True
