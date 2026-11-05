# Local Python control

Pulsar can expose an opt-in control API for Python scripts running on the same
machine as the viewer server. The scripts and browser share one workspace.
The server remains running when a script exits.

Start the normal application with a new session-file path:

```bash
python app.py /path/to/campaign.aca --control-session /tmp/pulsar-session.json
```

The parent directory must exist and the file must not already exist. After
startup, Pulsar prints `Pulsar control session: /tmp/pulsar-session.json`.
The file contains a loopback endpoint, protocol version, instance identity,
and authentication token. It has mode 0600, is never sent to the browser, and
is removed when its server shuts down normally. After a crash, use a new path
or remove the stale file once you have confirmed the original server stopped.
Do not share or commit session files.

In another Python process, using an environment where Pulsar is installed:

```python
from pulsar.client import connect

viewer = connect(session_file="/tmp/pulsar-session.json")
context = viewer.context()
variables = viewer.catalog()
print(context["campaign"])
print(context["selected_variable_id"], context["selected_tiles"])

tab = viewer.create_tab("Resolution comparison")
plot = viewer.add_visualization(
    variables[0]["variable_id"],
    tab_id=tab["tab_id"],
)
print(plot["status"], plot["media_type"])
print(viewer.tabs())
```

Choose a variable with an available visualization or supported local renderer.
`catalog()` lists the current catalog after the viewer's catalog query and
visualized-only filter. `context()` includes the selected variable, selected
source keys and source descriptors, active pane/tab, selected tile summaries,
active query, scalar-generation policy, and timeline-driver cell index.
Browser-local playback position, pan/zoom state, image bytes, and plot arrays
are not included.

`create_tab(title, pane_id=None)` creates and activates a tab in the active pane
or a named pane. `add_visualization(variable_id, tab_id=..., source_ref=None)` activates the
specified tab and uses the same assignment, source-selection, rendering, and
default-visualization rules as the browser. Freeform uses normal canvas
placement; Uniform and Spanning use an empty visible cell. A full workspace
returns an error rather than replacing an existing tile. Each successful
operation is one normal workspace undo step.

By default, the API uses the current query, source selection, and visualization
defaults. Pass an opaque `source_ref` returned by a metadata query to choose an
exact source for that call instead of the current source selection:

```python
result = viewer.query(
    "select source_ref from q_sources where source_dataset=:source",
    {"source": "rusanov_128/output.bp"},
)
plot = viewer.add_visualization(
    "current_z", tab_id=tab["tab_id"], source_ref=result["rows"][0][0],
)
```

References can come from a query over another variable, such as ranking pressure
and then displaying `current_z` for each matching source. The requested variable
must exist in that source within the current catalog query. An unavailable
reference returns `source_not_found` (404); an ambiguous match returns
`ambiguous_source` (409). Both leave the workspace unchanged. Omit `source_ref`
to retain the default behavior. There are no per-call visualization options.
If raw scalar generation is set to Ask, an operation requiring confirmation
fails without leaving a pending dialog or partial plot. Select Always in the
viewer if automatic generation is desired. Existing pending confirmations
must be resolved before adding another visualization.

Responses describe server-applied state. Browser rendering can finish later;
`set_time()` additionally waits for a browser to confirm its seek.
Both the scientist and scripts can edit the workspace; use returned tab IDs
instead of relying on the active tab remaining unchanged between calls.
The existing workspace Save/Load controls persist the resulting arrangements.
Generated PNG plots and MP4 movies can be registered, displayed, and explicitly
published into the campaign as described below.

## Unpublished working results

For read-only SQL over campaign metadata and sortable result tables, see
[Metadata SQL queries](metadata-queries.md). The Python client provides
`query_schema()`, `query()`, `queries()`, `query_result()`, and `show_query()`.
Queries are independent of the current catalog filter and require no raw data
reads. Saved query tables participate in workspace Save/Load and undo/redo.

Register a generated PNG, an optional analysis script, and the scientific
context supplied by the caller:

