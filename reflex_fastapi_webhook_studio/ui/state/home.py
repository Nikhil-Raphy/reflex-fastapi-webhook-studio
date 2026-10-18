"""State for the home page: make a bin, open one, and list bins."""

from collections.abc import AsyncIterator

import reflex as rx
from reflex_base.event import EventSpec

from reflex_fastapi_webhook_studio import runtime
from reflex_fastapi_webhook_studio.domain import MAX_LABEL_LENGTH, BinLimitError, BinListing
from reflex_fastapi_webhook_studio.ui.views import BinRowView, bin_row, known_ids, parse_bin_id, remember


class HomeState(rx.State):
    """The home page state."""

    known_bins: str = rx.LocalStorage("[]", name="known_bins", sync=True)
    """The ids of the bins this browser made, as a JSON list, newest first."""
    bins: rx.Field[list[BinRowView]] = rx.field(default_factory=list)
    new_label: rx.Field[str] = rx.field("")
    open_text: rx.Field[str] = rx.field("")
    listing_all: rx.Field[bool] = rx.field(default=False)
    creating: rx.Field[bool] = rx.field(default=False)

    def set_new_label(self, value: str) -> None:
        """Keep the label typed for a new bin.

        Args:
            value: The text in the label box.
        """
        self.new_label = value

    def set_open_text(self, value: str) -> None:
        """Keep the text typed in the open box.

        Args:
            value: The text in the open box.
        """
        self.open_text = value

    async def load(self) -> None:
        """List every bin in `all` mode, or the bins this browser made in `browser` mode."""
        self.listing_all = runtime.settings.bin_listing is BinListing.ALL
        if self.listing_all:
            summaries = await runtime.bin_service.list_all()
        else:
            summaries = await runtime.bin_service.summaries(known_ids(self.known_bins))
        self.bins = [bin_row(summary) for summary in summaries]

    async def create_bin(self) -> AsyncIterator[EventSpec | None]:
        """Make a bin with the typed label, remember it in this browser, and open it.

        Yields:
            A state update while it works, then a move to the new bin or an error toast.
        """
        label = self.new_label.strip() or None
        if label is not None and len(label) > MAX_LABEL_LENGTH:
            yield rx.toast.error(f"A label holds at most {MAX_LABEL_LENGTH} characters.")
            return
        self.creating = True
        yield None
        try:
            bin_ = await runtime.bin_service.create(label)
        except BinLimitError:
            yield rx.toast.error("The app holds the most bins it may.")
            return
        finally:
            self.creating = False
        self.known_bins = remember(self.known_bins, bin_.id, limit=runtime.settings.max_bins)
        self.new_label = ""
        yield rx.redirect(f"/bins/{bin_.id}")

    def open_bin(self) -> EventSpec:
        """Open the bin whose id or URL the user typed.

        Returns:
            A move to the bin, or an error toast.
        """
        bin_id = parse_bin_id(self.open_text)
        if bin_id is None:
            return rx.toast.error("Type a bin id, or a URL that holds one.")
        self.open_text = ""
        return rx.redirect(f"/bins/{bin_id}")
