"""Build the Reflex app and mount the FastAPI app on it."""

import reflex as rx

from reflex_fastapi_webhook_studio.api.app import create_api
from rxconfig import config


class State(rx.State):
    """The app state."""


def index() -> rx.Component:
    """Build the home page.

    Returns:
        The home page.
    """
    return rx.container(
        rx.color_mode.button(position="top-right"),  # type: ignore[attr-defined]  # Reflex stub types it as Var.
        rx.vstack(
            rx.heading("Welcome to Reflex!", size="9"),
            rx.text(
                "Get started by editing ",
                rx.code(f"{config.app_name}/{config.app_name}.py"),
                size="5",
            ),
            rx.link(
                rx.button("Check out our docs!"),
                href="https://reflex.dev/docs/getting-started/introduction/",
                is_external=True,
            ),
            spacing="5",
            justify="center",
            min_height="85vh",
        ),
    )


app = rx.App(api_transformer=create_api())
app.add_page(index)
