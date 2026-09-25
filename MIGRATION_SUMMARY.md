# Pulsar Migration Summary

This repo was created by splitting the viewer code out of the original
`campaign_viewer` repository.

## Current Repositories

New local repo:

```text
/Users/dpn/proj/pulsar
```

GitHub repo:

```text
https://github.com/dpugmire/pulsar
```

Original repo:

```text
/Users/dpn/proj/campaign_viewer/campaign_viewer
```

## Current Git State

The Trame rearchitecture work is on:

```text
branch: rearchitect-trame-phase5a
remote: origin -> https://github.com/dpugmire/pulsar.git
```

Phase 1 was merged into `main` by GitHub PR #4 at merge commit
`82fd7bc660bd07cca1ba0965b80742b6ed24f0a4`. Phase 2 was merged by GitHub PR #5
at merge commit `6dee8a153727cf08f979636e4db88cc6785ecbb7`; it decomposed the remaining
controller closure into domain-owned Trame adapters and extracted pure
controller logic into testable model modules.

Phase 3 was merged by GitHub PR #6 at merge commit
`e37c19c3a62e8797be3ea81c00629c757bd66ee8`. Phase 3A added an opt-in
Playwright/Chromium characterization suite around a
deterministic Trame application. It covers client mounting, variable group
state, grid selection and assignment, layout controls, context menus, rendered
plot output, and step-index versus physical-time timeline behavior.

Phase 3B began the client-side lifecycle migration. A registered
`pulsar-grid-runtime` Vue component now owns grid timeline/VCR listeners and
the grid-media observer for the mounted workspace, including cleanup on
unmount.

Phase 3C.1 adds an app-scoped `pulsar-interaction-runtime` Vue component for
variable/grid drag-and-drop and context menus. The runtime owns listener
registration and cleanup across the catalog and grid. It was merged by GitHub
PR #7 at merge commit `fee56b6cd95dec9b6021ee54c03f49f191fe76e3`.

Phase 3C.2 adds an app-scoped `pulsar-resize-runtime` Vue component for
variable-panel and grid-track resizing. It preserves the existing grid sizing
controller contracts while replacing document-global resize listeners with
mounted ownership, pointer capture, idempotent registration, and complete
cleanup on unmount. It was merged by GitHub PR #8 at merge commit
`e8cb321769d3da37a0b5fee8f9d460818689ad33`.

Phases 3C.3 through 3C.5 are combined on
`rearchitect-trame-phase3c3-5`. Floating-panel movement is owned by the
app-scoped interaction runtime. Media pan/zoom, plot hover/pan/zoom, reset-view
observation, plot resize/mutation observation, and render scheduling are owned
by the mounted grid runtime. These lifecycles use pointer capture, cancel
timers, disconnect observers, clear transient state on unmount, and remain
idempotent across repeated mount calls. Obsolete document-global interaction
handlers, initialization flags, and generic window-level plot/VCR hooks were
removed while preserving the existing rendering, timeline, and controller
semantics. They were merged by GitHub PR #9 at merge commit
`9997d5aac35c4a347f250e0ba5eba7d673eb5226`.

Phase 4A begins the behavior-preserving client-runtime decomposition on
`rearchitect-trame-phase4a`. Media pan/zoom, pointer interaction state, and
reset-view observation are extracted from the remaining monolithic client
script into `pulsar-media-runtime.js`. The mounted grid runtime coordinates the
media lifecycle through a narrow `mount`, `unmount`, and
`resetViewForCellIndex` interface while continuing to own combined media/plot
reset semantics. It was merged by GitHub PR #10 at merge commit
`77cf4310bd09f3841daf84d7ccc690072f592309`.

Phase 4B continues the behavior-preserving decomposition on
`rearchitect-trame-phase4b`. Plot-data parsing, settings normalization, SVG
rendering, cursor drawing, hover/pan/zoom interaction, resize/mutation
observation, render scheduling, and transient plot state are extracted into
`pulsar-plot-runtime.js`. Cross-media timeline policy remains in the grid
client, which supplies the resolved time or normalized video progress through
the plot runtime API and coordinates combined media/plot resets. It was merged
by GitHub PR #11 at merge commit
`91ac3c57de23e1440704cd8492ba8d7596dfee7b`.

