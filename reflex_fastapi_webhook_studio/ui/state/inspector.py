"""State for the inspector page: one bin, its requests and the one picked, kept live."""

import dataclasses
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import reflex as rx
from reflex.config import get_config
from reflex_base.event import EventSpec

from reflex_fastapi_webhook_studio import runtime
from reflex_fastapi_webhook_studio.domain import (
    MAX_SEARCH_LENGTH,
    BinEvent,
    BinNotFoundError,
    EventType,
    HttpMethod,
    InvalidReplyError,
    ReplayBlockedError,
    ReplayFailedError,
    ReplayMode,
    ReplayTargetError,
    RequestFilter,
    RequestNotFoundError,
    RequestSummary,
)
from reflex_fastapi_webhook_studio.services.curl import curl_command as replay_as_curl
from reflex_fastapi_webhook_studio.ui.live import HEARTBEAT_S, WORKER_ID, merge_request, sockets
from reflex_fastapi_webhook_studio.ui.state.home import HomeState
from reflex_fastapi_webhook_studio.ui.views import (
    NO_LABEL,
    PairView,
    ReplayView,
    ReplyForm,
    RequestRowView,
    RequestView,
    capture_url,
    curl_example,
    forget,
    parse_bin_id,
    replay_view,
    reply_config,
    reply_form,
    request_row,
    request_view,
)

PAGE_SIZE = 50
"""Requests read per page of the list."""
ALL_METHODS = "ALL"
"""The method filter's value for every method; a select item cannot hold an empty value."""
SKIP = "true"
"""What a "Don't ask again" box stores in the browser."""
GONE = "This request is gone."


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


