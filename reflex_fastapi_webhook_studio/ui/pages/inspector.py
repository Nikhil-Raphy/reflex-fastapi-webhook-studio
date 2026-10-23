"""The inspector page: a bin's requests on the left, the one picked in tabs on the right."""

from typing import Any, cast

import reflex as rx
from reflex_base.vars.base import Var
from reflex_base.vars.object import ObjectVar
from reflex_base.vars.sequence import ArrayVar
from reflex_components_lucide.icon import Icon
from reflex_components_moment.moment import Moment

from reflex_fastapi_webhook_studio.security.masking import MASK
from reflex_fastapi_webhook_studio.ui.components.common import bind, method_badge, status_dot, top_bar
from reflex_fastapi_webhook_studio.ui.state.inspector import InspectorState
from reflex_fastapi_webhook_studio.ui.views import PairView, RequestRowView, RequestView

# Reflex's type hints read a dataclass field as an array; it is an object.
_detail = cast(ObjectVar[RequestView], InspectorState.detail)  # noqa: TC006  # pylint reads a quoted type as unused.


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


def _body() -> rx.Component:
    return rx.box(
        rx.match(
            _detail.body_kind,
            ("empty", rx.text("No body.", color_scheme="gray")),
            ("truncated", rx.text("The body was over the size cap, so it was not kept.", color_scheme="gray")),
            ("json", rx.code_block(_detail.body_text, language="json", wrap_long_lines=True, width="100%")),
            ("form", _pairs_table(_detail.form_fields.to(list[PairView]))),
            (
                "binary",
                rx.hstack(
                    rx.text("Binary body, ", _detail.body_size, " bytes."),
                    rx.button(
                        Icon.create("download", size=16),
                        "Download",
                        on_click=InspectorState.download_body,
                        variant="soft",
                        size="1",
                    ),
                    align="center",
                ),
            ),
            rx.text(_detail.body_text, white_space="pre-wrap", font_family="var(--code-font-family)", size="2"),
        ),
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
            default_value="overview",
            width="100%",
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
            align="center",
            wrap="wrap",
        ),
        rx.cond(
            InspectorState.requests.length() > 0,
            rx.grid(
                rx.scroll_area(
                    rx.vstack(rx.foreach(InspectorState.requests, _request_row), spacing="1", width="100%"),
                    type="auto",
                    max_height="80vh",
                ),
                _detail_panel(),
                columns="minmax(16rem, 1fr) 2fr",
                spacing="4",
                width="100%",
            ),
            _empty_state(),
        ),
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
                rx.callout("No bin has this id.", icon="triangle_alert", color_scheme="red"),
                rx.link("Back to the home page", href="/"),
            ),
        ),
        padding="1rem 1.5rem",
        width="100%",
    )
