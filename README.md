# JWST Image Processing → Personal AI Astrophysics Laboratory

This repository started as a JWST image-processing prototype. It is being rebuilt, step by step, into a
research-grade environment that combines:
- real archive data (JWST, HST, Gaia, …);
- observations from a personal telescope;
- the scientific literature;
- simulations;
- an AI assistant that separates measurement from interpretation.

## Status

**Phase 0 (honest baseline) is complete. Phase 1–2 tasks 5–12 are done; no full analysis pipeline yet.**

What works now (all tested; numbers below are on authentic JWST data of NGC 3132, program 2733):

| Capability | Module / command | Real-data check |
|---|---|---|
| Read JWST/HST/plain FITS with units, ERR, DQ mask, WCS | `astroledger.io.open_image` | MIRI F770W `cal` file, verified against its archive checksum |
| Resolve the true bandpass (NIRCam pupil wheel, NIRISS CLEAR/PUPIL, HST ACS) | `astroledger.core.Bandpass` | F444W+F405N → F405N, F444W+F470N → F470N |
| Sky-axis display and chromatic colour composites (data untouched) | `astroledger.viz` | F356W/F405N/F470N composite |
| Provenance of every step (inputs' checksums, parameters, versions, git commit) | `astroledger.provenance` | all downloads and measurements recorded |
| Archive access: MAST search; MAST's public AWS copy with verified downloads and range-request cutouts | `astroledger.archives` | cutout pixels byte-identical, WCS exact |
| Fact sheet of a file | `astroledger inspect FILE` | — |
| Aperture photometry in Jy/AB with uncertainties | `astroledger.photometry` | matches JWST pipeline catalogue to <1e-6 |
| Source detection with false-positive estimate | `astroledger.imaging.detect` | 34/34 pipeline sources on clean sky |

The original scripts are **frozen** in [`legacy/`](legacy/README.md) and documented as scientifically invalid. The audit is in [`docs/lab-roadmap/01-repository-audit.md`](docs/lab-roadmap/01-repository-audit.md), and the plan in [`docs/lab-roadmap/`](docs/lab-roadmap/README.md).

## Repository layout

```
src/astroledger/    the new package (working name): core, io, viz, provenance, archives, photometry, imaging, cli
tests/              unit tests, science tests (incl. documented legacy defects), legacy freeze check
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
