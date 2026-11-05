# Metadata SQL queries

Pulsar's opt-in Python control session supports SQL over stored campaign
metadata. Queries return flexible tables, independently of the current catalog
filter. They do not read ADIOS arrays, images, or movies, calculate new field
statistics, or modify the ACA archive. Codex or another local Python caller can
inspect the schema, formulate SQL, inspect the result, and display it in Pulsar.
This milestone does not add a SQL tool loop to the in-app natural-language
assistant; its existing filter translator remains available.

Start the viewer with the existing local control option:

```bash
python app.py /path/to/campaign.aca --control-session /tmp/pulsar-session.json
```

In another process:

```python
from pulsar.client import connect

viewer = connect(session_file="/tmp/pulsar-session.json")
schema = viewer.query_schema()
for view in schema["views"]:
    print(view["name"], view["description"], view["columns"])

result = viewer.query(
    """
    SELECT s.source_dataset, v.variable_id, v.minimum, v.maximum
    FROM q_sources AS s
    JOIN q_variables AS v USING (source_ref)
    WHERE v.variable_id = :variable
    ORDER BY v.maximum DESC, s.source_dataset
    """,
    parameters={"variable": "pressure"},
    request="Compare stored pressure ranges across sources",
)
print(result["columns"], result["rows"])
tab = viewer.create_tab("Pressure metadata")
viewer.show_query(result["query_id"], tab_id=tab["tab_id"])
viewer.save_workspace("pressure-metadata.workspace.json")
```

The table supports numeric/text sorting, pagination, and **Export CSV**. **Inspect query**
in the tile header shows the original request, exact SQL/parameters, column
types, execution details, limits reached, and recorded campaign identity. Null
cells represent unavailable metadata. Export contains the saved query order,
not the browser's temporary sorting. CSV preserves the saved values.
Use the existing grid layout/size controls to give a wide table more space.
Freeform query tiles initially use a larger footprint.

## Views and semantics

`query_schema()` is the authoritative discoverable contract and includes the
schema version, view descriptions, columns, joins, campaign identity, and limits.
Each worker copies approved metadata columns from a read-only index snapshot
into private temporary tables, detaches the index, and exposes these views to
read-only query SQL. Payload columns are absent from that connection. This does
not change the existing index schema or the campaign writer.

| View | One row represents | Important columns |
| --- | --- | --- |
| `q_sources` | A source dataset, declared collection, file-per-step group, or legacy descriptor | `source_ref`, `source_dataset`, `source_collection_id`, `dataset_uuid` |
| `q_variables` | A variable within a source | `source_ref`, `variable_id`, `minimum`, `maximum`, `metadata_json`, `statistics_scope` |
| `q_representations` | A source/variable/type/visualization sequence | `representation_ref`, `source_ref`, `variable_id`, `variable_type`, `visualization_name`, `record_count` |
| `q_samples` | An indexed image or scalar-field sample association | `sample_ref`, `representation_ref`, `source_ref`, `source_dataset`, `variable_id`, `variable_type`, `physical_time`, `time_index`, `minimum`, `maximum`, `payload_uuid` |

References are opaque semantic keys scoped to the recorded campaign, not cache
row IDs. Source dataset identity takes precedence over differing legacy
producer/file fields. Collections may include multiple datasets; `source_dataset`
and `dataset_uuid` are null when they do not have a single value. Missing UUIDs
remain null. Dataset UUIDs and campaign UUID, when available, are read from ACA
SQLite metadata. No embedded payload is read.

`q_variables.minimum/maximum` summarize indexed raw-variable metadata across
the source (`statistics_scope='whole_source'`). `metadata_json` is null if a
source's members have conflicting metadata. `q_samples` extrema belong to the
stored sample representation (`statistics_scope='stored_sample'`). A float32
scalar-field representation may have different precision from its original
field. Images generally have no numeric extrema.

Multiple representations can describe the same source step. Select a specific
representation or type before counting samples or aggregating their extrema.
Movie encoded frames are not exposed as field samples. Statistic-array values
are not yet expanded into queryable rows; their representations remain
discoverable. Provenance traversal is a later increment.

Use physical time for cross-source comparisons, with an explicit alignment
policy when times differ. A frame index or source step is not physical time.
Missing times or units remain unknown. Nested metadata can be inspected using
SQLite JSON functions, for example `json_extract(metadata_json, '$.shape[0]')`.

## Ranking example

The MHD campaign has stored pressure scalar-field extrema at each saved time.
This query ranks Rusanov sources by their largest recorded sample maximum after
a requested time and returns the time at which each maximum occurred:

