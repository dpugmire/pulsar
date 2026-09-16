# Seurat

This is a small Trame (Vue3) application for viewing ADIOS campaign data.
On startup, it reads a `.aca` campaign file into a Seurat SQLite sidecar DB and
provides a UI to browse variables, view min/max summaries, filter with a simple
query language, and preview image sequences as short videos.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a diagram of the browser, Trame,
application, backend, local ACA/SQLite, and future Phobos layers.
See [SEURAT_OVERVIEW.md](SEURAT_OVERVIEW.md) for a consolidated product,
interaction-design, implementation, and prioritized roadmap overview.

`seurat.app.SeuratApp` is the composition root. It owns the Trame server,
enables Seurat's web module, initializes state, connects the data access layer
to controller adapters, and constructs the UI. The top-level `app.py`, `ui.py`,
and `state_init.py` modules remain compatibility entry points.

The main architectural boundaries are:

- `seurat/components/`: composable `TrameComponent` UI sections. The root UI
  owns the query toolbar, variable catalog, grid workspace, dialogs/settings,
  and context menu.
- `seurat/module/`: registered JavaScript and CSS assets served by Trame. Web
  identifiers use the `seurat` namespace and assets are included in wheels.
- `seurat/widgets.py`: Python wrappers for Seurat's registered Vue components.
  The grid runtime component coordinates focused timeline, media, and plot
  lifecycles. The timeline runtime owns timeline selection, VCR controls,
  image/video synchronization, timers, and media observation. The media runtime
  owns pan/zoom and reset-view observation. The plot runtime owns plot-data
  parsing, SVG rendering, cursor drawing, hover/pan/zoom interactions, and
  render observation. The interaction runtime owns app-scoped variable/grid
  and tab drag-and-drop, pane-divider resizing, context menus, and floating-panel movement. The resize runtime
  owns variable-panel and grid-track resizing, including pointer capture. All
  runtimes release their listeners, observers, timers, pointer state, and
  transient styling on unmount.
- `seurat/models/`: pure, dependency-free grid, timeline, and source-selection
  behavior, plus plot, plugin-option, and grid-layout normalization. Controllers
  adapt Trame state to these testable operations.
- `seurat/state/`: explicit, non-overlapping state ownership for catalog,
  sources, visualization settings, grid/timeline, and context menus.
- `seurat/controllers/`: Trame-facing adapters organized by catalog, source,
  grid, visualization, context-menu, and lifecycle ownership. Each domain
  declares the actions, triggers, and state-change callbacks it registers.
- `seurat/backends/`: backend-neutral capability contracts and the current
  local ACA/SQLite adapter. Catalog navigation, availability, source
  descriptors, source statistics, and source restriction resolution now route
  through this seam; later query, media, and compute capabilities remain
  documented in [PHOBOS_INTEGRATION.md](PHOBOS_INTEGRATION.md).
- `application.py`: application facade over the injected backend capabilities;
  it retains compatibility exports for the typed navigation and source
  contracts.
- `controllers.py`: compatibility exports for the packaged controller adapters.
- `ingest_campaign.py`, `sqlite_store.py`, and `db.py`: ACA ingestion, SQLite
  collection compatibility, and campaign data access/rendering.

Keep domain decisions in `seurat/models/` and state defaults in the owning
`seurat/state/` module. Keep Trame callbacks and their registration declarations
in the matching `seurat/controllers/` domain. UI components should bind state
and controller actions, not duplicate those decisions in markup or browser
code. Backend implementations should return normalized application DTOs rather
than exposing collection documents, ACA paths, or remote API objects to Trame
controllers. See [PHOBOS_INTEGRATION.md](PHOBOS_INTEGRATION.md) for the planned
Phobos boundary and remaining migration phases.

Query rearchitecture is currently paused for product and workflow review. See
[QUERY_REDESIGN.md](QUERY_REDESIGN.md) for the current behavior, design options,
backend constraints, acceptance criteria, and open decisions that should be
resolved before Phase 5B.2 resumes.

