"""A marker that fires an event each time it scrolls into view, so a list can load more as the user nears its end."""

from collections.abc import Sequence
from typing import override

import reflex as rx
from reflex_base.event import no_args_event_spec
from reflex_base.utils.imports import ImportDict, ImportVar
from reflex_base.utils.types import ArgsSpec

# The observer reads the newest handler from a ref, so it is made once per mount, not on every render.
_SENTINEL = """
function VisibilitySentinel({ onVisible, ...props }) {
  const marker = useRef(null);
  const handler = useRef(onVisible);
  handler.current = onVisible;
  useEffect(() => {
    if (!marker.current || typeof IntersectionObserver === "undefined") {
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          handler.current?.();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(marker.current);
    return () => observer.disconnect();
  }, []);
  return createElement("div", { ref: marker, ...props });
}
"""


class VisibilitySentinel(rx.Component):
    """An empty block that calls `on_visible` when it comes within 200 px of the visible area."""

    tag = "VisibilitySentinel"

    @classmethod
    @override
    def get_event_triggers(cls) -> dict[str, ArgsSpec | Sequence[ArgsSpec]]:
        """Add `on_visible` to the usual triggers.

        Returns:
            The event triggers.
        """
        return super().get_event_triggers() | {"on_visible": no_args_event_spec}

    @override
    def add_imports(self) -> ImportDict:
        """Import the React functions the marker uses.

        Returns:
            The imports.
        """
        return {"react": [ImportVar(tag="createElement"), ImportVar(tag="useEffect"), ImportVar(tag="useRef")]}

    @override
    def add_custom_code(self) -> list[str]:
        """Define the marker's React component in the page.

        Returns:
            The component's code.
        """
        return [_SENTINEL]


visibility_sentinel = VisibilitySentinel.create
