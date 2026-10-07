# Part 2: Target Architecture, Provenance, Technology Stack, Repository Structure

> Report sections covered: **7** Target architecture · **18** Provenance/reproducibility architecture ·
> **20** Recommended technology stack · **21** Repository structure · plus the multimodal interface (Part XXII).

---

## 7. Target architecture

### 7.1 Design principles (derived from the audit)

1. **Deterministic science core, AI at the edges.**
   - Calibration, photometry, astrometry, registration, source extraction and PSF work are done by
     established, tested algorithms.
   - The language model plans, explains, retrieves, writes code and talks to you. It never produces a
     number that a measurement step did not produce.
2. **Typed, self-describing data objects.** Every array carries `unit`, `uncertainty`, `mask`, `wcs`,
   `bandpass`, `meta`, plus a provenance ID. Nothing downstream may guess these.
3. **Mission-specific adapters behind a common contract.** Common search, products and provenance
   interfaces, but native calibration (the `jwst` pipeline, `calwf3`, CIAO, CASA) is wrapped, never re-implemented.
4. **Hardware behind a safety kernel the AI cannot bypass.** The AI talks to a sequencer API that
   validates every command against limits and interlocks. Safety does not depend on the AI behaving well.
5. **Local-first, single-user, modular monolith.** One installable package with optional extras. It
   gets split into services only when a component must run on another machine (the observatory controller).
6. **Everything reproducible.** Any figure, table or claim can regenerate its notebook or script from
   recorded inputs, parameters and code versions.
7. **Evidence levels everywhere.** Every output statement is tagged:
   - **L1 Observation** (measured);
   - **L2 Inference** (interpretation supported by measurements plus cited knowledge);
   - **L3 Hypothesis** (possible, insufficiently established).

### 7.2 Component architecture

This is not the diagram in the brief. The main differences:
- a **safety kernel** and **sequencer** sit between the AI and the hardware;
- a single **evidence and provenance store** is shared by every subsystem;
- the AI is a **client** of the science engine, not its centre.

```
                        ┌──────────────────────────────────────────────────────────┐
  INTERFACES            │  Chat (Claude app / web)  ·  Jupyter  ·  CLI  ·  Web UI  │
                        │          (sky view, FITS viewer, spectra, tables)        │
                        └──────────────┬──────────────────────────────┬────────────┘
                                       │ MCP / HTTP (authenticated)    │ Python API
                        ┌──────────────▼────────────────┐             │
  ASSISTANT             │  Assistant orchestrator       │             │
                        │  · tool router (typed tools)  │             │
                        │  · evidence ledger (L1/L2/L3) │             │
                        │  · claim verifier             │             │
                        │  · tutor mode                 │             │
                        └──┬─────────┬─────────┬────────┘             │
                           │         │         │                      │
        ┌──────────────────▼──┐ ┌────▼──────┐ ┌▼───────────────────────▼───────────────────┐
KNOW-   │ Knowledge layer     │ │ Planner   │ │ SCIENCE ENGINE (deterministic)             │
LEDGE   │ · literature (ADS,  │ │ · targets │ │ io · calibration · imaging · photometry    │
        │   arXiv) + RAG      │ │ · weather │ │ astrometry · spectroscopy · time-domain    │
        │ · object knowledge  │ │ · ETC     │ │ crossmatch · interpretation (evidence)     │
        │   (SIMBAD, NED)     │ │ · schedule│ │ simulation · ML (classifiers, anomalies)   │
        │ · instrument docs   │ └────┬──────┘ └───────┬───────────────────┬────────────────┘
        └─────────┬───────────┘      │                │                   │
                  │                  │       ┌────────▼───────┐   ┌───────▼────────────────┐
DATA              │                  │       │ Archive layer  │   │ Personal observation   │
ACCESS            │                  │       │ adapters + VO  │   │ archive (raw → reduced)│
                  │                  │       │ MAST, CDS, Gaia│   └───────▲────────────────┘
                  │                  │       │ IRSA, ESA, ... │           │ FITS + metadata
                  │                  │       └────────┬───────┘           │
        ┌─────────▼──────────────────▼────────────────▼────────────────────┴───────────────┐
STORE   │  Evidence & provenance store: metadata DB · content-addressed file store ·       │
        │  catalogue store (Parquet) · vector index · audit log                            │
        └───────────────────────────────────────────────────────────────▲──────────────────┘
                                                                        │ ingest
════════════════════ network boundary (observatory LAN / VPN) ══════════╪═══════════════════
                        ┌───────────────────────────────────────────────┴──────────────────┐
OBSERVATORY             │  Observatory controller (runs at the telescope)                  │
(separate process,      │  ┌───────────────┐  ┌──────────────┐   ┌───────────────────────┐ │
separate machine)       │  │ Sequencer     │→ │ SAFETY KERNEL│ → │ Hardware abstraction  │ │
                        │  │ (state machine│  │ limits, inter│   │ layer (HAL)           │ │
                        │  │  plans, NL→DSL│  │ locks, perms,│   │ Alpaca │ INDI │ vendor│ │
                        │  │  validation)  │  │ watchdog)    │   └───┬────┴──┬───┴───┬───┘ │
                        │  └───────────────┘  └──────────────┘       │       │       │     │
                        │  PHD2 (guiding) · ASTAP/astrometry.net (plate solving)           │
                        └──────────────────────────────────────────────┼───────┼───────┼───┘
                                                                       ▼       ▼       ▼
                                          mount · camera · focuser · filter wheel · dome/roof
                                          · weather · safety monitor · switches · spectrograph
                     + hardware interlocks independent of all software (rain → roof close)
```