Client-side event and observer ownership is lifecycle-scoped rather than
document-global. The registered runtimes own grid timeline/VCR behavior,
variable/grid/tab drag-and-drop, Freeform canvas placement and resizing,
pane-divider resizing, context menus, floating-panel movement,
variable-panel and grid-track resizing, media pan/zoom, plot interaction, and
plot rendering observation. Timeline/VCR policy lives in
`seurat/module/serve/seurat-timeline-runtime.js`; media pan/zoom and its reset
observer live in `seurat/module/serve/seurat-media-runtime.js`; plot parsing,
SVG rendering, and plot interaction live in
`seurat/module/serve/seurat-plot-runtime.js`. The small
`seurat/module/serve/seurat.js` coordinator mounts these domains and connects
combined reset/cursor behavior. Internal runtime objects are collected under
`window.seurat.runtimes`; existing top-level aliases remain for Trame Vue plugin
registration compatibility.

### Workspace panes and tabs

Each workspace tab owns its grid dimensions, track sizes, cell contents,
selection, timeline-driver cell, and per-cell visualization settings. A split
pane owns which of its tabs is visible. Campaign selection, the query and
variable catalog, and the current timestep remain shared across the workspace.

The workspace layout is a binary split tree with pane leaves. Any pane can be
split right or down until the four-pane limit is reached. Drag a divider to
resize its two child regions; double-click it to restore an even split. Split
ratios are stored proportionally in workspace JSON so they survive window-size
changes and save/load cycles. Older one- and two-pane workspace files are
migrated to the tree representation when loaded.

Closing a tab removes that tab's grid after confirmation. Tabs can be renamed
or closed from their context menu, and the visible close button provides the
same close action. Drag tabs to reorder them within a pane or move them to a
specific position in another pane. Moving the last tab out of a pane closes
that empty pane. Tab strips remain on one line and show edge fades when more
tabs are available by horizontal scrolling.

Drag a filled visualization cell onto a cell in an inactive pane preview to
move it between tab-owned grids. A valid destination is highlighted during the
drag, and a successful drop activates the destination pane and tab.

## Run

Requirements (at minimum):

- Python deps: `trame`, `trame-vuetify`, `adios2`, `numpy`, `Pillow`.
- Optional for YAML campaign and image-association schemas: `pyyaml`.
- Optional for synthetic demo campaigns: `hpc-campaign` and `python-dateutil`.
- `ffmpeg` available on PATH for movie preview tiles.

Image sequence bytes are loaded lazily from the ACA file when a preview tile is
built. The SQLite sidecar stores frame metadata and ADIOS variable paths, not
copied image blobs.

Install the Python dependencies from this repo:

```bash
python -m pip install -e ".[schema]"
```

Include the demo dependencies to use the synthetic campaign launcher:

```bash
python -m pip install -e ".[schema,demo]"
```

Install the browser-test dependencies and Chromium with:

```bash
python -m pip install -e ".[schema,test]"
python -m playwright install chromium
```

The browser tests are opt-in so the normal suite remains fast and does not
require a browser installation:

```bash
SEURAT_RUN_BROWSER_TESTS=1 python -m pytest -q tests/browser
```

The deterministic browser fixture does not require a campaign archive. It
exercises application mounting, variable grouping, grid selection and
assignment, layout controls, context menus, rendering, and both schema-less
step-index and declared physical-time timelines in a real Chromium client. It
also covers variable-panel and grid-track resizing, pointer capture, cleanup,
and idempotent runtime remounting. Floating-panel movement, media pan/zoom,
plot hover/pan/zoom, reset requests, observer teardown, and render-timer cleanup
are exercised through the same mounted-client suite.

Example:

```bash
python app.py campaign.aca

# Generate an ephemeral synthetic campaign and launch it
python app.py --demo
# Optionally choose a source count from 1 through 49
python app.py --demo 12
# Equivalent after an editable install: seurat --demo

# Optional: supply a campaign schema when schema.yaml is not embedded
python app.py campaign.aca --campaign-schema schema.yaml

# Optional: pass image association schema text/YAML
python app.py campaign.aca --image-association-schema image_variable_map.yaml
```

Demo mode creates 20 time steps for five deterministic sources by default;
`--demo SOURCE_COUNT` accepts counts from 1 through 49. Each source contains
three 1D profiles, two scalar time series, and three 2D scalar fields. The
scalar time series track the moving pulse's circular centroid and the damped
mode's mean squared amplitude. Every 2D field has both heatmap images and a
`scalar_field` representation. The campaign, source data, rendered images,
scalar payloads, and Seurat sidecar are kept in one temporary directory and
removed when the viewer exits normally. `--demo` is mutually exclusive with a
campaign path and external schema options.

## Natural-Language Viewer Assistant

