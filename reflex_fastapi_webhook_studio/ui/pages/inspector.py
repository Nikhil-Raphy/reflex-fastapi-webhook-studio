"""The inspector page: a bin's requests on the left, the one picked in tabs on the right."""

from typing import Any, cast

import reflex as rx
from reflex_base.vars.base import Var
from reflex_base.vars.object import ObjectVar
from reflex_base.vars.sequence import ArrayVar
from reflex_components_lucide.icon import Icon
from reflex_components_moment.moment import Moment

from reflex_fastapi_webhook_studio.domain import MAX_SEARCH_LENGTH, HttpMethod
from reflex_fastapi_webhook_studio.security.masking import MASK
from reflex_fastapi_webhook_studio.ui.components.common import bind, method_badge, status_dot, top_bar
from reflex_fastapi_webhook_studio.ui.components.sentinel import visibility_sentinel
from reflex_fastapi_webhook_studio.ui.state.inspector import ALL_METHODS, InspectorState
from reflex_fastapi_webhook_studio.ui.views import PairView, ReplayView, ReplyForm, RequestRowView, RequestView

# Reflex's type hints read a dataclass field as an array; it is an object.
_detail = cast(ObjectVar[RequestView], InspectorState.detail)  # noqa: TC006  # pylint reads a quoted type as unused.
_reply = cast(ObjectVar[ReplyForm], InspectorState.reply)  # noqa: TC006  # pylint reads a quoted type as unused.
_replay = cast(ObjectVar[ReplayView], InspectorState.replay_result)  # noqa: TC006  # pylint reads a quoted type as unused.


def _request_row(row: ObjectVar[RequestRowView]) -> rx.Component:
    picked = _detail.id == row.id
    return rx.hstack(
        method_badge(row.method),
        rx.text(row.target, trim="both", truncate=True, flex="1"),
        rx.text(Moment.create(row.received_at, from_now=True), size="1", color_scheme="gray", white_space="nowrap"),
        on_click=bind(InspectorState.select, row.id),
        background=rx.match(picked, (True, "var(--accent-a4)"), "transparent"),
        border_radius="var(--radius-2)",
        cursor="pointer",
        padding="2",
        width="100%",
        align="center",
        custom_attrs={"data-testid": "request-row"},
    )


def _pairs_table(rows: ArrayVar[list[Any]]) -> rx.Component:
    def row(pair: ObjectVar[PairView]) -> rx.Component:
        return rx.table.row(
            rx.table.row_header_cell(rx.code(pair.name, variant="ghost")),
            rx.table.cell(rx.text(pair.value, white_space="pre-wrap")),
        )

    return rx.cond(
        rows.length() > 0,
        rx.table.root(rx.table.body(rx.foreach(rows, row)), size="1", width="100%"),
        rx.text("None.", color_scheme="gray"),
    )


def _header_row(pair: ObjectVar[PairView]) -> rx.Component:
    shown = ~pair.secret | InspectorState.revealed.contains(pair.index)
    return rx.table.row(
        rx.table.row_header_cell(rx.code(pair.name, variant="ghost")),
        rx.table.cell(
            rx.cond(
                shown,
                rx.text(pair.value, white_space="pre-wrap", word_break="break-all"),
                rx.tooltip(
                    rx.button(
                        MASK,
                        on_click=bind(InspectorState.reveal, pair.index),
                        variant="ghost",
                        size="1",
                        custom_attrs={"data-testid": "masked-header"},
                    ),
                    content="Click to show",
                ),
            )
        ),
    )


def _overview() -> rx.Component:
    def line(name: str, value: Var[Any] | rx.Component) -> rx.Component:
        return rx.table.row(rx.table.row_header_cell(name), rx.table.cell(value))

    return rx.table.root(
        rx.table.body(
            line("Request id", rx.code(_detail.id, variant="ghost")),
            line("Received", _detail.received_at),
            line("Method", method_badge(_detail.method)),
            line("Path", rx.code(_detail.path, variant="ghost")),
            line("Query string", rx.code(_detail.query_string, variant="ghost")),
            line("Content type", _detail.content_type),
            line("Body size", rx.text(_detail.body_size, " bytes")),
            line("From", _detail.remote_addr),
            line("HTTP version", _detail.http_version),
            line("Reply status", _detail.reply_status),
        ),
        size="1",
        width="100%",
    )


