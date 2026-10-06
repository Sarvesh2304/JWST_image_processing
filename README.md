# JWST Image Processing → Personal AI Astrophysics Laboratory

This repository started as a JWST image-processing prototype. It is being rebuilt, step by step, into a
research-grade environment that combines:
- real archive data (JWST, HST, Gaia, …);
- observations from a personal telescope;
- the scientific literature;
- simulations;
- an AI assistant that separates measurement from interpretation.

## Status

**Phase 0 (honest baseline) is complete; Phase 1 (JWST/HST product core) is next. There is no working science pipeline yet.**

- A code and scientific audit of the original prototype found that it cannot produce trustworthy
  measurements:
  - it cannot open JWST science files;
  - its "calibration" creates false sources;
  - it mislabels filters.

  Details: [audit](docs/lab-roadmap/01-repository-audit.md). Reproducible evidence:
  [`docs/lab-roadmap/audit_checks.py`](docs/lab-roadmap/audit_checks.py).
- The original scripts are **frozen** in [`legacy/`](legacy/README.md), kept for comparison only.
  Do not use their output scientifically.
- The plan (architecture, data sources, telescope strategy, AI design, projects, roadmap) is in
  [`docs/lab-roadmap/`](docs/lab-roadmap/README.md).

## Repository layout

```
src/astroledger/    the new package (working name; skeleton only so far)
tests/              test suite: legacy freeze check, documented legacy defects (tests/science/)
docs/lab-roadmap/   audit, architecture, roadmap, prioritised tasks (start here)
legacy/             original prototype, frozen (checksummed)
.github/workflows/  CI: lint + offline tests on Python 3.11 and 3.13
.claude/            setup hook for Claude Code cloud sessions
CLAUDE.md           project rules for AI-assisted development
pyproject.toml, uv.lock   package metadata, optional extras, locked dependencies
```

## Working on it

- **Next steps:** [`docs/lab-roadmap/07-roadmap-and-backlog.md` §27](docs/lab-roadmap/07-roadmap-and-backlog.md#27-first-1020-implementation-tasks-do-these-in-this-order) lists the first 20 implementation tasks in order.
- **Run the checks locally:**

  ```bash
  uv sync --extra dev --extra legacy      # or: pip install -e ".[dev,legacy]"
  uv run pytest                           # freeze check + documented legacy defects (expected failures)
  uv run ruff check .
  uv run python docs/lab-roadmap/audit_checks.py   # the audit's original evidence script
  ```

  `tests/science/test_legacy_defects.py` states what correct code must do. Each test fails
  against the frozen legacy code and is marked as an expected failure. The new package must
  pass equivalent tests.

- **Claude Code** sessions (including from the Claude iPad app) install these dependencies automatically.
  Access to astronomy archives requires allowing their hosts in the cloud environment's network
  settings; see [Using this from the iPad](docs/lab-roadmap/README.md#using-this-from-the-ipad).

## Scientific principles

These apply to everything new in this repository:
- No invented data, identifications or citations.
- Every measurement carries its units, uncertainty and provenance.
- Every claim is labelled as observation, inference or hypothesis.
- Official mission pipelines are wrapped, never reimplemented.

The full list is in [`CLAUDE.md`](CLAUDE.md).

## License

MIT (as declared by the original project).
