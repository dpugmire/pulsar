# Pulsar Interaction Log v1

Pulsar can write a local, append-only JSON Lines log of semantic user
interactions. The log supports usage auditing and future offline training for
visualization ranking and workspace-organization recommendations. It does not
change visualization selection behavior.

Logging is disabled unless `PULSAR_INTERACTION_LOG_DIR` is set. Pulsar creates
the directory, a pseudonymous `.pulsar-profile-id`, and one or more mode-0600
session files. `PULSAR_INTERACTION_LOG_MAX_MB` controls segment rotation and
defaults to 64 MiB. Rotation never deletes old segments.

```bash
export PULSAR_INTERACTION_LOG_DIR=/path/to/private/pulsar-logs
export PULSAR_INTERACTION_LOG_MAX_MB=64
python app.py campaign.aca
```

## Event envelope

Every line is one JSON object with these required fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer event schema version; v1 is `1`. |
| `event_id` | Unique event identifier. |
| `event_sequence` | Monotonic sequence within the session. |
| `timestamp_utc` | ISO-8601 UTC wall-clock time. |
| `elapsed_session_ms` | Monotonic elapsed session time. |
| `user_profile_id` | Pseudonymous ID stored in the log directory. |
| `session_id` | Unique Pulsar process-session identifier. |
| `campaign_version_id` | Hash of campaign path and file-version metadata. |
| `event_type` | Versioned semantic event name. |
| `source` | UI or controller path that caused the event. |
| `model_version` | Selection or capture policy version. |
| `payload` | Event-specific JSON object. |

V1 records session lifecycle, normalized query application and clearing,
visualization assignment/change/removal, workspace tab and pane operations,
grid layout and cell operations, saved/loaded workspace snapshots, and timeline
driver changes. It also records `plugin.executed` for successful and failed
plugin render attempts.

Visualization assignments include the complete supported candidate set, the
chosen default, the active normalized query ID, and the semantic workspace
location. Manual changes reference the original assignment event and record
the elapsed time since assignment.

Plugin execution events include plugin identity, module, version, scope,
execution timing and status, normalized option values, input variable IDs,
pseudonymous source IDs, output type, optional scientific context, and the
exception type for failed attempts. The event never stores generated plot data
or campaign file contents.

## Query data

`query.applied` records the validated action plan, compiled query filters,
source filters, result counts, origin, and target. It does not record the raw
manual query string or natural-language assistant request. Subsequent
visualization and workspace events carry the active `query_id` where relevant.

## Workspace snapshots

Snapshots contain the pane tree and split ratios, ordered pane/tab identifiers,
grid dimensions and sizing, semantic cell contents, cell spans, source
fingerprints, visualization settings, and timeline driver. Tab titles are not
recorded. The active grid is captured from live Trame state; inactive tab grids
come from the workspace layout.

Snapshots and events intentionally exclude:

- campaign absolute paths;
- workspace save/load paths;
- raw query and assistant text;
- tab titles;
- ADIOS arrays and scalar payloads;
- images, movies, previews, and data URLs;
- transient browser rendering state.

Normalized plugin option values and optional scientific annotations are stored
in `plugin.executed` events because they are necessary to reproduce and learn
from the plugin workflow. These fields are plugin-defined and may contain
sensitive text or paths. Review plugin schemas and hooks before sharing logs.

Variable IDs and structured numeric query operands remain present because they
are required to learn variable- and task-specific behavior. Logs should be
stored in a private location and should not be uploaded without a separate
sanitization and consent process.

## Validation and audit

Run the bundled audit over a file or directory:

```bash
python -m pulsar.learning.audit /path/to/private/pulsar-logs
```

The audit validates envelopes, ignores an incomplete final line left by a
process interruption, and reports sessions, queries, visualization assignments
and changes, saved snapshots, common visualization transitions, and variables
that co-occur in saved tabs.

Raw logs are immutable training input. Future label builders and models must
write separate versioned artifacts rather than changing v1 events.