The optional Query Assistant translates a natural-language request into a
versioned, structured Viewer Action proposal. The current action types are
`catalog.query` and `visualization.add`. Seurat validates and previews every
proposal and changes viewer state only after explicit confirmation. The model
proposes an action; it cannot invoke viewer operations, read array values, or
bypass server-side validation.

Source ranking uses the campaign's stored per-source `minimum` and `maximum`
metadata. For example, select `pressure` in the catalog and ask `largest max`.
The model describes the ranking operation without guessing a value, and Seurat
locally finds the source or tied sources whose pressure maximum is largest.
Phase 1 supports AND-combined conditions and top-one source ranking with ties.

The dialog shows a read-only **Resolved Advanced Query** because the current
local backend still consumes the existing Python-like query representation.
That string is generated by Seurat from the validated Viewer Action; it is a
compatibility detail, not model output. Manually authored queries remain
available in the toolbar as **Advanced Query**.

The Sources dialog uses the same assistant without changing the global catalog
query. Enter natural language in **Filter Sources** and choose **Ask** to review
a source-filter proposal for the currently selected variable. **Apply to Source
Filter** updates only the visible source rows. The existing **Filter** button
continues to accept manually authored Advanced Query expressions.

To add a visualization, first select a grid cell and choose **Visualize** in the
toolbar. Requests such as `Show pressure`, `Plot rho in the selected cell`, or
`Add temperature to the active cell` propose one `visualization.add` action.
The review dialog identifies the variable, destination cell, and visualization
that the viewer will use. **Add to Grid** applies the action through the same
assignment path used by the GUI.

The first visualization increment accepts one exact variable and the active
cell. Seurat applies the active catalog query, current source selection, default
visualization choice, plugin availability, and scalar-plot generation policy.
Explicit visualization types, sources, multiple variables or cells, overlays,
and visualization settings are not yet accepted. If raw scalar data requires
generation and the session policy is **Ask**, the existing scalar-plot
confirmation dialog still appears.

Seurat talks to an OpenAI-compatible Chat Completions endpoint using Python's
standard library, so no additional Python package is required. For a local
Ollama `gpt-oss:20b` server:

```bash
ollama pull gpt-oss:20b
ollama serve

export SEURAT_LLM_MODEL="gpt-oss:20b"
export SEURAT_LLM_BASE_URL="http://localhost:11434/v1"
export SEURAT_LLM_API_KEY="ollama"
python app.py campaign.aca
```

`SEURAT_LLM_MODEL` enables the **Ask** and **Visualize** buttons. The base URL
defaults to the Ollama endpoint above, the API key defaults to Ollama's dummy
`ollama` value, and `SEURAT_LLM_TIMEOUT_SECONDS` defaults to 30. A `llama.cpp`
server or another provider can be used by setting its OpenAI-compatible `/v1`
base URL, model name, and API key.

For each translation, Seurat sends the request, at most 200 variable catalog
entries (IDs, names, labels, paths, and source-dataset names), and at most 200
distinct source-dataset names to the configured endpoint. Individual metadata
values are also length-bounded. Per-source numeric statistics used for ranking
are not sent to the model. It does not send array values or media. Provider
credentials remain in the Python process and are not placed in Trame state.

## Save And Load Workspace State

Open the hamburger menu to access **Save**, **Save As…**, and **Load…**.
**Save As…** opens a native file browser and defaults to `<campaign>.json`.
After saving or loading, the drawer shows the absolute path; subsequent
**Save** commands write to that file. The selected path is on the machine
running Seurat.

The versioned JSON document stores the active query and catalog view, grid
layout and sizing, variable/source assignments, visualization choices and
settings, selected cells, and timeline driver. Rendered plots, image/video
bytes, frame payloads, and other derived media are intentionally excluded.
Seurat validates the state-file version and campaign name, then rebuilds
derived content from the campaign when loading.

The grid settings menu offers **Uniform**, **Spanning**, and **Freeform**
layouts. Freeform uses a 24-column canvas with a fixed vertical unit. Drag tile
headers to move them, use the bottom-right handle to resize, and control grid
snapping, collision nudging, and grid visibility from the same menu. Workspace
files store Freeform tile positions and sizes in canvas units rather than
pixels.

## Optional Interaction Log

Seurat can write a local, append-only JSONL log of normalized queries,
visualization choices, workspace tab/pane/grid organization, and sanitized
saved-workspace snapshots. Logging is disabled by default and does not change
visualization behavior. Enable it by selecting a private directory:

```bash
export SEURAT_INTERACTION_LOG_DIR=/path/to/private/seurat-logs
export SEURAT_INTERACTION_LOG_MAX_MB=64
```

The log excludes campaign and workspace file paths, raw query/assistant text,
tab titles, arrays, and media payloads. Validate and summarize it with:

```bash
python -m seurat.learning.audit /path/to/private/seurat-logs
```

See [Interaction Log v1](docs/interaction-log-v1.md) for the event contract,
privacy boundaries, and workspace snapshot schema.

By default, Seurat stores its viewer sidecar DB under `~/.cache/seurat` using a
filename derived from the resolved campaign path. Override the location with:

```bash
export SEURAT_CACHE_DIR=/path/to/cache-dir
export SEURAT_SQLITE_DB=/path/to/viewer-cache.sqlite
```

## Embedded Campaign Schema

Seurat reads hpc-campaign's canonical embedded text dataset
`__campaign_schema.yaml`. Archives using the earlier `schema.yaml` name remain
supported as a fallback. If both names are present, the canonical name wins.
A time-series group written by appending steps to one ADIOS dataset can select
either one exact campaign dataset with `path` or multiple datasets with
`pattern`. Each matched append-mode dataset resolves its time variable relative
to itself.

For example, this schema associates every BOUT++ simulation and analysis
dataset with its own appended `wtime` values:

```yaml
schema_version: 1
name: boutpp-selected-runs

time:
  variable: wtime

files:
  simulations:
    role: time_series
    mode: append
    pattern: "runs/**/simulation"

  analyses:
    role: time_series
    mode: append
    pattern: "runs/**/analysis"
```

Embedding the schema keeps it available when the campaign is copied to another
system. For archives without an embedded schema, pass the same schema explicitly
with `--campaign-schema path/to/schema.yaml`.

Optional `axes`, `meshes`, `basis`, `variable_groups`, and
`visualization_templates` sections describe multiple logical data models inside
one source dataset. Variable-group patterns match complete ADIOS variable paths;
`*` stays within one path segment and `**` may cross `/` separators. Seurat
validates referenced ADIOS variables during ingest and attaches the matched
group, role, data model, resources, axes, and static status to each variable.

This permits one M3D-C1 BP dataset, for example, to use
`metadata/time_values` for `fields/*`, `scalars/time` for `scalars/*` and
`pellet/*`, and no timeline for static `equilibrium/fields/*`. The canonical
M3D-C1 example is `data/schema_examples/code_m3dc1.yaml` in hpc-campaign.

### Multiple coordinate axes

An axis-aware variable group may declare the coordinate associated with each
array dimension separately from the coordinate shown on a plot and the
coordinate controlled by the workspace slider. This is useful for acquisition
data in which an ADIOS dataset contains one step but its arrays contain many
shots:

```yaml
schema_version: 1
name: lasernet

files:
  laser_runs:
    role: static
    pattern: "data/*.bp5"

axes:
  shot:
    file: laser_runs
    variable: data/meshes/shots/shot_number/value
    kind: shot
    label: Shot number
    dimension: 0

  trace_time:
    file: laser_runs
    variable_template: "{variable_parent}/time"
    kind: within_shot_time
    label: Time within shot
    unit: s
    dimension: 1
    layout: per_selection

timeline:
  default_axis: shot

variable_groups:
  shot_scalars:
    file: laser_runs
    pattern: data/meshes/scalars/*/value
    role: scalar_trace
    dimension_axes: [shot]
    plot_x_axis: shot
    selection_axis: shot

  waveforms:
    file: laser_runs
    pattern: data/meshes/traces/*_Trace/signal
    role: waveform
    dimension_axes: [shot, trace_time]
    plot_x_axis: trace_time
    selection_axis: shot
```

`dimension_axes` must have one entry per data-array dimension. An axis-level
`dimension`, when present, must agree with that position. `plot_x_axis` controls
the plot coordinates; `selection_axis` controls the slider. Selection-axis
coordinates must be one-dimensional numeric values. Plot coordinates may be a
shared one-dimensional vector or, with `layout: per_selection`, a rank-two
array whose matching row is loaded with the selected data row.

`variable_template` supports `{variable}`, `{variable_parent}`, and
`{variable_name}` placeholders. It allows each matched waveform to resolve a
sibling coordinate such as `time` without listing every trace explicitly.

