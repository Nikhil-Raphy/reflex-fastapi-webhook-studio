"""Tests for the records that UI state holds and the parsing of what users type."""

import json
from dataclasses import replace

import pytest

from reflex_fastapi_webhook_studio.domain import BinSummary, ReplayResult, ReplyConfig, RequestSummary
from reflex_fastapi_webhook_studio.ui.views import (
    REPLAY_SHOWN_BYTES,
    PairView,
    ReplyForm,
    bin_row,
    body_view,
    capture_url,
    curl_example,
    forget,
    known_ids,
    parse_bin_id,
    remember,
    replay_view,
    reply_config,
    reply_form,
    request_row,
    request_view,
)
from tests.factories import NOW, make_request

BIN_ID = "AbCdEfGhIjKlMnOpQrStUv"
OTHER_ID = "ZyXwVuTsRqPoNmLkJiHgFe"


@pytest.mark.parametrize(
    ("body", "content_type", "kind", "text"),
    [
        (b'{"a":[1,2]}', "application/json", "json", '{\n  "a": [\n    1,\n    2\n  ]\n}'),
        (b'  [{"x": "\xc3\xa9"}]', None, "json", '[\n  {\n    "x": "\u00e9"\n  }\n]'),
        (b"{not json", "application/json", "text", "{not json"),
        (b"hello\nworld", "text/plain", "text", "hello\nworld"),
        (b"<b>hi</b>", "text/html", "text", "<b>hi</b>"),
        (b"", "application/json", "empty", ""),
        (b"\xff\xfe\x00", "application/octet-stream", "binary", ""),
    ],
)
def test_given_body_when_viewed_then_kind_and_text_fit_it(
    body: bytes, content_type: str | None, kind: str, text: str
) -> None:
    """Given a body and its content type, when viewed, then the kind and text suit it, and HTML stays plain text."""
    # Given
    raw = body
    # When
    result = body_view(raw, content_type, truncated=False)
    # Then
    assert result == (kind, text, [])


def test_given_form_body_when_viewed_then_fields_keep_order_and_blanks() -> None:
    """Given a form body, when viewed, then its fields keep their order and blank values."""
    # Given
    body = b"name=Ada&lang=python&empty=&name=Bob"
    # When
    kind, _, fields = body_view(body, "application/x-www-form-urlencoded; charset=utf-8", truncated=False)
    # Then
    assert kind == "form"
    assert [(field.name, field.value) for field in fields] == [
        ("name", "Ada"),
        ("lang", "python"),
        ("empty", ""),
        ("name", "Bob"),
    ]


def test_given_truncated_body_when_viewed_then_it_says_so() -> None:
    """Given a body that was over the cap, when viewed, then the kind says it was not kept."""
    # Given
    body = b""
    # When
    result = body_view(body, "application/json", truncated=True)
    # Then
    assert result == ("truncated", "", [])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (BIN_ID, BIN_ID),
        (f"  {BIN_ID}\n", BIN_ID),
        (f"http://localhost:17301/api/webhook/{BIN_ID}", BIN_ID),
        (f"https://host/api/webhook/{BIN_ID}/github?x=1", BIN_ID),
        (f"http://localhost:17300/bins/{BIN_ID}", BIN_ID),
        (f"http://localhost:17300/bins/{BIN_ID}#top", BIN_ID),
        ("short", None),
        (f"https://host/other/{BIN_ID}", None),
        (f"https://host/api/webhook/{BIN_ID}x", None),
        ("", None),
    ],
)
def test_given_typed_text_when_parsed_then_bin_id_is_found_or_not(text: str, expected: str | None) -> None:
    """Given text a user typed, when parsed, then a bin id is found in an id, capture URL or inspector URL."""
    # Given
    typed = text
    # When
    found = parse_bin_id(typed)
    # Then
    assert found == expected


def test_given_api_url_when_capture_url_is_built_then_it_points_at_the_bin() -> None:
    """Given the backend address, when the capture URL and curl example are built, then both point at the bin."""
    # Given
    api_url = "http://localhost:17301/"
    # When
    url = capture_url(api_url, BIN_ID)
    command = curl_example(url)
    # Then
    assert url == f"http://localhost:17301/api/webhook/{BIN_ID}"
    assert command.startswith(f"curl -X POST {url} ")
    assert "application/json" in command


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (json.dumps([BIN_ID, "bad", 7, OTHER_ID]), [BIN_ID, OTHER_ID]),
        ("not json", []),
        ('{"a": 1}', []),
        ("[]", []),
    ],
)
def test_given_stored_list_when_read_then_only_good_ids_return(stored: str, expected: list[str]) -> None:
    """Given the value in local storage, when read, then only well-formed ids return, and bad values give none."""
    # Given
    value = stored
    # When
    ids = known_ids(value)
    # Then
    assert ids == expected


def test_given_known_ids_when_bin_is_remembered_then_it_goes_first_once_within_limit() -> None:
    """Given remembered ids, when a bin is remembered again, then it moves to the front once and the limit holds."""
    # Given
    stored = json.dumps([OTHER_ID, BIN_ID])
    # When
    again = remember(stored, BIN_ID, limit=5)
    capped = remember(stored, "QqQqQqQqQqQqQqQqQqQqQq", limit=2)
    # Then
    assert json.loads(again) == [BIN_ID, OTHER_ID]
    assert json.loads(capped) == ["QqQqQqQqQqQqQqQqQqQqQq", OTHER_ID]


