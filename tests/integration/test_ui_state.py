"""Tests for the home and inspector state handlers, on SQLite and PostgreSQL."""

# Fixtures take other fixtures as arguments of the same name.
# pylint: disable=redefined-outer-name

import json
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest
from reflex.istate.data import RouterData

from reflex_fastapi_webhook_studio import runtime
from reflex_fastapi_webhook_studio.domain import BinEvent, BinListing, EventType, HttpMethod, IncomingRequest
from reflex_fastapi_webhook_studio.services.bins import BinService
from reflex_fastapi_webhook_studio.services.capture import CaptureService
from reflex_fastapi_webhook_studio.services.requests import RequestService
from reflex_fastapi_webhook_studio.settings import Settings
from reflex_fastapi_webhook_studio.ui.state.home import HomeState
from reflex_fastapi_webhook_studio.ui.state.inspector import InspectorState
from reflex_fastapi_webhook_studio.ui.views import RequestView

if TYPE_CHECKING:
    from reflex.state import BaseState
    from reflex_base.event import EventSpec

    from reflex_fastapi_webhook_studio.db.engine import Database

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
    # When
    await home.load()
    # Then
    assert not home.listing_all
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
    # When
    await inspector.load()
    # Then
    assert (inspector.found, inspector.label, inspector.live) == (True, "orders", False)
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
    """Given an empty open inspector, when bin events arrive, then requests join once, the label and resync follow."""
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
    await apply(BinEvent(type=EventType.BIN_UPDATED, bin_id=bin_.id, label=None))
    labelled = inspector.label
    await runtime.bin_service.rename(bin_.id, "renamed")
    await apply(BinEvent(type=EventType.RESYNC, bin_id=bin_.id))
    # Then
    assert [row.id for row in inspector.requests] == [str(stored.id)]
    assert inspector.detail.id == str(stored.id)
    assert (labelled, inspector.label) == ("No label", "renamed")
