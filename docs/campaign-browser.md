# Browsing campaign contents

Start Pulsar with a directory of campaign archives:

```bash
python app.py --campaign-directory /path/to/campaigns
```

Pulsar discovers regular `.aca` files directly in that directory at startup.
It opens the **Campaigns** overview in **List** view, with an expandable row per archive.
All archive inventories are visible together. Directory discovery is not
recursive and does not watch for changes after startup.

Use **Open** next to a campaign name to select that campaign in the workspace
viewer. It opens the whole campaign and clears any previous dataset selection.

Each campaign shows expandable directory groups such as `hll_128` and `hll_64`.
Collapsed groups show the BP file count and available time coverage. A shared
range is shown only when all BP files have the same recorded coverage;
otherwise the summary indicates varying or partial coverage. Variables and
preview frames are never added together to estimate a BP file's step count.
Expand a directory to see its BP filenames. Select a campaign, directory, or BP
row to show its recorded metadata and up to three visualization previews in
the preview pane. Selecting a BP file uses its recorded source/artifact links;
it does not show unlinked visualizations from neighboring files. Directory
groups start collapsed. BP datasets are selected by the archive's recorded
`ADIOS` format, so logical names without a `.bp` suffix also appear. Other data
formats, supporting files, variables, IDs, and metadata counts are
kept out of this overview. Copies with the same campaign ID remain separate
archive entries.

## List, sorting, and gallery

The list initially shows **Name**, **Recorded modified**, and **Information**.
Use **Columns** to hide optional columns or show **Added to campaign**. Name
always remains visible. Click the Name or date column headers to sort, then
click again to reverse the direction. The toolbar also provides sort and order
controls, including for columns currently hidden. Dates initially sort newest
first; names initially sort ascending with natural numeric ordering, so
`hll_8`, `hll_64`, and `hll_128` appear in that order.

Sorting operates separately among campaigns, among each campaign's directories,
and among each directory's files. It preserves expansion and selection. Missing
dates remain last in both directions; equal dates use ascending natural name
order as a tie-breaker. A directory/campaign modification date is the latest
recorded BP file modification in that group. A directory addition date is the
earliest BP file insertion, shown only when every BP file in the directory has
an insertion date. Campaign rows do not show an addition date derived from
their files. These are summaries of recorded file metadata, not filesystem
directory timestamps or campaign creation dates.

**Gallery** retains the expandable directory groups with inline BP filenames
and sample images. Both views use the same sort settings and preview pane.
View, sort direction, sort field, and visible columns are saved in browser local
storage for this Pulsar origin; they do not modify campaign archives or workspace
JSON. If storage is unavailable, the controls still work for the current page.
The preview pane moves below the inventory on narrow windows.

Directories are taken from each BP dataset's parent path in the campaign.
Files stored at the campaign root appear under **Campaign root**. Dataset
actions retain the full path, even though the expanded group shows just the
filename.

Each BP row exposes a **Recorded modified** timestamp and its available step/time
coverage. Gallery filenames show the same date as **Modified**. This is the
most recent recorded modification time among its
active replicas, falling back to the dataset's recorded modification time.
This is a packaging-time snapshot, not a live filesystem check. For BP
directories, the recorded time may describe the directory rather than changes
inside every data file. Missing modification dates are shown as unknown.

An **Added** timestamp appears when insertion history is available. Dates use
the browser's local time zone. Added comes from the earliest dataset insertion
event for the
current dataset identity in ACA 0.8 history. Source-file modification times and
upgrade baseline timestamps are not used as addition dates. Older archives and
datasets without a recorded insertion have no Added caption; their details show
**Added to campaign: unknown**. File creation dates and simulation status are
not inferred from other timestamps.

Select a BP file, then use **Details** in its preview pane (or below its gallery
filename) to inspect indexed variable names, types,
shapes, individual coverage, and recorded metadata/provenance. Recorded replica
locations and sizes remain separate; sizes are not summed across copies.
Dataset history lists up to 20 events for the current dataset identity. These
are dataset-row events, not a log of all filesystem writes or replica changes.

Explicit `run_parameters` dictionaries in indexed variable metadata or recorded
visualization sequence/item metadata appear in the associated file's details.
Parameters common to every BP file in a directory are also available in the
selected directory's preview pane. Values are not guessed from filenames or
directory names. Other freeform metadata and configuration files remain
available through the inspectors; this does not introduce a campaign-wide
owner, project, or job-status convention.

## Results and related files

The result gallery groups recorded visualization sequences into cards. Multiple
frames and variable associations belonging to one sequence share one card.
Standalone image/video datasets are eligible for the preview sample. Scalar
field records without rendered previews are omitted. Thumbnails are requested
lazily; collecting the overview does not read image or field payloads.

Image-sequence previews use the saved image nearest the midpoint of the
recorded time span. When physical times are unavailable, they use the middle
image in frame order. Duplicate variable associations do not count as extra
frames. Movie previews similarly use a middle frame, extracted with FFmpeg
on demand; their recorded poster is a fallback when extraction is unavailable.
Preview captions identify the associated variables and the selected image's
recorded physical time, including units when supplied. Images without physical
times identify their position in the image sequence. Movie captions describe
the recorded movie time range so they remain valid when a poster is used.
Visualization timing is never substituted for BP source coverage.

Previews are grouped using their recorded BP source associations, with linked
BP artifacts or their recorded storage directory as fallbacks. A comparison
with inputs in two directories can appear in both. The three-preview limit
applies separately to each directory. Unmatched results are available under
**Other visualizations**.

Select a result to inspect its preview or movie, recorded source associations,
linked files, and recorded metadata/provenance. Configuration and plotted-data
links require exact dataset names or UUIDs in the recorded metadata. Files are
not grouped into packages by matching their filenames. The inspector does not
claim unrecorded processing history or reproducibility.

Linked supporting files are available in the result inspector.
Embedded UTF-8 text up to 128 KiB can be previewed, and JSON
is formatted for inspection. Referenced BP datasets can be explored when their
variables were successfully indexed.

## Exploring data

Selecting a BP row previews it without leaving the campaign overview. Use
**Browse variables** in the preview pane, or double-click an indexed BP file,
to open the existing workspace scoped to the chosen campaign and dataset.
**All data** clears the dataset scope. **Campaigns** returns to the
overview; **Workspace** returns to the existing visualization workspace.
The workspace retains its variable and file grouping options and campaign
filter. Single-file startup still opens the workspace initially.

Workspace sources retain their campaign path as well as their dataset name.
Dragging a variable into either grid layout, adding it from its context menu,
and running variable/source plugins use that recorded archive. Saved workspaces
retain the same source identity on restore. Browsing another campaign does not
redirect existing plots to same-named files in the new campaign. Comparison
plots can include independently scoped sources from multiple campaigns.

If data ingestion fails, an information icon identifies the affected campaign;
the explanation is available in its tooltip and in the dataset inspector.
The overview still displays readable BP inventory and visualization previews. Embedded
images remain inspectable without a compatible ADIOS campaign reader. Raw data
exploration requires an ADIOS reader compatible with the archive version and
access to the source replicas.

The catalog remains a rebuildable local cache. Multi-campaign startup rebuilds
it from all discovered archives. Publishing working results is disabled when
multiple archives are loaded; open the target archive directly to publish.
This browser does not merge archives or submit updates to a campaign service.
