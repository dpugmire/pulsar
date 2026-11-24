# Query Redesign Considerations

## Status

The catalog/source predicate contract now uses a typed query model and
versioned JSON documents. Broader query UX and scope redesign remains deferred
while the viewer's query model is reevaluated. This document records the current
predicate contract and decisions needed before Phase 5B.2 expands backend query
capabilities or changes viewer scope.

The goal is not to preserve the current implementation automatically. The goal
is to identify the campaign-analysis workflows Pulsar must support, choose a
clear user model, and only then encode that model in the UI and backend
contracts.

The Implemented Predicate Contract section describes current behavior. Later
workflow, interface, and scope proposals remain design options until their open
questions have explicit answers.

## Related Documents

- [README.md](README.md) describes the current application and runtime.
- [ARCHITECTURE.md](ARCHITECTURE.md) shows the current local architecture and
  the planned Phobos boundaries.
- [PHOBOS_INTEGRATION.md](PHOBOS_INTEGRATION.md) describes the future backend
  capabilities and the original Phase 5B.2 scope.
- [MIGRATION_SUMMARY.md](MIGRATION_SUMMARY.md) records the completed Trame and
  backend-boundary phases.

## Current User Model

Pulsar currently exposes two query-like surfaces.

### Global Query

The toolbar accepts Python-like expressions such as:

```python
var == "density"
min > 0
contains(source, "hll")
var == "U" and source(var == "valid" and min == 1)
```

The global Query currently affects the variable catalog and is propagated into
source discovery, grid assignment, stored visualization lookup, and generated
visualization operations. That broad scope is powerful, but it is not obvious
from the control itself.

### Source Filter

The source-selection dialog accepts similar expressions, but applies them only
to the source rows that already passed the active global Query. It uses much of
the same syntax while operating on a different data shape and scope.

### Current `source(...)` Meaning

`source(expression)` is allowed only as a top-level `and` term. It means:

1. find sources/runs containing records that satisfy `expression`;
2. identify the matching sources;
3. restrict the outer query to records belonging to those sources.

Multiple `source(...)` terms are currently intersected. For example:

```python
var == "temperature" and source(var == "valid" and min == 1)
```

asks for `temperature`, but only from sources where the separate `valid`
variable satisfies the inner condition. This cross-variable source selection
is an important scientific workflow, even if the current syntax is ultimately
replaced.

## Current Implementation Constraints

The text parser uses Python's expression AST for syntax validation and produces
`QueryPlan`, `Compare`, `Junction`, and `Negate` model nodes. A plan separates
record predicates from top-level `source(...)` predicates. Controllers send
version-1 JSON query documents through the backend seam; these contain named
operations, fields, and values rather than SQL or Mongo operators.

SQLite compiles predicates to parameterized SQL at its storage boundary. The
source-dialog evaluator uses the same model and two-valued Boolean semantics.
The remaining collection-shaped local data-access code accepts legacy filters
through `query_from_filter()`. Source restriction resolution adapts predicates
to that format internally for its existing candidate/aggregate logic. The old
`python_query_to_filters()`, `python_query_to_mongo()`, and
`mongo_filter_matches()` names remain compatibility exports for existing callers;
active controllers use the new parser and evaluator.

### Implemented Predicate Contract

- Aliases, supported text syntax, and parser complexity limits remain in
  `query_parser.py`. Unknown fields, type mismatches, nested membership values,
  and ordered comparisons to `None` or lists are rejected.
- Missing fields and explicit nulls both compare equal to `None`. A bare field
  means non-null, so numeric zero and empty text count as present.
- Equality to a non-null value, ordered comparisons, and substring tests return
  false for nulls. `not` always complements a Boolean result, including for
  nulls. Thus `not (min > 0)` includes missing extrema.
- Membership supports `None`: `min in [None, 0]` includes null extrema and zero.
  `not in` is its complement. Membership in an empty list is always false;
  membership exclusion from an empty list is always true.
- `contains(field, text)` performs a case-sensitive literal substring match.
  Text is regex-escaped internally; the public language does not accept raw
  regex patterns.
- `and`, `or`, and `not` use Python precedence and respect parentheses.
  All predicates apply, including sibling fields beside legacy Boolean groups.
- Source clauses remain top-level conjuncts and intersect resolved source
  identities across clauses. Campaign path participates in source identity.
  Existing aggregation of per-variable source extrema remains in place.
- Global filters still propagate to catalog, source discovery, and visualization
  operations. Source filters still operate on summary rows after global
  filtering, so summary extrema and individual stored-record extrema can differ.
