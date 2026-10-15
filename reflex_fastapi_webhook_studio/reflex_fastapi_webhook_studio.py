"""Build the Reflex app, and put the FastAPI app ahead of it for every path under /api."""

from typing import TYPE_CHECKING, override

import reflex as rx

from reflex_fastapi_webhook_studio.api.app import ApiFirst, create_api
from reflex_fastapi_webhook_studio.db.engine import Database
from reflex_fastapi_webhook_studio.log_config import configure_logging
from reflex_fastapi_webhook_studio.settings import get_settings
from rxconfig import config

if TYPE_CHECKING:
    from starlette.types import ASGIApp

settings = get_settings()
configure_logging(settings.log_level)
database = Database(settings.database_url)
api = create_api(settings, database)


class StudioApp(rx.App):
    """The Reflex app, with the API in front so Reflex's CORS layer never touches /api."""

    @override
    def __call__(self) -> ASGIApp:
        """Build the ASGI app that the server runs.

        Returns:
            The API-first ASGI app.
        """
        return ApiFirst(api, super().__call__())


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


app = StudioApp()
app.add_page(index)
app.register_lifespan_task(database.lifespan)
