# ADR-0008: Docs with Zensical

## Status

Accepted

## Context

MkDocs 1.6.1, its latest release, lists Python only up to 3.12. Material for MkDocs now gets only critical fixes.
Zensical comes from the same team as Material, is under active work and builds `mkdocs.yml` sites as they stand. It
has not reached 1.0.

## Decision

Build the docs with Zensical from `mkdocs.yml`. The `docs` dependency group pins it in `uv.lock`. The `docs.yml`
workflow builds the site on each push to `main` and deploys it to GitHub Pages.

## Consequences

- The tool keeps getting updates.
- Before 1.0, minor releases may break things, so `uv.lock` pins the version and Dependabot proposes updates.
- Because the config stays `mkdocs.yml`, a move back to MkDocs and Material is a small change.
- `zensical build --strict` builds this `mkdocs.yml` with no warnings.
