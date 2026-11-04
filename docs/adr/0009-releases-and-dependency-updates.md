# ADR-0009: Releases and dependency updates

## Status

Accepted

## Context

The project needs semantic versions, a changelog and steady dependency updates. Releases publish nothing; users
build from source.

## Decision

- Commits follow Conventional Commits. A pre-commit hook checks each commit message.
- release-please (a GitHub Action) opens a release pull request. Merging it sets the version in
  `reflex_fastapi_webhook_studio/_version.py`, writes `CHANGELOG.md` (it creates the file on the first release), tags
  `vX.Y.Z` and makes a GitHub release.
- `reflex_fastapi_webhook_studio/_version.py` is the one place that holds the version. Hatchling reads it at build
  time, the package imports it, and the health route returns it. `pyproject.toml` marks the version as dynamic, so
  neither it nor `uv.lock` holds a copy. To change the version by hand, edit that one line.
- Dependabot sends weekly grouped updates for `uv` and `github-actions`. It proposes a release only once it is 7
  days old, so a bad release has time to be pulled first. Security updates do not wait.
- Workflows pin each action by commit SHA.
- The CI `audit` job runs pip-audit on every locked package, with hashes, and fails on any known flaw.

## Consequences

- A release needs no manual step beyond merging a pull request.
- Every commit message must follow Conventional Commits; the pre-commit hook rejects any that do not.
- release-please uses its `simple` release type, which knows no Python files, and updates `_version.py` through the
  `x-release-please-version` mark on its version line. `release-please-config.json` names the file as an extra file.
