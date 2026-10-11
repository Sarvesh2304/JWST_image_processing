# CLAUDE.md: context for Claude sessions on this repository

## What this project is
A JWST image-processing prototype that is being evolved into a **personal AI astrophysics laboratory**:
- real archive data (JWST, HST, Gaia, …);
- the owner's future telescope;
- literature;
- simulations;
- an evidence-graded AI assistant.

The full analysis and plan are in `docs/lab-roadmap/`. **Read `docs/lab-roadmap/README.md` first.**
The implementation task list is in `docs/lab-roadmap/07-roadmap-and-backlog.md` §27.

## Current state (audit of commit cccbb2c)
The original scripts now live in `legacy/` as the **frozen legacy prototype**. `tests/test_legacy_frozen.py`
checks them against `legacy/MANIFEST.sha256`, so never edit them or the manifest. They are scientifically invalid:
- negative clipping causes false detections;
- the main pipeline cannot read JWST multi-extension FITS;
- bandpasses are mislabelled;
- `jwst_real_data_demo.py` saved archive files under fabricated target/filter names (fixed before freezing).

Do not build on them. `docs/lab-roadmap/audit_checks.py` reproduces the defects.
New code goes into the package described in `docs/lab-roadmap/02-target-architecture.md` §21 (`src/astroledger/`).

## Scientific rules (non-negotiable)
1. **Never invent data.** No fabricated measurements, catalogue matches, object identities, papers,
   bibcodes, DOIs, program IDs or telescope metadata. Unknown means "unknown".
2. **Evidence levels.** Label claims L1 Observation (measured), L2 Inference (measurement + cited
   knowledge), or L3 Hypothesis (possible; state how to test). Never present L3 as L1.
3. **Units, uncertainties, masks, WCS and bandpass travel with every array.** Never clip, smooth or
   stretch science arrays. Display transforms belong in the display layer only.
4. **Respect instrument specifics:**
   - JWST data are in the `SCI`/`ERR`/`DQ` extensions;
   - the NIRISS bandpass is in `PUPIL` when `FILTER=CLEAR`;
   - NIRCam pupil-wheel filters pair with filter-wheel elements (e.g. `F444W`+`F405N` means F405N);
   - wrap official pipelines (`jwst`, `calwf3`, drizzlepac); don't reinvent calibration.
5. **Never rename archive files.** Keep `obs_id`, product URIs, `CAL_VER` and `CRDS_CTX` in provenance.
6. **Deterministic algorithms for measurement.** LLMs and ML are for interfaces, retrieval,
   classification and anomaly ranking, never for producing photometry or astrometry.
7. **Hardware (future):** the AI only proposes plans in the typed DSL. A safety kernel validates
   them, and consequential physical actions require the user's confirmation unless a signed
   Trusted-Automation plan is running. Actions toward a safe state (park, close, abort) are always allowed.

## Environment notes (Claude Code cloud sessions, including the iPad app)
- The SessionStart hook (`.claude/hooks/session-start.sh`) creates `.venv` with `pip install -e ".[dev,legacy]"` and puts it on `PATH` with `MPLBACKEND=Agg`.
- Dependencies are declared in `pyproject.toml` (extras: `archives`, `imaging`, `legacy`, `dev`) and locked in `uv.lock`. After changing dependencies, run `uv lock`; CI uses `uv sync --locked`.
- Commands:
  - audit checks: `python docs/lab-roadmap/audit_checks.py`;
  - estimates: `python docs/lab-roadmap/etc_estimates.py`;
  - lint: `ruff check .` and `ruff format --check src tests`;
  - tests: `pytest` (offline; tests needing archives are marked `remote` and excluded by default).
- `tests/science/test_legacy_defects.py` holds strict expected failures against `legacy/`. When new
  code replaces a legacy function, add a *passing* test for it citing the same audit item.
- Archive access needs the cloud environment's network policy to allow the astronomy hosts listed in
  `docs/lab-roadmap/README.md` ("Using this from the iPad"). The default policy blocks `mast.stsci.edu`.
- The container is ephemeral. Commit and push work. Never commit FITS data (`*.fits` is gitignored).

## Conventions
- British spelling in documentation.
- Code style: NumPy-style docstrings; `ruff` clean; type hints on public functions.
- Network-dependent tests are marked and excluded from default CI.
