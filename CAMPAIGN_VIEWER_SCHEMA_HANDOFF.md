# Campaign Viewer Semantic Metadata: Design Handoff

Status: 2026-08-07

## Purpose of this document

This document summarizes the current discussion and implementation state around
semantic metadata for HPC campaign viewers, especially Pulsar. It is intended
to be copied into a new chat as the starting context for a design discussion.

The goal is to decide what additional information belongs in a campaign so that
a viewer can do more than enumerate ADIOS files and variables. The design should
reuse ADIOS, `hpc_campaign`, and Fides instead of reproducing their models. Some
overlap is acceptable when it gives consumers a simpler and more reliable
interface, but new schema content should primarily fill genuine gaps.

No final replacement schema has been agreed upon yet. In particular, examples
in this document are design sketches, not specifications.

## The problem being solved

A campaign viewer can already inspect an ACA campaign and discover its ADIOS
datasets, variable names, shapes, types, steps, attributes, images, and some
statistics. That is enough to show an inventory. It is not enough to understand
all of the scientific and visualization relationships represented by that
inventory.

Given a variable, the viewer should eventually be able to answer questions such
as:

- What is this variable, beyond its physical ADIOS name?
- Is it stored directly, or is it derived from other variables?
- If it is derived, what are its direct inputs?
- Which stored or generated visualizations directly include it?
- Which visualizations include quantities derived from it?
- Can it be interpreted as a field on a mesh, and which Fides model describes
  that interpretation?
- Is it a scalar trace, spatial field, distribution, moment, diagnostic, mesh
  resource, or some other code-defined kind of output?
- Which analysis or Pulsar plugins can operate on it or on its containing run?
- Which time coordinate and run/source does it belong to?

A particularly important query is transitive visualization discovery. A search
for `pressure` should find:

1. images and plots that directly use pressure; and
2. images and plots of a quantity derived from pressure, when the dependency
   chain is recorded.

The existing `hpc_campaign` visualization API largely supports the first case.
A general variable derivation graph is still missing.

## Working separation of responsibilities

| Concern | Primary owner | Notes |
|---|---|---|
| Array bytes, primitive dtype, storage shape, ADIOS steps and attributes | ADIOS | These facts should be discovered, not repeated in a new schema. |
| Campaign inventory, dataset identity, locations, replicas, archival state, embedded objects and time-series membership | `hpc_campaign` / ACA | This is campaign organization and data lifecycle. |
| Coordinates, topology, fields, point/cell association, data-source mapping and visualization-ready data model | Fides | Do not recreate Fides mesh or field semantics in a code schema. |
| Direct relationship between a rendered artifact and its source variables | `hpc_campaign` visualization API | Stored in ACA `visualization_*` tables. |
| Alternate representation and its source variable(s) | `hpc_campaign` representation API | Present on the current scalar-data-representations branch; not a complete general derivation DAG. |
| Code/run classification, code-specific logical organization, derivation dependencies, and bindings to optional Fides documents | Proposed campaign/code semantic schema plus ACA associations | This is the main design gap. |
| Browsing, search, rendering, plugin execution, UI state and caches | Pulsar | Pulsar should consume semantics, not become their only authoritative store. |

This boundary is deliberately not absolute. For example, a schema may repeat a
small data-source or time association when that makes a campaign self-contained
and dramatically easier to consume. It should not copy coordinate arrays,
connectivity rules, field centering, or other detailed Fides content.

## What ADIOS provides

ADIOS provides the physical data interface. Through an ADIOS dataset or ACA
view, a consumer can discover information such as:

- variable and attribute names;
- primitive data types;
- array shapes and selections;
- available steps and blocks;
- min/max metadata when available;
- values such as a stored `time` variable;
- code-written semantic attributes such as description, units, axes,
  centering, normalization, species context, or mesh context when producers
  emit them.

ADIOS does not inherently establish a campaign-wide scientific identity for a
variable, a general derivation graph, a code-specific product taxonomy, or the
relationship between an arbitrary image and the variables used to make it.

Several different dimensions must not be conflated:

- **ADIOS shape** is the physical array extent.
- **Tuple/value structure** distinguishes a scalar value from a vector or
  tensor value.
- **Mesh dimension and field association** describe how values live on a
  geometric data model.
- **Plot dimension** describes a particular visualization, such as a 1-D line
  plot or a 2-D heat map.

These are related but are not the same property. The first schema iteration
does not need to introduce `value_shape` or `components`; ADIOS and Fides
already cover most immediate needs, and a scalar should not need artificial
component names.

## What `hpc_campaign` provides