### 7.3 Component responsibilities

| Component | Responsibility | Must never |
|-----------|----------------|------------|
| Archive layer | Discover, retrieve and cache datasets. Expose mission metadata as-is. | Invent metadata, rename files, or hide product level |
| Science engine | Deterministic transformations and measurements with uncertainties | Call an LLM to produce a number |
| Interpretation (evidence engine) | Turn measurements plus catalogue matches plus cited knowledge into L1/L2/L3 statements by explicit rules | Promote L3 to L1 |
| Knowledge layer | Retrieve literature and object knowledge with citations and passages | Answer without retrieved support |
| Assistant | Plan tool calls, explain, teach, draft code and notebooks | Bypass the sequencer or safety kernel |
| Planner | Rank targets using physics (visibility, S/N) plus a science value model | Schedule outside safety envelopes |
| Sequencer | Execute validated plans as a state machine | Accept free-text commands directly |
| Safety kernel | Enforce limits, interlocks, permissions and the watchdog. Always able to reach a safe state. | Depend on the AI or the network to make things safe |
| Store | Persist everything with provenance | Allow untracked edits to derived data |

### 7.4 Deployment topology (evolves by stage)

| Stage | Topology |
|-------|----------|
| MVP | One laptop or desktop: Python package, SQLite, files on disk. Claude Code / the Claude app reads and writes the repository. |
| Personal telescope | **Observatory controller** (small Linux PC at the mount: INDI server and/or Alpaca devices, PHD2, plate solver) plus the **lab machine** (desktop/NAS: archive, science engine, assistant). Connected over the LAN, and remotely via WireGuard/Tailscale, never by port-forwarding device protocols. |
| Research platform | Lab services in Docker Compose (Postgres, object store, API, workers). GPU workstation for ML and embeddings. Controller unchanged. |
| Large-scale | Kubernetes or cloud compute co-located with archives (MAST's AWS copy is in `us-east-1`), multi-user authentication, multiple controllers federated. |

### 7.5 Multimodal interface (Part XXII)

The interface is a **workspace** of linked views around a shared selection, not a chat window with
images pasted in.

| View | Content | Implementation (MVP → later) |
|------|---------|------------------------------|
| Sky view | HiPS backgrounds, footprints (`S_REGION`), catalogue overlays, own fields | Aladin Lite (embeddable JS) |
| Image view | FITS with WCS axes, stretch controls, region tools, DQ overlay | matplotlib + WCSAxes in Jupyter → JS9 or a custom viewer in the web UI |
| Spectrum view | 1-D spectra, line identification, model overlays | `specutils` + Bokeh/Plotly |
| Cube view | Moment maps, channel slider | `spectral-cube` + glue / web viewer |
| Table view | Catalogues with sortable, filterable columns linked to the sky view | pandas/astropy Table → web data grid |
| Time series | Light curves, periodograms, phase folds | lightkurve / astropy `timeseries` + Bokeh |
| Literature | Papers with the exact supporting passages, citation graph | Knowledge layer UI |
| Observatory | Device states, sky camera, safety banner, sequence timeline, **pending confirmations** | Separate pane; safety state always visible |
| Evidence ledger | Every claim with its level, evidence and provenance links | Rendered from the store |
| Chat | Natural-language questions; answers link into the views above | Claude app via MCP; web chat later |

"Generate the notebook that reproduced this analysis" works because every result already has a
provenance DAG. The notebook exporter walks the DAG and emits the calls in order (§18.5).

**iPad access path:**
- **Now:** Claude Code cloud sessions on this repository (see the [README](README.md#using-this-from-the-ipad)).
- **Later:** the platform's own **MCP server**, reachable from the Claude app through a remote MCP
  connector. It is exposed only over an authenticated tunnel, so you can say "what am I looking at"
  from the iPad and it runs on your lab machine.
- Hardware tools are exposed through MCP only at the permission level you grant (§19 in [04](04-observatory.md)).

---

## 18. Provenance and reproducibility architecture

### 18.1 Model

Use the **W3C PROV** concepts (Entity, Activity, Agent), aligned with the **IVOA Provenance Data
Model** so the records are interoperable with VO services.

```
Entity  : raw file, calibrated product, catalogue, figure, table, claim, notebook
Activity: download, calibrate, reduce, measure, crossmatch, interpret, plot, observe
Agent   : you, the platform version, external pipeline (jwst 3.0.0 + CRDS ctx), AI model, telescope
Relations: used, wasGeneratedBy, wasDerivedFrom, wasAssociatedWith, wasInformedBy
```

### 18.2 What is recorded per Activity

| Field | Example |
|-------|---------|
| `activity_id` | ULID (time-sortable) |
| `type`, `function` | `photometry.aperture`, `astroledger.photometry.aperture:measure@0.3.1` |
| Inputs | entity IDs plus **SHA-256** of each file or array (array hash over the canonical bytes) |
| Archive identity | archive, `obs_id`, product URI, dataset DOI where minted (MAST mints DOIs under `10.17909`), download time |
| Calibration context | `CAL_VER`, `CRDS_CTX`, reference file names (JWST); `CAL_VER` / IDCTAB / DRZCAL (HST); own master bias/dark/flat entity IDs |
| Parameters | Canonical JSON (sorted keys, units as strings) and its hash |
| Code | git commit + dirty flag + diff hash; package versions (`importlib.metadata`); lockfile hash; container digest if used |
| Environment | OS, Python, CPU/GPU, random seeds |
| AI involvement | model ID, prompt/template hash, tool calls made, which outputs were AI-drafted vs computed |
| Outputs | entity IDs plus hashes, units, shapes |
| Timing and agent | start/end (UTC), user, permission level (for observatory actions) |

### 18.3 Implementation sketch

```python
@step("photometry.aperture", version="0.3.1")
def aperture_photometry(image: ImageProduct, sources: SourceTable,
                        radius: u.Quantity = 0.2 * u.arcsec) -> PhotometryTable:
    ...
# The decorator records inputs, params, code version and outputs into the store,
# and returns objects whose .provenance_id links back into the DAG.
```

- **Storage:** SQLite (MVP) → Postgres. Files live in a content-addressed store (`sha256/ab/cd…`)
  with human-readable symlinks.
- **FITS outputs:** `HISTORY` cards plus `PROVID` / `PARENTS` keywords, and the full record in an
  attached ASDF/JSON extension.
- **Figures:** the provenance ID goes in PNG text chunks or PDF metadata, and in the caption footer.
- **Observations from your telescope:** the observing log (device states, conditions, guiding RMS,
  plate solutions) is an Activity whose outputs are the raw frames. "Every result traceable to the
  raw observation" then holds by construction.

### 18.4 Integrity rules
- Derived data is immutable. Reprocessing creates new entities and never overwrites old ones.
- `reproduce <entity_id>` re-executes the DAG from raw inputs and compares hashes. A difference
  produces a report of which step diverged and why (code, parameters, reference files, randomness).
- Archive re-downloads are compared by checksum. If MAST has reprocessed a product, the new version
  becomes a new entity with a `wasRevisionOf` link.

### 18.5 Publication packaging
`export <result_id>` produces an **RO-Crate**:
- data references (archive URIs and DOIs, not redistributed proprietary data);
- code at a commit, the lockfile, the provenance graph (PROV-JSON) and an executed notebook;
- a `CITATION.cff`.

This is the unit for papers, theses and Zenodo deposits.

---

## 20. Recommended technology stack

Each choice was evaluated against the alternatives. "Why" gives the deciding reason.

### 20.1 MVP (what one person can build first)

| Concern | Choice | Why (and rejected alternatives) |
|---------|--------|----------------------------------|
| Language / env | Python ≥ 3.11, **uv** + `pyproject.toml` + lockfile | Fast, reproducible lockfiles. Conda only if a dependency demands it (e.g., CIAO, which ships its own). |
| Core astronomy | **astropy** (units, coordinates, WCS, time, NDData, tables, visualisation) | Community standard. Everything else interoperates with it. |
| Archive access | **astroquery** (MAST, SIMBAD, VizieR, Gaia, IRSA, ESA, ALMA, HEASARC…), **pyvo** (TAP/SIA/SSA/SCS/DataLink) | astroquery for mission-specific conveniences; pyvo for the generic VO path and ADQL. |
| JWST / HST | **jwst** + **stdatamodels** + **crds** (optional extra), **stpsf**, **synphot/stsynphot**; **drizzlepac**, **wfc3tools/acstools** (HST extra) | Official pipelines. Heavy, so optional extras. |
| Imaging and photometry | **photutils**, **reproject**, **regions**, **astroscrappy**, **sep** (fast extraction) | photutils for completeness and correctness. sep for speed on own data. |
| Own-CCD reduction | **ccdproc** | Built on astropy's CCDData with uncertainty propagation. |
| Astrometry | **astrometry.net** (local index) or **ASTAP** for blind solving; astropy for fitting; Gaia DR3 reference | Both are mature. ASTAP is fast and cross-platform; astrometry.net is the reference for blind solving. |
| Spectroscopy | **specutils**, **specreduce** | Astropy-coordinated packages. |
| Time domain | **lightkurve**, `astropy.timeseries` (Lomb–Scargle, BLS) | TESS/Kepler native; standard periodograms. |
| Planning | **astroplan**, **skyfield** (fast ephemerides), JPL Horizons via astroquery | astroplan has constraint-based observability and schedulers built in. |
| Storage | **SQLite** (metadata + provenance), **Parquet + DuckDB** (catalogues), files on disk | Zero-ops. DuckDB queries Parquet catalogues of millions of rows on a laptop. |
| Vector search | **sqlite-vec** or **LanceDB** (embedded) + SQLite FTS5 (BM25) | Hybrid lexical plus dense search with no server. |
| LLM | **Claude via the Anthropic API** with tool use; the platform exposed as an **MCP server** | Strong tool use and long-context reading of papers. MCP lets the Claude app (including on iPad) use your tools directly. |
| Visualisation | matplotlib + WCSAxes, **Aladin Lite**, Bokeh/Plotly | Static figures plus interactive sky. |
| UI | **Jupyter** + CLI (Typer); minimal **FastAPI** endpoints | Do not build a web front-end before the science engine exists. |
| Hardware | **alpyca** (Alpaca client), **pyindi-client** (INDI client), PHD2 event server (JSON over TCP 4400) | Standards-based; see [04](04-observatory.md) §12. |
| Testing | pytest, hypothesis, pytest-remotedata-style markers (network tests opt-in), **science validation tests** | Offline CI is deterministic. Science tests compare against known values. |
| CI | GitHub Actions: ruff, mypy (gradually), offline tests, notebook execution on tiny fixtures | Free for public repositories. |
| Docs | Sphinx + MyST + numpydoc | Matches the astropy ecosystem; notebooks render as docs. |

### 20.2 Research platform (if the project grows)

| Concern | Change |
|---------|--------|
| Metadata / provenance | **PostgreSQL** + **pgvector**, with a HEALPix index column (or the `q3c` extension) for cone searches |
| Files | **MinIO** (S3-compatible) or a NAS with checksums; JWST/HST caches with CRDS mirrors |
| Workflows | **Prefect** or **Dagster** for scheduled and remote reductions (Prefect is lighter for one person). The observatory sequencer stays separate: it is real-time control, not a data DAG. |
| Telemetry | NATS or MQTT for device telemetry → **TimescaleDB/InfluxDB** + **Grafana** dashboards |
| API / UI | FastAPI service + web front-end (Svelte/React) embedding Aladin Lite, JS9 or a custom FITS viewer; JupyterHub |
| Compute | GPU workstation (one GPU with 24 GB or more) for ML training/inference, embeddings and optional local LLMs (vLLM/Ollama); **Numba** for custom kernels; **JAX** for differentiable forward models |
| Containers | Docker Compose; images pinned by digest and recorded in provenance |

### 20.3 Large-scale platform (many users, large data, multiple observatories)

| Concern | Change |
|---------|--------|
| Compute near data | Run next to archives: MAST public data on AWS (`s3://stpubdata`), NASA's Fornax Science Console, ESA Datalabs. Do not download petabytes. |
| Distributed processing | **Dask** or **Ray** on Kubernetes |
| Auth | OIDC (Keycloak), per-project RBAC, per-observatory device permissions |
| Search | Dedicated vector database (Qdrant/Weaviate) or OpenSearch hybrid search |
| Publishing | Serve your own data through IVOA protocols with **DaCHS** (GAVO Data Center Helper Suite), so others can query your observatory archive with TAP/SIA |
| Streams | Kafka consumers for Rubin/ZTF alert brokers; event-driven follow-up triggers |
| Observatories | Federated controllers, each with its own local safety kernel; central scheduler issues **requests**, never direct commands |

### 20.4 What not to adopt early
- A custom web front-end: Jupyter plus the Claude app are enough until Phase 4.
- Kubernetes, Kafka or a microservice split: a modular monolith is right for one developer.
- Fine-tuning an LLM: retrieval and tools give better, verifiable results, and fine-tuned knowledge cannot be cited.
- A custom device driver framework: use INDI or Alpaca drivers.

---

## 21. Repository structure

This evolves the current repository rather than starting another one. Git history and the "JWST
image processing" origin are preserved, and the legacy scripts remain runnable for comparison. The
package name `astroledger` is a working name (the names `astrolab` and `astrolabium` were already taken on PyPI).

```
JWST_image_processing/                # rename later if wanted, once Phase 3 lands
├── pyproject.toml                    # one package, optional extras: [jwst] [hst] [observatory] [ai] [sim] [ml]
├── uv.lock
├── CLAUDE.md                         # rules + context for Claude sessions (exists now)
├── README.md  CITATION.cff  LICENSE
├── .claude/                          # SessionStart hook for cloud sessions (exists now)
├── src/astroledger/
│   ├── core/            # Product types (Image, Spectrum, Cube, TimeSeries, Catalog), Bandpass,
│   │                    # units helpers, IDs, EvidenceLevel enum, errors
│   ├── provenance/      # @step decorator, PROV records, hashing, RO-Crate export, reproduce()
│   ├── store/           # metadata DB, content-addressed files, catalogue store, personal archive
│   ├── io/              # format sniffing; FITS/ASDF/VOTable/Parquet/HDF5 readers → core types
│   ├── archives/
│   │   ├── base.py      # MissionAdapter protocol
│   │   ├── vo/          # pyvo TAP/SIA/SSA/ObsCore helpers, Sesame, MOC/HiPS
│   │   ├── mast/        # JWST, HST, TESS, Kepler/K2, PS1, GALEX
│   │   ├── cds/         # SIMBAD, VizieR, XMatch, hips2fits
│   │   ├── esa/         # Gaia, Euclid, XMM-Newton (XSA), eHST/eJWST mirrors
│   │   ├── irsa/  heasarc/  alma/  noirlab/  sdss/  rubin/  horizons/  mpc/  aavso/  tns/
│   ├── missions/        # instrument knowledge + pipeline wrappers
│   │   ├── jwst/        # modes, product levels, bandpasses, artefacts, pipeline runner (CRDS)
│   │   ├── hst/         # WFC3, ACS, STIS, COS; drizzlepac wrapper
│   │   └── tess/ …
│   ├── calibration/     # own-telescope CCD/CMOS: bias, dark, flat, linearity, masters
│   ├── imaging/         # background, detection, segmentation, reprojection, PSF matching, mosaics
│   ├── photometry/      # aperture, PSF, differential, zero points (Gaia XP synthetic), transforms
│   ├── astrometry/      # plate solving wrappers, Gaia fitting, epoch propagation, ADES export
│   ├── spectroscopy/    # extraction, wavelength calibration, flux calibration, line fitting
│   ├── timedomain/      # light curves, periodograms, transit fitting, difference imaging
│   ├── crossmatch/      # positional + probabilistic matching, chance-coincidence, conflicts
│   ├── interpret/       # "What am I looking at?" evidence engine; rules → L1/L2/L3 statements
│   ├── knowledge/       # literature clients (ADS/SciX, arXiv), RAG index, object knowledge
│   ├── assistant/       # tool schemas, MCP server, orchestrator, claim verifier, tutor
│   ├── planning/        # site/equipment profiles, visibility, ETC, weather, target scoring, scheduler
│   ├── observatory/     # runs on the controller machine
│   │   ├── hal/         # device interfaces; backends: alpaca/, indi/, sim/, vendor/
│   │   ├── safety/      # interlocks, limits, permission tiers, watchdog, safe-state actions
│   │   ├── sequencer/   # plan DSL, validator, state machine, NL→DSL proposals
│   │   ├── acquisition/ # exposure handling, FITS header writer, ingest to store
│   │   └── services/    # PHD2 client, plate-solver client
│   ├── simulation/      # wrappers: REBOUND, galpy/gala, synthetic images (GalSim/STPSF), injection
│   ├── ml/              # classifiers, anomaly detection, model cards
│   ├── viz/             # display stretches, WCS plots, Lupton RGB, comparison figures
│   └── cli/             # `astroledger fetch | inspect | measure | explain | plan | observe | reproduce`
├── pipelines/           # declarative workflow definitions (YAML) for recurring analyses
├── configs/             # site.yaml, equipment/*.yaml, archives.yaml, safety_limits.yaml (versioned)
├── notebooks/           # tutorials/ (learning), analyses/ (reproduced results, exported by provenance)
├── tests/
│   ├── unit/  integration/ (network, opt-in)  science/ (validation vs known values)
│   ├── hardware/ (against Alpaca OmniSim + INDI simulators)  fixtures/ (tiny FITS, generated)
├── docs/                # Sphinx; lab-roadmap/ (this report)
├── legacy/              # the original nine scripts, frozen, with a README pointing to the audit
└── data/                # gitignored: cache/, archive/, personal/
```

**Why this shape:**
- `core` and `provenance` are dependencies of everything and depend on nothing in the package.
- `missions/` (knowledge about instruments) is kept separate from `archives/` (how to fetch). HST data can come from MAST or from ESA's eHST, and the instrument knowledge is the same.
- `observatory/` is importable on its own (`pip install astroledger[observatory]`) so the controller machine does not need JWST pipelines or LLM libraries.
- `interpret/` is separate from `assistant/`. The evidence engine is deterministic and testable without an LLM; the assistant only renders and discusses its output.
