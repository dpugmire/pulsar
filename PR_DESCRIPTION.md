# Suggested title

Add structured LLM query interface

## Summary

This PR adds the first phase of an LLM interface to Pulsar.

The Query Assistant translates natural-language requests into a versioned,
validated Viewer Action. The application—not the model—resolves campaign
metadata, previews the result, and applies the query only after explicit user
confirmation.

The assistant is available from:

- The global **Advanced Query** toolbar.
- The **Filter Sources** field in the Sources dialog.

Existing manually authored Advanced Query expressions continue to work
unchanged.

## Design

The LLM is treated as a proposal generator rather than an autonomous
controller:

```text
Natural-language request
        ↓
LLM-generated Viewer Action proposal
        ↓
Schema and campaign-reference validation
        ↓
Local metadata/ranking resolution
        ↓
Query preview and match counts
        ↓
Explicit user Apply
        ↓
Existing query execution path
```

The model does not execute Python, generate SQL, invoke viewer operations, or
directly change application state.

This establishes a structured extension point for eventually exposing other
viewer capabilities to an LLM. This PR intentionally exposes only one action
type: `catalog.query`.

## User-facing functionality

### Global catalog queries

When an LLM model is configured, an **Ask** button appears beside the existing
Advanced Query input.

Example requests include:

```text
pressure with largest max
```

```text
Find sources where pressure has max > 5.0
```

```text
sources where pressure max is > 5.0 and source dataset name contains "128"
```

```text
temperature from the source where pressure has the largest max
```

The Query Assistant dialog presents:

- The original natural-language request.
- The provider and model.
- A summary of the proposed operation.
- Assumptions or clarification requests.
- Previewed variable and source match counts.
- The resolved Advanced Query expression.

The active catalog query is not changed until the user selects **Apply**.

### Source dialog filtering

The Sources dialog now exposes the same assistant through an **Ask** button
beside **Filter Sources**.

The field supports both paths:

- Enter natural language and select **Ask**.
- Enter an existing Advanced Query expression and select **Filter**.

A source-filter request:

- Uses the variable currently selected in the Sources dialog.
- Evaluates against the currently visible source rows.
- Previews the number of matching sources.
- Applies only to the Sources dialog.
- Does not change the global catalog query.
- Leaves the Sources dialog open after applying the filter.

## Viewer Action contract

The new schema-v1 Viewer Action envelope provides a constrained interface
between the model and the application.

Phase 1 accepts exactly one `catalog.query` action with:

- A variable or source selection.
- AND-combined catalog conditions.
- Source-specific conditions.
- An optional deterministic source ranking.

Supported fields are:

- `variable_id`
- `variable_name`
- `variable_type`
- `source_dataset`
- `producer`
- `casename`
- `file`
- `minimum`
- `maximum`

Supported operators are:

- `eq`
- `ne`
- `gt`
- `gte`
- `lt`
- `lte`
- `in`
- `not_in`
- `contains`

All proposals are parsed and validated server-side. Unsupported fields,
operators, action types, schema versions, or malformed values are rejected
before preview or execution.

## Campaign metadata and ranking

The assistant supports queries based on the campaign's stored per-source
`minimum` and `maximum` metadata.

For example:

```text
pressure with largest max
```

The model identifies:

- The ranking variable: `pressure`.
- The statistic: `maximum`.
- The direction: descending.
- The limit: one, including ties.

Pulsar then reads the actual per-source statistics locally and determines the
winning source or tied sources. Numeric ranking metadata is not sent to the
LLM, and the model is not asked to guess the winning value.

The shorter request:

```text
largest max
```

also works when a variable such as `pressure` is already selected.

For source-dialog queries, ranking is limited to the source rows currently
visible under the active global query. Missing or non-finite statistics produce
an explicit error instead of an incorrect result.

## Query compilation and compatibility

Validated Viewer Actions are compiled into the existing Python-like Advanced
Query representation used by the local backend.

The generated expression is:

- Produced by Pulsar, not by the model.
- Displayed read-only in the review dialog.
- Revalidated by the existing parser.
- Previewed against the backend before Apply.

This keeps the implementation compatible with the current query execution path
while separating the public Viewer Action contract from the backend-specific
query syntax.