```python
result = viewer.register_result(
    "/work/current_z_comparison.png",
    title="Current density across resolutions at t=1",
    script_path="/work/compare_current_z.py",
    parameters={"physical_time": 1.0, "color_range": [-6.01, 6.01]},
    provenance={
        "request": "Compare current_z across resolutions at physical time 1.0",
        "intent": "Inspect resolution sensitivity",
        "intent_attribution": "scientist",
        "inputs": [
            {
                "source_dataset": "hll_32/output.bp",
                "variable_id": "current_z",
                "timestep": 21,
                "physical_time": 1.0,
                "dataset_uuid": "<the dataset UUID>",
                "campaign_sha256": "<the input archive checksum>",
            },
            # Include every input and its actual version/timestep.
        ],
        "execution": {"status": "success", "python": "<version used>"},
    },
)
viewer.add_result(result["result_id"], tab_id=tab["tab_id"])
print(viewer.result(result["result_id"]))
print(viewer.results())
viewer.save_workspace("/work/comparison.workspace.json")
```

Paths refer to files on the server's local filesystem. Registration validates
the PNG and copies the original PNG/script, with SHA-256 checksums, into a
durable result bundle. Scripts are retained as artifacts and are never executed
by registration. Later edits to the original files do not change the bundle.
Each registration receives a new result ID, even if its title or image matches
an earlier result. Metadata is optional; missing intent or inputs are not
inferred. Supply real input identities, versions, and times for scientific
provenance. Assistant-written interpretations should retain their attribution.

The tile's **Unpublished** button opens its manifest, including parameters,
provenance, and artifact checksums. Results can coexist with campaign plots,
move/resize normally, and participate in workspace undo/redo. Removing a tile
does not remove its registered bundle; it can be added again by result ID.

`PULSAR_RESULTS_DIR` controls durable storage, defaulting to
`~/.local/share/pulsar/results`. Each campaign's resolved absolute path selects
its own store directory. This is independent of `PULSAR_CACHE_DIR` and the
rebuildable SQLite sidecar. Store creation is lazy and occurs on registration.
Workspace JSON retains only the result ID and tile layout; media, scripts,
and manifests remain in the result store. Unpublished results require the same
resolved campaign path and result directory on reload; copying workspace JSON
alone does not copy their artifacts. Published results resolve from the campaign
and no longer require their working bundles.
Missing or modified artifacts produce an error tile rather than silently
displaying a different result.

After restarting Pulsar against the same campaign and result directory:

```python
viewer = connect(session_file="/tmp/new-pulsar-session.json")
print(viewer.results())
viewer.load_workspace("/work/comparison.workspace.json")
```

The browser's existing Save/Load actions also retain working-result references.
`save_workspace()` writes JSON on the Python client's filesystem;
`load_workspace()` reads it there and sends the document to the server using
the existing workspace validation/restoration rules.

For the MHD resolution-sweep campaign, a complete example computes a shared-scale
`current_z` comparison at an exact common physical time, records the input
archive checksum/dataset UUIDs/timesteps, registers it, and saves a workspace:

```bash
python examples/mhd_resolution_comparison.py \
  --campaign ~/ORNL_Dropbox/campaign-store/mhd_orszag_tang_resolution_sweep.aca \
  --output /work/current_z_comparison.png \
  --session-file /tmp/pulsar-session.json
```

The script reads the campaign without modifying it and uses only existing
NumPy, Pillow, and ADIOS2 dependencies. Without `--session-file` it just writes
the PNG and its provenance JSON. It requires an output at the requested time
for every selected source and does not silently interpolate in time.

## Working movies

Register a browser-compatible H.264 MP4 alongside a PNG preview:

```python
movie = viewer.register_result(
    "/work/pressure_comparison.png",
    title="Pressure contours: HLL 64 vs Rusanov 64",
    video_path="/work/pressure_comparison.mp4",
    script_path="/work/render_comparison.py",
    parameters={"pressure_level": 0.2},
)
tab = viewer.create_tab("Pressure comparison movie")
viewer.add_result(movie["result_id"], tab_id=tab["tab_id"])
```

Pulsar copies the MP4 into the durable result bundle and records its checksum,
dimensions, duration, frame count, and frame rate. Playback and seeking use the
existing grid controls. HTTP byte ranges support browser seeking; the script
is never served through this route. Workspace restoration uses the copied
movie and preview, so the original files can be moved afterward.

MP4 validation requires `ffprobe`, supplied by the existing FFmpeg installation.
Movies are limited to 512 MiB and must use H.264 with 4:2:0 color. Registration
adds no dependencies. Supply `frame_times` to use a physical-time timeline;
without a mapping, the viewer uses frame/playback timing. Movie captions and
registered provenance can retain additional scientific context.

