"""Tests that the Reflex pages build."""

from typing import Any

import reflex as rx

from reflex_fastapi_webhook_studio.ui.pages.home import home
from reflex_fastapi_webhook_studio.ui.pages.inspector import inspector


def by_test_id(node: object, test_id: str) -> dict[str, Any] | None:
    """Find the rendered component that carries a test id.

    Args:
        node: A rendered component, or any part of one.
        test_id: The `data-testid` value.

    Returns:
        The component, or None if no part of the tree carries the id.
    """
    if isinstance(node, dict):
        if f'"data-testid":"{test_id}"' in node.get("props", []):
            return node
        parts: list[object] = list(node.values())
    elif isinstance(node, list):
        parts = node
    else:
        return None
    return next((found for part in parts if (found := by_test_id(part, test_id)) is not None), None)


def test_given_pages_when_built_then_each_is_a_component_with_its_test_ids() -> None:
    """Given the home and inspector pages, when built, then each holds the ids the browser tests use."""
    # Given
    pages = {"home": home, "inspector": inspector}
    # When
    built = {name: page() for name, page in pages.items()}
    # Then
    assert all(isinstance(component, rx.Component) for component in built.values())
    assert "new-bin" in str(built["home"].render())
    assert '"data-testid":"loading"' in str(built["home"].render())
    rendered = str(built["inspector"].render())
    test_ids = (
        "capture-url",
        "request-row",
        "masked-header",
        "body-tab",
        "empty-state",
        "method-filter",
        "search",
        "load-older",
        "delete-request",
        "confirm-delete",
        "dont-ask",
        "export",
        "reply-settings",
        "reply-save",
        "replay-tab",
        "replay-send",
    )
    for test_id in test_ids:
        assert test_id in rendered
    assert "VisibilitySentinel" in rendered
    assert '"data-testid":"loading"' in rendered
    # Without it React Router routes the same-origin Export click itself and no download starts.
    assert "reloadDocument" in rendered


def test_given_inspector_page_when_built_then_search_waits_300_ms_after_typing_stops() -> None:
    """Given the inspector page, when built, then the search box sends its text 300 ms after typing stops."""
    # Given
    page = inspector()
    # When
    search = by_test_id(page.render(), "search")
    # Then
    assert search is not None
    assert search["name"] == "DebounceInput"
    assert "debounceTimeout:300" in search["props"]
