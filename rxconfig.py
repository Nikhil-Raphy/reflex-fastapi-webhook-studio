"""Reflex config."""

import reflex as rx

config = rx.Config(
    app_name="reflex_fastapi_webhook_studio",
    telemetry_enabled=False,
    # Unassigned by IANA and below Linux's outbound range (32768-60999), unlike Reflex's 3000 and 8000.
    frontend_port=17300,
    backend_port=17301,
    plugins=[
        rx.plugins.SitemapPlugin(),
        # No @tailwindcss/typography: it pins postcss-selector-parser 6.0.10 (GHSA-rj75-hqrm-r3gf).
        rx.plugins.TailwindV4Plugin(config={"plugins": []}),
        # Indigo, unlike Radix's default blue, gives white text on solid buttons the 4.5:1 contrast WCAG AA asks for.
        rx.plugins.RadixThemesPlugin(theme=rx.theme(accent_color="indigo")),
    ],
)
