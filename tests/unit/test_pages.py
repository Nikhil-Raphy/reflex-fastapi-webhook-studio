"""Tests that the Reflex pages build."""

import reflex as rx

from reflex_fastapi_webhook_studio.ui.pages.home import home
from reflex_fastapi_webhook_studio.ui.pages.inspector import inspector


def test_given_pages_when_built_then_each_is_a_component_with_its_test_ids() -> None:
    """Given the home and inspector pages, when built, then each holds the ids the browser tests use."""
    # Given
    pages = {"home": home, "inspector": inspector}
    # When
    built = {name: page() for name, page in pages.items()}
    # Then
    assert all(isinstance(component, rx.Component) for component in built.values())
    assert "new-bin" in str(built["home"].render())
    rendered = str(built["inspector"].render())
    for test_id in ("capture-url", "request-row", "masked-header", "body-tab", "empty-state"):
        assert test_id in rendered