- Invalid global queries preserve the active query. Invalid source-filter drafts
  preserve the active filter, rows, and selection and show an error. The Source
  Filter action submits the current textbox value explicitly so a rapid click
  cannot apply the previous draft while Trame batches model updates.

`tests/test_query_semantics.py` fixes expected Python/SQLite selections for nulls,
negation, membership, literal substrings, and compound predicates.
`tests/test_multi_campaign_sources.py` covers source-clause intersections and
archive identity through the controller/backend/storage path.

The separate metadata SQL API retains SQL semantics (including SQL null logic);
its contract and result tables are described in `docs/metadata-queries.md`.

Remaining design constraints:

- local policy code still builds collection filters and uses collection reads;
- catalog records and source summary rows have different grains;
- changing grid refresh scope, query UX, or arbitrary metadata discovery requires
  the product decisions below;
- legacy filters remain accepted during migration; new query consumers should
  use the versioned model documents.

## Start With Workflows

Before choosing syntax or controls, collect representative queries from actual
campaign work. At minimum, evaluate the following workflows.

### Variable Discovery

- Find a variable by logical or physical name.
- Limit variables by dimensionality or variable type.
- Show only variables with stored or generated visualization support.
- Find variables available in one file, source, run, or file group.

### Run And Source Comparison

- Select one or several named runs.
- Select runs whose parameter metadata meets a condition.
- Select runs containing another variable with a specified value or range.
- Compare the same variable across selected sources.
- Handle reused producer, case, file, and dataset names without ambiguity.

### Statistics And Quality Conditions

- Filter by minimum, maximum, moments, or other summary statistics.
- Select sources where a validity or convergence variable meets a condition.
- Distinguish a statistic of the selected variable from a statistic used only
  to select sources.
- Define behavior when statistics are missing, non-finite, or unavailable.

### Visualization Discovery

- Find variables with a particular visualization kind or name.
- Distinguish stored images, videos, scalar fields, generated plots, and plugin
  results.
- Decide whether visualization metadata belongs in the main query language or
  in visualization-specific controls.

### XGC And Other Domain Workflows

- Filter on campaign-specific metadata without adding new parser code for every
  campaign.
- Support grouped variables such as moments while keeping domain terminology
  discoverable.
- Decide whether arbitrary metadata keys are queryable, and how their types and
  availability are described.

Representative examples should be recorded with the expected catalog, source,
and grid results. Those examples should become semantic acceptance tests.

## Define The Concepts First

The query model should distinguish these entities explicitly:

- **campaign**: the selected campaign and its version;
- **variable**: a source-independent scientific variable identity;
- **source/run**: the producer, file group, dataset, or Phobos foray providing
  variables;
- **record/sample**: a source-specific observation or metadata record;
- **visualization**: a stored or generated representation associated with a
  variable and source;
- **artifact**: image, movie, plot, or plugin result delivered to the viewer.

Every public query field should say which entity it describes. Ambiguous names
such as `source`, `file`, and `min` need precise definitions.

## Query Scope Decisions

For each query surface, decide which parts of the viewer it controls.

| Viewer area | Current global Query | Decision needed |
| --- | --- | --- |
| Variable catalog | Filters available variables | Keep filtering, or highlight matches? |
| Source dialog | Filters source discovery | Should the dialog inherit the global Query automatically? |
| Existing grid cells | Operations consult the active query | Should already-loaded cells remain stable? |
| New grid assignments | Uses currently matching sources | Define deterministic default-source selection. |
| Stored visualizations | Lookup receives the active query | Decide whether query changes may replace an existing artifact. |
| Generated plots and fields | Generation receives the active query | Decide whether query changes invalidate or regenerate results. |
| Plugins | Plugin context may inherit query-selected data | Define whether plugins receive a query, resolved IDs, or explicit inputs. |

The safest default may be to treat a query as a catalog/source selection and
leave existing grid cells unchanged until the user explicitly refreshes or
replaces them. That is a design option, not a settled decision.

## Query Surface Options

### Option A: Text Query Only

Retain an advanced textual language as the primary interface.

Advantages:

- compact and expressive;
- easy to copy, save, and share;
- supports cross-variable source conditions;
- efficient for experienced users.

Risks:

- poor discoverability;
- users must know field names, types, and scope;
- validation and error messages must be excellent;
- complex expressions are difficult to edit safely.

### Option B: Structured Filter Builder

Provide rows or groups containing field, operator, and value controls.

Advantages:

- discoverable fields and valid operators;
- type-aware values and validation;
- can expose available values and counts;
- easier to use without memorizing documentation.

Risks:

- cumbersome for complex Boolean expressions;
- cross-variable source conditions require a clear nested UI;
- sharing and versioning still need a serialized representation.

