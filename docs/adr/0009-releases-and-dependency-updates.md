# ADR-0009: Releases and dependency updates

## Status

Accepted

## Context

The project needs semantic versions, a changelog and steady dependency updates. Releases publish nothing; users
build from source.

## Decision

- Commits follow Conventional Commits. A pre-commit hook checks each commit message.
- release-please (a GitHub Action) opens a release pull request. Merging it bumps the version in `pyproject.toml`
  and `uv.lock`, writes `CHANGELOG.md` (it creates the file on the first release), tags `vX.Y.Z` and makes a
  GitHub release.
- `pyproject.toml` is the one place that holds the version. The `uv_build` backend needs it there as a fixed value;
  it cannot read it from a `__version__` file. The package sets `__version__` from the installed package metadata,
  and the health route returns it, so no other file holds a copy to keep in step.
- Dependabot sends weekly grouped updates for `uv` and `github-actions`. It proposes a release only once it is 7
  days old, so a bad release has time to be pulled first. Security updates do not wait.
- Workflows pin each action by commit SHA.
- The CI `audit` job runs pip-audit on every locked package, with hashes, and fails on any known flaw.

## Consequences

- A release needs no manual step beyond merging a pull request.
- Every commit message must follow Conventional Commits; the pre-commit hook rejects any that do not.
- release-please does not know `uv.lock`, so `release-please-config.json` names it as an extra file. Without that,
  `uv sync --locked` would fail after each release.
