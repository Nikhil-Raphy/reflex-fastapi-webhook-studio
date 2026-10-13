"""Tests for the package version."""

import tomllib
from pathlib import Path

import reflex_fastapi_webhook_studio


def test_given_pyproject_version_when_package_is_imported_then_version_matches() -> None:
    """Given the version in pyproject.toml, when the package is imported, then __version__ matches it."""
    # Given
    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    # When
    version = reflex_fastapi_webhook_studio.__version__
    # Then
    assert version == pyproject["project"]["version"]
