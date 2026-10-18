"""Browser tests for the home and inspector pages."""

import re

import httpx
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def new_bin(page: Page, app_url: str, label: str) -> str:
    """Make a bin from the home page and wait until its inspector is live.

    Args:
        page: The browser page.
        app_url: The app's base URL.
        label: The bin label.

    Returns:
        The new bin id.
    """
    page.goto(app_url)
    page.get_by_test_id("new-label").fill(label)
    page.get_by_test_id("new-bin").click()
    page.wait_for_url(re.compile(r"/bins/[A-Za-z0-9_-]{22}$"))
    expect(page.get_by_test_id("empty-state")).to_be_visible()
    expect(page.get_by_test_id("status")).to_have_text("Live")
    return page.url.rsplit("/", 1)[1]


def test_given_inspector_open_when_request_arrives_then_it_shows_within_one_second(page: Page, app_url: str) -> None:
    """Given the inspector is open, when a request arrives, then it shows within 1 s with no refresh."""
    # Given
    bin_id = new_bin(page, app_url, "live")
    # When
    httpx.post(f"{app_url}/api/webhook/{bin_id}/first", content=b"x")
    # Then
    expect(page.get_by_test_id("request-row")).to_have_count(1, timeout=1000)
    expect(page.get_by_test_id("request-row")).to_contain_text("/first")


def test_given_two_tabs_on_one_bin_when_request_arrives_then_both_show_it(page: Page, app_url: str) -> None:
    """Given two tabs open on one bin, when a request arrives, then both show it."""
    # Given
    bin_id = new_bin(page, app_url, "two tabs")
    other = page.context.new_page()
    other.goto(page.url)
    expect(other.get_by_test_id("status")).to_have_text("Live")
    # When
    httpx.post(f"{app_url}/api/webhook/{bin_id}", content=b"x")
    # Then
    for tab in (page, other):
        expect(tab.get_by_test_id("request-row")).to_have_count(1)


def test_given_inspector_open_when_bin_is_renamed_then_label_changes(page: Page, app_url: str) -> None:
    """Given the inspector is open, when the bin is renamed through the API, then the new label shows."""
    # Given
    bin_id = new_bin(page, app_url, "old name")
    # When
    httpx.patch(f"{app_url}/api/v1/bins/{bin_id}", json={"label": "new name"})
    # Then
    expect(page.get_by_text("new name")).to_be_visible()


def test_given_new_bin_when_client_sends_json_then_body_tab_shows_formatted_json(page: Page, app_url: str) -> None:
    """Given a new bin, when a client sends JSON, then the request is listed and the Body tab shows formatted JSON."""
    # Given
    bin_id = new_bin(page, app_url, "json")
    # When
    httpx.post(f"{app_url}/api/webhook/{bin_id}/github", json={"event": "push", "ids": [1, 2]})
    page.get_by_test_id("body-tab").click()
    # Then
    expect(page.get_by_test_id("request-row")).to_have_count(1)
    expect(page.get_by_test_id("body")).to_contain_text('"event": "push"')


def test_given_authorization_header_when_headers_open_then_value_is_masked_until_clicked(
    page: Page, app_url: str
) -> None:
    """Given a request with an Authorization header, when Headers opens, then the value shows as dots until clicked."""
    # Given
    bin_id = new_bin(page, app_url, "masked")
    httpx.post(f"{app_url}/api/webhook/{bin_id}", json={}, headers={"Authorization": "Bearer s3cret"})
    expect(page.get_by_test_id("request-row")).to_have_count(1)
    # When
    page.get_by_test_id("headers-tab").click()
    masked = page.get_by_test_id("masked-header")
    # Then
    expect(masked).to_have_text("••••")
    expect(page.get_by_text("Bearer s3cret")).to_have_count(0)
    masked.click()
    expect(page.get_by_text("Bearer s3cret")).to_be_visible()


def test_given_browser_listing_when_user_makes_bin_and_reloads_home_then_bin_is_listed(
    page: Page, app_url: str
) -> None:
    """Given `browser` listing, when the user makes a bin and reloads the home page, then the bin is still listed."""
    # Given
    new_bin(page, app_url, "kept in this browser")
    # When
    page.goto(app_url)
    page.reload()
    # Then
    expect(page.get_by_test_id("bin-row").filter(has_text="kept in this browser")).to_have_count(1)


def test_given_binary_body_when_body_opens_then_size_and_download_show(page: Page, app_url: str) -> None:
    """Given a binary body, when the Body tab opens, then it shows the size and a download of the exact bytes."""
    # Given
    bin_id = new_bin(page, app_url, "binary")
    body = bytes(range(256))
    httpx.put(
        f"{app_url}/api/webhook/{bin_id}/blob", content=body, headers={"content-type": "application/octet-stream"}
    )
    expect(page.get_by_test_id("request-row")).to_have_count(1)
    # When
    page.get_by_test_id("body-tab").click()
    with page.expect_download() as download:
        page.get_by_role("button", name="Download").click()
    # Then
    expect(page.get_by_test_id("body")).to_contain_text("Binary body, 256 bytes.")
    assert download.value.path().read_bytes() == body
