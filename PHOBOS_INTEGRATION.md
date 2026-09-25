# Phobos Backend Integration

This document records the intended boundary between Pulsar's Trame UI and a
future Phobos backend. It reflects the Pulsar and Phobos repositories as of
July 22, 2026.

Phases 5A and 5B.1 do not add a Phobos dependency. They establish narrow
catalog and source capabilities while keeping the existing ACA/SQLite
implementation behind a local adapter. The remaining backend work should move
through that boundary rather than exposing Phobos REST objects, Django models,
ACA paths, or SQLite documents to Trame controllers.

## Ownership Boundary

Pulsar should continue to own presentation and interactive workspace policy:

- Trame state and controller callbacks;
- variable-panel and grid selection;
- grid layout, cell movement, spanning, and resizing;
- context menus and dialogs;
- plot appearance and client-side SVG interaction;
- selection of the timeline-driver cell and synchronized client playback;
- user-visible loading, pending, ready, and error state.

The backend should own data and compute concerns:

- campaign discovery and authorization;
- variable, source/run, image, video, and metadata discovery;
- query execution over campaign metadata;
- access to ADIOS/ACA payloads;
- generated images, scalar plots, and analysis/plugin execution;
- durable caching and invalidation;
- background job execution and result storage;
- transport URLs or streams for media and generated artifacts.

Pulsar controllers should call application operations that return normalized
Pulsar DTOs. A backend adapter is responsible for translating those operations
to the local implementation or to Phobos.

## Phase 5A Boundary

Phase 5A introduces the following catalog contract:

- `CatalogBackend.get_navigation(request)` returns normalized navigation nodes;
- `CatalogBackend.get_status()` reports availability without exposing storage;
- `LocalCampaignBackend` adapts the existing `CampaignDb` implementation;
- `PulsarApplication` depends on the contract;
- the catalog controller receives the backend through `ControllerContext`.

Navigation resources use string identifiers deliberately. The local backend can
continue to use Pulsar variable IDs, while a future Phobos adapter can encode
Phobos identifiers without making the controller depend on integer Django
primary keys.

The current `query` member preserves Pulsar's existing filter-document dialect
for compatibility. It is a Pulsar application contract, not permission for
controllers to access a database collection. A Phobos adapter will either
translate that filter tree to Phobos requests or use a future Phobos query
endpoint. Phase 5B.2 should formalize the supported fields and operators before
a remote adapter is implemented.

## Phase 5B.1 Source Boundary

Phase 5B.1 adds a separate source capability rather than growing the catalog
contract into a single backend-specific interface:

- `SourceBackend.get_source_summary(request)` returns aggregate statistics and
  normalized source descriptors;
- `SourceBackend.find_source(request)` resolves the source associated with a
  stored visualization;
- `SourceBackend.resolve_source_restriction(request)` isolates the current
  compatibility implementation of `source(...)` clauses;
- `PulsarBackend` composes the catalog and source capabilities required by the
  current application;
- `LocalCampaignBackend` assigns deterministic opaque `local-source:v1:*`
  identifiers rather than exposing composite controller keys as identity.

Local source identity follows schema file group, then source dataset, then the
legacy producer/case/file tuple. It does not include the variable ID, so the
same run/source has the same identity across variables.

The source descriptor retains optional local metadata needed by visualization
and plugin paths that have not migrated yet. Controllers must treat `id` as the
source identity; fields such as `source_dataset`, `producer`, `casename`, and
`file` remain descriptive and compatibility data rather than identifiers.

`SourceRestrictionResult.query` still contains the existing filter-document
dialect because catalog, media, and generated-plot reads have not all moved
behind backend operations. Phase 5B.2 must replace that compatibility result
with the formal backend-neutral query contract before a Phobos adapter is
implemented.

Phase 5B.2 is currently paused while the viewer's query workflows, scope,
language, and user interface are reevaluated. The required design questions,
Phobos constraints, and acceptance criteria are recorded in
[QUERY_REDESIGN.md](QUERY_REDESIGN.md). The overall component and capability
layout is shown in [ARCHITECTURE.md](ARCHITECTURE.md).

## Current Phobos Coverage

Phobos currently provides authenticated Django REST resources for:

- campaigns and campaign kinds;
- forays;
- variables and variable kinds;
- images and image kinds;
- metadata and metadata kinds;
- videos, including media URL, frame count, timestamps, and frame rate.

Campaign, foray, variable, image, metadata, and video querysets are scoped to
campaigns visible to the authenticated user. Phobos also has remote/background
task paths for campaign loading, image retrieval, metadata computation, and
video construction.

Those resources are useful building blocks, but they do not yet implement the
complete Pulsar application contract.

## Operation Mapping And Gaps

