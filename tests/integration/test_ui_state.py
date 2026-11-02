"""Tests for the home and inspector state handlers, on SQLite and PostgreSQL."""

# Fixtures take other fixtures as arguments of the same name.
# pylint: disable=redefined-outer-name

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid7

import pytest
from reflex.istate.data import RouterData

from reflex_fastapi_webhook_studio import runtime
from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.domain import (
    BinEvent,
    BinListing,
    EventType,
    HttpMethod,
    IncomingRequest,
    ReplayMode,
    ReplyConfig,
)
from reflex_fastapi_webhook_studio.services.bins import BinService
from reflex_fastapi_webhook_studio.services.capture import CaptureService
from reflex_fastapi_webhook_studio.services.replay import ReplayService
from reflex_fastapi_webhook_studio.services.requests import RequestService
from reflex_fastapi_webhook_studio.settings import Settings
from reflex_fastapi_webhook_studio.ui.live import sockets
from reflex_fastapi_webhook_studio.ui.state import inspector as inspector_module
from reflex_fastapi_webhook_studio.ui.state.home import HomeState
from reflex_fastapi_webhook_studio.ui.state.inspector import ALL_METHODS, SKIP, InspectorState
from reflex_fastapi_webhook_studio.ui.views import PairView, ReplayView, ReplyForm, RequestView

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    import reflex as rx
    from reflex.state import BaseState
    from reflex_base.event import EventSpec

    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.domain import CapturedRequest
    from tests.echo import EchoServer

SETTINGS = Settings(max_bins=3)
INCOMING = IncomingRequest(
    method=HttpMethod.POST,
    path="/github",
    query_string="",
    headers=(("content-type", "application/json"), ("authorization", "Bearer x")),
    body=b'{"a": 1}',
    body_size=8,
    body_truncated=False,
    content_type="application/json",
    remote_addr="203.0.113.7",
    http_version="1.1",
)


