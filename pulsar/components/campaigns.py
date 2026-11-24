"""Campaign contents and result packages in the main display area."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify

from pulsar.widgets import CampaignBrowser


def _date(field):
    return "{{ " + field + " ? new Date(" + field + ").toLocaleString(undefined, " + (
        "{year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', timeZoneName:'short'}) : 'unknown' }}"
    )


class CampaignOverview(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(classes="pulsar-campaign-overview"):
            html.H2("Campaigns", classes="pulsar-campaign-heading")
            html.Div("Loading campaign contents…", v_if="!campaignOverview.length", classes="pa-6")
            with CampaignBrowser(
                campaigns=("campaignOverview",), selection=("campaignSelection",),
                select=(ctrl.select_campaign_overview_entry, "[$event]"),
                open=(ctrl.explore_campaign_dataset, "[$event.campaign_path, $event.dataset_name || '']"),
                inspect=(ctrl.inspect_campaign_result, "[$event]"),
                details=(ctrl.inspect_campaign_file, "[$event.campaign_path, $event.dataset_name]"),
            ):
                self.build_preview()
        self.build_inspector()

    def build_preview(self):
        ctrl = self.ctrl
        html.P("Select a campaign, directory, or BP file to preview its contents.", v_if="!campaignSelection.kind", classes="pulsar-campaign-empty-selection")
        with html.Div(v_if="campaignSelection.kind"):
            html.Div("{{ campaignSelection.kind === 'file' ? 'BP file' : campaignSelection.kind === 'directory' ? 'Directory' : 'Campaign' }}", classes="pulsar-campaign-muted")
            html.H3("{{ campaignSelection.title }}", classes="pulsar-campaign-selection-title")
            html.Div("{{ campaignSelection.campaign_name }}", v_if="campaignSelection.kind !== 'campaign'", classes="pulsar-campaign-muted")
            html.P("{{ campaignSelection.file_count }} BP {{ campaignSelection.file_count === 1 ? 'file' : 'files' }}", v_if="campaignSelection.kind !== 'file'", classes="pulsar-campaign-muted")
            html.Div("{{ campaignSelection.coverage }}", v_if="campaignSelection.coverage", classes="pulsar-campaign-muted")
            html.Div("{{ campaignSelection.kind === 'file' ? 'Recorded modified: ' : 'Latest file modification: ' }}" + _date("campaignSelection.modified_at"), classes="pulsar-campaign-muted")
            html.Div("Added to campaign: " + _date("campaignSelection.added_at"), v_if="campaignSelection.kind === 'file' && campaignSelection.added_at", classes="pulsar-campaign-muted")
            html.P("Data exploration is unavailable", v_if="campaignSelection.error", title=("campaignSelection.error",), classes="pulsar-campaign-muted")
            with html.Div(classes="pulsar-campaign-selection-actions", v_if="campaignSelection.kind === 'file'"):
                vuetify.VBtn("Browse variables", v_if="campaignSelection.explorable", size="small", variant="outlined", click=(ctrl.explore_campaign_dataset, "[campaignSelection.campaign_path, campaignSelection.dataset_name]"))
                vuetify.VBtn("Details", size="small", variant="text", click=(ctrl.inspect_campaign_file, "[campaignSelection.campaign_path, campaignSelection.dataset_name]"))
            with html.Details(v_if="campaignSelection.parameters && campaignSelection.parameters.length", classes="pulsar-campaign-files"):
                html.Summary("Recorded run parameters")
                with html.Div(v_for="parameter in campaignSelection.parameters", key="parameter.name + parameter.value"):
                    html.Div("{{ parameter.name }} = {{ parameter.value }}", classes="pulsar-campaign-input")
            html.H4("{{ campaignSelection.kind === 'campaign' ? 'Campaign visualizations' : 'Visualizations' }}", classes="pulsar-campaign-selection-gallery-title")
            html.P("No recorded visualization previews for this selection", v_if="!campaignSelection.results.length", classes="pulsar-campaign-muted")
            with html.Div(classes="pulsar-campaign-selection-gallery"):
                with vuetify.Template(v_for="result in campaignSelection.results", key="result.id"):
                    with html.Button(classes="pulsar-campaign-result", type="button", click=(ctrl.inspect_campaign_result, "[result.id]")):
                        with html.Div(classes="pulsar-campaign-preview"):
                            html.Span("{{ result.kind }}", classes="pulsar-campaign-placeholder")
                            html.Img(v_if="result.preview", src=("result.preview",), alt=("result.title",), loading="lazy", raw_attrs=['onerror="this.style.display=\'none\'"'])
                        html.Strong("{{ result.title }}")
                        html.Span("{{ result.caption }}", classes="pulsar-campaign-muted")

    def build_inspector(self):
        ctrl = self.ctrl
        with vuetify.VDialog(v_model=("showCampaignPackage",), max_width=1100, scrollable=True):
            with vuetify.VCard():
                with vuetify.VCardTitle(classes="d-flex align-center"):
                    html.Span("{{ campaignPackage.title || campaignFile.name || 'Recorded result' }}", style="white-space:normal;")
                    vuetify.VSpacer()
                    vuetify.VBtn("Close", variant="text", click="showCampaignPackage = false")
                with vuetify.VCardText():
                    with html.Div(v_if="campaignPackage.id"):
                        html.Div("{{ campaignPackage.campaign_name }} · {{ campaignPackage.kind }}", classes="pulsar-campaign-muted")
                        html.Div("{{ campaignPackage.caption }}", classes="pulsar-campaign-muted")
                        html.Video(v_if="campaignPackage.video && showCampaignPackage", src=("campaignPackage.video",), controls=True, preload="metadata", classes="pulsar-campaign-inspector-media")
                        html.Img(v_if="campaignPackage.preview && !campaignPackage.video", src=("campaignPackage.preview",), alt=("campaignPackage.title",), classes="pulsar-campaign-inspector-media", raw_attrs=['onerror="this.style.display=\'none\'"'])
                        html.H3("Associated data")
                        html.P("No source associations recorded", v_if="!campaignPackage.inputs.length", classes="pulsar-campaign-muted")
                        with html.Div(v_for="group in campaignPackage.source_groups", key="group.source"):
                            html.Div("{{ group.source }}", classes="pulsar-campaign-input")
                            html.Div("{{ group.roles.join(', ') }}", v_if="group.roles.length", classes="pulsar-campaign-muted")
                            with html.Div(v_for="variable in group.variables", key="variable", classes="pulsar-campaign-source-variable"):
                                html.Span("↳ {{ variable }}")
                            vuetify.VBtn("Browse source", v_if="campaignPackage.explorable_sources.includes(group.source)", variant="text", size="small", click=(ctrl.explore_campaign_dataset, "[campaignPackage.campaign_path, group.source]"))
                            vuetify.VBtn("File details", v_if="!campaignPackage.explorable_sources.includes(group.source)", variant="text", size="small", click=(ctrl.inspect_campaign_file, "[campaignPackage.campaign_path, group.source]"))
                        html.H3("Linked files")
                        html.P("No configuration or data file links recorded", v_if="!campaignPackage.artifacts.length", classes="pulsar-campaign-muted")
                        with vuetify.Template(v_for="file in campaignPackage.artifacts", key="file.name"):
                            html.Button("{{ file.name }} · {{ file.fileformat }}", click=(ctrl.inspect_campaign_file, "[campaignPackage.campaign_path, file.name]"), classes="pulsar-campaign-link", type="button")
                        with html.Details(classes="pulsar-campaign-files"):
                            html.Summary("Recorded metadata and provenance")
                            html.Pre("{{ campaignPackage.metadata_text }}", classes="pulsar-campaign-metadata")
                    with html.Div(v_if="campaignFile.name", classes="pulsar-campaign-file-inspector"):
                        html.H3("{{ campaignFile.name }}")
                        html.Div("{{ campaignFile.fileformat }} · {{ campaignFile.uuid || 'No dataset ID recorded' }}", classes="pulsar-campaign-muted")
                        html.Div("Recorded source modified: " + _date("campaignFile.modified_at"), classes="pulsar-campaign-muted")
                        html.Div("Added to campaign: " + _date("campaignFile.added_at"), classes="pulsar-campaign-muted")
                        html.Div("{{ campaignFile.coverage }}", v_if="campaignFile.coverage", classes="pulsar-campaign-muted")
                        html.P("{{ campaignFile.load_error }}", v_if="campaignFile.load_error", classes="pulsar-campaign-error")
                        with html.Div(v_if="campaignFile.parameters && campaignFile.parameters.length"):
                            html.H3("Recorded run parameters")
                            with vuetify.Template(v_for="parameter in campaignFile.parameters", key="parameter.name + parameter.value"):
                                html.Div("{{ parameter.name }} = {{ parameter.value }}", classes="pulsar-campaign-input")
                        with html.Div(v_if="campaignFile.variable_details && campaignFile.variable_details.length"):
                            html.H3("Variables")
                            with html.Table(classes="pulsar-campaign-variable-table"):
                                with html.Thead():
                                    with html.Tr():
                                        for label in ("Name", "Type", "Shape", "Information"):
                                            html.Th(label)
                                with html.Tbody():
                                    with html.Tr(v_for="variable in campaignFile.variable_details", key="variable.name"):
                                        html.Td("{{ variable.name }}")
                                        html.Td("{{ variable.type || 'unknown' }}")
                                        html.Td("{{ variable.shape || 'unknown' }}")
                                        html.Td("{{ variable.coverage || 'unknown' }}")
                        html.P("Variable metadata is unavailable", v_else_if="campaignFile.fileformat === 'ADIOS'", classes="pulsar-campaign-muted")
                        with html.Details(classes="pulsar-campaign-files", v_if="campaignFile.locations && campaignFile.locations.length"):
                            html.Summary("Recorded locations and sizes")
                            with html.Div(v_for="(location, index) in campaignFile.locations", key="index", classes="pulsar-campaign-input"):
                                html.Div("{{ location.host ? location.host + ':' : '' }}{{ location.path }}")
                                html.Div("Recorded size: {{ location.size_bytes !== null ? location.size_bytes.toLocaleString() + ' bytes' : 'unknown' }}", classes="pulsar-campaign-muted")
                                html.Div("Recorded modified: " + _date("location.modified_at"), classes="pulsar-campaign-muted")
                        with html.Details(classes="pulsar-campaign-files"):
                            html.Summary("Dataset history · latest 20 recorded events")
                            html.P("No dataset history recorded", v_if="!campaignFile.history || !campaignFile.history.length", classes="pulsar-campaign-muted")
                            with html.Div(v_for="(event, index) in campaignFile.history", key="index", classes="pulsar-campaign-input"):
                                html.Span("{{ event.action }} · " + _date("event.timestamp"))
                        with html.Details(classes="pulsar-campaign-files", v_if="campaignFile.variable_details && campaignFile.variable_details.length"):
                            html.Summary("Recorded variable metadata and provenance")
                            html.Pre("{{ campaignFile.metadata_text }}", classes="pulsar-campaign-metadata")
                        html.Pre("{{ campaignFile.text }}", v_if="campaignFile.text", classes="pulsar-campaign-metadata")
                        vuetify.VBtn("Browse variables", v_if="campaignFile.explorable", variant="text", click=(ctrl.explore_campaign_dataset, "[campaignFile.campaign_path, campaignFile.name]"))