```python
result = viewer.query(
    """
    WITH ranked AS (
      SELECT *, ROW_NUMBER() OVER (
        PARTITION BY source_ref
        ORDER BY maximum DESC, physical_time, sample_ref
      ) AS rank_in_source
      FROM q_samples
      WHERE variable_id = :variable
        AND variable_type = 'scalarField'
        AND source_dataset LIKE :source_pattern
        AND physical_time > :after
        AND maximum IS NOT NULL
    )
    SELECT source_ref, source_dataset, variable_id, maximum, physical_time, time_index
    FROM ranked
    WHERE rank_in_source = 1
    ORDER BY maximum DESC, source_dataset
    LIMIT :limit
    """,
    {"variable": "pressure", "source_pattern": "rusanov_%/output.bp",
     "after": 0.5, "limit": 2},
    request="Rank Rusanov sources by stored pressure maximum after t=0.5",
)
viewer.show_query(result["query_id"], tab_id=tab["tab_id"])

# Display current_z for each source returned by the pressure ranking.
for row in result["rows"]:
    viewer.add_visualization(
        "current_z", tab_id=tab["tab_id"], source_ref=row[0],
    )

# Seek the comparison to the first event and inspect actual times per source.
time_column = next(i for i, c in enumerate(result["columns"]) if c["name"] == "physical_time")
receipt = viewer.set_time(result["rows"][0][time_column], tab_id=tab["tab_id"])
print(receipt["plots"])
```

If a query explicitly returns columns named `source_ref`, `representation_ref`,
or `sample_ref`, Pulsar verifies their values against the same metadata snapshot
and includes resolvable references in `result['references']`, keyed by row and
column. This establishes reference existence, not automatic lineage for arbitrary
SQL expressions or aggregates. Pass a returned `source_ref` to
`add_visualization()` to open a variable for that exact source. References are
opaque; copy the value rather than constructing it from a dataset name. The
current catalog query still applies, and an unavailable or ambiguous source
produces an error rather than falling back to another run. Charting result
columns remains a subsequent increment.

## Results, bounds, and restoration

`query()` returns `query_id`, `columns`, `rows`, `references`, `row_count`,
`truncated`, `truncation_reason`, and recorded execution/campaign metadata.
Rows are arrays in column order. Columns have unique positional keys (`c0`,
`c1`, ...) even if SQL returns duplicate names. Types describe observed values;
an all-null/empty column has type `unknown`, and heterogeneous values are `mixed`.
`row_count` counts saved rows, not the size of an unbounded original result.

One query runs at a time per control session, in a worker with its own
connection. SQL execution is read-only and limited to the documented views and
approved built-in functions. Writes, attachment, extension loading, direct cache
table access, blobs, and multiple statements are rejected. The default budget is
5 seconds, 1,000 rows, and 1 MiB of encoded row data. Row/byte limits yield a
clearly marked truncated result; cancellation, invalid SQL, and deadlines fail
without creating a snapshot. Client request cancellation signals the worker.

Snapshots are stored under the campaign's existing durable result directory,
in `.queries/<query_id>/query.json`, independently of PNG/MP4 working results and
the rebuildable cache. Each snapshot contains its checksum, SQL, parameters,
request, rows, references, execution details, campaign fingerprint/UUID, index
generation (a hash of the projected metadata), and query schema version. The fingerprint uses the resolved campaign
path, size, and modification time; it is a change detector, not a content hash.

`show_query()` adds one undoable table tile to an existing tab, without replacing
tiles or changing catalog filters. Workspace JSON retains the query ID and tile
geometry; the snapshot stays in the durable store. Save/Load restores the saved
rows without executing SQL. Missing/corrupted snapshots produce an error tile.
Restoration requires the same resolved campaign path and result directory.

After reconnecting, use `viewer.queries()` to list snapshot summaries and
`viewer.query_result(query_id)` to read one. To rerun, call `query()` again with
its saved SQL/parameters/request; this produces a new query ID. A changed
campaign marks restored results as stale, and fresh queries require an index
refresh. Saved rows are retained as historical results.

## HTTP additions

These authenticated loopback routes use the existing control protocol:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/pulsar-api/v1/query-schema` | Discover the query schema |
| POST | `/pulsar-api/v1/queries` | Execute `{sql, parameters, request}` |
| GET | `/pulsar-api/v1/queries` | List saved result summaries |
| GET | `/pulsar-api/v1/queries/{query_id}` | Read a saved result |
| POST | `/pulsar-api/v1/query-views` | Display `{query_id, tab_id}` |

Provider integration remains caller-owned: the query service itself does not
send campaign metadata or results to an LLM provider.