def _body_content(
    kind: Var[str], text: Var[str], size: Var[int], form: rx.Component, binary_extra: rx.Component
) -> rx.Component:
    return rx.box(
        rx.match(
            kind,
            ("empty", rx.text("No body.", color_scheme="gray")),
            ("truncated", rx.text("The body was over the size cap, so it was not kept.", color_scheme="gray")),
            ("json", rx.code_block(text, language="json", wrap_long_lines=True, width="100%")),
            ("form", form),
            ("binary", rx.hstack(rx.text("Binary body, ", size, " bytes."), binary_extra, align="center")),
            rx.text(text, white_space="pre-wrap", font_family="var(--code-font-family)", size="2"),
        ),
        width="100%",
    )


def _body() -> rx.Component:
    download = rx.button(
        Icon.create("download", size=16), "Download", on_click=InspectorState.download_body, variant="soft", size="1"
    )
    return rx.box(
        _body_content(
            _detail.body_kind,
            _detail.body_text,
            _detail.body_size,
            _pairs_table(_detail.form_fields.to(list[PairView])),
            download,
        ),
        width="100%",
    )


def _replay_result() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.badge(_replay.status, " ", _replay.reason, size="2", custom_attrs={"data-testid": "replay-status"}),
            rx.text(_replay.elapsed_ms, " ms · ", _replay.body_size, " bytes", size="1", color_scheme="gray"),
            align="center",
        ),
        rx.table.root(
            rx.table.body(
                rx.foreach(
                    _replay.headers.to(list[PairView]),
                    lambda pair: rx.table.row(
                        rx.table.row_header_cell(rx.code(pair.name, variant="ghost")),
                        rx.table.cell(rx.text(pair.value, white_space="pre-wrap", word_break="break-all")),
                    ),
                )
            ),
            size="1",
            width="100%",
        ),
        rx.cond(_replay.body_cut, rx.text("Showing the first 64 KiB of the body.", size="1", color_scheme="gray")),
        _body_content(_replay.body_kind, _replay.body_text, _replay.body_size, rx.fragment(), rx.fragment()),
        width="100%",
        custom_attrs={"data-testid": "replay-result"},
    )


def _replay_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            InspectorState.replay_local,
            rx.text("Replays may reach any address, including this machine.", size="1", color_scheme="gray"),
            rx.text("Replays may reach public internet addresses only.", size="1", color_scheme="gray"),
        ),
        rx.hstack(
            rx.input(
                placeholder="https://example.com/hook",
                value=InspectorState.replay_target,
                on_change=InspectorState.set_replay_target,
                width="100%",
                custom_attrs={"data-testid": "replay-target"},
            ),
            rx.button(
                Icon.create("send", size=16),
                "Send",
                on_click=InspectorState.send_replay,
                loading=InspectorState.replaying,
                custom_attrs={"data-testid": "replay-send"},
            ),
            width="100%",
        ),
        rx.text(
            rx.switch(
                checked=InspectorState.replay_keep_query,
                on_change=InspectorState.set_replay_keep_query,
                size="1",
                margin_right="0.5rem",
            ),
            "Use original query string",
            as_="label",
            size="2",
        ),
        rx.cond(
            InspectorState.replay_error != "",
            rx.callout(InspectorState.replay_error, icon="triangle_alert", color_scheme="red", size="1"),
        ),
        rx.cond(_replay.status.to(int) > 0, _replay_result()),
        width="100%",
    )


