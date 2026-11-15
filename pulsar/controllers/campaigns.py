"""Campaign overview navigation and inspection of recorded result packages."""

import json
import re
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from pulsar.campaign_media import _read_embedded_file
from pulsar.campaign_overview import archive_file_history, build_campaign_overview, campaign_overview_card


class CampaignOverviewControllerMixin:
    ACTION_BINDINGS = (
        ("explore_campaign_dataset", "explore_campaign_dataset"),
        ("inspect_campaign_result", "inspect_campaign_result"),
        ("inspect_campaign_file", "inspect_campaign_file"),
        ("select_campaign_overview_entry", "select_campaign_overview_entry"),
    )
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = ()

    def refresh_campaign_overview(self):
        campaigns = build_campaign_overview(self.collection, self.campaign_paths)
        self._campaign_result_records.clear()
        for campaign in campaigns:
            campaign["error"] = self._campaign_load_errors.get(campaign["path"], campaign["error"])
            campaign["error"] = re.sub(r"\x1b\[[0-9;]*m", "", campaign["error"])
            versions = re.search(r"reads only ACA version ([\d.]+), this file has version ([\d.]+)", campaign["error"])
            if versions:
                campaign["error"] = (
                    f"Data exploration requires an ADIOS reader for ACA {versions[2].rstrip('.')}. "
                    f"The installed reader supports ACA {versions[1]}. Embedded images and file metadata remain available."
                )
            for result in campaign["results"]:
                self._campaign_result_records[result["id"]] = result
        self._campaign_overview_records = campaigns
        self.state.campaignOverview = [campaign_overview_card(campaign) for campaign in campaigns]

    def select_campaign_overview_entry(self, selection, **_):
        if not isinstance(selection, dict):
            return
        campaign = next((item for item in self._campaign_overview_records
                         if item["path"] == selection.get("campaign_path")), None)
        if campaign is None:
            return
        card = campaign_overview_card(campaign)
        kind = selection.get("kind")
        results = campaign["results"]
        detail = {
            "campaign_path": campaign["path"], "campaign_name": campaign["name"],
            "kind": kind, "error": campaign["error"], "title": campaign["name"],
            "directory_path": "", "dataset_name": "", "file_count": sum(len(group["datasets"]) for group in card["directories"]),
            "modified_at": card["modified_at"], "added_at": "",
        }
        if kind == "file":
            dataset = next((item for item in campaign["datasets"]
                            if item["name"] == selection.get("dataset_name") and str(item["fileformat"]).upper() == "ADIOS"), None)
            if dataset is None:
                return
            detail.update({key: deepcopy(dataset.get(key)) for key in
                           ("modified_at", "added_at", "coverage", "parameters", "explorable")})
            detail.update(title=dataset["name"], dataset_name=dataset["name"], file_count=1)
            results = [result for result in results if any(
                item.get("source") == dataset["name"] for item in result.get("inputs", [])
            ) or any(item.get("name") == dataset["name"] for item in result.get("artifacts", []))]
        elif kind == "directory":
            directory = next((group for group in card["directories"]
                              if group["path"] == selection.get("directory_path")), None)
            if directory is None:
                return
            detail.update(
                title=directory["name"], directory_path=directory["path"],
                coverage=directory["coverage"], parameters=directory["parameters"],
                file_count=len(directory["datasets"]),
                modified_at=directory["modified_at"], added_at=directory["added_at"],
            )
            result_ids = {result["id"] for result in directory["results"]}
            results = [result for result in results if result["id"] in result_ids]
        elif kind != "campaign":
            return
        detail["results"] = [
            {key: result[key] for key in ("id", "title", "preview", "caption", "kind")}
            for result in results if result.get("preview")
        ][:3]
        self.state.campaignSelection = detail

    def explore_campaign_dataset(self, campaign_path, dataset="", **_):
        campaign = next(
            (item for item in self._campaign_overview_records if item["path"] == campaign_path), None
        )
        if campaign is None:
            return
        if dataset and not any(item["name"] == dataset and item["explorable"] for item in campaign["datasets"]):
            return
        self.state.campaignDatasetPath = str(dataset or "")
        self.state.selectedCampaignPath = campaign_path
        self.state.selectedVar = ""
        self.state.variablePaneView = "files"
        self.state.campaignDisplay = "workspace"
        self.state.showCampaignPackage = False
        self.refresh_variable_list()

    def inspect_campaign_result(self, result_id, **_):
        result = self._campaign_result_records.get(str(result_id))
        if result is None:
            return
        package = deepcopy(result)
        package.pop("_preview", None)
        self.state.campaignPackage = package
        self.state.campaignFile = {}
        self.state.showCampaignPackage = True

    def inspect_campaign_file(self, campaign_path, name, **_):
        campaign = next(
            (item for item in self._campaign_overview_records if item["path"] == campaign_path), None
        )
        if campaign is None:
            return
        files = [*campaign["datasets"], *campaign["supporting_files"]]
        dataset = next((item for item in files if item["name"] == name), None)
        if dataset:
            if not self.state.showCampaignPackage:
                self.state.campaignPackage = {}
            dataset = dict(dataset)
            dataset["load_error"] = campaign["error"]
            dataset["history"] = archive_file_history(campaign_path, name)
            if str(dataset.get("fileformat", "")).upper() in {"TEXT", "JSON", "YAML"}:
                dataset["text"] = self._campaign_text_preview(campaign_path, dataset.get("uuid", ""))
            self.state.campaignFile = {**dataset, "campaign_path": campaign_path}
            self.state.showCampaignPackage = True

    @staticmethod
    def _campaign_text_preview(path, dataset_uuid):
        # Bound the embedded content before reading or decompressing a text file.
        try:
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as con:
                row = con.execute(
                    "select max(f.lenorig) from dataset d join replica r on r.datasetid=d.rowid "
                    "join repfiles rf on rf.replicaid=r.rowid join file f on f.fileid=rf.fileid "
                    "where d.uuid=? and r.deltime=0 and d.deltime=0", (dataset_uuid,)
                ).fetchone()
            if row is None or row[0] is None or not 0 < int(row[0]) <= 131072:
                return "Text preview is unavailable or exceeds 128 KiB."
            payload = _read_embedded_file(path, dataset_uuid, "TEXT")
            if payload is None:
                return "Text content is not embedded in this archive."
            text = payload.decode("utf-8", errors="replace")
            try:
                return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                return text
        except (OSError, sqlite3.Error, ValueError):
            return "Text preview is unavailable."
