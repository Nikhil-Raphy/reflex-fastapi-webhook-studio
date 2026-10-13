"""Catch, inspect and replay webhooks and HTTP requests."""

from importlib.metadata import version

# pyproject.toml holds the version; uv_build cannot read it from a file.
__version__ = version("reflex-fastapi-webhook-studio")