def _detail_panel() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            method_badge(_detail.method),
            rx.code(_detail.target, variant="ghost"),
            rx.text("·"),
            Moment.create(_detail.received_at, from_now=True),
            rx.text("· ", _detail.body_size, " bytes · reply ", _detail.reply_status, color_scheme="gray"),
            align="center",
            wrap="wrap",
        ),
        rx.tabs.root(
            rx.tabs.list(
                rx.tabs.trigger("Overview", value="overview"),
                rx.tabs.trigger("Headers", value="headers", custom_attrs={"data-testid": "headers-tab"}),
                rx.tabs.trigger("Query", value="query"),
                rx.tabs.trigger("Body", value="body", custom_attrs={"data-testid": "body-tab"}),
                rx.tabs.trigger("Replay", value="replay", custom_attrs={"data-testid": "replay-tab"}),
            ),
            rx.tabs.content(_overview(), value="overview", padding_top="3"),
            rx.tabs.content(
                rx.table.root(
                    rx.table.body(rx.foreach(_detail.headers.to(list[PairView]), _header_row)), size="1", width="100%"
                ),
                value="headers",
                padding_top="3",
            ),
            rx.tabs.content(
                rx.vstack(
                    rx.code(_detail.query_string, variant="ghost"),
                    _pairs_table(_detail.query_params.to(list[PairView])),
                    width="100%",
                ),
                value="query",
                padding_top="3",
            ),
            rx.tabs.content(_body(), value="body", padding_top="3", custom_attrs={"data-testid": "body"}),
            rx.tabs.content(_replay_tab(), value="replay", padding_top="3"),
            default_value="overview",
            width="100%",
        ),
        rx.hstack(
            rx.button(
                Icon.create("terminal", size=16),
                "Copy as curl",
                on_click=InspectorState.copy_as_curl,
                variant="soft",
                size="1",
                custom_attrs={"data-testid": "copy-as-curl"},
            ),
            rx.button(
                Icon.create("trash-2", size=16),
                "Delete request",
                on_click=InspectorState.ask_delete_request,
                color_scheme="red",
                variant="soft",
                size="1",
                custom_attrs={"data-testid": "delete-request"},
            ),
            spacing="2",
        ),
        width="100%",
        min_width="0",
    )


def _empty_state() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Waiting for requests…", size="4"),
            rx.text("Send a request to the bin URL, for example:"),
            rx.code_block(InspectorState.curl_command, language="bash", wrap_long_lines=True, width="100%"),
            rx.button(Icon.create("copy", size=16), "Copy command", on_click=InspectorState.copy_curl, variant="soft"),
            width="100%",
        ),
        width="100%",
        custom_attrs={"data-testid": "empty-state"},
    )


def _filters() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.select.root(
                rx.select.trigger(custom_attrs={"data-testid": "method-filter"}),
                rx.select.content(
                    rx.select.item("All methods", value=ALL_METHODS),
                    *(rx.select.item(method.value, value=method.value) for method in HttpMethod),
                ),
                value=InspectorState.method_filter,
                on_change=InspectorState.set_method_filter,
                size="2",
            ),
            rx.input(
                rx.input.slot(Icon.create("search", size=16)),
                placeholder="Search",
                value=InspectorState.search,
                on_change=InspectorState.set_search,
                max_length=MAX_SEARCH_LENGTH,
                width="100%",
                custom_attrs={"data-testid": "search"},
            ),
            width="100%",
        ),
        rx.hstack(
            rx.text(
                InspectorState.total,
                rx.cond(InspectorState.filtered, rx.text.span(" matching"), rx.text.span(" requests")),
                rx.cond(InspectorState.has_older, rx.text.span(" · showing ", InspectorState.requests.length())),
                size="1",
                color_scheme="gray",
                custom_attrs={"data-testid": "request-count"},
            ),
            rx.spacer(),
            rx.cond(
                InspectorState.filtered,
                rx.button("Clear filters", on_click=InspectorState.clear_filters, variant="ghost", size="1"),
            ),
            width="100%",
            align="center",
        ),
        width="100%",
        spacing="2",
    )


def _request_list() -> rx.Component:
    return rx.vstack(
        _filters(),
        rx.cond(
            InspectorState.requests.length() > 0,
            rx.scroll_area(
                rx.vstack(
                    rx.foreach(InspectorState.requests, _request_row),
                    rx.cond(
                        InspectorState.has_older,
                        rx.vstack(
                            visibility_sentinel(
                                on_visible=InspectorState.load_older, key=InspectorState.requests.length()
                            ),
                            rx.button(
                                "Load older",
                                on_click=InspectorState.load_older,
                                variant="ghost",
                                size="1",
                                width="100%",
                                custom_attrs={"data-testid": "load-older"},
                            ),
                            width="100%",
                        ),
                    ),
                    spacing="1",
                    width="100%",
                ),
                type="auto",
                max_height="75vh",
            ),
            rx.text("No requests match.", color_scheme="gray", size="2"),
        ),
        width="100%",
        min_width="0",
    )


