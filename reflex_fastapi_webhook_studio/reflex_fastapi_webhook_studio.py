"""Build the Reflex app, and put the FastAPI app ahead of it for every path under /api."""

from typing import TYPE_CHECKING, override

import reflex as rx

from reflex_fastapi_webhook_studio.api.app import ApiFirst, create_api
from reflex_fastapi_webhook_studio.bus.redis_bus import RedisBus
from reflex_fastapi_webhook_studio.runtime import bus, database, redis, settings
from reflex_fastapi_webhook_studio.ui.live import sockets
from reflex_fastapi_webhook_studio.ui.pages.home import home
from reflex_fastapi_webhook_studio.ui.pages.inspector import inspector
from reflex_fastapi_webhook_studio.ui.state.home import HomeState
from reflex_fastapi_webhook_studio.ui.state.inspector import InspectorState

if TYPE_CHECKING:
    from starlette.types import ASGIApp

api = create_api(settings, database, bus=bus, redis=redis)


class StudioApp(rx.App):
    """The Reflex app, with the API in front so Reflex's CORS layer never touches /api."""

    @override
    def __call__(self) -> ASGIApp:
        """Build the ASGI app that the server runs.

        Returns:
            The API-first ASGI app.
        """
        return ApiFirst(api, super().__call__())


app = StudioApp()
app.add_page(home, route="/", title="Webhook Studio", on_load=HomeState.load)
app.add_page(
    inspector,
    route="/bins/[bin_id]",
    title="Bin · Webhook Studio",
    on_load=[InspectorState.load, InspectorState.watch],
)
app.register_lifespan_task(database.lifespan)
if isinstance(bus, RedisBus):
    app.register_lifespan_task(bus.listen)
sockets.attach(app)
