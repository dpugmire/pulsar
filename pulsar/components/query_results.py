"""A flexible metadata table embedded in an ordinary workspace tile."""

from trame.widgets import html
from trame.widgets import vuetify3 as vuetify


def build_query_table():
    # Both active grids and inactive pane previews bind the current cell as tile.
    with html.Div(
        v_if="tile.media_type === 'query_table'",
        classes="pulsar-query-result",
        style="height:100%; overflow:auto; background:#fff; color:#222;",
        raw_attrs=["@pointerdown.stop", "@dblclick.stop"],
    ):
        with html.Div(
            style="display:flex; gap:12px; align-items:center; padding:8px; flex-wrap:wrap;"
        ):
            html.Span("{{ tile.query_row_count + ' rows' }}", class_="text-caption")
            html.Span(
                "Truncated: {{ tile.query_truncation_reason }}",
                v_if="tile.query_truncated",
                class_="text-caption",
            )
            html.Span(
                "Campaign changed · saved result",
                v_if="tile.query_stale",
                class_="text-caption",
            )
            html.A(
                "Export CSV",
                href=("tile.query_csv_uri",),
                download=("'query-' + tile.query_result_id + '.csv'",),
                raw_attrs=["@click.stop"],
            )
        vuetify.VDataTable(
            headers=("tile.query_headers || []",),
            items=("tile.query_rows || []",),
            items_per_page=10,
            density="compact",
            hover=True,
        )
