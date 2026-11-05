"""Small, standard-library client for a running local Pulsar viewer."""

import json
import math
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

API_VERSION = 1


class PulsarClientError(RuntimeError):
    """A connection, protocol, or viewer operation failed."""

    def __init__(self, message, *, code="connection_error", status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PulsarClient:
    """Control the viewer described by an explicitly selected session file.

    Responses are plain dictionaries/lists containing semantic metadata, not
    image bytes or array data. Closing a script does not close the viewer.
    """

    def __init__(self, *, session_file: str | Path, timeout: float = 30.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        try:
            session = json.loads(Path(session_file).expanduser().read_text())
        except (OSError, ValueError) as error:
            raise PulsarClientError(
                f"Cannot read Pulsar session file: {error}"
            ) from error
        if not isinstance(session, dict) or session.get("api_version") != API_VERSION:
            raise PulsarClientError(
                "Unsupported Pulsar control API version", code="version_mismatch"
            )
        endpoint = session.get("endpoint", "")
        if not endpoint:
            raise PulsarClientError(
                "Pulsar control endpoint is not ready", code="not_ready"
            )
        if not isinstance(endpoint, str):
            raise PulsarClientError("Invalid Pulsar control endpoint")
        try:
            parts = urlsplit(endpoint)
            port = parts.port
        except ValueError as error:
            raise PulsarClientError("Invalid Pulsar control endpoint") from error
        if (
            parts.scheme != "http"
            or parts.hostname != "127.0.0.1"
            or port is None
            or port == 0
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.path != "/pulsar-api/v1"
        ):
            raise PulsarClientError("Expected a local Pulsar control endpoint")
        self._endpoint = endpoint
        self._token = session.get("token")
        self._instance_id = session.get("instance_id")
        if (
            not isinstance(self._token, str)
            or not self._token
            or not isinstance(self._instance_id, str)
            or not self._instance_id
        ):
            raise PulsarClientError(
                "Session file is missing its token or instance identity"
            )
        self._timeout = timeout
        self._opener = build_opener(ProxyHandler({}), _NoRedirects())
        context = self.context()
        if (
            not isinstance(context, dict)
            or context.get("instance_id") != self._instance_id
        ):
            raise PulsarClientError(
                "Session file refers to another Pulsar instance",
                code="instance_mismatch",
            )

    def _request(self, path, payload=None):
        data = (
            None
            if payload is None
            else json.dumps(payload, allow_nan=False).encode("utf-8")
        )
        request = Request(
            self._endpoint + path,
            data=data,
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-Pulsar-Instance": self._instance_id,
                "Content-Type": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                detail = json.load(error).get("error", {})
                message = detail.get("message", str(error))
                code = detail.get("code", "http_error")
            except (ValueError, AttributeError):
                message, code = str(error), "http_error"
            raise PulsarClientError(message, code=code, status=error.code) from error
        except (OSError, URLError) as error:
            raise PulsarClientError(f"Cannot contact Pulsar: {error}") from error
        except ValueError as error:
            raise PulsarClientError(
                "Pulsar returned invalid JSON", code="protocol_error"
            ) from error
        if (
            not isinstance(result, dict)
            or result.get("api_version") != API_VERSION
            or "result" not in result
        ):
            raise PulsarClientError(
                "Invalid Pulsar control response", code="protocol_error"
            )
        return result["result"]

    def context(self) -> dict[str, Any]:
        """Read campaign, active tab, selection, and timeline metadata."""
        return self._request("/context")

    def catalog(self) -> list[dict[str, Any]]:
        """List variables in the current (possibly filtered) catalog."""
        return self._request("/catalog")

    def query_schema(self) -> dict[str, Any]:
        """Discover read-only metadata SQL views, their grain, joins, and limits."""
        return self._request("/query-schema")

    def query(self, sql: str, parameters=None, request: str = "") -> dict[str, Any]:
        """Execute metadata SQL over the whole campaign and save its bounded result.

        parameters is a dictionary for named bindings or a list for positional
        bindings. Querying never changes the current catalog filter/workspace.
        """
        return self._request(
            "/queries", {"sql": sql, "parameters": parameters, "request": request}
        )

    def queries(self) -> list[dict[str, Any]]:
        """List durable metadata-query snapshots for this campaign."""
        return self._request("/queries")

    def query_result(self, query_id: str) -> dict[str, Any]:
        """Read a saved result, including whether its campaign fingerprint changed."""
        from uuid import UUID

        return self._request("/queries/" + str(UUID(query_id)))

    def show_query(self, query_id: str, *, tab_id: str) -> dict[str, Any]:
        """Add a saved query table to a tab without replacing existing tiles."""
        return self._request("/query-views", {"query_id": query_id, "tab_id": tab_id})

    def tabs(self) -> list[dict[str, Any]]:
        """List workspace tabs and their visualization summaries."""
        return self._request("/tabs")

    def create_tab(self, title: str, *, pane_id: str | None = None) -> dict[str, Any]:
        """Create and activate a tab, in the active pane by default."""
        return self._request("/tabs", {"title": title, "pane_id": pane_id})

    def set_time(self, physical_time: float, *, tab_id: str) -> dict[str, Any]:
        """Pause and seek a tab's physical-time slider, awaiting a browser receipt.

        The slider selects the nearest driver sample (clamped to its range).
        The receipt reports the time actually selected for each displayed plot.
        A connected browser is required. A timeout can leave the outcome unknown.
        """
        return self._request(
            "/time", {"physical_time": physical_time, "tab_id": tab_id}
        )

    def add_visualization(
        self, variable_id: str, *, tab_id: str, source_ref: str | None = None
    ) -> dict[str, Any]:
        """Add a variable using the viewer's current filters/defaults.

        source_ref selects an exact source from a metadata-query result instead
        of the viewer's source selection. The current catalog query still applies.
        The target tab is activated. Existing tiles are never replaced. This
        returns after the server updates state, before browser render completion.
        """
        payload = {"variable_id": variable_id, "tab_id": tab_id}
        if source_ref is not None:
            payload["source_ref"] = source_ref
        return self._request("/visualizations", payload)

    def register_result(
        self,
        image_path: str | Path,
        *,
        title: str,
        video_path: str | Path | None = None,
        frame_times: list[float] | None = None,
        time_unit: str | None = None,
        time_source: dict | None = None,
        script_path: str | Path | None = None,
        parameters: dict | None = None,
        provenance: dict | None = None,
    ) -> dict[str, Any]:
        """Copy a PNG preview, optional MP4/script, and context into durable storage.

        Paths refer to the server's local filesystem. Registration does not
        modify the campaign or add a tile; use add_result to display it.
        """
        return self._request(
            "/results",
            {
                "title": title,
                "image_path": str(Path(image_path).expanduser().resolve()),
                **(
                    {"video_path": str(Path(video_path).expanduser().resolve())}
                    if video_path is not None
                    else {}
                ),
                "script_path": str(Path(script_path).expanduser().resolve())
                if script_path is not None
                else None,
                "parameters": parameters,
                "provenance": provenance,
                **(
                    {
                        "frame_times": frame_times,
                        "time_unit": time_unit,
                        "time_source": time_source,
                    }
                    if any(
                        value is not None
                        for value in (frame_times, time_unit, time_source)
                    )
                    else {}
                ),
            },
        )

    def results(self) -> list[dict[str, Any]]:
        """List working results and campaign publications."""
        return self._request("/results")

    def result(self, result_id: str) -> dict[str, Any]:
        """Read a working manifest and any committed campaign publication."""
        # IDs are UUIDs, never URL paths or query strings.
        from uuid import UUID

        return self._request("/results/" + str(UUID(result_id)))

    def add_result(self, result_id: str, *, tab_id: str) -> dict[str, Any]:
        """Display a working or published result in a workspace tab."""
        return self._request(
            "/result-views", {"result_id": result_id, "tab_id": tab_id}
        )

    def publish_result(
        self,
        result_id: str,
        *,
        title: str | None = None,
        associations: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Embed a PNG or MP4 working result in the campaign and refresh its catalogue.

        An association is {"name": "current_z", "source_dataset": "run/output.bp",
        "role": "primary"}. Omit associations for a standalone plot or movie. A repeated
        result ID returns the original publication and retries the refresh.
        Inspect refresh_status separately from publication_status.
        """
        return self._request(
            "/publications",
            {"result_id": result_id, "title": title, "associations": associations},
        )

    def save_workspace(self, path: str | Path) -> str:
        """Save semantic workspace JSON on the client's local filesystem."""
        path = Path(path).expanduser().resolve()
        path.write_text(
            json.dumps(self._request("/workspace"), indent=2, allow_nan=False),
            encoding="utf-8",
        )
        return str(path)

    def load_workspace(self, path: str | Path) -> dict[str, Any]:
        """Restore workspace JSON using the browser Load action's validation."""
        document = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return self._request("/workspace", document)


def connect(*, session_file: str | Path, timeout: float = 30.0) -> PulsarClient:
    """Attach to an existing viewer; no server or browser is launched."""
    return PulsarClient(session_file=session_file, timeout=timeout)