Axis identity is based on the schema name, file group, and axis name. Tiles
with the same selection-axis identity synchronize by coordinate value. Tiles
with a different axis, or without the selected coordinate value, remain static
and are marked as incompatible or unavailable. Schemas using the existing
`x_axis`, `time_axis`, and `time_values` fields retain their previous behavior.

Visualization association notes:

- Unified hpc-campaign image and scalar-field representations are associated
  through the ACA `logical_variable` and `variable_*` graph tables.
- Campaigns created with the earlier hpc-campaign visualization API remain
  associated through the ACA `visualization_*` metadata tables.
- Seurat treats `variable_id` as a source-independent variable identity. Different source datasets for that same variable remain separate through the `source_dataset` field.
- For visualization API images, `variable_id` comes from `visualization_variable.variable_name`.
- Legacy image path parsing is still used as a fallback for older campaigns.
- Longer term, the viewer should use an explicit display/grouping schema that separates the raw source variable name, the viewer display label, the variable grouping id, and the source dataset. Until that exists, the campaign variable name is used directly for both grouping and display.

Schema notes (`image_variable_map.yaml`):

- `rules` map image logical paths to `variable_name` + `visualization_name`.
- Optional `physical_to_logical` maps file variable names to logical names.

Example:

```yaml
schema_version: 1
physical_to_logical:
  exact:
    hll_pressure: pressure
  regex:
    - pattern: "^hll_(.+)$"
      replace: "\\1"
```

## Plugins

Seurat loads built-in plugins from `seurat_plugins/` and personal plugins from:

```text
~/.seurat/plugins
```

Add more personal plugin search directories with a colon-separated environment
variable:

```bash
export SEURAT_PLUGIN_PATH=~/.seurat/plugins:/path/to/other/plugins
```

For persistent per-user plugin paths, add `plugin_paths` to
`~/.seurat/profile.json`:

```json
{
  "plugin_paths": [
    "/path/to/hpc-campaign-examples/plugins/seurat",
    "~/other/seurat/plugins"
  ]
}
```

Seurat expands `~` and environment variables in these paths. Plugin paths are
loaded in this order, with duplicates ignored:

1. `~/.seurat/plugins`
2. `~/.seurat/profile.json`
3. `SEURAT_PLUGIN_PATH`

Each plugin is a Python file. Files whose names start with `_` are ignored.
Broken personal plugins are skipped and reported on stderr so one bad local
plugin does not prevent Seurat from starting.

Plugin directories may also contain helper modules whose names start with `_`.
Plugin files can import those helpers with relative imports, for example:

```python
from ._helpers import shared_function
```

Simulation-specific plugins should live with the simulation or example repo
that defines the relevant variables. For example, the Orszag-Tang MHD energy
diagnostic plugins live in `hpc-campaign-examples/plugins/seurat` and can be
enabled with:

```bash
export SEURAT_PLUGIN_PATH=/path/to/hpc-campaign-examples/plugins/seurat
```

Minimal variable plugin:

```python
PLUGIN_ID = "my_profile_plugin"
LABEL = "My profile plugin"
PLUGIN_SCOPE = "variable"  # default

def supports(meta):
    return meta.get("ndims") == 1

def options_schema(meta):
    return []

def render(ctx):
    helpers = ctx["helpers"]
    # Return a Seurat tile dict, for example media_type="plot1d".
    ...
```

Minimal source/run plugin:

```python
PLUGIN_ID = "my_source_plugin"
LABEL = "My source plugin"
PLUGIN_SCOPE = "source"

def supports_context(meta):
    return "my_file.bp" in meta.get("source_dataset", "")

def options_schema(meta):
    return []

def render(ctx):
    # Return a Seurat tile dict, for example media_type="image".
    ...
```

Variable plugins appear as `plugin:<id>` visualization choices for compatible
variables. Source plugins appear in the tile right-click menu under `Run
Plugin` for compatible source contexts.

Current cache note: the app currently drops and re-ingests the sidecar each time
it starts. The sidecar is metadata-only for image frames, but the next cache
phase should skip ingest when the ACA file is unchanged.

## TODO

- Source Filter field parity: either enrich source rows with visualization
  metadata so fields like `visualization_name` and `frame_index` work locally,
  or document that those fields are Query-only.
- Source restriction identity: use a compound source/run identity instead of
  preferring `producer` alone, so reused producer names across cases/files do
  not over-include unrelated sources.
