"""Tests for the package version."""

from importlib.metadata import version

import reflex_fastapi_webhook_studio
from reflex_fastapi_webhook_studio import _version


def test_given_version_file_when_package_is_installed_then_metadata_and_package_match_it() -> None:
    """Given the version in _version.py, when the package is installed, then its metadata and __version__ match it."""
    # Given
    expected = _version.__version__
    # When
    installed = version("reflex-fastapi-webhook-studio")
    # Then
    assert (installed, reflex_fastapi_webhook_studio.__version__) == (expected, expected)