def _bin_actions() -> rx.Component:
    return rx.hstack(
        rx.button(
            Icon.create("reply", size=16),
            "Reply settings",
            on_click=InspectorState.open_reply,
            variant="soft",
            size="1",
            custom_attrs={"data-testid": "reply-settings"},
        ),
        rx.button(
            Icon.create("file-down", size=16),
            "Export",
            on_click=InspectorState.export,
            variant="soft",
            size="1",
            custom_attrs={"data-testid": "export"},
        ),
        rx.button(
            Icon.create("eraser", size=16),
            "Clear",
            on_click=InspectorState.ask_clear,
            color_scheme="red",
            variant="soft",
            size="1",
            custom_attrs={"data-testid": "clear-bin"},
        ),
        rx.button(
            Icon.create("trash-2", size=16),
            "Delete bin",
            on_click=InspectorState.ask_delete_bin,
            color_scheme="red",
            variant="soft",
            size="1",
            custom_attrs={"data-testid": "delete-bin"},
        ),
        spacing="2",
        wrap="wrap",
    )


def _confirm_dialog() -> rx.Component:
    def wording(title: str, text: str, action: str) -> rx.Component:
        return rx.fragment(
            rx.alert_dialog.title(title),
            rx.alert_dialog.description(text, size="2"),
            rx.hstack(
                rx.checkbox(
                    "Don't ask again",
                    checked=InspectorState.dont_ask,
                    on_change=InspectorState.set_dont_ask,
                    size="2",
                    custom_attrs={"data-testid": "dont-ask"},
                ),
                rx.spacer(),
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(
                    rx.button(
                        action,
                        on_click=InspectorState.confirm,
                        color_scheme="red",
                        custom_attrs={"data-testid": "confirm-delete"},
                    )
                ),
                margin_top="1rem",
                align="center",
                width="100%",
            ),
        )

    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.match(
                InspectorState.confirming,
                ("request", wording("Delete this request?", "It is gone for good, in every open tab.", "Delete")),
                (
                    "clear",
                    wording(
                        "Delete every request in this bin?",
                        "The bin keeps its URL and reply settings.",
                        "Clear",
                    ),
                ),
                wording("Delete this bin?", "Its URL stops working, and every request in it is gone.", "Delete bin"),
            ),
            max_width="28rem",
        ),
        open=InspectorState.confirming != "",
        on_open_change=InspectorState.set_confirm_open,
    )


def _reply_header_row(pair: ObjectVar[PairView]) -> rx.Component:
    return rx.hstack(
        rx.input(
            placeholder="Name",
            value=pair.name,
            on_change=lambda value: bind(InspectorState.set_reply_header_name, pair.index, value),
            width="40%",
        ),
        rx.input(
            placeholder="Value",
            value=pair.value,
            on_change=lambda value: bind(InspectorState.set_reply_header_value, pair.index, value),
            width="100%",
        ),
        rx.icon_button(
            Icon.create("x", size=16),
            on_click=bind(InspectorState.remove_reply_header, pair.index),
            variant="ghost",
            color_scheme="gray",
            aria_label="Remove header",
        ),
        width="100%",
        align="center",
    )