| Pulsar operation | Phobos building blocks | Remaining work |
| --- | --- | --- |
| List/select campaigns | Campaign API and user campaign filtering | Add server-side credential/session design for the Trame process and select an active campaign by opaque ID. |
| Variable navigation | Campaign, Foray, VariableKind, and Variable APIs | Define grouping by dimension and file/source, efficient filtering, pagination, and stable display labels. Avoid reconstructing the entire catalog with many client-side REST calls. |
| Query catalog | Existing filtered Phobos list endpoints | Define a Phobos query endpoint or a complete translation of Pulsar's filter tree, including boolean expressions, comparisons, `contains`, and source restrictions. |
| Source/run rows | Foray, Variable, Image, and Metadata relations | Define the normalized source descriptor and aggregate min/max/statistic response required by Pulsar. |
| Visualization choices | ImageKind, Image, and Video resources | Expose visualization identity and association explicitly; distinguish stored images, videos, scalar fields, generated plots, and plugin results. |
| Image sequences | Image metadata plus remote image task | Add an authorized media delivery endpoint or artifact URL. Avoid returning large image sequences as Trame data URIs. |
| Video previews | Video API and stored media URL | Align timeline semantics and define pending/failed build status. |
| Scalar timeseries | Variable and Metadata resources | Add a backend response for plotted series or a generated plot artifact, including series identity and timeline values. |
| Scalar-field rendering | Remote ACA access and image infrastructure | Define render options, cache keys, artifact generation, and job/result APIs. |
| Analysis plugins | Remote worker/task infrastructure | Define plugin discovery, typed options, authorization, execution, progress, cancellation, and result artifacts. Do not import Pulsar's local plugin runtime into Trame controllers. |
| Cache invalidation | Phobos persistence and task results | Define campaign/version identity and result invalidation. Local Pulsar sidecar caching should remain a local-adapter concern. |

## Timeline Contract

Timeline meaning must be explicit at the backend boundary. Pulsar's established
fallback is step index, not a normalized interval:

```text
timeline_mode: "physical_time" | "step_index"
step_index: required for each frame/sample
physical_time: optional and present only when supplied by campaign data
```

If physical time is unavailable, values must be `0, 1, ..., n-1`. A backend or
client must not synthesize `0..1` or `0..10` timestamps.

Phobos currently generates a `0..10` timestamp sequence when image timestamps
are absent during video construction, and its Vue client has the same fallback.
That behavior must be removed or represented separately from simulation time
before Pulsar uses Phobos video timestamps. Video file playback time
(`frame_index / encoded_framerate`) is also distinct from simulation time and
must not be used as the plot/image timeline.

For mixed-length runs, each source retains its own available values. The shared
timeline driver determines the workspace range, while other sources clamp or
stop at their available endpoints according to Pulsar's existing behavior.

## Asynchronous Operations

Catalog reads can remain request/response operations. Expensive visualization
and analysis operations should use an explicit job contract:

```text
request -> accepted(job_id) -> pending/running -> ready(result) | failed(error)
```

The eventual contract needs:

- stable job and result identifiers;
- progress/status polling or server-driven notification;
- cancellation where supported;
- typed, user-displayable errors;
- idempotency/cache keys for repeated requests;
- expiration and regeneration rules for artifacts.

Pulsar already has pending/status state for some generated plots, but controllers
currently call local generation synchronously. Phase 5D should adapt those UI
states to the job model without changing grid and plot runtime APIs.

## Authentication And Deployment

The Phobos API is user-scoped; the current Pulsar application opens one local
campaign at process startup. Before adding the remote adapter, decide:

- whether Pulsar receives an end-user Phobos token or uses a service identity;
- how credentials remain server-side and are refreshed;
- how a Trame session selects a campaign;
- whether multiple users/sessions share one Pulsar process;
- how Phobos authorization failures map to Pulsar state;
- whether browser media URLs require cookies, bearer tokens, or signed URLs.

Authentication tokens must not be placed in Trame state or media attributes
that are serialized to the browser.

## Media Transport

The local adapter currently turns images into data URIs and can build previews
inside the Pulsar process. That is acceptable for local ACA mode but should not
become the Phobos protocol.

The Phobos adapter should return media descriptors containing authorized URLs,
content type, frame/timeline metadata, and artifact status. Pulsar's grid DTOs
can then reference those URLs without copying every image through Trame state.
The design must account for CORS, range requests for video, URL expiration, and
session authorization.

## Planned Follow-On Phases

### Phase 5B.1: Source Capability

- define normalized source descriptors and statistic summaries;
- move source discovery out of direct collection access;
- keep a local implementation and fake contract tests.

### Phase 5B.2: Query Capability

- complete and approve the query redesign described in
  [QUERY_REDESIGN.md](QUERY_REDESIGN.md) before implementation;
- formalize the Pulsar filter tree and source-restriction semantics;
- replace compatibility filter documents at the backend boundary;
- migrate catalog and source query execution behind typed operations;
- keep the current query language and user-visible behavior.

### Phase 5C: Stored Visualization And Media Capability

- define visualization and media descriptors;
- migrate image/video lookup behind the backend;
- establish the explicit timeline contract;
- keep local data-URI generation inside `LocalCampaignBackend` only.

### Phase 5D: Generated Visualization And Job Capability

- define job, progress, result, error, and cancellation DTOs;
- migrate scalar plot, scalar-field, and plugin execution;
- preserve current Trame pending/error UI behavior.

### Phase 5E: Phobos Adapter And Cutover

- add the authenticated Phobos client/adapter;
- add or extend Phobos endpoints identified above;
- run the same backend contract tests against local and Phobos fixtures;
- support explicit local versus Phobos configuration;
- retain local ACA mode until remote parity is demonstrated.

## Integration Acceptance Criteria

The Phobos path is ready to replace the local backend only when:

- controllers no longer access `CampaignDb.collection` for migrated domains;
- no controller or UI payload requires an ACA filesystem path;
- local and Phobos adapters produce the same normalized catalog/source/media
  contracts for shared fixtures;
- schema-less timelines use step indices consistently;
- physical-time timelines preserve campaign values exactly;
- mixed-length source behavior matches the browser characterization suite;
- pending, failed, and expired jobs are visible and recoverable;
- authorization is enforced without exposing credentials to browser state;
- media loading works without embedding complete remote sequences as data URIs.
