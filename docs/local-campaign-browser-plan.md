# Multiple-campaign browser plan

## Goal

Let a scientist point Pulsar at a directory of `.aca` archives and browse the
contents of all those campaigns in one running viewer. Add a campaign-centric
navigation level while retaining the current variable and file views for
detailed exploration.

This milestone is a local multi-campaign reader. It does not define a shared
campaign store, update queue, archive merge protocol, or campaign editing
workflow.

## User flow

1. Start Pulsar with a campaign directory.
2. Pulsar discovers and ingests each eligible `.aca` archive into a shared
   read-only browsing catalog, retaining each archive's path and campaign
   identity on every record.
3. Browse the directory's campaigns in one campaign-centric navigation view.
4. Select a campaign to filter the existing source/file/variable and
   visualization views to that campaign; clear the selection to browse across
   all loaded campaigns.

Preserve the current `pulsar /path/to/campaign.aca` single-campaign entrypoint.
Add directory mode explicitly (for example `--campaign-directory PATH`) so
existing invocation behavior stays unambiguous.

## Proposed implementation plan

Build the multi-campaign read path in stages, keeping the current one-archive
mode unchanged. The key architectural change is that the sidecar and backend
must query records from many archives while retaining the originating archive
for every file read, visualization, and source selection.

### Milestone A: directory discovery and multi-archive ingestion

1. **Discovery:** add a small module that scans the selected directory
   non-recursively for regular `.aca` files, sorts resolved paths
   deterministically, and reports per-file stat/readability errors without
   suppressing other campaigns.
2. **CLI:** add an explicit `--campaign-directory PATH` mode alongside the
   existing positional single-campaign path and `--demo`; reject ambiguous
   combinations. Preserve single-file behavior.
3. **Stable scoping:** add a campaign identity/path field to catalog records
   and ensure every query, selection, and navigation descriptor retains it.
   The current `campaign_path` field is the natural discriminator in the
   sidecar. Do not merge same-named variables or sources across archives.
4. **Ingestion:** ingest every discovered archive into the same sidecar
   collection. Current ingestion accepts one path and many controllers assume
   one campaign path, so introduce a narrow multi-ingest coordinator while
   preserving per-archive ingestion semantics. Avoid clearing other campaigns'
   records when one archive is re-ingested.
5. **Readers:** maintain readers keyed by campaign path (the DB already has a
   path-keyed reader cache in some operations) and route media/field reads to
   the path attached to the selected record. Verify close behavior covers all
   readers.

### Milestone B: campaign overview and result packages

1. Open a main-area overview with expandable sections for all loaded archives,
   each showing its data inventory, supporting files, and result gallery.
2. Inspect result sequences as packages: preview/movie, recorded source
   associations, exact metadata links to configuration/data, and provenance.
   Missing associations remain explicit gaps.
3. Load previews on demand. Use archive metadata for inventories and preserve
   separate archive entries when copies share the same campaign UUID.
4. Link indexed datasets into the existing workspace. Keep campaign selection
   as a workspace filter, and retain variable/file grouping within it.

The implemented behavior and current limits are described in
[Campaign browser](campaign-browser.md).

### Milestone C: validation and usability

1. Test directory discovery, CLI mode validation, multi-archive ingestion, and
   campaign-scoped query results.
2. Use two fixtures with overlapping variable/source names to verify no
   accidental deduplication and correct archive routing for detail reads.
3. Verify re-ingesting one changed archive refreshes only its documents while
   retaining other campaigns in the directory catalog.
4. Manually inspect all-campaign browsing, campaign filtering, and navigation
   from overview rows into existing detail views.

## Deferred work

- A NERSC-hosted public or private campaign store.
- User authentication, authorization, uploads, and publication review.
- Competing-update queues or database-backed campaign management.
- Merging downloaded or forked campaigns, stale-base detection, and conflict
  resolution.
- Editing campaign metadata from the browser.

These require a campaign update protocol and archive merge semantics; browsing
multiple local archives does not provide them.