### Option C: Facets Plus Advanced Text

Use search and common facets for ordinary filtering, with an advanced textual
query for complex cases.

Advantages:

- common operations are visible;
- advanced workflows remain possible;
- both interfaces can compile to one semantic query model.

Risks:

- synchronization between text and structured controls must be defined;
- two interfaces can become inconsistent if they do not share one compiler;
- the UI needs a rule for expressions the structured editor cannot represent.

This hybrid is a strong candidate, but should be tested with actual campaign
workflows before adoption.

## Field Model

The current language recognizes aliases and storage-oriented fields. The
redesign should publish a typed field catalog instead of relying on parser code
as documentation.

| Concept | Current names | Questions |
| --- | --- | --- |
| Variable identity | `id`, `variable_id` | Is this stable across campaigns and backends? |
| Variable name | `var`, `variable_name` | Does it mean logical, physical, or display name? |
| Variable type | `type`, `variable_type` | Which values are public and stable? |
| Source/run | `source`, `dataset`, `source_dataset` | Should users select an opaque source ID, a label, or either? |
| Producer/case/file | `producer`, `casename`, `file` | Are these legacy local fields or durable concepts? |
| Statistics | `min`, `max` | Which record or variable do they describe? What other statistics are supported? |
| Visualization | visualization name/kind/source | Are these query fields or separate visualization filters? |
| Paths | campaign, variable, and location paths | Should backend/local paths be exposed to users? |
| Frame | `frame_index` | Is frame-level filtering useful in the catalog? |
| Metadata | currently fixed fields | Should typed arbitrary campaign metadata be supported? |

For every retained field, specify:

- canonical name and optional aliases;
- value type;
- entity and scope;
- supported operators;
- null and missing-value behavior;
- whether values are enumerable for UI completion;
- whether local and Phobos backends can implement it efficiently;
- whether it is safe to serialize and share.

## Operator Model

The current implementation supports equality, inequality, ordered comparisons,
membership, negation, Boolean groups, existence-by-name, and `contains()`.

The redesign must define:

- type compatibility for every operator;
- case sensitivity and Unicode behavior for text matching;
- literal substring versus regular-expression support;
- whether numeric strings are coerced or rejected;
- whether `in` and `not in` require a list or tuple;
- missing versus explicit null values;
- floating-point comparisons and non-finite values;
- precedence and parenthesis rules;
- maximum query complexity, depth, and list size.

Regular expressions should not be enabled accidentally through storage
translation. If regex is supported, it should be an explicit, documented
operator with complexity limits.

## Reconsider `source(...)`

The underlying cross-variable selection is useful, but the syntax and name may
not communicate its meaning. Alternatives include:

- retaining `source(expression)` with clearer documentation and completion;
- renaming it to `sources_where(expression)` or `run_where(expression)`;
- representing it as a structured "sources containing..." filter group;
- separating source selection from the variable query entirely;
- allowing saved named source sets that can be reused across queries.

Questions to resolve:

- Does more than one source clause mean intersection or union?
- Can source clauses appear under `or` or `not`?
- Does the inner expression operate on individual records or aggregate source
  statistics?
- How are two variables in the same inner condition correlated?
- Does a matching visualization record select its source, or only scientific
  variable records?
- How is an empty source match displayed?
- Should users see the resolved source set before applying it globally?

Whatever syntax is chosen, source matching must use a stable compound source
identity. Reused producer names must not select unrelated cases or files.

## Query And Source Filter Relationship

Possible models include:

1. keep two filters, but give each an explicit label, field catalog, and scope;
2. use one query with a scope selector;
3. keep global campaign filtering and replace Source Filter with simple search
   and facets;
4. make source selection a first-class saved set rather than a second textual
   query.

The redesign must avoid presenting identical syntax that behaves differently
without explaining why. If the surfaces remain separate, validation should
reject fields unavailable in the selected scope rather than silently returning
no rows.

## Application And Result Behavior

Decide the following interaction rules:

- apply on every keystroke, explicit Apply, or both with a debounce;
- preserve the previous successful result after a syntax/backend error;
- distinguish zero matches from unavailable data and backend failure;
- show total versus filtered variable and source counts;
- display the active query persistently when dialogs are closed;
- make Clear and undo behavior predictable;
- define whether query changes alter current selection or only available
  choices;
- provide progress/cancellation if a remote query is expensive;
- define deterministic ordering and pagination.

Errors should identify the problematic field, operator, or source clause and,
where possible, its text range. Backend errors must not be reported as a valid
empty result.

## Viewer-State Persistence

Viewer state save/restore should not serialize Mongo/SQLite filters or an
unversioned Python AST. Consider storing:

- the original query text for display and editing;
- a versioned normalized semantic query when exact round-trip behavior is
  required;
- explicit selected source IDs when the user chose sources directly;
- the query-language version used to interpret saved text;
- whether the saved query should be re-executed on restore.

Resolved source sets can become stale when campaign data changes. Saved state
needs campaign/version identity and a defined policy for missing variables,
sources, and query fields.

## Backend-Neutral Contract Requirements

The eventual Phase 5B.2 contract should describe meaning, not storage syntax.
It should provide:

- a versioned, serializable Boolean expression tree;
- typed predicates using canonical field names and semantic operators;
- explicit source-selection clauses or source-set references;
- normalized result counts and stable variable/source IDs;
- typed validation and execution errors;
- capability discovery for supported fields and operators;
- pagination, ordering, and limits where applicable;
- cancellation or job behavior for expensive remote execution.

The local adapter may translate that model to SQLite. A Phobos adapter may
translate it to REST parameters or call a dedicated query endpoint. Neither
translation should be visible to Trame state or controllers.

## Phobos Considerations

The query redesign should not force Phobos to emulate MongoDB or local ACA
document structure. Before implementing a Phobos adapter, determine:

- which fields already exist on Campaign, Foray, Variable, Image, Video, and
  Metadata resources;
- which filters can be executed by existing list endpoints;
- whether cross-variable source selection requires a dedicated server-side
  query endpoint;
- how arbitrary metadata is typed and indexed;
- how authorization affects counts and source-set resolution;
- whether result IDs are stable across reingestion and campaign versions;
- how large result sets are paginated;
- how query capabilities and language versions are advertised;
- how errors from multiple underlying resources are normalized.

Credentials and authorization tokens must remain server-side. Query text and
errors must not expose inaccessible object names or backend implementation
details.

## Performance And Safety

Evaluate queries against realistic campaign sizes and remote latency. Define:

- indexed fields for the local SQLite sidecar and Phobos;
- maximum Boolean depth, predicate count, and membership-list size;
- substring/regex cost limits;
- timeouts and cancellation behavior;
- caching keyed by campaign version and normalized query;
- whether counts are exact, estimated, or deferred;
- protection against pathological expressions and excessive server work.

Python expressions must remain a restricted language. Never use `eval`, permit
attribute access, invoke arbitrary functions, or accept arbitrary Python
objects.

## Compatibility And Migration

Once a design is selected:

1. write semantic tests for current workflows before changing implementation;
2. define a versioned normalized query representation;
3. compile both text and structured controls to that representation;
4. implement local evaluation and storage translation behind the backend;
5. compare old and new results on representative campaigns;
6. document intentional behavior changes;
7. migrate controller state away from storage dictionaries;
8. retain a compatibility parser only for saved queries that need it;
9. add the Phobos implementation against the same contract tests.

Do not preserve parser quirks solely for compatibility. Preserve documented and
validated user workflows.

## Acceptance Criteria For A Redesign

A query redesign is ready for implementation when:

- representative XGC, MHD, and schema-less workflows have expected results;
- Query and Source Filter scope is unambiguous;
- fields, aliases, types, operators, and null behavior are documented;
- source/run identity and cross-variable selection semantics are explicit;
- common operations are discoverable without memorizing internal field names;
- text and structured controls, if both present, share one semantic model;
- invalid input and backend failures produce useful, distinct errors;
- saved viewer state has a versioned query representation;
- both local SQLite and future Phobos execution paths are feasible;
- performance limits and pagination behavior are defined;
- contract, parser, integration, and browser tests cover the agreed behavior.

## Suggested Design Review Sequence

1. Gather 10–20 real queries and expected results from current users.
2. Classify each query as variable discovery, source selection, statistics,
   visualization discovery, or domain metadata.
3. Prototype the simplest common operations as search/facets.
4. Test whether the advanced text language is still needed for the remaining
   workflows.
5. Decide the future of `source(...)` using cross-variable examples.
6. Write the field/operator specification and scope matrix.
7. Review the design against local SQLite and Phobos capabilities.
8. Approve the semantic contract before beginning Phase 5B.2 implementation.

## Open Decisions

- What are the five most common queries users actually run?
- Should Query modify existing grid cells or only future catalog/source choices?
- Is Source Filter still needed as a separate textual language?
- Should common source/run parameters be facets?
- Is `source(...)` understandable, or should source sets be first-class?
- Which metadata fields must be extensible per campaign?
- Which fields are safe and meaningful across both local and Phobos backends?
- Should query execution be immediate or explicit?
- How should query text, normalized form, and resolved sources be persisted?
- Which old behaviors are requirements, and which are implementation accidents?