Publish a movie through the same Python operation used for PNG plots:

```python
published = viewer.publish_result(
    movie["result_id"],
    associations=[
        {"name": "pressure", "source_dataset": "hll_64/output.bp"},
        {"name": "pressure", "source_dataset": "rusanov_64/output.bp"},
    ],
)
print(published["publication_status"], published["refresh_status"])
```

Omit `associations` for a standalone movie. Movie publication requires the
companion writer's `Manager.publish_video`. It embeds the MP4, PNG preview,
and catalogue record in one transaction. Associated movies appear under their
source variables, without an extra **Published movies** entry. Standalone
movies appear in **Published movies**. A VIDEO
visualization item references the movie, with the separate IMAGE as its
thumbnail. Playback retains the stored frame rate, duration, and frame count;
no scientific time mapping is inferred from elapsed movie time.

To preserve physical time, pass `frame_times`, `time_unit`, and optionally
`time_source` to `register_result()`. There must be one finite, non-decreasing
physical time per **encoded** movie frame. Repeated frames and final holds
repeat the same physical time; these values must not be replaced by a uniform
range over playback duration. For example:

```python
movie = viewer.register_result(
    "preview.png", title="Timed analysis", video_path="analysis.mp4",
    frame_times=[0.0, 0.0, 0.25, 1.0], time_unit="s",  # four encoded frames
)
viewer.publish_result(movie["result_id"])
```

Registration validates this mapping against the probed encoded frame count.
Publication preserves `time_mode="physical_time"`, `time_values`, `time_unit`,
and `time_source` in the campaign record and visualization metadata. Working,
published, restored, and source-variable tiles all use that mapping for the
physical-time timeline. A movie without a mapping retains frame/playback timing.

All matching workspace tiles become **Published**. Both old workspace files
and catalogue views resolve to campaign URLs, including after the working
bundle is unavailable. A retry returns the same publication and retries any
failed refresh. The browser Publish button remains available for PNG plots;
use Python for movie publication in this milestone.

## Publish a plot into the campaign

The browser's **Publish** button opens a title and optional source-variable
association dialog. Python invokes the same operation:

```python
published = viewer.publish_result(
    result["result_id"],
    title="Current density across resolutions at t=1",
    associations=[
        {"name": "current_z", "source_dataset": "hll_32/output.bp", "role": "primary"},
        {"name": "current_z", "source_dataset": "hll_64/output.bp", "role": "primary"},
        {"name": "current_z", "source_dataset": "hll_128/output.bp", "role": "primary"},
    ],
)
print(published["publication_status"], published["refresh_status"])
```

Omit `associations` for a standalone plot. Names are campaign variable IDs
and source datasets, rather than filesystem paths. Pulsar validates them
against the source variables in its current index.

Publishing requires the optional hpc-campaign writer. The Python client and
read-only viewer do not need it. Install the `publish` extra for writer
dependencies. Until `Manager.publish_image` and `Manager.publish_video` are
released, use the companion checkout containing those helpers:

```bash
python -m pip install -e ../hpc_campaign/hpc-campaign
python -m pip install -e ".[publish,schema]"
```

Restart Pulsar after updating its code. Publication writes a frozen PNG as an
embedded IMAGE dataset, or an MP4 VIDEO plus an IMAGE preview, and a small JSON
catalogue record as an embedded TEXT dataset. Normal visualization associations
are added when requested. These writes share one SQLite transaction. Published
plots appear in **Published plots** and under any associated source variables.
Movies with associations appear under their source variables; standalone movies
appear in **Published movies**. A comparison linked to several runs stores a
single image or movie.

After commit, Pulsar rebuilds its sidecar index and refreshes the catalogue
and grid. Tabs, geometry, settings, queries, and other working results remain.
All matching working tiles become **Published** and use `/pulsar-image/…`
or `/pulsar-media/…` URLs backed by the campaign. Saved workspaces retain the working result UUID;
even a workspace saved before publication resolves that UUID from the archive
on restore. Published plots and movies no longer require their local result bundles.

`publication_status == "published"` reports a durable archive commit.
`refresh_status == "failed"` means the commit succeeded but the viewer refresh
failed; `refresh_error` explains why. Repeat `publish_result` with the same
result ID to retry the refresh. A lost HTTP response can be recovered the same
way. The existing publication is returned without writing duplicate data or
changing its original title or associations. Register a new result to publish
a revision. Workspace Undo changes the workspace, and does not undo archive
publication.