@pytest.fixture
def services(database: Database, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Point the UI's shared services at the test database.

    Args:
        database: The test database.
        monkeypatch: Swaps the shared objects for this test.

    Returns:
        The settings in use.
    """
    monkeypatch.setattr(runtime, "settings", SETTINGS)
    monkeypatch.setattr(runtime, "bin_service", BinService(database, SETTINGS))
    monkeypatch.setattr(runtime, "request_service", RequestService(database))
    monkeypatch.setattr(runtime, "replay_service", ReplayService(RequestService(database), SETTINGS))
    return SETTINGS


def make_state[S: BaseState](cls: type[S], path: str = "/") -> S:
    """Build a state as Reflex would for a page, with no server.

    Args:
        cls: The state class.
        path: The page path the state belongs to.

    Returns:
        The state.
    """
    # Reflex's own flag for building a state outside its event loop.
    state = cls(_reflex_internal_init=True)
    state.router = RouterData.from_router_data({"pathname": path, "asPath": path, "query": {}})
    return state


def args_of(spec: EventSpec) -> str:
    """Join an event's arguments into one string, for assertions.

    Args:
        spec: The event.

    Returns:
        The arguments as JavaScript text.
    """
    return " ".join(f"{name!s}={value!s}" for name, value in spec.args)


@pytest.mark.anyio
async def test_given_browser_listing_when_home_loads_then_only_remembered_bins_show(
    database: Database, services: Settings
) -> None:
    """Given `browser` listing and one remembered bin of two, when the home page loads, then only that bin shows."""
    # Given
    bins = BinService(database, services)
    kept = await bins.create("kept")
    await bins.create("other")
    home = make_state(HomeState)
    home.known_bins = json.dumps([kept.id, "bad"])
    assert home.loading
    # When
    await home.load()
    # Then
    assert (home.listing_all, home.loading) == (False, False)
    assert [(row.id, row.label) for row in home.bins] == [(kept.id, "kept")]


@pytest.mark.anyio
async def test_given_all_listing_when_home_loads_then_every_bin_shows(
    database: Database, monkeypatch: pytest.MonkeyPatch, services: Settings
) -> None:
    """Given `all` listing and two bins, when the home page loads, then both show."""
    # Given
    settings = replace(services, bin_listing=BinListing.ALL)
    monkeypatch.setattr(runtime, "settings", settings)
    monkeypatch.setattr(runtime, "bin_service", BinService(database, settings))
    await runtime.bin_service.create("one")
    await runtime.bin_service.create(None)
    home = make_state(HomeState)
    # When
    await home.load()
    # Then
    assert home.listing_all
    assert sorted(row.label for row in home.bins) == ["No label", "one"]


@pytest.mark.anyio
@pytest.mark.usefixtures("services")
async def test_given_label_when_bin_is_created_then_it_is_remembered_and_opened() -> None:
    """Given a typed label, when a bin is made, then it is remembered first, the box clears and the inspector opens."""
    # Given
    home = make_state(HomeState)
    home.set_new_label("  orders  ")
    # When
    events = [event async for event in home.create_bin()]
    # Then
    bin_id = json.loads(home.known_bins)[0]
    assert (await runtime.bin_service.get(bin_id)).label == "orders"
    assert (home.new_label, home.creating) == ("", False)
    assert events[0] is None
    assert events[-1] is not None
    assert f'path="/bins/{bin_id}"' in args_of(events[-1])


@pytest.mark.anyio
@pytest.mark.usefixtures("services")
async def test_given_long_label_or_full_app_when_bin_is_created_then_error_toast_and_no_move() -> None:
    """Given a label over 80 characters, or no room for bins, when a bin is made, then an error toast shows."""
    # Given
    home = make_state(HomeState)
    home.set_new_label("x" * 81)
    for _ in range(SETTINGS.max_bins):
        await runtime.bin_service.create(None)
    # When
    too_long = [event async for event in home.create_bin()]
    home.set_new_label("")
    full = [event async for event in home.create_bin()]
    # Then
    assert too_long[-1] is not None
    assert "80 characters" in args_of(too_long[-1])
    assert full[-1] is not None
    assert "most bins" in args_of(full[-1])
    assert (home.known_bins, home.creating) == ("[]", False)


def test_given_typed_text_when_bin_is_opened_then_it_moves_or_warns() -> None:
    """Given a bin URL or junk in the open box, when opened, then the page moves to the bin or warns."""
    # Given
    home = make_state(HomeState)
    bin_id = "AbCdEfGhIjKlMnOpQrStUv"
    # When
    home.set_open_text(f"http://localhost:17301/api/webhook/{bin_id}")
    moved = home.open_bin()
    home.set_open_text("junk")
    warned = home.open_bin()
    # Then
    assert f'path="/bins/{bin_id}"' in args_of(moved)
    assert "bin id" in args_of(warned)
    assert home.open_text == "junk"


@pytest.mark.anyio
async def test_given_bin_with_requests_when_inspector_loads_then_newest_shows_first_and_picked(
    database: Database, services: Settings
) -> None:
    """Given a bin with two requests, when the inspector loads, then they list newest first and the newest shows."""
    # Given
    bin_ = await BinService(database, services).create("orders")
    capture = CaptureService(database, services)
    older = await capture.capture(bin_.id, INCOMING, reply_status=200)
    newer = await capture.capture(bin_.id, replace(INCOMING, path="/second"), reply_status=200)
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    assert inspector.loading
    # When
    await inspector.load()
    # Then
    assert (inspector.found, inspector.label, inspector.live, inspector.loading) == (True, "orders", False, False)
    assert inspector.capture_url.endswith(f"/api/webhook/{bin_.id}")
    assert inspector.curl_command.startswith(f"curl -X POST {inspector.capture_url}")
    assert [row.id for row in inspector.requests] == [str(newer.id), str(older.id)]
    assert inspector.detail.id == str(newer.id)


@pytest.mark.anyio
async def test_given_older_request_picked_when_inspector_reloads_then_pick_is_kept(
    database: Database, services: Settings
) -> None:
    """Given the older request picked with a header shown, when the inspector reloads, then the pick stays."""
    # Given
    bin_ = await BinService(database, services).create(None)
    capture = CaptureService(database, services)
    older = await capture.capture(bin_.id, INCOMING, reply_status=200)
    await capture.capture(bin_.id, INCOMING, reply_status=200)
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    await inspector.load()
    await inspector.select(str(older.id))
    inspector.reveal(1)
    inspector.reveal(1)
    # When
    await inspector.load()
    # Then
    assert inspector.detail.id == str(older.id)
    assert inspector.label == "No label"
    assert inspector.revealed == [1]
    assert inspector.detail.headers[1].secret


@pytest.mark.anyio
@pytest.mark.usefixtures("services")
async def test_given_unknown_bin_when_inspector_loads_then_not_found_and_cleared() -> None:
    """Given no bin with the id in the path, when the inspector loads, then it shows not found with nothing kept."""
    # Given
    inspector = make_state(InspectorState, "/bins/AbCdEfGhIjKlMnOpQrStUv")
    inspector.label = "stale"
    # When
    await inspector.load()
    # Then
    assert not inspector.found
    assert (inspector.label, inspector.capture_url, inspector.requests) == ("", "", [])
    assert inspector.detail == RequestView()


@pytest.mark.anyio
async def test_given_bad_or_unknown_request_id_when_picked_then_nothing_shows(
    database: Database, services: Settings
) -> None:
    """Given a malformed or unknown request id, when picked, then the tabs show nothing and download warns."""
    # Given
    bin_ = await BinService(database, services).create(None)
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    # When
    await inspector.select("not-a-uuid")
    bad = inspector.detail
    await inspector.select(str(uuid7()))
    unknown = inspector.detail
    download = await inspector.download_body()
    # Then
    assert bad == unknown == RequestView()
    assert "gone" in args_of(download)


@pytest.mark.anyio
async def test_given_request_on_show_when_user_copies_and_downloads_then_events_carry_the_data(
    database: Database, services: Settings
) -> None:
    """Given a request on show, when the user copies the URL or curl, or downloads, then the events hold that data."""
    # Given
    bin_ = await BinService(database, services).create(None)
    stored = await CaptureService(database, services).capture(bin_.id, INCOMING, reply_status=200)
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    await inspector.load()
    # When
    copy_url = inspector.copy_url()
    copy_curl = inspector.copy_curl()
    download = await inspector.download_body()
    # Then
    assert inspector.capture_url in args_of(copy_url[0])
    assert "Copied the bin URL" in args_of(copy_url[1])
    assert "curl -X POST" in args_of(copy_curl[0])
    assert "base64,eyJhIjogMX0=" in args_of(download)
    assert f'filename="{stored.id}.bin"' in args_of(download)


@pytest.mark.anyio
async def test_given_open_inspector_when_bin_events_arrive_then_list_and_label_follow(
    database: Database, services: Settings
) -> None:
    """Given an empty open inspector, when bin events arrive, then requests join once, and the label reloads."""
    # Given
    bin_ = await BinService(database, services).create("old")
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    await inspector.load()
    stored = await CaptureService(database, services).capture(bin_.id, INCOMING, reply_status=200)
    captured = BinEvent(type=EventType.REQUEST_CAPTURED, bin_id=bin_.id, request=stored.summary())
    # The watch task's event step is private; the test drives it directly.
    apply = inspector._apply  # noqa: SLF001  # pylint: disable=protected-access
    # When
    await apply(captured)
    await apply(captured)
    await runtime.bin_service.rename(bin_.id, "renamed")
    await apply(BinEvent(type=EventType.BIN_UPDATED, bin_id=bin_.id, label="renamed"))
    labelled = inspector.label
    await runtime.bin_service.rename(bin_.id, None)
    await apply(BinEvent(type=EventType.RESYNC, bin_id=bin_.id))
    # Then
    assert [row.id for row in inspector.requests] == [str(stored.id)]
    assert inspector.detail.id == str(stored.id)
    assert (labelled, inspector.label) == ("renamed", "No label")


async def until(check: Callable[[], bool]) -> None:
    """Wait up to 5 s for a background task to make a condition true.

    Args:
        check: The condition.
    """
    async with asyncio.timeout(5):
        while not check():  # noqa: ASYNC110  # Page state offers no event to wait on, so poll it.
            await asyncio.sleep(0.01)


def watch(inspector: InspectorState) -> Coroutine[Any, Any, None]:
    """Run the inspector's watch task on a state, as Reflex's background runner does.

    Reflex refuses a direct call to a background task, so this calls the function its handler wraps.

    Args:
        inspector: The state.

    Returns:
        The running task's coroutine.
    """
    handler = cast("rx.EventHandler", InspectorState.watch)
    # Reflex makes the method an EventHandler when the class is built, which pylint cannot see.
    return cast("Coroutine[Any, Any, None]", handler.fn(inspector))  # pylint: disable=no-member


@pytest.mark.anyio
async def test_given_watched_bin_when_tab_closes_then_watch_stops_at_the_next_quiet_heartbeat(
    database: Database, services: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a watched bin whose tab has closed, when a heartbeat passes with no event, then the watch task stops."""
    # Given
    bin_ = await BinService(database, services).create(None)
    monkeypatch.setattr(runtime, "bus", MemoryBus())
    monkeypatch.setattr(inspector_module, "HEARTBEAT_S", 0.01)
    monkeypatch.setattr(sockets, "connected", lambda _token: False)
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    # When
    async with asyncio.timeout(5):
        await watch(inspector)
    # Then
    assert (inspector.found, inspector.loading, inspector.live) == (True, False, False)
    # Clearing the guard lets the tab start a new watch task after a reconnect.
    assert inspector._watcher == ""  # noqa: SLF001  # pylint: disable=protected-access


@pytest.mark.anyio
async def test_given_watched_bin_when_events_arrive_then_page_follows_until_the_bin_is_deleted(
    database: Database, services: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a watched bin, when a request, a resync and a delete arrive, then the page follows them and stops."""
    # Given
    bin_ = await BinService(database, services).create(None)
    bus = MemoryBus()
    monkeypatch.setattr(runtime, "bus", bus)
    monkeypatch.setattr(sockets, "connected", lambda _token: True)
    capture = CaptureService(database, services)
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    async with asyncio.TaskGroup() as group:
        group.create_task(watch(inspector))
        await until(lambda: inspector.live)
        async with asyncio.timeout(1):
            await watch(inspector)
        still_live = inspector.live
        # When
        first = await capture.capture(bin_.id, INCOMING, reply_status=200)
        await bus.publish(BinEvent(type=EventType.REQUEST_CAPTURED, bin_id=bin_.id, request=first.summary()))
        unseen = await capture.capture(bin_.id, replace(INCOMING, path="/unseen"), reply_status=200)
        await bus.publish(BinEvent(type=EventType.RESYNC, bin_id=bin_.id))
        await until(lambda: len(inspector.requests) == 2)
        listed = [row.id for row in inspector.requests]
        await bus.publish(BinEvent(type=EventType.BIN_DELETED, bin_id=bin_.id))
    # Then
    assert still_live
    assert listed == [str(unseen.id), str(first.id)]
    assert (inspector.found, inspector.deleted, inspector.live) == (False, True, False)


def args_text(specs: EventSpec | list[EventSpec] | None) -> str:
    """Join the arguments of one or more events, for assertions.

    Args:
        specs: The events a handler returned.

    Returns:
        Their arguments as JavaScript text.
    """
    if specs is None:
        return ""
    return " ".join(args_of(spec) for spec in (specs if isinstance(specs, list) else [specs]))


async def open_bin(
    database: Database, settings: Settings, *incoming: IncomingRequest
) -> tuple[InspectorState, list[CapturedRequest]]:
    """Make a bin, capture requests in it, and load its inspector.

    Args:
        database: The test database.
        settings: The settings in use.
        *incoming: The requests to capture, oldest first.

    Returns:
        The loaded inspector and the stored requests.
    """
    bin_ = await BinService(database, settings).create("orders")
    capture = CaptureService(database, settings)
    stored = [await capture.capture(bin_.id, request, reply_status=200) for request in incoming]
    inspector = make_state(InspectorState, f"/bins/{bin_.id}")
    await inspector.load()
    return inspector, stored


@pytest.mark.anyio
async def test_given_bin_with_get_and_post_when_filtered_then_only_matches_list(
    database: Database, services: Settings
) -> None:
    """Given GET and POST requests, when filtered by POST, then searched, then cleared, then the list follows."""
    # Given
    get = replace(INCOMING, method=HttpMethod.GET, body=b"", body_size=0)
    invoice = replace(INCOMING, body=b'{"kind": "invoice"}')
    inspector, stored = await open_bin(database, services, get, INCOMING, invoice)
    # When
    await inspector.set_method_filter("POST")
    posts = [row.id for row in inspector.requests]
    await inspector.set_search("INVOICE")
    found = ([row.id for row in inspector.requests], inspector.total, inspector.filtered)
    await inspector.set_method_filter("TRACE")
    any_method = inspector.method_filter
    await inspector.clear_filters()
    # Then
    assert posts == [str(stored[2].id), str(stored[1].id)]
    assert found == ([str(stored[2].id)], 1, True)
    assert any_method == ALL_METHODS
    assert (len(inspector.requests), inspector.filtered) == (3, False)


@pytest.mark.anyio
async def test_given_more_requests_than_a_page_when_scrolled_then_older_pages_load(
    database: Database, monkeypatch: pytest.MonkeyPatch, services: Settings
) -> None:
    """Given five requests and pages of two, when older pages load, then all five show and loading stops."""
    # Given
    monkeypatch.setattr(inspector_module, "PAGE_SIZE", 2)
    inspector, stored = await open_bin(database, services, *[INCOMING] * 5)
    first_page = (len(inspector.requests), inspector.total, inspector.has_older)
    # When
    await inspector.load_older()
    await inspector.load_older()
    await inspector.load_older()
    # Then
    assert first_page == (2, 5, True)
    assert [row.id for row in inspector.requests] == [str(request.id) for request in reversed(stored)]
    assert not inspector.has_older


@pytest.mark.anyio
async def test_given_count_older_than_rows_when_older_page_is_empty_then_loading_stops(
    database: Database, services: Settings
) -> None:
    """Given a count that says more requests exist than do, when the next page is empty, then the count drops."""
    # Given
    inspector, _ = await open_bin(database, services, INCOMING)
    inspector.total = 5
    # When
    await inspector.load_older()
    # Then
    assert inspector.total == 1


@pytest.mark.anyio
async def test_given_open_inspector_when_delete_and_clear_events_arrive_then_list_follows(
    database: Database, services: Settings
) -> None:
    """Given three requests with the newest picked, when it is deleted elsewhere, then the next shows; clear empties."""
    # Given
    inspector, stored = await open_bin(database, services, INCOMING, INCOMING, INCOMING)
    apply = inspector._apply  # noqa: SLF001  # pylint: disable=protected-access
    bin_id = stored[0].bin_id
    # When
    await runtime.request_service.delete(bin_id, stored[2].id)
    await apply(BinEvent(type=EventType.REQUEST_DELETED, bin_id=bin_id, request_id=stored[2].id))
    await apply(BinEvent(type=EventType.REQUEST_DELETED, bin_id=bin_id, request_id=uuid7()))
    after_delete = ([row.id for row in inspector.requests], inspector.total, inspector.detail.id)
    await apply(BinEvent(type=EventType.BIN_CLEARED, bin_id=bin_id))
    # Then
    assert after_delete == ([str(stored[1].id), str(stored[0].id)], 2, str(stored[1].id))
    assert (inspector.requests, inspector.total, inspector.detail) == ([], 0, RequestView())


@pytest.mark.anyio
async def test_given_open_inspector_when_bin_is_deleted_elsewhere_then_page_says_so(
    database: Database, services: Settings
) -> None:
    """Given an open inspector, when its bin is deleted elsewhere, then it shows the bin as deleted, with no data."""
    # Given
    inspector, stored = await open_bin(database, services, INCOMING)
    apply = inspector._apply  # noqa: SLF001  # pylint: disable=protected-access
    # When
    await apply(BinEvent(type=EventType.BIN_DELETED, bin_id=stored[0].bin_id))
    # Then
    assert (inspector.found, inspector.deleted) == (False, True)
    assert (inspector.requests, inspector.capture_url, inspector.export_url) == ([], "", "")


@pytest.mark.anyio
async def test_given_filter_on_when_request_arrives_then_list_reloads_with_matches_only(
    database: Database, services: Settings
) -> None:
    """Given a POST filter, when a GET and then a POST arrive, then only the POST joins the list."""
    # Given
    inspector, _ = await open_bin(database, services)
    await inspector.set_method_filter("POST")
    apply = inspector._apply  # noqa: SLF001  # pylint: disable=protected-access
    capture = CaptureService(database, services)
    bin_id = inspector.export_url.split("/")[-2]
    # When
    for request in (replace(INCOMING, method=HttpMethod.GET), INCOMING):
        stored = await capture.capture(bin_id, request, reply_status=200)
        await apply(BinEvent(type=EventType.REQUEST_CAPTURED, bin_id=bin_id, request=stored.summary()))
    # Then
    assert [row.method for row in inspector.requests] == ["POST"]
    assert inspector.total == 1


@pytest.mark.anyio
async def test_given_full_list_when_request_arrives_then_count_stays_at_the_cap(
    database: Database, monkeypatch: pytest.MonkeyPatch, services: Settings
) -> None:
    """Given a bin at its request cap, when one more arrives, then the oldest row goes and the count holds."""
    # Given
    settings = replace(services, max_requests_per_bin=2)
    monkeypatch.setattr(runtime, "settings", settings)
    inspector, stored = await open_bin(database, settings, INCOMING, INCOMING)
    apply = inspector._apply  # noqa: SLF001  # pylint: disable=protected-access
    newest = await CaptureService(database, settings).capture(stored[0].bin_id, INCOMING, reply_status=200)
    # When
    await apply(BinEvent(type=EventType.REQUEST_CAPTURED, bin_id=newest.bin_id, request=newest.summary()))
    # Then
    assert [row.id for row in inspector.requests] == [str(newest.id), str(stored[1].id)]
    assert inspector.total == 2


@pytest.mark.anyio
async def test_given_request_on_show_when_user_deletes_it_with_dont_ask_then_next_delete_skips_the_dialog(
    database: Database, services: Settings
) -> None:
    """Given three requests, when one is deleted with "Don't ask again", then the next delete asks nothing."""
    # Given
    inspector, stored = await open_bin(database, services, INCOMING, INCOMING, INCOMING)
    # When
    asked = await inspector.ask_delete_request()
    dialog = inspector.confirming
    inspector.set_dont_ask(True)
    deleted = await inspector.confirm()
    skipped = await inspector.ask_delete_request()
    # Then
    assert (asked, dialog) == (None, "request")
    assert "Deleted the request" in args_text(deleted)
    assert "Deleted the request" in args_text(skipped)
    assert (inspector.skip_request_confirm, inspector.confirming) == (SKIP, "")
    assert [row.id for row in inspector.requests] == [str(stored[0].id)]
    assert await runtime.request_service.count(stored[0].bin_id) == 1


@pytest.mark.anyio
async def test_given_confirm_dialog_when_dismissed_then_nothing_is_deleted(
    database: Database, services: Settings
) -> None:
    """Given the clear dialog open, when dismissed, then nothing is deleted; confirming nothing does nothing."""
    # Given
    inspector, _ = await open_bin(database, services, INCOMING)
    await inspector.ask_clear()
    # When
    inspector.set_confirm_open(True)
    still_open = inspector.confirming
    inspector.set_confirm_open(False)
    nothing = await inspector.confirm()
    # Then
    assert (still_open, inspector.confirming, nothing) == ("clear", "", None)
    assert len(inspector.requests) == 1


@pytest.mark.anyio
async def test_given_bin_when_user_clears_it_with_dont_ask_then_it_empties_and_next_clear_skips(
    database: Database, services: Settings
) -> None:
    """Given a bin with requests, when cleared with "Don't ask again", then it empties and the next clear asks not."""
    # Given
    inspector, stored = await open_bin(database, services, INCOMING, INCOMING)
    await inspector.ask_clear()
    inspector.set_dont_ask(True)
    # When
    cleared = await inspector.confirm()
    again = await inspector.ask_clear()
    # Then
    assert "Cleared the bin" in args_text(cleared)
    assert "Cleared the bin" in args_text(again)
    assert (inspector.requests, inspector.skip_clear_confirm) == ([], SKIP)
    assert await runtime.request_service.count(stored[0].bin_id) == 0


@pytest.mark.anyio
async def test_given_bin_when_user_deletes_it_then_home_forgets_it_and_page_moves_home(
    database: Database, monkeypatch: pytest.MonkeyPatch, services: Settings
) -> None:
    """Given a remembered bin, when the user deletes it and confirms, then it is gone, forgotten, and the page moves."""
    # Given
    inspector, stored = await open_bin(database, services, INCOMING)
    bin_id = stored[0].bin_id
    home = make_state(HomeState)
    home.known_bins = json.dumps([bin_id])

    async def same_home(_self: InspectorState, _state: type[HomeState]) -> HomeState:
        return home

    monkeypatch.setattr(InspectorState, "get_state", same_home)
    await inspector.ask_delete_bin()
    # When
    moved = await inspector.confirm()
    gone = await inspector.ask_delete_bin()
    # Then
    assert 'path="/"' in args_text(moved)
    assert "Deleted the bin" in args_text(moved)
    assert (inspector.found, inspector.deleted, home.known_bins) == (False, True, "[]")
    assert gone is None
    assert inspector.confirming == "bin"
    inspector.skip_bin_confirm = SKIP
    assert "gone" in args_text(await inspector.ask_delete_bin())


@pytest.mark.anyio
async def test_given_nothing_on_show_when_deleting_copying_or_replaying_then_it_says_gone(
    database: Database, services: Settings
) -> None:
    """Given an empty bin, when the user deletes, copies or replays the request on show, then each says it is gone."""
    # Given
    inspector, _ = await open_bin(database, services)
    inspector.skip_request_confirm = SKIP
    # When
    deleted = await inspector.ask_delete_request()
    copied = await inspector.copy_as_curl()
    _ = [step async for step in inspector.send_replay()]
    inspector.detail = replace(inspector.detail, id=str(uuid7()))
    deleted_unknown = await inspector.ask_delete_request()
    copied_unknown = await inspector.copy_as_curl()
    # Then
    for result in (deleted, copied, deleted_unknown, copied_unknown):
        assert "gone" in args_text(result)
    assert inspector.replay_error == "This request is gone."


@pytest.mark.anyio
async def test_given_request_on_show_when_copied_as_curl_then_command_points_at_the_bin(
    database: Database, services: Settings
) -> None:
    """Given a request on show, when copied as curl, then the command aims at the bin; export points at the API."""
    # Given
    inspector, stored = await open_bin(database, services, INCOMING)
    # When
    copied = await inspector.copy_as_curl()
    # Then
    assert f"curl -X POST {inspector.capture_url}/github" in args_text(copied)
    assert inspector.export_url.endswith(f"/api/v1/bins/{stored[0].bin_id}/export")


@pytest.mark.anyio
async def test_given_reply_dialog_when_user_edits_and_saves_then_bin_replies_that_way(
    database: Database, services: Settings
) -> None:
    """Given the reply dialog, when the user sets 418, a header and a body, and saves, then the bin keeps them."""
    # Given
    inspector, stored = await open_bin(database, services)
    await inspector.open_reply()
    # When
    inspector.set_reply_status("418")
    inspector.set_reply_content_type("text/plain")
    inspector.set_reply_delay("5")
    inspector.add_reply_header()
    inspector.add_reply_header()
    inspector.set_reply_header_name(0, "X-Tea")
    inspector.set_reply_header_value(0, "yes")
    inspector.remove_reply_header(1)
    inspector.set_reply_custom_body(True)
    inspector.set_reply_body("short and stout")
    saved = await inspector.save_reply()
    # Then
    assert "Saved the reply settings" in args_text(saved)
    assert not inspector.reply_open
    bin_id = inspector.export_url.split("/")[-2]
    assert (await runtime.bin_service.get(bin_id)).reply == ReplyConfig(
        status=418, content_type="text/plain", headers=(("X-Tea", "yes"),), body="short and stout", delay_ms=5
    )
    assert inspector.reply.headers == [PairView(index=0, name="X-Tea", value="yes")]
    assert stored == []


@pytest.mark.anyio
async def test_given_reply_dialog_when_settings_break_a_rule_then_dialog_shows_why_and_stays(
    database: Database, services: Settings
) -> None:
    """Given the reply dialog, when the status is not a number or a header is banned, then the error shows."""
    # Given
    inspector, _ = await open_bin(database, services)
    await inspector.open_reply()
    # When
    inspector.set_reply_status("abc")
    not_number = (await inspector.save_reply(), inspector.reply_error)
    inspector.set_reply_status("200")
    inspector.add_reply_header()
    inspector.set_reply_header_name(0, "Set-Cookie")
    banned = (await inspector.save_reply(), inspector.reply_error)
    inspector.default_reply()
    # Then
    assert not_number == (None, "The status and the delay must be whole numbers.")
    assert banned == (None, "A reply may not set Set-Cookie.")
    assert inspector.reply_open
    assert (inspector.reply, inspector.reply_error) == (ReplyForm(), "")
    inspector.set_reply_open(False)
    assert not inspector.reply_open


@pytest.mark.anyio
async def test_given_bin_gone_when_reply_dialog_opens_or_saves_then_page_shows_it_deleted(
    database: Database, services: Settings
) -> None:
    """Given a bin deleted elsewhere, when the dialog opens or saves, then the page shows the bin as deleted."""
    # Given
    inspector, _ = await open_bin(database, services)
    bin_id = inspector.export_url.split("/")[-2]
    await runtime.bin_service.delete(bin_id)
    # When
    saved = await inspector.save_reply()
    after_save = (inspector.found, inspector.deleted)
    await inspector.open_reply()
    # Then
    assert saved is None
    assert after_save == (False, True)
    assert not inspector.reply_open
    assert "gone" in args_text(await inspector._clear())  # noqa: SLF001  # pylint: disable=protected-access


@pytest.mark.anyio
async def test_given_local_replay_when_user_sends_then_result_shows(
    database: Database, monkeypatch: pytest.MonkeyPatch, services: Settings, echo_server: EchoServer
) -> None:
    """Given `local` replay mode, when the user replays to an echo server, then the tab shows its reply."""
    # Given
    settings = replace(services, replay_mode=ReplayMode.LOCAL)
    monkeypatch.setattr(runtime, "settings", settings)
    monkeypatch.setattr(runtime, "replay_service", ReplayService(RequestService(database), settings))
    inspector, _ = await open_bin(database, settings, INCOMING)
    inspector.set_replay_target(f"{echo_server.url}/hook")
    inspector.set_replay_keep_query(False)
    # When
    steps = [step async for step in inspector.send_replay()]
    # Then
    assert inspector.replay_local
    assert len(steps) == 1
    assert (inspector.replay_result.status, inspector.replay_result.body_kind) == (201, "json")
    assert (inspector.replaying, inspector.replay_error) == (False, "")
    assert echo_server.received[0].path == "/hook"


@pytest.mark.anyio
async def test_given_restricted_replay_when_user_sends_to_loopback_then_error_shows(
    database: Database, services: Settings, echo_server: EchoServer
) -> None:
    """Given `restricted` mode, when the user replays to 127.0.0.1, then the tab shows that the address is refused."""
    # Given
    inspector, _ = await open_bin(database, services, INCOMING)
    inspector.set_replay_target(f"{echo_server.url}/hook")
    # When
    _ = [step async for step in inspector.send_replay()]
    # Then
    assert not inspector.replay_local
    assert inspector.replay_error == "Target address not allowed."
    assert inspector.replay_result == ReplayView()
    assert echo_server.received == []


@pytest.mark.anyio
async def test_given_remembered_bins_when_one_is_gone_then_home_forgets_it(
    database: Database, services: Settings
) -> None:
    """Given two remembered bins, one deleted, when the home page loads, then only the other is listed and kept."""
    # Given
    bins = BinService(database, services)
    kept = await bins.create("kept")
    gone = await bins.create("gone")
    await bins.delete(gone.id)
    home = make_state(HomeState)
    home.known_bins = json.dumps([gone.id, kept.id])
    # When
    await home.load()
    # Then
    assert [row.id for row in home.bins] == [kept.id]
    assert json.loads(home.known_bins) == [kept.id]
    assert home.bins[0].expires_at == kept.expires_at.isoformat()
