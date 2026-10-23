"""Start the app in production mode once, for the browser tests."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).parents[2]
PORT = int(os.environ.get("WEBHOOK_STUDIO_E2E_PORT", "17320"))
START_TIMEOUT_S = 300


def _wait_until_up(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            msg = f"The app stopped while starting, with exit code {process.returncode}."
            raise RuntimeError(msg)
        try:
            if all(httpx.get(f"{url}{path}", timeout=2).status_code == 200 for path in ("/api/v1/health", "/")):
                return
        except httpx.TransportError:
            pass
        time.sleep(1)
    msg = f"The app did not answer on {url} within {START_TIMEOUT_S} s."
    raise RuntimeError(msg)


@pytest.fixture(scope="session")
def app_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Run the app in production mode on one port with an empty SQLite database.

    Args:
        tmp_path_factory: Makes a folder for the database.

    Yields:
        The app's base URL.

    Raises:
        RuntimeError: If the app stops or does not answer while starting.
    """
    database_url = f"sqlite+aiosqlite:///{tmp_path_factory.mktemp('e2e') / 'studio.db'}"
    env = {**os.environ, "WEBHOOK_STUDIO_DATABASE_URL": database_url}
    # The commands and their arguments are fixed; nothing comes from outside the test.
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
    command = [sys.executable, "-m", "reflex", "run", "--env", "prod"]
    with subprocess.Popen(  # noqa: S603
        [*command, "--frontend-port", str(PORT), "--backend-port", str(PORT)],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    ) as process:
        url = f"http://localhost:{PORT}"
        try:
            _wait_until_up(url, process)
            yield url
        finally:
            # Reflex starts worker processes; stop the whole group.
            os.killpg(process.pid, signal.SIGTERM)
