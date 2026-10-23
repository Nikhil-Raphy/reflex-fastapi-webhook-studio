"""Helpers for live updates: which tabs are still open, and how a new request joins the list."""

from uuid import uuid4

import reflex as rx

from reflex_fastapi_webhook_studio.domain import RequestSummary
from reflex_fastapi_webhook_studio.ui.views import RequestRowView, request_row

HEARTBEAT_S = 15.0
"""How often a quiet watch task checks that its tab is still open."""
WORKER_ID = uuid4().hex
"""Tells this worker's watch tasks apart from other workers' when state lives in Redis."""


class Sockets:
    """Tells whether a browser tab still holds a websocket on this worker."""

    def __init__(self) -> None:
        """Start with no app; every tab counts as closed until one is attached."""
        self._app: rx.App | None = None

    def attach(self, app: rx.App) -> None:
        """Use the app's websocket namespace.

        Args:
            app: The Reflex app.
        """
        self._app = app

    def connected(self, token: str) -> bool:
        """Check a tab's websocket.

        Args:
            token: The tab's client token.

        Returns:
            Whether the tab holds a websocket on this worker.
        """
        namespace = None if self._app is None else self._app.event_namespace
        return namespace is not None and token in namespace.token_to_sid


sockets = Sockets()


def merge_request(rows: list[RequestRowView], summary: RequestSummary, *, limit: int) -> list[RequestRowView] | None:
    """Put a new request at the top of the list, keeping at most `limit` rows.

    Args:
        rows: The rows on show, newest first.
        summary: The new request.
        limit: The most rows to keep.

    Returns:
        The new rows, or None if the request is already listed.
    """
    row = request_row(summary)
    if any(existing.id == row.id for existing in rows):
        return None
    return [row, *rows][:limit]
