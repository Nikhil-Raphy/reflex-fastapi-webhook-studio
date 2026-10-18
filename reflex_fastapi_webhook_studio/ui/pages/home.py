"""The home page: make a bin, open one, and list bins."""

import reflex as rx
from reflex_base.vars.object import ObjectVar
from reflex_components_moment.moment import Moment

from reflex_fastapi_webhook_studio.domain import MAX_LABEL_LENGTH
from reflex_fastapi_webhook_studio.ui.components.common import top_bar
from reflex_fastapi_webhook_studio.ui.state.home import HomeState
from reflex_fastapi_webhook_studio.ui.views import BinRowView


def _bin_row(row: ObjectVar[BinRowView]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.link(row.label, href=row.href)),
        rx.table.cell(rx.code(row.short_id)),
        rx.table.cell(row.request_count),
        rx.table.cell(Moment.create(row.last_activity_at, from_now=True)),
        custom_attrs={"data-testid": "bin-row"},
    )


def home() -> rx.Component:
    """Build the home page.

    Returns:
        The page.
    """
    return rx.container(
        rx.vstack(
            top_bar(),
            rx.text("Make a bin, send requests to its URL, and see them here."),
            rx.card(
                rx.vstack(
                    rx.heading("New bin", size="3"),
                    rx.hstack(
                        rx.input(
                            placeholder="Label (optional)",
                            value=HomeState.new_label,
                            on_change=HomeState.set_new_label,
                            max_length=MAX_LABEL_LENGTH,
                            width="100%",
                            custom_attrs={"data-testid": "new-label"},
                        ),
                        rx.button(
                            "New bin",
                            on_click=HomeState.create_bin,
                            loading=HomeState.creating,
                            custom_attrs={"data-testid": "new-bin"},
                        ),
                        width="100%",
                    ),
                    width="100%",
                ),
                width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Open a bin", size="3"),
                    rx.hstack(
                        rx.input(
                            placeholder="Bin id or URL",
                            value=HomeState.open_text,
                            on_change=HomeState.set_open_text,
                            width="100%",
                            custom_attrs={"data-testid": "open-text"},
                        ),
                        rx.button("Open", on_click=HomeState.open_bin, variant="soft"),
                        width="100%",
                    ),
                    width="100%",
                ),
                width="100%",
            ),
            rx.cond(
                HomeState.listing_all,
                rx.heading("All bins", size="4"),
                rx.heading("Bins made in this browser", size="4"),
            ),
            rx.cond(
                HomeState.bins.length() > 0,
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("Label"),
                            rx.table.column_header_cell("Id"),
                            rx.table.column_header_cell("Requests"),
                            rx.table.column_header_cell("Last activity"),
                        )
                    ),
                    rx.table.body(rx.foreach(HomeState.bins, _bin_row)),
                    width="100%",
                ),
                rx.text("No bins yet.", color_scheme="gray"),
            ),
            spacing="4",
            width="100%",
        ),
        size="3",
        padding_y="1rem",
    )