An ACA file is a compact campaign archive and index. `hpc_campaign` currently
provides or is developing the following capabilities:

- registration of ADIOS and HDF5 datasets;
- stable dataset UUIDs and campaign hierarchy names;
- multiple replicas across hosts, directories, archives, TAR files, HTTPS and
  S3-backed locations;
- lifecycle and history information for replicas;
- embedded or referenced images and text files;
- embedded metadata for self-describing datasets;
- named time-series that order several campaign datasets;
- a visualization API linking rendered image sequences to source dataset and
  variable pairs;
- scalar-field and Gaussian-splat payload support;
- a generic alternate-representation model linking representation items back
  to one or more ground-truth dataset/variable pairs.

### Direct visualization associations

The visualization API uses ACA SQLite tables conceptually equivalent to:

- `visualization_sequence`: name, visualization kind, thumbnail and metadata;
- `visualization_variable`: source dataset, variable name and visualization
  role;
- `visualization_item`: ordered image or supported payload items.

A visualization can name multiple variables and distinguish uses such as
`color-by`, `contour-by`, `streamline-by`, `x-axis`, and `y-axis`. This is the
right place for the direct relationship between an existing visualization
artifact and the source variables used to produce it.

### Alternate representations

The local branch `scalar-data-representations` adds a generic representation
model. A representation records ground-truth dataset/variable sources, ordered
derived items, source-step correspondence, representation parameters, metrics,
and metadata. This is useful for scalar grids, Gaussian splats, and future
encodings such as wavelets or ZFP.

This model supplies provenance for an alternate representation, but its own
documentation still lists a general derivation DAG, cycle detection, immutable
provenance, and lifecycle policy as future work. It should not yet be treated
as the complete answer to primary-versus-derived variables.

### Current branch state

The local checkout at `/Users/dpn/proj/hpc_campaign/hpc-campaign` is currently
on branch `scalar-data-representations` at commit `7062032`. The code-schema
implementation is on the separate `code_schema` branch at commit `1e3ac55`.
The `m3dc1-schema-support` branch adds the richer M3D-C1 schema example.

Consequently, code-schema and generic-representation work are not yet one
integrated implementation branch.

## What Fides provides

Fides describes how variables from one or more data sources form a
visualization-ready Viskores/VTK data model. A Fides JSON document can describe:

- one or more `data_sources`, including separate mesh and field files;
- a coordinate system and the ADIOS variables used to construct it;
- cell-set/topology information and connectivity variables;
- fields and their point, cell, or whole-dataset association;
- mappings from physical ADIOS variable names to exposed field names;
- static arrays and vector interpretation;
- step information and an optional variable containing physical time;
- predefined or specialized models, including XGC-specific coordinate,
  topology, and field handling.

For example, the existing XGC Fides model maps `rz` and
`nd_connect_list`/`nextnode` from the mesh source into XGC coordinates and
topology, and maps `dpot` from the 3-D source as a point field.

Fides therefore owns the detailed answer to “what mesh is this field on?” and
“how can these ADIOS arrays be constructed as a data set?” The new schema
should normally point to a Fides document/model/field instead of repeating
coordinate, topology, centering, or connectivity definitions.

Fides does not provide:

- ACA campaign storage and replica management;
- a campaign-wide run/code assignment model;
- code-specific product categories such as XGC moments or diagnostics;
- general primary/derived dependency relationships;
- associations between arbitrary rendered images and their inputs;
- Pulsar plugin discovery or viewer presentation policy.

Fides is optional. A campaign can still contain non-spatial diagnostics,
tables, scalar traces, images, or code outputs that have no Fides model.

## What the current campaign code schema provides

The schema prototype is a YAML document with `schema_version: 1`. Its generic
core describes logical file groups:

- `role: static` or `role: time_series`;
- `mode: append` or `mode: file_per_timestep` for time series;
- exact `path` or wildcard `pattern` selection;
- filename-based timestep extraction;
- associations between file groups, such as a field group referring to a
  static mesh group;
- a time variable or index.

The current XGC example is:

`/Users/dpn/proj/xgc/data/schema.yaml`

It identifies `xgc.mesh.bp` and `xgc.f0.mesh.bp` as static groups, groups XGC
file-per-timestep sequences such as `xgc.3d.*.bp`, and identifies
`xgc.oneddiag.bp` as an append-mode time series.

### How the prototype is stored

On the `hpc_campaign` `code_schema` branch, `Manager.set_schema()` stores the
YAML as an embedded `TEXT` dataset with the fixed canonical name:

```text
__campaign_schema.yaml
```

The source filename is not significant. Setting it again updates the singleton
schema. The CLI form is:

```bash
python -m hpc_campaign manager \
  --campaign_store /path/to/campaign-store \
  campaign.aca \
  schema /path/to/code_schema.yaml
```

The Python API is `Manager.set_schema(path)`, and
`Manager.validate_schema()` validates the generic file layout against the
campaign inventory without opening the original ADIOS data.

Pulsar reads `__campaign_schema.yaml` and accepts the earlier `schema.yaml`
name as a fallback. It can also accept an external override with:

```bash
python app.py campaign.aca --campaign-schema /path/to/schema.yaml
```

### Richer Pulsar interpretation

Pulsar currently interprets optional schema sections beyond the generic
`files` and `time` core:

- `axes`;
- `meshes`;
- `basis`;
- `variable_groups`;
- `visualization_templates`.

These were demonstrated with M3D-C1 so that fields, equilibrium fields,
scalars, and pellet traces can have different axes and data models inside one
BP dataset. Pulsar validates referenced ADIOS variables and attaches the
resolved grouping, role, data model, resource names, axes, static state, and
visualization template references to ingested variable records.

This is useful implementation experience, but parts of it overlap Fides. In
particular, `meshes`, basis/data-model interpretation, and some field semantics
should be reconsidered now that Fides has been identified as the proper owner
of visualization data-model semantics.

### Current schema limitations

- It is a singleton campaign-wide text object.
- It cannot store and independently identify multiple code schemas.
- It cannot assign different schemas to different runs or subtrees in one
  campaign.
- It has no explicit association with one or more Fides documents.
- It has no general variable derivation graph.
- Its name “campaign schema” is ambiguous because the document actually
  describes code-output conventions and logical interpretation, not the ACA
  file format itself.
- `role` is overloaded: in the generic file section it only means static or
  time-series behavior, while elsewhere role can mean field, x-axis, color-by,
  and so forth.
- The current richer model risks growing into a parallel visualization schema
  instead of referencing Fides.

## What Pulsar currently provides

The current Pulsar repository is `/Users/dpn/proj/pulsar`, on branch
`variable-catalog-search` at commit `8f748c4` when this handoff was written.

Pulsar currently provides:

- ingestion of ACA/ADIOS metadata into a local SQLite sidecar;
- variable browsing, grouping, search and source selection;
- min/max and source summaries;
- query filtering;
- image and image-sequence browsing with synchronized timelines;
- scalar-field rendering and summaries for supported campaign payloads;
- direct use of `hpc_campaign` visualization associations;
- legacy path-based image association as a fallback;
- an optional external image-association YAML for old campaigns;
- reading the canonical embedded campaign schema and its legacy name;
- schema-driven time coordinates and richer M3D-C1 variable metadata;
- built-in and personal Python plugins;
- XGC source plugins backed by XGC-Analysis, including Eich profiles,
  divertor lambda-q time series, divertor load maps, and divertor target-total
  time series.

Pulsar normalizes direct visualization associations so each artifact can retain
the physical variable name, logical display name, source dataset, visualization
roles, sequence name, visualization kind, item order, and item metadata.

Pulsar does **not** currently have a Fides hook. It cannot generally consume a
campaign-contained Fides document to construct and render arbitrary fields.
It also does not have a general derivation graph, transitive dependency search,
or robust multiple-code-schema assignment.

Pulsar-side caches, display labels, saved workspaces, panel state, chosen color
maps, and other viewer preferences should remain Pulsar concerns. Scientific
identity and dependency facts that should be shared by other consumers should
live in the campaign or referenced semantic documents.

## The XGC catalog as useful prior art

XGC-Analysis has a code-specific catalog that groups physical files into
logical products and hides whether time is represented by internal ADIOS steps,
a sequence of files, a static file, or a mixed layout.

Its `ProductType` values include:

- `mesh_geometry`, `equilibrium`, and `magnetic_field`;
- `field_2d` and `field_3d`;
- `distribution_function`;
- `fmoment_2d` and `fmoment_3d`;
- `heat_diag`, `one_d_diag`, `neutral_diag`, `fsource_diag`, and
  `sheath_diag`;
- diffusion products and analysis products.

Its current `product_family` strings are the coarser values `mesh`, `field`,
`distribution`, `moment`, `diagnostic`, `workflow`, and `analysis`.

This terminology is useful evidence, but `product_family` is an XGC catalog
implementation name and should not automatically become the universal schema
term. For a CFD code, pressure, velocity, and Q-criterion may all be fields,
while Q-criterion is derived from velocity. XGC “moment” and “field” are also
not opposites:

- **field** describes how values are distributed over a spatial domain or
  mesh;
- **moment** describes how a quantity was obtained, usually by integrating a
  distribution function over velocity space.

A moment can therefore be a field. Likewise, “diagnostic” often describes why
or when a product was written, not its geometric value structure. A single
mandatory enum that mixes all these axes is likely to be brittle.

A practical first version can permit code-defined groups or tags without first
standardizing a universal scientific ontology. Generic concepts such as stored
versus derived and a Fides field reference can remain portable across XGC,
M3D-C1, CFD, and other codes.

## Multi-code campaigns

A campaign may contain outputs from several codes. For example, one campaign
could contain both XGC and M3D-C1 runs.

The agreed direction is:

- XGC and M3D-C1 should have separate code-schema documents.
- They do not need to be combined into one large YAML document.
- Each code can have a separate optional Fides document.
- A run or campaign subtree must be able to point to the applicable code schema
  and to zero or more applicable Fides documents.
- Fides is not required.
- There should not be an extra user-authored `resources.yaml` merely to list
  these documents.

The code schema and Fides document should be independent campaign objects with
their own identities. The association between a run scope and those objects
should be represented by campaign metadata.

Physically, these documents can continue to be stored as embedded text. The
important improvement is to make their **semantic types and relationships**
first-class so a consumer does not have to guess their purpose from filenames.

For example, the conceptual relationship is:

```text
campaign
  XGC run scope
    -> XGC code schema
    -> XGC Fides document (optional)
  M3D-C1 run scope
    -> M3D-C1 code schema
    -> M3D-C1 Fides document (optional)
```

The exact ACA table/API design and names remain to be decided.

## Important gaps

### 1. Multiple semantic resources and scope bindings

ACA can store multiple text objects, but the schema API currently exposes one
fixed singleton. A viewer needs discoverable, typed code-schema and Fides
resources plus an explicit run/dataset-scope binding.

### 2. Primary and derived variable relationships

Given a variable, the viewer should know whether it is primary or derived and,
for a derived variable, its direct inputs. This should be included in the first
useful schema increment.

A minimal relationship is sufficient initially:

```yaml
variables:
  qcriterion:
    derived_from:
      - velocity
```

Real references must include enough dataset/run scope to be unambiguous. A
`method` name or an implementation `path` is not required for the first step.
They may be added later as optional provenance if a concrete query needs them.

Derivation should be modeled as directed edges. Transitive ancestry can then be
computed by the viewer or backend rather than redundantly stored.

### 3. Fides binding without Fides duplication

The viewer needs to locate the appropriate Fides document and know which Fides
data source/model applies to a campaign dataset or run scope. It may also need
a direct reference from a schema variable to the corresponding exposed Fides
field.

The code schema should not duplicate coordinates, connectivity, topology,
point/cell association, or detailed field construction.

### 4. Portable grouping with code-specific vocabulary

The viewer needs useful organization such as XGC mesh, field, moment,
distribution, diagnostic, workflow, and analysis groups. Other codes need
different vocabularies. A small generic grouping mechanism is needed, but a
large cross-code ontology is not a prerequisite for the first step.

### 5. Stable variable identity

An ADIOS variable name alone is not globally unique. The minimum identity is a
campaign dataset plus a variable path, interpreted within a run/code scope.
Display names and cross-run aliases are separate concerns and should not replace
the physical identity.

### 6. General transitive discovery

The backend needs to combine:

- direct visualization-to-variable edges from `hpc_campaign`;
- source-variable-to-alternate-representation edges;
- variable derivation edges from the semantic schema.

This permits queries such as “show every artifact related to pressure,” with
the result able to distinguish direct matches from transitive derived matches.

### 7. Validation and versioning

The design needs:

- a versioned schema format;
- validation of references against ACA dataset identities and ADIOS variable
  inventory;
- validation of Fides resource references;
- detection of missing dependency targets and derivation cycles;
- forward-compatible handling of code-specific sections or tags.

## Proposed small first step

The first step should demonstrate generality across at least XGC and one other
code without attempting to encode every scientific concept.

Recommended scope:

1. Add first-class, multiple embedded semantic resources to ACA:
   `code_schema` and `fides`, with Fides optional.
2. Add explicit bindings from a run/dataset scope to one code schema and zero or
   more Fides resources.
3. In each code schema, support stable variable references and a minimal
   `derived_from` list.
4. Allow code-defined variable groups/tags for catalog organization, without
   requiring a universal `product_family` enum.
5. Allow a variable or group to refer to a Fides model/field, while leaving all
   mesh construction semantics in Fides.
