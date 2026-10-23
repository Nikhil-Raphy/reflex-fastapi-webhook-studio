"""Small pieces used on more than one page."""

from collections.abc import Callable
from typing import Any, Literal, cast

import reflex as rx
from reflex_base.event import EventSpec
from reflex_base.vars.base import Var
from reflex_components_core.core.banner import has_connection_errors, has_too_many_connection_errors

type Colour = Literal["green", "blue", "orange", "purple", "red", "gray", "amber"]
METHOD_COLOURS: tuple[tuple[str, Colour], ...] = (
    ("GET", "green"),
    ("POST", "blue"),
    ("PUT", "orange"),
    ("PATCH", "purple"),
    ("DELETE", "red"),
)


def bind(handler: Callable[..., Any], *args: Var[Any]) -> EventSpec:
    """Bind browser-side values to a state's event handler.

    Args:
        handler: A state method, such as `InspectorState.select`.
        *args: The values to pass when the event fires.

    Returns:
        The event.
    """
    # Reflex turns each public state method into an EventHandler; type checkers still see the plain method.
    return cast("rx.EventHandler", handler)(*args)


def method_badge(method: Var[str]) -> rx.Component:
    """Show an HTTP method in a badge coloured by method; HEAD and OPTIONS are gray.

    Args:
        method: The method.

    Returns:
        The badge.
    """

    def badge(colour: Colour) -> rx.Component:
        return rx.badge(method, color_scheme=colour, variant="soft", min_width="4.5em", justify="center")

    return rx.box(
        rx.match(method, *((name, badge(colour)) for name, colour in METHOD_COLOURS), badge("gray")),
        flex_shrink="0",
    )


def status_dot(live: Var[bool]) -> rx.Component:
    """Show the live state: green when connected and following, amber while connecting, red when down.

    Args:
        live: Whether a watch task follows the bin.

    Returns:
        The dot and its word.
    """

    def dot(colour: Colour, word: str) -> rx.Component:
        return rx.hstack(
            rx.box(width="0.6rem", height="0.6rem", border_radius="50%", background=f"var(--{colour}-9)"),
            rx.text(word, size="2"),
            align="center",
            spacing="2",
            custom_attrs={"data-testid": "status"},
        )

    return rx.cond(
        has_too_many_connection_errors,
        dot("red", "Offline"),
        rx.cond(has_connection_errors | ~live, dot("amber", "Connecting"), dot("green", "Live")),
    )


def top_bar(*children: rx.Component) -> rx.Component:
    """Show the app name, linked to the home page, followed by the given parts.

    Args:
        *children: What follows the app name.

    Returns:
        The bar.
    """
    return rx.hstack(
        rx.link(rx.heading("Webhook Studio", size="5"), href="/", underline="none"),
        *children,
        align="center",
        spacing="3",
        width="100%",
    )
