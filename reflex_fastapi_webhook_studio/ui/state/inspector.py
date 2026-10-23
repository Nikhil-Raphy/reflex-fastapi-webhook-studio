"""State for the inspector page: one bin, its requests and the one picked, kept live."""

from uuid import UUID

import reflex as rx
from reflex.config import get_config
from reflex_base.event import EventSpec

from reflex_fastapi_webhook_studio import runtime
from reflex_fastapi_webhook_studio.domain import BinEvent, BinNotFoundError, EventType, RequestNotFoundError
from reflex_fastapi_webhook_studio.ui.live import HEARTBEAT_S, WORKER_ID, merge_request, sockets
from reflex_fastapi_webhook_studio.ui.views import (
    NO_LABEL,
    RequestRowView,
    RequestView,
    capture_url,
    curl_example,
    parse_bin_id,
    request_row,
    request_view,
)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


class InspectorState(rx.State):
    """The inspector page state."""

    found: rx.Field[bool] = rx.field(default=True)
    label: rx.Field[str] = rx.field("")
    capture_url: rx.Field[str] = rx.field("")
    requests: rx.Field[list[RequestRowView]] = rx.field(default_factory=list)
    detail: rx.Field[RequestView] = rx.field(default_factory=RequestView)
    revealed: rx.Field[list[int]] = rx.field(default_factory=list)
    live: rx.Field[bool] = rx.field(default=False)
    """Whether a watch task follows this bin's events."""
    _watcher: str = ""
    """The worker and bin of the running watch task, so a second one does not start."""

    @rx.var
    def curl_command(self) -> str:
        """A curl command that sends JSON to this bin.

        Returns:
            The command.
        """
        return curl_example(self.capture_url)

    def _bin_id(self) -> str:
        return parse_bin_id(self.router.url.path) or ""

    async def load(self) -> None:
        """Read the bin and its newest requests, and show the newest one."""
        await self._load()

    @rx.event(background=True)  # pylint: disable=not-callable  # rx.event is a class whose __new__ makes the decorator.
    async def watch(self) -> None:
        """Follow this bin's events until the tab closes or moves to another bin.

        It subscribes first and then reloads, so no event falls between the two, and skips requests already listed.
        Every quiet heartbeat it checks that the tab still holds its websocket.
        """
        async with self:
            bin_id = self._bin_id()
            key = f"{WORKER_ID}:{bin_id}"
            if not bin_id or not self.found or self._watcher == key:
                return
            self._watcher = key
            token = self.router.session.client_token
        try:
            async with runtime.bus.subscribe(bin_id) as events:
                async with self:
                    if self._watcher != key:
                        return
                    await self._load()
                    self.live = True
                while True:
                    event = await events.next(HEARTBEAT_S)
                    if event is None and not sockets.connected(token):
                        return
                    async with self:
                        if self._watcher != key:
                            return
                        if event is not None:
                            await self._apply(event)
        finally:
            async with self:
                if self._watcher == key:
                    self._watcher = ""
                    self.live = False

    async def _apply(self, event: BinEvent) -> None:
        match event.type:
            case EventType.REQUEST_CAPTURED if event.request is not None:
                rows = merge_request(self.requests, event.request, limit=runtime.settings.max_requests_per_bin)
                if rows is not None:
                    self.requests = rows
                    if not self.detail.id:
                        await self._show(rows[0].id)
            case EventType.BIN_UPDATED:
                self.label = event.label or NO_LABEL
            case EventType.RESYNC:
                await self._load()
            case _:
                pass

    async def _load(self) -> None:
        bin_id = self._bin_id()
        try:
            bin_ = await runtime.bin_service.get(bin_id)
            rows = await runtime.request_service.list(bin_id, limit=runtime.settings.max_requests_per_bin)
        except BinNotFoundError:
            self.found = False
            self.label, self.capture_url, self.requests, self.detail = "", "", [], RequestView()
            return
        self.found = True
        self.label = bin_.label or NO_LABEL
        self.capture_url = capture_url(get_config().api_url, bin_id)
        self.requests = [request_row(row) for row in rows]
        kept = self.detail.id and any(row.id == self.detail.id for row in self.requests)
        if not kept:
            await self._show(self.requests[0].id if self.requests else "")

    async def select(self, request_id: str) -> None:
        """Show one request in the tabs.

        Args:
            request_id: The request id.
        """
        await self._show(request_id)

    async def _show(self, request_id: str) -> None:
        self.revealed = []
        parsed = _uuid(request_id)
        if parsed is None:
            self.detail = RequestView()
            return
        try:
            self.detail = request_view(await runtime.request_service.get(self._bin_id(), parsed))
        except BinNotFoundError, RequestNotFoundError:
            self.detail = RequestView()

    def reveal(self, index: int) -> None:
        """Show the value of a masked header.

        Args:
            index: The header's position in the list.
        """
        if index not in self.revealed:
            self.revealed = [*self.revealed, index]

    def copy_url(self) -> list[EventSpec]:
        """Copy the capture URL.

        Returns:
            The copy and a toast.
        """
        return [rx.set_clipboard(self.capture_url), rx.toast.success("Copied the bin URL.")]

    def copy_curl(self) -> list[EventSpec]:
        """Copy the curl example.

        Returns:
            The copy and a toast.
        """
        return [rx.set_clipboard(curl_example(self.capture_url)), rx.toast.success("Copied the curl command.")]

    async def download_body(self) -> EventSpec:
        """Download the body of the request on show, as it was sent.

        Returns:
            The download, or an error toast.
        """
        parsed = _uuid(self.detail.id)
        if parsed is None:
            return rx.toast.error("This request is gone.")
        try:
            request = await runtime.request_service.get(self._bin_id(), parsed)
        except BinNotFoundError, RequestNotFoundError:
            return rx.toast.error("This request is gone.")
        return rx.download(data=request.body, filename=f"{request.id}.bin", mime_type="application/octet-stream")