Phase 4C completes the planned client-runtime decomposition on
`rearchitect-trame-phase4c`. Timeline selection, image/video synchronization,
VCR actions, labels/sliders, timers, media mutation observation, and plot cursor
coordination are extracted into `pulsar-timeline-runtime.js`. The remaining
`pulsar.js` becomes a small grid coordinator. Runtime objects are registered
under `window.pulsar.runtimes`, while the existing top-level grid, interaction,
and resize aliases are retained for Trame Vue plugin compatibility. It was
merged by GitHub PR #12 at merge commit
`301b63e9aa6ba073c13e904ce292ef7d3e08d668`.

Phase 5A begins the backend-boundary work on `rearchitect-trame-phase5a`. A
narrow catalog capability contract separates normalized navigation and backend
availability from the local `CampaignDb` implementation. The existing ACA and
SQLite behavior is retained by `LocalCampaignBackend`, while
`PulsarApplication` and the catalog controller consume the injected contract.
Contract/fake-backend tests characterize the seam. `PHOBOS_INTEGRATION.md`
records the ownership boundary, current Phobos coverage, timeline requirements,
API and asynchronous-job gaps, and the planned Phase 5B through 5E migration.

Phase 5B.1 continues the backend-boundary work on
`rearchitect-trame-phase5b1-sources`. A separate source capability introduces
normalized source descriptors, aggregate statistics, stored-visualization
source lookup, and source-restriction resolution. The local adapter assigns
deterministic opaque source IDs, while controllers consume the capability
through `PulsarApplication`. Query-language formalization, media transport,
generated plots, and plugin execution remain separate follow-on work.

The last commit before the rearchitecture is preserved by the annotated tag:

```text
pre-rearchitect-trame-phase1 -> fe0926f7a7ccb5fe012816f9fc962edf0a8588f3
```

The original repo still has the subtree split branch used to create this repo:

```text
pulsar-split
```

## What Was Done

- Created a subtree split from the original viewer subdirectory.
- Cloned that split history into `/Users/dpn/proj/pulsar`.
- Renamed the new repo branch to `main`.
- Removed the temporary local remote pointing back to the old repo.
- Added a new GitHub remote for `dpugmire/pulsar`.
- Created and pushed the public GitHub repository.
- Added repo metadata:
  - `.gitignore`
  - `pyproject.toml`
  - updated `README.md`

## Included Source

The new repo contains the tracked viewer source from the original viewer,
including:

- `app.py`
- `config.py`
- `controllers.py`
- `db.py`
- `ingest_campaign.py`
- `media_utils.py`
- `query_parser.py`
- `state_init.py`
- `ui.py`
- `README.md`

Untracked prototypes, generated `.aca` files, data directories, simulation
outputs, build directories, caches, and editor metadata from the original repo
were not moved into `pulsar`.

Unsupported tracked prototype applications inherited by the initial split were
removed before the Trame architecture work began.

## Verification

The standard verification commands are:

```bash
python -m py_compile app.py config.py controllers.py db.py ingest_campaign.py media_utils.py query_parser.py state_init.py ui.py
python -m pytest -q
PULSAR_RUN_BROWSER_TESTS=1 python -m pytest -q tests/browser
python -m pip check
```

Install the repo dependencies with:

```bash
cd /Users/dpn/proj/pulsar
python -m pip install -e ".[schema,test]"
python -m playwright install chromium
```

Then run:

```bash
python app.py --help
```

## Notes

- The original `campaign_viewer` repo was not cleaned up.
- Existing untracked simulation/data/prototype files in the original repo were
  left untouched.
- Internal legacy branding from the original viewer was removed during the
  first Trame rearchitecture phase.
