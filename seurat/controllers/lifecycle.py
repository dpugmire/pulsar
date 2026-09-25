"""Campaign ingestion and server lifecycle controller behavior."""


class LifecycleControllerMixin:
    ACTION_BINDINGS = ()
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = ()

    def ingest_campaign_every_time(self, **_kwargs):
        if not self.db.ok:
            self.state.dbOk = False
            self.state.dbStatus = f"DB error: {self.db.last_error}"
            return

        try:
            self.state.dbOk = True
            schema_paths = [
                path
                for path in (
                    self.campaign_schema_path,
                    self.image_association_schema_path,
                )
                if path
            ]
            schema_note = (
                f" (schema: {', '.join(schema_paths)})" if schema_paths else ""
            )
            self.state.dbStatus = f"Loading {self.campaign_path}{schema_note}..."

            close_db = getattr(self.db, "close", None)
            if callable(close_db):
                close_db()
            self.collection.drop()
            self.parse_campaign(
                self.campaign_path,
                self.collection,
                image_association_schema_path=self.image_association_schema_path
                or None,
                campaign_schema_path=self.campaign_schema_path or None,
            )

            self.refresh_variable_list()
            self.state.dbStatus = f"Loaded {self.campaign_path} • variables={len(self.state.variableNames)}"
            self.record_interaction(
                "workspace.snapshot",
                source="campaign_loaded",
                payload={
                    "reason": "campaign_loaded",
                    "workspace": self.interaction_workspace_snapshot(),
                },
            )
        except Exception as e:
            self.state.dbOk = False
            self.state.dbStatus = f"Load failed: {type(e).__name__}: {e}"
            print(self.state.dbStatus, flush=True)