`viewer.results()` and `viewer.result(id)` include publication receipts.
Working manifests stay immutable. Scripts, parameters, and scientific
provenance remain in working storage and are **not yet published** into the
campaign.

Errors are exposed as `PulsarClientError` with a `code` and optional HTTP
`status`, for example:

```python
from pulsar.client import PulsarClientError

try:
    viewer.add_visualization("temperature", tab_id=tab["tab_id"])
except PulsarClientError as error:
    print(error.code, error.status, str(error))
```

There are no automatic retries of mutations: after a timeout, inspect the
workspace before repeating an operation that may already have completed.
The client uses the Python standard library; the server reuses Trame's
existing aiohttp server. Publishing additionally uses the optional
hpc-campaign writer described above.

## Set physical time

```python
receipt = viewer.set_time(0.5, tab_id=tab["tab_id"])
print(receipt["requested_time"], receipt["physical_time"])
for plot in receipt["plots"]:
    print(plot["source_dataset"], plot["physical_time"], plot["status"])
```

The call activates the target tab, pauses playback, and seeks its existing
physical-time slider. It uses the slider's current driver and selects the nearest
driver sample; ties choose the earlier sample, and requests outside the driver's
range clamp to an endpoint. The argument uses the displayed timeline's physical
time units. It is not a frame ordinal or source step. Non-time selection axes
(such as shot number) and tabs without a physical timeline return
`time_unavailable` (409).

The receipt includes `requested_time`, the applied slider `physical_time`,
`slider_index`, and a `plots` list with cell/source identities, time units, and
the actual physical time used. Existing synchronization rules apply: image
sequences hold the latest sample at or before the slider time, and mapped movies
select their nearest physical-time frame. `sample_index` is the frame ordinal;
`frame_index` is the stored frame index when available. A plot with a continuous
time cursor returns status `cursor`, rather than claiming a sampled field value.
Media without a physical mapping or with an incompatible selection axis report
`no_physical_time` or `incompatible_axis` and a null physical time. A cursor that
has not rendered reports `not_ready`; rendered cursor times respect the plot's
current displayed bounds.

A connected viewer with the current frontend is required. The call waits up to
10 seconds for a browser receipt. No confirmation returns `seek_timeout` (504),
with the outcome unknown; reconnect/reload the viewer before retrying. Requests
are not automatically retried. Concurrent seeks return `seek_busy` (409), and
switching tabs or changing a source during a seek can return `workspace_changed`
(409). Completed and timed-out commands are cleared so they cannot replay on a
later browser connection. Time seeking does not add a workspace undo step, and
the playback position remains outside saved workspace documents.

## HTTP contract

All endpoints are under `/pulsar-api/v1`, accept loopback clients only, and
require `Authorization: Bearer <token>` and `X-Pulsar-Instance: <instance_id>`.
Successful responses are `{"api_version": 1, "result": ...}`. Errors use
`{"api_version": 1, "error": {"code": ..., "message": ...}}`.

| Method | Endpoint | Arguments |
| --- | --- | --- |
| GET | `/context` | None |
| GET | `/catalog` | None |
| GET | `/tabs` | None |
| POST | `/tabs` | `title`, optional `pane_id` |
| POST | `/time` | `physical_time`, `tab_id`; waits for a browser seek receipt |
| POST | `/visualizations` | `variable_id`, `tab_id`, optional `source_ref` |
| GET | `/results` | None |
| GET | `/results/{result_id}` | None |
| POST | `/results` | `title`, `image_path`, optional `video_path`, `frame_times`, `time_unit`, `time_source`, `script_path`, `parameters`, `provenance` |
| POST | `/result-views` | `result_id`, `tab_id` |
| POST | `/publications` | `result_id`, optional `title`, `associations` |
| GET | `/workspace` | None |
| POST | `/workspace` | Workspace document |

POST bodies are JSON objects limited to 16 KiB, except result registration
(160 KiB) and workspace restoration (5 MiB). Copied PNGs are limited to 64 MiB,
MP4s to 512 MiB, scripts to 4 MiB, and parameters, provenance, and movie timing
together to 128 KiB.
Unrecognized arguments and
invalid targets are rejected. Authentication/instance tokens stay in the
connection file and request headers, outside Trame's browser-visible state.
