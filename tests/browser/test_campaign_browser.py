"""Campaign list sorting, selection, and browser-local preferences."""

import os

import pytest


pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(os.environ.get("PULSAR_RUN_BROWSER_TESTS") != "1",
                       reason="set PULSAR_RUN_BROWSER_TESTS=1 to run browser tests"),
]


def _open(page, pulsar_server):
    page.goto(pulsar_server("campaigns"), wait_until="networkidle")
    page.locator(".pulsar-campaign-list").wait_for(state="visible")


def _directories(page):
    return page.locator(".pulsar-campaign-list-row.is-directory .pulsar-campaign-list-label").all_text_contents()


def test_natural_and_date_sort_preserve_hierarchy_selection_and_unknowns(page, pulsar_server):
    _open(page, pulsar_server)
    assert _directories(page) == ["hll_8", "hll_64", "hll_128"]
    page.get_by_role("button", name="Expand hll_128", exact=True).click()
    row = page.locator(".pulsar-campaign-list-row.is-file")
    row.press("Enter")
    heading = page.locator(".pulsar-campaign-selection-title")
    page.get_by_role("heading", name="hll_128/output.bp", exact=True).wait_for(state="visible")
    assert heading.inner_text() == "hll_128/output.bp"
    assert page.locator(".pulsar-campaign-selection-gallery img").count() == 1
    page.get_by_role("button", name="Recorded modified", exact=True).click()
    assert _directories(page) == ["hll_64", "hll_128", "hll_8"]
    assert heading.inner_text() == "hll_128/output.bp"
    assert row.count() == 1
    page.get_by_role("button", name="Recorded modified ↓", exact=True).click()
    assert _directories(page) == ["hll_128", "hll_64", "hll_8"]
    page.get_by_role("button", name="Expand hll_64", exact=True).click()
    page.locator(".pulsar-campaign-list-row.is-file").last.press("Enter")
    page.get_by_role("heading", name="hll_64/output.bp", exact=True).wait_for(state="visible")
    assert page.locator(".pulsar-campaign-selection-gallery img").count() == 0


def test_columns_sort_and_view_survive_reload(page, pulsar_server):
    _open(page, pulsar_server)
    page.get_by_text("Columns", exact=True).click()
    page.get_by_role("checkbox", name="Added to campaign", exact=True).check()
    page.get_by_role("checkbox", name="Information", exact=True).uncheck()
    page.get_by_text("Columns", exact=True).click()
    page.get_by_role("button", name="Name ↑", exact=True).click()
    page.reload(wait_until="networkidle")
    assert _directories(page) == ["hll_128", "hll_64", "hll_8"]
    assert page.get_by_role("button", name="Added to campaign", exact=True).is_visible()
    assert page.locator(".pulsar-campaign-list thead").inner_text().find("Information") == -1
    page.get_by_role("button", name="Gallery", exact=True).click()
    page.reload(wait_until="networkidle")
    assert page.locator(".pulsar-campaign-gallery-view").is_visible()
    page.get_by_role("button", name="List", exact=True).click()
    page.get_by_role("button", name="Open", exact=True).click()
    page.locator("#pulsar-variable-column").wait_for(state="visible")