class InspectorState(rx.State):  # pylint: disable=too-many-instance-attributes,too-many-public-methods  # One page's state.
    """The inspector page state."""

    found: rx.Field[bool] = rx.field(default=True)
    deleted: rx.Field[bool] = rx.field(default=False)
    """Whether the bin was deleted while the page was open."""
    label: rx.Field[str] = rx.field("")
    capture_url: rx.Field[str] = rx.field("")
    export_url: rx.Field[str] = rx.field("")
    expires_at: rx.Field[str] = rx.field("")
    replay_local: rx.Field[bool] = rx.field(default=False)
    """Whether replays may reach this machine and private networks."""
    requests: rx.Field[list[RequestRowView]] = rx.field(default_factory=list)
    total: rx.Field[int] = rx.field(0)
    """How many of the bin's requests match the filter, loaded or not."""
    method_filter: rx.Field[str] = rx.field(ALL_METHODS)
    search: rx.Field[str] = rx.field("")
    detail: rx.Field[RequestView] = rx.field(default_factory=RequestView)
    revealed: rx.Field[list[int]] = rx.field(default_factory=list)
    live: rx.Field[bool] = rx.field(default=False)
    """Whether a watch task follows this bin's events."""
    confirming: rx.Field[str] = rx.field("")
    """Which delete waits for the user to confirm: request, clear or bin; empty when none."""
    dont_ask: rx.Field[bool] = rx.field(default=False)
    skip_request_confirm: str = rx.LocalStorage("", name="skip_confirm_request", sync=True)
    skip_clear_confirm: str = rx.LocalStorage("", name="skip_confirm_clear", sync=True)
    skip_bin_confirm: str = rx.LocalStorage("", name="skip_confirm_bin", sync=True)
    reply_open: rx.Field[bool] = rx.field(default=False)
    reply: rx.Field[ReplyForm] = rx.field(default_factory=ReplyForm)
    reply_error: rx.Field[str] = rx.field("")
    replay_target: rx.Field[str] = rx.field("")
    replay_keep_query: rx.Field[bool] = rx.field(default=True)
    replaying: rx.Field[bool] = rx.field(default=False)
    replay_result: rx.Field[ReplayView] = rx.field(default_factory=ReplayView)
    replay_error: rx.Field[str] = rx.field("")
    _watcher: str = ""
    """The worker and bin of the running watch task, so a second one does not start."""

    @rx.var
    def curl_command(self) -> str:
        """A curl command that sends JSON to this bin.

        Returns:
            The command.
        """
        return curl_example(self.capture_url)

    @rx.var
    def has_older(self) -> bool:
        """Whether some matching requests are not loaded yet.

        Returns:
            True when the list holds fewer rows than match.
        """
        return len(self.requests) < self.total

    @rx.var
    def filtered(self) -> bool:
        """Whether the list leaves out some requests.

        Returns:
            True when a method or search text is set.
        """
        return self.method_filter != ALL_METHODS or bool(self.search.strip())

    def _bin_id(self) -> str:
        return parse_bin_id(self.router.url.path) or ""

    def _filter(self) -> RequestFilter:
        method = None if self.method_filter == ALL_METHODS else HttpMethod(self.method_filter)
        return RequestFilter(method=method, text=self.search.strip())

    async def load(self) -> None:
        """Read the bin and the newest page of its requests, and show the newest one."""
        await self._load()

    @rx.event(background=True)  # pylint: disable=not-callable  # rx.event is a class whose __new__ makes the decorator.
    async def watch(self) -> None:
        """Follow this bin's events until the tab closes, moves to another bin, or the bin is deleted.

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
                        if not self.found:
                            return
        finally:
            async with self:
                if self._watcher == key:
                    self._watcher = ""
                    self.live = False

    async def _apply(self, event: BinEvent) -> None:
        match event.type:
            case EventType.REQUEST_CAPTURED if event.request is not None:
                await self._captured(event.request)
            case EventType.REQUEST_DELETED if event.request_id is not None:
                if await self._drop(str(event.request_id)):
                    self.total = max(self.total - 1, len(self.requests))
            case EventType.BIN_CLEARED:
                await self._empty()
            case EventType.BIN_UPDATED:
                await self._load_bin()
            case EventType.BIN_DELETED:
                self._gone(deleted=True)
            case EventType.RESYNC:
                await self._load()
            case _:
                pass

    async def _captured(self, request: RequestSummary) -> None:
        self.expires_at = (request.received_at + timedelta(days=runtime.settings.bin_ttl_days)).isoformat()
        if self._filter().active:
            # Only the database knows whether the new request matches the search.
            await self._reload_list(keep=len(self.requests))
            return
        cap = runtime.settings.max_requests_per_bin
        rows = merge_request(self.requests, request, limit=cap)
        if rows is not None:
            self.requests = rows
            self.total = min(self.total + 1, cap)
            if not self.detail.id:
                await self._show(rows[0].id)

    async def _load(self) -> None:
        if await self._load_bin():
            await self._reload_list()

    async def _load_bin(self) -> bool:
        bin_id = self._bin_id()
        try:
            bin_ = await runtime.bin_service.get(bin_id)
        except BinNotFoundError:
            self._gone(deleted=False)
            return False
        api_url = get_config().api_url.rstrip("/")
        self.found, self.deleted = True, False
        self.label = bin_.label or NO_LABEL
        self.capture_url = capture_url(runtime.settings.public_base_url or api_url, bin_id)
        self.export_url = f"{api_url}/api/v1/bins/{bin_id}/export"
        self.expires_at = bin_.expires_at.isoformat()
        self.replay_local = runtime.settings.replay_mode is ReplayMode.LOCAL
        return True

    async def _reload_list(self, keep: int = PAGE_SIZE) -> None:
        bin_id, where = self._bin_id(), self._filter()
        limit = min(max(keep, PAGE_SIZE), runtime.settings.max_requests_per_bin)
        try:
            rows = await runtime.request_service.list(bin_id, limit=limit, where=where)
            self.total = await runtime.request_service.count(bin_id, where)
        except BinNotFoundError:
            self._gone(deleted=False)
            return
        self.requests = [request_row(row) for row in rows]
        kept = self.detail.id and any(row.id == self.detail.id for row in self.requests)
        if not kept:
            await self._show(self.requests[0].id if self.requests else "")

    def _gone(self, *, deleted: bool) -> None:
        self.found, self.deleted = False, deleted
        self.label, self.capture_url, self.export_url, self.expires_at = "", "", "", ""
        self.requests, self.total, self.detail = [], 0, RequestView()
        self.confirming, self.reply_open = "", False

    async def _empty(self) -> None:
        self.requests, self.total = [], 0
        await self._show("")

    async def _drop(self, request_id: str) -> bool:
        index = next((i for i, row in enumerate(self.requests) if row.id == request_id), None)
        if index is None:
            return False
        self.requests = [row for row in self.requests if row.id != request_id]
        if self.detail.id == request_id:
            await self._show(self.requests[min(index, len(self.requests) - 1)].id if self.requests else "")
        return True

    async def load_older(self) -> None:
        """Add the next page of older requests to the list."""
        if not self.requests or len(self.requests) >= self.total:
            return
        bin_id = self._bin_id()
        before = UUID(self.requests[-1].id)
        try:
            rows = await runtime.request_service.list(bin_id, limit=PAGE_SIZE, where=self._filter(), before=before)
        except BinNotFoundError:
            self._gone(deleted=False)
            return
        listed = {row.id for row in self.requests}
        self.requests = [*self.requests, *(row for row in map(request_row, rows) if row.id not in listed)]
        if not rows:
            # Some were deleted since the count; stop asking for more.
            self.total = len(self.requests)

    async def set_method_filter(self, value: str) -> None:
        """Show only requests with one method, or with any.

        Args:
            value: The method, or "ALL".
        """
        self.method_filter = value if value in HttpMethod.__members__ else ALL_METHODS
        await self._reload_list()

    async def set_search(self, value: str) -> None:
        """Show only requests that hold some text. The search box waits 300 ms after typing stops.

        Args:
            value: The text to find.
        """
        self.search = value[:MAX_SEARCH_LENGTH]
        await self._reload_list()

    async def clear_filters(self) -> None:
        """Show every request again."""
        self.method_filter, self.search = ALL_METHODS, ""
        await self._reload_list()

    async def select(self, request_id: str) -> None:
        """Show one request in the tabs.

        Args:
            request_id: The request id.
        """
        await self._show(request_id)

    async def _show(self, request_id: str) -> None:
        self.revealed = []
        self.replay_result, self.replay_error = ReplayView(), ""
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
            return rx.toast.error(GONE)
        try:
            request = await runtime.request_service.get(self._bin_id(), parsed)
        except BinNotFoundError, RequestNotFoundError:
            return rx.toast.error(GONE)
        return rx.download(data=request.body, filename=f"{request.id}.bin", mime_type="application/octet-stream")

    async def copy_as_curl(self) -> EventSpec | list[EventSpec]:
        """Copy a curl command that sends the request on show to this bin again.

        Returns:
            The copy and a toast, or an error toast.
        """
        parsed = _uuid(self.detail.id)
        if parsed is None:
            return rx.toast.error(GONE)
        try:
            request = await runtime.request_service.get(self._bin_id(), parsed)
        except BinNotFoundError, RequestNotFoundError:
            return rx.toast.error(GONE)
        return [rx.set_clipboard(replay_as_curl(request, self.capture_url)), rx.toast.success("Copied as curl.")]

    def export(self) -> EventSpec:
        """Download the bin and every request as one JSON file.

        Returns:
            The download.
        """
        return rx.download(url=self.export_url)

    async def ask_delete_request(self) -> EventSpec | list[EventSpec] | None:
        """Delete the request on show, after the user confirms unless they chose not to be asked.

        Returns:
            A toast once deleted, or nothing while the dialog asks.
        """
        if self.skip_request_confirm == SKIP:
            return await self._delete_request()
        self.confirming, self.dont_ask = "request", False
        return None

    async def ask_clear(self) -> EventSpec | list[EventSpec] | None:
        """Delete every request of the bin, after the user confirms unless they chose not to be asked.

        Returns:
            A toast once cleared, or nothing while the dialog asks.
        """
        if self.skip_clear_confirm == SKIP:
            return await self._clear()
        self.confirming, self.dont_ask = "clear", False
        return None

    async def ask_delete_bin(self) -> EventSpec | list[EventSpec] | None:
        """Delete the bin, after the user confirms unless they chose not to be asked.

        Returns:
            A move to the home page once deleted, or nothing while the dialog asks.
        """
        if self.skip_bin_confirm == SKIP:
            return await self._delete_bin()
        self.confirming, self.dont_ask = "bin", False
        return None

    def set_dont_ask(self, checked: bool) -> None:  # noqa: FBT001  # Reflex passes the checkbox state as one value.
        """Keep the state of the dialog's "Don't ask again" box.

        Args:
            checked: Whether the box is ticked.
        """
        self.dont_ask = checked

    def set_confirm_open(self, is_open: bool) -> None:  # noqa: FBT001  # Reflex passes the open state as one value.
        """Close the confirm dialog when the user dismisses it.

        Args:
            is_open: Whether the dialog stays open.
        """
        if not is_open:
            self.confirming = ""

    async def confirm(self) -> EventSpec | list[EventSpec] | None:
        """Do the delete the dialog asked about, and remember "Don't ask again" for that kind.

        Returns:
            A toast or a move, from the delete.
        """
        kind, self.confirming = self.confirming, ""
        match kind:
            case "request":
                if self.dont_ask:
                    self.skip_request_confirm = SKIP
                return await self._delete_request()
            case "clear":
                if self.dont_ask:
                    self.skip_clear_confirm = SKIP
                return await self._clear()
            case "bin":
                if self.dont_ask:
                    self.skip_bin_confirm = SKIP
                return await self._delete_bin()
            case _:
                return None

    async def _delete_request(self) -> EventSpec:
        parsed = _uuid(self.detail.id)
        if parsed is None:
            return rx.toast.error(GONE)
        try:
            await runtime.request_service.delete(self._bin_id(), parsed)
        except BinNotFoundError, RequestNotFoundError:
            return rx.toast.error(GONE)
        if await self._drop(str(parsed)):
            self.total = max(self.total - 1, len(self.requests))
        return rx.toast.success("Deleted the request.")

    async def _clear(self) -> EventSpec:
        try:
            await runtime.request_service.clear(self._bin_id())
        except BinNotFoundError:
            self._gone(deleted=True)
            return rx.toast.error("This bin is gone.")
        await self._empty()
        return rx.toast.success("Cleared the bin.")

    async def _delete_bin(self) -> EventSpec | list[EventSpec]:
        bin_id = self._bin_id()
        try:
            await runtime.bin_service.delete(bin_id)
        except BinNotFoundError:
            self._gone(deleted=True)
            return rx.toast.error("This bin is gone.")
        home = await self.get_state(HomeState)
        home.known_bins = forget(home.known_bins, {bin_id})
        self._gone(deleted=True)
        return [rx.redirect("/"), rx.toast.success("Deleted the bin.")]

    async def open_reply(self) -> None:
        """Open the reply settings dialog, filled from the bin's settings."""
        try:
            bin_ = await runtime.bin_service.get(self._bin_id())
        except BinNotFoundError:
            self._gone(deleted=True)
            return
        self.reply, self.reply_error, self.reply_open = reply_form(bin_.reply), "", True

    def set_reply_open(self, is_open: bool) -> None:  # noqa: FBT001  # Reflex passes the open state as one value.
        """Open or close the reply settings dialog.

        Args:
            is_open: Whether the dialog is open.
        """
        self.reply_open = is_open

    def set_reply_status(self, value: str) -> None:
        """Keep the typed reply status.

        Args:
            value: The status as typed.
        """
        self.reply = dataclasses.replace(self.reply, status=value)

    def set_reply_content_type(self, value: str) -> None:
        """Keep the typed reply content type.

        Args:
            value: The content type as typed.
        """
        self.reply = dataclasses.replace(self.reply, content_type=value)

    def set_reply_custom_body(self, checked: bool) -> None:  # noqa: FBT001  # Reflex passes the switch state as one value.
        """Choose between the typed body and the default JSON body.

        Args:
            checked: Whether to send the typed body.
        """
        self.reply = dataclasses.replace(self.reply, custom_body=checked)

    def set_reply_body(self, value: str) -> None:
        """Keep the typed reply body.

        Args:
            value: The body as typed.
        """
        self.reply = dataclasses.replace(self.reply, body=value)

    def set_reply_delay(self, value: str) -> None:
        """Keep the typed reply delay.

        Args:
            value: The delay in milliseconds, as typed.
        """
        self.reply = dataclasses.replace(self.reply, delay_ms=value)

    def add_reply_header(self) -> None:
        """Add an empty header row to the reply settings."""
        headers = [*self.reply.headers, PairView(index=len(self.reply.headers), name="", value="")]
        self.reply = dataclasses.replace(self.reply, headers=headers)

    def remove_reply_header(self, index: int) -> None:
        """Remove a header row from the reply settings.

        Args:
            index: The row's position.
        """
        kept = [pair for pair in self.reply.headers if pair.index != index]
        headers = [dataclasses.replace(pair, index=position) for position, pair in enumerate(kept)]
        self.reply = dataclasses.replace(self.reply, headers=headers)

    def set_reply_header_name(self, index: int, value: str) -> None:
        """Keep a typed header name.

        Args:
            index: The row's position.
            value: The name as typed.
        """
        headers = [
            dataclasses.replace(pair, name=value) if pair.index == index else pair for pair in self.reply.headers
        ]
        self.reply = dataclasses.replace(self.reply, headers=headers)

    def set_reply_header_value(self, index: int, value: str) -> None:
        """Keep a typed header value.

        Args:
            index: The row's position.
            value: The value as typed.
        """
        headers = [
            dataclasses.replace(pair, value=value) if pair.index == index else pair for pair in self.reply.headers
        ]
        self.reply = dataclasses.replace(self.reply, headers=headers)

    def default_reply(self) -> None:
        """Fill the dialog with the default reply: 200 with the request id as JSON."""
        self.reply, self.reply_error = ReplyForm(), ""

    async def save_reply(self) -> EventSpec | None:
        """Save the reply settings, or show what is wrong with them.

        Returns:
            A toast once saved.
        """
        config = reply_config(self.reply)
        if isinstance(config, str):
            self.reply_error = config
            return None
        try:
            await runtime.bin_service.set_reply(self._bin_id(), config)
        except InvalidReplyError as error:
            self.reply_error = str(error)
            return None
        except BinNotFoundError:
            self._gone(deleted=True)
            return None
        self.reply_open = False
        return rx.toast.success("Saved the reply settings.")

    def set_replay_target(self, value: str) -> None:
        """Keep the typed replay target.

        Args:
            value: The URL as typed.
        """
        self.replay_target = value

    def set_replay_keep_query(self, checked: bool) -> None:  # noqa: FBT001  # Reflex passes the switch state as one value.
        """Choose whether a replay adds the original query string to the target.

        Args:
            checked: Whether to add it.
        """
        self.replay_keep_query = checked

    async def send_replay(self) -> AsyncIterator[None]:
        """Send the request on show to the typed target, and show what came back.

        Yields:
            A state update while the replay runs.
        """
        parsed = _uuid(self.detail.id)
        if parsed is None:
            self.replay_error = GONE
            return
        self.replaying, self.replay_error, self.replay_result = True, "", ReplayView()
        yield
        try:
            result = await runtime.replay_service.replay(
                self._bin_id(), parsed, self.replay_target, keep_query=self.replay_keep_query
            )
        except (ReplayTargetError, ReplayBlockedError, ReplayFailedError) as error:
            self.replay_error = str(error)
        except BinNotFoundError, RequestNotFoundError:
            self.replay_error = GONE
        else:
            self.replay_result = replay_view(result)
        finally:
            self.replaying = False