6. Teach Pulsar ingestion to construct the dependency graph and expose both
   direct and transitive artifact queries.
7. Validate the design with examples from:
   - XGC: `dpot`, `eden`, distribution moments, and diagnostics;
   - M3D-C1: fields and scalar traces with different time axes; or
   - CFD: pressure, velocity, and Q-criterion derived from velocity.

This is intentionally narrower than the current M3D-C1 schema experiment. It
does not require components, a universal value-shape taxonomy, visualization
templates, analysis methods, or full provenance records.

## Acceptable overlap

Overlap is reasonable when it acts as a binding or makes a common query
possible without executing a specialized library. Examples include:

- repeating a data-source identifier so a campaign dataset can be bound to a
  Fides `data_source`;
- retaining a lightweight static/time-series or time-source declaration for
  catalog browsing even though Fides also has step information;
- recording a direct Fides field name in the code schema;
- caching normalized semantic facts in Pulsar's sidecar while retaining the
  campaign resources as the authority.

Overlap is probably not justified for:

- coordinate values or coordinate construction;
- connectivity/topology definitions;
- point/cell field association;
- primitive dtype and physical array extents;
- image-to-source-variable relationships already represented by the
  `hpc_campaign` visualization tables.

## Naming issues still open

- **Campaign schema** may be too broad. The document is closer to a code-output
  schema, code semantic schema, or code catalog schema.
- **`product_family`** is established XGC-Analysis terminology but may be too
  tied to the XGC catalog. `category`, `group`, or code-defined tags may be more
  neutral.
- **`data_type`** is misleading because programmers read it as float, double,
  or integer.
- **`role`** is too overloaded. Static versus time-series is better described
  as temporal behavior/layout, while visualization use and scientific grouping
  need different fields.
- **`value_shape`** sounds like physical array dimensions. ADIOS already owns
  those dimensions, and mesh dimension belongs in Fides.
- **`components`** is naturally vector/tensor terminology and should not be a
  required scalar concept.
- **field versus moment** must not be forced into a mutually exclusive choice.

Names should be chosen after the minimum queries and ownership boundaries are
agreed upon.

## Decisions already made or strongly agreed

- Do not recreate Fides' visualization semantics in the new schema.
- Fides documents can be embedded as campaign text files for the initial
  design.
- A campaign may contain multiple Fides documents, normally one or more per
  code.
- A campaign may contain multiple separate code-schema documents.
- Runs must explicitly select the applicable code schema and may select an
  optional Fides document.
- Do not require an additional `resources.yaml` just to enumerate schema and
  Fides documents.
- Treat schema and Fides documents as first-class semantic campaign resources,
  even if their payload storage remains `TEXT`.
- Include primary/derived status and direct input variables in the first useful
  increment.
- Use Fides references for mesh association instead of defining another mesh
  model.
- Keep the first increment small and demonstrate cross-code generality.

## Questions for the next design session

1. What is the smallest ACA API/table model for multiple typed semantic
   resources and their scope bindings?
2. What exactly constitutes a run scope in ACA: a hierarchy prefix, an explicit
   run object, a set of datasets, or another existing identity?
3. Should a code-schema variable reference use dataset UUID, campaign name,
   logical file-group name, or a combination?
4. How should wildcard variable groups coexist with explicit derived-variable
   records?
5. What is the minimum Fides binding: document only, document plus data-source
   map, or document/model/field reference?
6. Should code-defined categories be free-form tags, named groups, or a small
   portable vocabulary plus code-specific extensions?
7. How should `hpc_campaign`'s generic alternate representations participate in
   the same dependency graph as derived ADIOS variables?
8. Which component performs graph traversal and validation: `hpc_campaign`, a
   reusable campaign-query library, Pulsar ingestion, or a combination?
9. How should the older singleton `__campaign_schema.yaml` be migrated or
   supported as a compatibility resource?
10. Which two or three concrete campaign examples will serve as acceptance
    tests?

## Suggested next-chat prompt

Use this document as context. First verify the current relevant branches and
implementations in `hpc_campaign`, Fides, and Pulsar. Then propose a focused
design plan for the smallest campaign metadata extension that supports:

- multiple code schemas and optional Fides documents;
- per-run or per-scope bindings;
- stable variable identity;
- primary/derived dependencies;
- Fides-backed mesh/field interpretation; and
- direct plus transitive variable-to-visualization queries.

Keep ADIOS storage metadata, Fides visualization semantics, campaign lifecycle
metadata, and Pulsar presentation concerns separated where practical. Identify
every proposed overlap and explain what concrete simplification it provides.
Do not implement the design until the plan has been reviewed and approved.
