# Pulsar

This repository contains the active Trame/Vue3 campaign viewer for ADIOS
campaign archives. Use `app.py` as the main entrypoint. Unsupported prototype
applications inherited from the original viewer repository have been removed;
do not restore them as alternate application paths.

## From-Scratch Setup

Start from this repository:

```bash
cd /Users/dpn/proj/pulsar
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Equivalent editable install:

```bash
python -m pip install -e ".[schema]"
```

The `schema` extra installs `PyYAML`, which is only needed for YAML image
association schemas.

## External Tools

The app needs `ffmpeg` in addition to the Python packages.

- Pulsar uses a local SQLite sidecar DB for viewer state/cache data.
- `ffmpeg` must be available on `PATH` for movie preview tiles.
- ADIOS2 must be importable as Python package `adios2`.
- Image sequence bytes are loaded lazily from the ACA file when preview tiles
  are built. The SQLite sidecar should store frame metadata and ADIOS variable
  paths, not copied image blobs.

Useful checks:

```bash
command -v ffmpeg
python -c "import adios2, numpy, sqlite3, trame; from PIL import Image"
```

On macOS with Homebrew, one possible local setup is:

```bash
brew install ffmpeg
```

## Runtime Configuration

The defaults are defined in `config.py`:

```bash
export PULSAR_CACHE_DIR="~/.cache/pulsar"
export PULSAR_SQLITE_DB=""
export MOVIE_FPS="2"
export MAX_MOVIE_FRAMES="240"
```

`PULSAR_CACHE_DIR` controls the default sidecar DB directory. `PULSAR_SQLITE_DB`
can point at a specific sidecar DB file or a directory where the generated
sidecar DB should be stored.

Current cache note: `app.py` still drops and re-ingests the Pulsar sidecar each
time the server starts. Do not point `PULSAR_SQLITE_DB` at data that should be
preserved outside the viewer cache. The next cache phase should skip ingest
when the ACA file is unchanged.

## Run The App

Run against a campaign archive:

```bash
source .venv/bin/activate
python app.py /path/to/campaign.aca
```

If installed editably, the console script is also available:

```bash
pulsar /path/to/campaign.aca
```

If using an image association schema:

```bash
python app.py /path/to/campaign.aca --image-association-schema /path/to/image_variable_map.yaml
```

Trame prints the local browser URL when the server starts, commonly on port
`8080`.

## Data Model Notes

Campaigns created with the hpc-campaign visualization API are associated through
the ACA `visualization_*` metadata tables. Pulsar treats `variable_id` as a
source-independent variable identity, while source-specific datasets remain
distinguished by `source_dataset`.

Legacy image path parsing is still used as a fallback for older campaigns.

## Quick Verification

Before handing changes back, use targeted checks when possible:

```bash
python -m py_compile app.py ingest_campaign.py db.py controllers.py ui.py
python -m pytest -q
python -m pip check
```

If ADIOS2 or `ffmpeg` are unavailable in the environment, state that explicitly
and report which verification was skipped.