def test_given_summaries_when_rows_are_built_then_they_hold_display_values() -> None:
    """Given bin and request summaries, when rows are built, then they hold the link, short id, label and target."""
    # Given
    bin_summary = BinSummary(
        id=BIN_ID, label=None, created_at=NOW, last_activity_at=NOW, expires_at=NOW, request_count=3
    )
    request = make_request(BIN_ID)
    summary = RequestSummary(
        id=request.id,
        received_at=NOW,
        method=request.method,
        path="/a",
        query_string="",
        body_size=0,
        body_truncated=False,
        content_type=None,
        reply_status=200,
    )
    # When
    bin_view = bin_row(bin_summary)
    plain = request_row(summary)
    queried = request_row(replace(summary, query_string="x=1"))
    # Then
    assert (bin_view.href, bin_view.short_id, bin_view.label, bin_view.request_count) == (
        f"/bins/{BIN_ID}",
        "AbCdEf\u2026",
        "No label",
        3,
    )
    assert bin_view.last_activity_at == NOW.isoformat()
    assert (plain.target, queried.target, plain.method) == ("/a", "/a?x=1", "POST")


def test_given_request_with_secret_header_when_viewed_then_only_that_header_is_masked() -> None:
    """Given a request with an Authorization header, when viewed, then that header alone is marked secret."""
    # Given
    request = replace(
        make_request(BIN_ID),
        headers=(("content-type", "application/json"), ("Authorization", "Bearer x")),
    )
    # When
    view = request_view(request)
    # Then
    assert view.headers == [
        PairView(index=0, name="content-type", value="application/json", secret=False),
        PairView(index=1, name="Authorization", value="Bearer x", secret=True),
    ]
    assert [(pair.name, pair.value) for pair in view.query_params] == [("x", "1"), ("x", "2")]
    assert (view.target, view.body_kind, view.content_type) == ("/github?x=1&x=2", "json", "application/json")


def test_given_known_ids_when_some_are_forgotten_then_the_rest_keep_their_order() -> None:
    """Given remembered ids, when some are forgotten, then the rest stay in order."""
    # Given
    stored = json.dumps([BIN_ID, "bad", OTHER_ID])
    # When
    kept = forget(stored, {BIN_ID})
    # Then
    assert json.loads(kept) == [OTHER_ID]


def make_result(body: bytes, content_type: str = "application/json", *, truncated: bool = False) -> ReplayResult:
    """Build a replay result.

    Args:
        body: The reply body.
        content_type: The reply content type.
        truncated: Whether the read stopped at the cap.

    Returns:
        The result.
    """
    return ReplayResult(
        status=201,
        reason="Created",
        elapsed_ms=12,
        headers=(("Content-Type", content_type), ("X-Echo", "yes")),
        body=body,
        body_truncated=truncated,
    )


@pytest.mark.parametrize(
    ("result", "kind", "text", "cut"),
    [
        (make_result(b'{"a":1}'), "json", '{\n  "a": 1\n}', False),
        (make_result(b"a=1&b=2", "application/x-www-form-urlencoded"), "text", "a=1&b=2", False),
        (make_result(b"\xff\xfe", "application/octet-stream"), "binary", "", False),
        (make_result(b""), "empty", "", False),
        (make_result(b"a" * (REPLAY_SHOWN_BYTES - 1) + "é".encode(), "text/plain"), "text", "a" * 65535, True),
        (make_result(b"ok", "text/plain", truncated=True), "text", "ok", True),
    ],
)
def test_given_replay_result_when_viewed_then_body_shows_as_text_json_or_binary(
    result: ReplayResult,
    kind: str,
    text: str,
    cut: bool,  # noqa: FBT001
) -> None:
    """Given a replay result, when viewed, then the body shows by kind, and a cut keeps whole characters."""
    # Given
    replayed = result
    # When
    view = replay_view(replayed)
    # Then
    assert (view.body_kind, view.body_text, view.body_cut) == (kind, text, cut)
    assert (view.status, view.reason, view.elapsed_ms, view.body_size) == (201, "Created", 12, len(replayed.body))
    assert [(pair.name, pair.value) for pair in view.headers][1] == ("X-Echo", "yes")


def test_given_reply_settings_when_shown_and_read_back_then_they_round_trip() -> None:
    """Given a bin's reply settings, when the dialog is filled and read back, then the settings are the same."""
    # Given
    reply = ReplyConfig(status=418, content_type="text/plain", headers=(("X-Tea", "yes"),), body="short", delay_ms=250)
    # When
    form = reply_form(reply)
    with_blank_row = replace(form, headers=[*form.headers, PairView(index=1, name="  ", value="x")])
    # Then
    assert (form.status, form.custom_body, form.delay_ms) == ("418", True, "250")
    assert reply_config(with_blank_row) == reply
    assert reply_config(ReplyForm()) == ReplyConfig()


@pytest.mark.parametrize(("status", "delay"), [("abc", "0"), ("200", "-5"), ("", "0")])
def test_given_non_numbers_when_reply_is_read_then_a_message_comes_back(status: str, delay: str) -> None:
    """Given a status or delay that is not a whole number, when the dialog is read, then it says so."""
    # Given
    form = ReplyForm(status=status, delay_ms=delay)
    # When
    result = reply_config(form)
    # Then
    assert result == "The status and the delay must be whole numbers."
