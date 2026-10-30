"""Browser tests for filters, deletes, export, reply settings and replay."""

import json
import threading
import time

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_pages import new_bin

pytestmark = pytest.mark.e2e


def send(app_url: str, bin_id: str, method: str, path: str, body: bytes = b"") -> None:
    """Send one request to a bin.

    Args:
        app_url: The app's base URL.
        bin_id: The bin id.
        method: The HTTP method.
        path: The sub-path, starting with "/".
        body: The body bytes.
    """
    httpx.request(method, f"{app_url}/api/webhook/{bin_id}{path}", content=body)


def test_given_get_and_post_requests_when_user_filters_by_post_then_only_post_shows(page: Page, app_url: str) -> None:
    """Given a bin with GET and POST requests, when the user filters by POST, then only POST requests show."""
    # Given
    bin_id = new_bin(page, app_url, "filters")
    send(app_url, bin_id, "GET", "/one")
    send(app_url, bin_id, "POST", "/two", b"x")
    expect(page.get_by_test_id("request-row")).to_have_count(2)
    # When
    page.get_by_test_id("method-filter").click()
    page.get_by_role("option", name="POST").click()
    # Then
    expect(page.get_by_test_id("request-row")).to_have_count(1)
    expect(page.get_by_test_id("request-row")).to_contain_text("/two")


def test_given_invoice_body_when_user_searches_invoice_then_that_request_shows(page: Page, app_url: str) -> None:
    """Given a request whose body holds "invoice", when the user searches "invoice", then that request shows."""
    # Given
    bin_id = new_bin(page, app_url, "search")
    send(app_url, bin_id, "POST", "/order", b'{"kind": "order"}')
    send(app_url, bin_id, "POST", "/bill", b'{"kind": "invoice"}')
    expect(page.get_by_test_id("request-row")).to_have_count(2)
    # When
    page.get_by_test_id("search").fill("invoice")
    # Then
    expect(page.get_by_test_id("request-row")).to_have_count(1)
    expect(page.get_by_test_id("request-row")).to_contain_text("/bill")
    expect(page.get_by_test_id("request-count")).to_contain_text("1 matching")


def test_given_request_when_user_deletes_it_then_it_is_gone_in_every_open_tab(page: Page, app_url: str) -> None:
    """Given a request open in two tabs, when the user deletes it in one, then it is gone from both."""
    # Given
    bin_id = new_bin(page, app_url, "delete")
    other = page.context.new_page()
    other.goto(page.url)
    expect(other.get_by_test_id("status")).to_have_text("Live")
    send(app_url, bin_id, "POST", "/gone", b"x")
    expect(page.get_by_test_id("request-row")).to_have_count(1)
    # When
    page.get_by_test_id("delete-request").click()
    page.get_by_test_id("confirm-delete").click()
    # Then
    for tab in (page, other):
        expect(tab.get_by_test_id("request-row")).to_have_count(0)
        expect(tab.get_by_test_id("empty-state")).to_be_visible()


def test_given_bin_when_user_exports_it_then_file_holds_every_request(page: Page, app_url: str) -> None:
    """Given a bin with two requests, when the user exports it, then the file is in the export format with both."""
    # Given
    bin_id = new_bin(page, app_url, "export")
    send(app_url, bin_id, "POST", "/a", b'{"a": 1}')
    send(app_url, bin_id, "PUT", "/b", b"\xff")
    expect(page.get_by_test_id("request-row")).to_have_count(2)
    # When
    with page.expect_download() as download:
        page.get_by_test_id("export").click()
    # Then
    document = json.loads(download.value.path().read_bytes())
    assert document["format"] == "webhook-studio-export"
    assert [entry["path"] for entry in document["requests"]] == ["/a", "/b"]


def test_given_reply_set_to_418_in_dialog_when_request_arrives_then_sender_gets_418(page: Page, app_url: str) -> None:
    """Given the user sets the reply to 418 with a body, when a request arrives, then the sender gets them."""
    # Given
    bin_id = new_bin(page, app_url, "teapot")
    page.get_by_test_id("reply-settings").click()
    page.get_by_test_id("reply-status").fill("418")
    page.get_by_role("switch").last.click()
    page.get_by_test_id("reply-body").fill("short and stout")
    page.get_by_test_id("reply-save").click()
    expect(page.get_by_text("Saved the reply settings.")).to_be_visible()
    # When
    response = httpx.post(f"{app_url}/api/webhook/{bin_id}", content=b"x")
    # Then
    assert (response.status_code, response.text) == (418, "short and stout")


def test_given_two_second_delay_when_request_arrives_then_page_shows_it_before_the_reply(
    page: Page, app_url: str
) -> None:
    """Given a bin with a 2 s delay, when a request arrives, then the page shows it before the sender gets a reply."""
    # Given
    bin_id = new_bin(page, app_url, "delay")
    httpx.patch(f"{app_url}/api/v1/bins/{bin_id}", json={"reply": {"delay_ms": 2000}})
    answered: list[float] = []

    def post() -> None:
        httpx.post(f"{app_url}/api/webhook/{bin_id}/slow", content=b"x", timeout=10)
        answered.append(time.monotonic())

    sender = threading.Thread(target=post)
    # When
    sender.start()
    expect(page.get_by_test_id("request-row")).to_have_count(1, timeout=1500)
    shown = time.monotonic()
    sender.join()
    # Then
    assert answered
    assert shown < answered[0]


def test_given_restricted_mode_when_user_replays_to_loopback_then_tab_says_not_allowed(
    page: Page, app_url: str
) -> None:
    """Given `restricted` mode, when the user replays to 127.0.0.1, then the Replay tab says the address is refused."""
    # Given
    bin_id = new_bin(page, app_url, "replay")
    send(app_url, bin_id, "POST", "/r", b"x")
    expect(page.get_by_test_id("request-row")).to_have_count(1)
    # When
    page.get_by_test_id("replay-tab").click()
    page.get_by_test_id("replay-target").fill("http://127.0.0.1:9/")
    page.get_by_test_id("replay-send").click()
    # Then
    expect(page.get_by_text("Target address not allowed.")).to_be_visible()


def test_given_more_than_a_page_when_user_scrolls_to_the_end_then_older_requests_load(page: Page, app_url: str) -> None:
    """Given 60 requests, when the user scrolls to the end of the list, then all 60 show."""
    # Given
    bin_id = new_bin(page, app_url, "scroll")
    with httpx.Client() as client:
        for n in range(60):
            client.post(f"{app_url}/api/webhook/{bin_id}/n{n}", content=b"x")
    page.reload()
    expect(page.get_by_test_id("request-row")).to_have_count(50)
    # When
    page.get_by_test_id("request-row").last.scroll_into_view_if_needed()
    # Then
    expect(page.get_by_test_id("request-row")).to_have_count(60)
    expect(page.get_by_test_id("load-older")).to_have_count(0)