def _reply_dialog() -> rx.Component:
    def field(label: str, control: rx.Component) -> rx.Component:
        return rx.vstack(rx.text(label, size="2", weight="medium"), control, spacing="1", width="100%")

    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Reply settings"),
            rx.dialog.description("What this bin sends back to each sender.", size="2"),
            rx.vstack(
                rx.hstack(
                    field(
                        "Status",
                        rx.input(
                            value=_reply.status,
                            on_change=InspectorState.set_reply_status,
                            type="number",
                            custom_attrs={"data-testid": "reply-status"},
                        ),
                    ),
                    field(
                        "Delay (ms)",
                        rx.input(value=_reply.delay_ms, on_change=InspectorState.set_reply_delay, type="number"),
                    ),
                    width="100%",
                ),
                field(
                    "Content type",
                    rx.input(
                        placeholder="application/json",
                        value=_reply.content_type,
                        on_change=InspectorState.set_reply_content_type,
                    ),
                ),
                field(
                    "Headers",
                    rx.vstack(
                        rx.foreach(_reply.headers.to(list[PairView]), _reply_header_row),
                        rx.button(
                            Icon.create("plus", size=16),
                            "Add header",
                            on_click=InspectorState.add_reply_header,
                            variant="ghost",
                            size="1",
                        ),
                        width="100%",
                        spacing="1",
                    ),
                ),
                rx.text(
                    rx.switch(
                        checked=_reply.custom_body,
                        on_change=InspectorState.set_reply_custom_body,
                        size="1",
                        margin_right="0.5rem",
                    ),
                    "Custom body",
                    as_="label",
                    size="2",
                ),
                rx.cond(
                    _reply.custom_body,
                    rx.text_area(
                        value=_reply.body,
                        on_change=InspectorState.set_reply_body,
                        rows="6",
                        width="100%",
                        font_family="var(--code-font-family)",
                        custom_attrs={"data-testid": "reply-body"},
                    ),
                    rx.text('Sends {"ok": true, "request_id": "…"} as JSON.', size="1", color_scheme="gray"),
                ),
                rx.cond(
                    InspectorState.reply_error != "",
                    rx.callout(InspectorState.reply_error, icon="triangle_alert", color_scheme="red", size="1"),
                ),
                rx.hstack(
                    rx.button("Use default", on_click=InspectorState.default_reply, variant="ghost"),
                    rx.spacer(),
                    rx.dialog.close(rx.button("Cancel", variant="soft", color_scheme="gray")),
                    rx.button("Save", on_click=InspectorState.save_reply, custom_attrs={"data-testid": "reply-save"}),
                    width="100%",
                ),
                spacing="3",
                width="100%",
                margin_top="1rem",
            ),
            max_width="36rem",
        ),
        open=InspectorState.reply_open,
        on_open_change=InspectorState.set_reply_open,
    )


def _bin_view() -> rx.Component:
    return rx.vstack(
        top_bar(
            rx.text("▸"),
            rx.text(InspectorState.label, weight="medium"),
            rx.spacer(),
            status_dot(InspectorState.live),
        ),
        rx.hstack(
            rx.code(InspectorState.capture_url, custom_attrs={"data-testid": "capture-url"}),
            rx.button(
                Icon.create("copy", size=16), "Copy URL", on_click=InspectorState.copy_url, variant="soft", size="1"
            ),
            rx.text("Expires ", Moment.create(InspectorState.expires_at, from_now=True), size="1", color_scheme="gray"),
            align="center",
            wrap="wrap",
        ),
        _bin_actions(),
        rx.cond(
            (InspectorState.requests.length() > 0) | InspectorState.filtered,
            rx.grid(
                _request_list(),
                rx.cond(
                    _detail.id != "",
                    _detail_panel(),
                    rx.text("Pick a request to see it here.", color_scheme="gray"),
                ),
                columns="minmax(16rem, 1fr) 2fr",
                spacing="4",
                width="100%",
            ),
            _empty_state(),
        ),
        _confirm_dialog(),
        _reply_dialog(),
        spacing="4",
        width="100%",
    )


def inspector() -> rx.Component:
    """Build the inspector page.

    Returns:
        The page.
    """
    return rx.box(
        rx.cond(
            InspectorState.found,
            _bin_view(),
            rx.vstack(
                top_bar(),
                rx.cond(
                    InspectorState.deleted,
                    rx.callout("This bin was deleted.", icon="info", color_scheme="gray"),
                    rx.callout("No bin has this id.", icon="triangle_alert", color_scheme="red"),
                ),
                rx.link("Back to the home page", href="/"),
            ),
        ),
        padding="1rem 1.5rem",
        width="100%",
    )