The action plan and original natural-language request are persisted in
workspace state for an applied global query.

## Provider integration

The assistant uses an OpenAI-compatible Chat Completions endpoint through
Python's standard library, so this PR adds no Python dependencies.

Example configuration for Ollama and `gpt-oss:20b`:

```bash
export PULSAR_LLM_MODEL="gpt-oss:20b"
export PULSAR_LLM_BASE_URL="http://localhost:11434/v1"
export PULSAR_LLM_API_KEY="ollama"
export PULSAR_LLM_TIMEOUT_SECONDS="30"
```

`PULSAR_LLM_MODEL` enables the assistant. The base URL, API key, and timeout
have Ollama-compatible defaults.

The provider request uses a JSON Schema response format. If an
OpenAI-compatible provider explicitly rejects `response_format` with HTTP 400
or 422, Pulsar retries once without it. The returned content must still pass
strict JSON and Viewer Action validation; malformed output is never silently
repaired.

The Trame controller is registered through the asynchronous controller path,
avoiding unawaited-coroutine warnings from wslink.

## Context and data boundaries

Each provider request contains only:

- The user's request.
- The selected variable, when applicable.
- Up to 200 bounded variable catalog entries.
- Up to 200 distinct source-dataset names.
- Instructions describing the allowed Viewer Action schema.

The provider does not receive:

- Array contents.
- Image or movie data.
- Per-source numeric ranking statistics.
- Viewer credentials.
- Arbitrary application state.

Provider credentials remain in the Python process and are not placed in Trame
browser state.

## Query and backend hardening

This PR also strengthens the existing Advanced Query path required to safely
consume generated actions:

- Bounds query length, AST size, depth, predicate count, list size, and string
  length.
- Rejects non-finite numeric values.
- Enforces field/operator type compatibility.
- Restricts `contains` to textual fields.
- Requires lists or tuples for membership operators.
- Restricts `source(...)` to supported top-level forms.
- Supports multiple source clauses using intersection semantics.
- Adds deterministic SQLite regular-expression support.
- Propagates backend restriction errors rather than treating them as zero
  matches.

Source-reference validation is now operator-aware:

- `eq` and `in` require exact known campaign references.
- `contains`, `ne`, and `not_in` accept non-exact operands.

This allows requests such as:

```text
source dataset name contains "128"
```

without incorrectly requiring `"128"` to be the complete name of a source
dataset.

For source-dialog filtering, conditions on the selected variable are evaluated
directly against each concrete source row. Cross-variable conditions continue
to use source restrictions. This avoids accidentally grouping or matching
unrelated sources that share producer identity.

## Current limitations

This first phase intentionally supports:

- One action per proposal.
- Only the `catalog.query` action type.
- AND-combined conditions.
- Top-one source ranking with ties.
- Existing local query execution semantics.

It does not yet support:

- Multiple viewer actions in one request.
- OR expressions.
- Autonomous viewer operation.
- Visualization or analysis commands.
- General conversational history or planning.
- Backend-neutral query execution beyond the current compatibility compiler.

Future viewer capabilities can be added as new explicitly defined Viewer Action
types with their own validation, preview, authorization, and application
semantics.

## Documentation and tests

README and architecture documentation now describe:

- Query Assistant setup.
- Provider and context boundaries.
- Viewer Action architecture.
- Source-ranking behavior.
- Source-dialog integration.
- Current limitations and planned extension points.

Test coverage includes:

- Viewer Action schema and version validation.
- Structured provider responses and fallback behavior.
- Bounded prompt context.
- Invalid-output handling.
- Review-before-apply behavior.
- Global-query preservation.
- Source-dialog targeting and application.
- Minimum/maximum conditions.
- Largest/smallest ranking.
- Ties and missing/non-finite metadata.
- Substring source matching.
- Parser and SQLite integration.
- Workspace persistence.
- Trame controller registration.
- Browser-level global and source-filter workflows.

Validation results:

```text
149 passed, 30 skipped, 7 subtests passed
Targeted Query Assistant browser tests: 2 passed
Ruff: passed
py_compile: passed
pip check: no broken requirements
git diff --check: passed
```

The remaining PyTorch/NumPy `_ARRAY_API` warning is pre-existing and unrelated
to this change.
