# From JWST Image Processing to a Personal AI Astrophysics Laboratory

**Repository analysis, scientific audit, architecture and roadmap.** Prepared 2026-10-06 for
`Sarvesh2304/JWST_image_processing` (audited commit `cccbb2c`).

## Executive summary

**Where the repository stands**
- The repository is a **visualisation prototype**, not yet a scientific pipeline.
- Running its own code against controlled inputs reproduced 8 serious defects, with
  [`audit_checks.py`](audit_checks.py) as evidence:
  - The main pipeline cannot open JWST files at all, because it reads the empty primary HDU.
  - Its "calibration" clips negative pixels. On pure noise, this produces 600 false "sources" in a 1024² image.
  - Bandpasses are mislabelled (NIRISS `CLEAR`/`PUPIL`, NIRCam pupil-wheel filters).
  - One script saves archive files under fabricated target and filter names. NGC 3132 was never observed in F444W, and the files come from a supernova follow-up in Abell 2744.
- The foundations it chose (Astropy, photutils, astroquery) are right.

**What to do first**
- Freeze the legacy scripts.
- Build a small, tested core in which every array carries units, uncertainties, masks, WCS, bandpass and provenance.
- Archives, the AI assistant and the telescope are all multipliers of that core, so it must be correct first.

**How the target system is shaped**
- A **deterministic science engine**.
- **Mission adapters** over IVOA standards (TAP/ObsCore, SIA, MOC, HiPS) with mission-specific semantics preserved.
- An **evidence engine** that grades every statement as Observation (L1), Inference (L2) or Hypothesis (L3).
- A **literature layer** that refuses to claim without a retrieved passage.
- An **assistant** that operates the platform through typed tools (exposed over MCP, so it works from the Claude app).
- An **observatory subsystem** in which the AI can only *propose* plans. A safety kernel validates them, and you confirm them.

**Telescope strategy**
- Use **ASCOM/Alpaca and INDI** behind our own hardware-abstraction layer, and buy hardware that has both kinds of driver.
- Get science from the telescope with existing capture software first, then build control against simulators.
- Autonomy comes last, behind hardware interlocks.

**Sequence**
correctness → JWST/HST core → measurement → discovery and evidence engine → knowledge and assistant →
own-data pipeline → planning → assisted control → science workflows → spectroscopy → automation.

## Contents (mapping to the 30 requested report sections)

| # | Section | Document |
|--:|---------|----------|
| 1 | Executive assessment | [01 Repository audit](01-repository-audit.md#1-executive-assessment) |
| 2 | Current repository capabilities | [01](01-repository-audit.md#2-current-repository-capabilities) |
| 3 | Code review | [01](01-repository-audit.md#3-code-review-engineering) |
| 4 | Scientific review | [01](01-repository-audit.md#4-scientific-review) |
| 5 | Critical problems | [01](01-repository-audit.md#5-critical-problems-ranked) |
| 6 | Immediate improvements | [01](01-repository-audit.md#6-immediate-improvements-phase-0-roughly-12-weeks-part-time) |
| 7 | Target architecture (incl. multimodal interface) | [02 Architecture](02-target-architecture.md#7-target-architecture) |
| 8 | Real-data architecture | [03 Data & analysis](03-data-missions-analysis.md#8-real-data-architecture) |
| 9 | JWST/HST integration | [03](03-data-missions-analysis.md#9-jwst-and-hst-integration) |
| 10 | Multi-mission integration | [03](03-data-missions-analysis.md#10-multi-mission-integration) |
| 11 | Telescope integration (incl. science feasibility, NL control, autonomy) | [04 Observatory](04-observatory.md#11-telescope-integration) |
| 12 | Hardware interoperability strategy | [04](04-observatory.md#12-hardware-interoperability-strategy) |
| 13 | Observation-planning architecture | [04](04-observatory.md#13-observation-planning-architecture) |
| 14 | Scientific-analysis engine ("What am I looking at?", cross-matching, pro-data comparison) | [03](03-data-missions-analysis.md#14-scientific-analysis-engine) |
| 15 | AI assistant architecture | [05 AI, knowledge, simulation](05-ai-knowledge-simulation.md#15-ai-assistant-architecture) |
| 16 | Literature/RAG architecture | [05](05-ai-knowledge-simulation.md#16-literature--knowledge-rag-architecture) |
| 17 | Simulation architecture | [05](05-ai-knowledge-simulation.md#17-simulation-architecture) |
| 18 | Provenance/reproducibility architecture | [02](02-target-architecture.md#18-provenance-and-reproducibility-architecture) |
| 19 | Security and hardware-safety architecture | [04](04-observatory.md#19-security-and-hardware-safety-architecture) |
| 20 | Recommended technology stack (MVP / research / large-scale) | [02](02-target-architecture.md#20-recommended-technology-stack) |
| 21 | Repository structure | [02](02-target-architecture.md#21-repository-structure) |
| 22 | Hardware procurement criteria (configurations A/B/C) | [04](04-observatory.md#22-hardware-procurement-criteria) |
| 23 | Beginner/intermediate/advanced/research projects | [06 Projects](06-projects.md) |
| 24 | MSc/PhD-level research opportunities | [06](06-projects.md#24-mscphd-level-research-opportunities-how-to-use-this-platform-as-preparation) |
| 25 | Development roadmap | [07 Roadmap](07-roadmap-and-backlog.md#25-development-roadmap) |
| 26 | Prioritised backlog | [07](07-roadmap-and-backlog.md#26-prioritised-backlog) |
| 27 | First 10–20 implementation tasks | [07](07-roadmap-and-backlog.md#27-first-1020-implementation-tasks-do-these-in-this-order) |
| 28 | Example workflows | [08 Workflows](08-workflows-and-interactions.md#28-example-workflows) |
| 29 | Example AI interactions | [08](08-workflows-and-interactions.md#29-example-ai-interactions-designed-behaviour) |
| 30 | Long-term vision | [08](08-workflows-and-interactions.md#30-long-term-vision) |

Progress reports: [update-2026-10-06.md](update-2026-10-06.md) (tasks 1–12) and [update-2026-10-07.md](update-2026-10-07.md) (tasks 13–15), validated on authentic JWST data.

Supporting files:
- [`audit_checks.py`](audit_checks.py): reproducible evidence for the audit.
- [`etc_estimates.py`](etc_estimates.py): the exposure-time numbers behind the hardware configurations.

## Using this from the iPad

1. **Read:** these Markdown files render in the GitHub app or Safari. The same report is also published as a claude.ai artifact (link in the session that created it).
2. **Continue the conversation:** open the Claude app → **Code** → the session that produced this report. Cloud sessions persist; the container behind them is recreated as needed.
3. **Start new work:** in the Claude app → **Code** → new session on `Sarvesh2304/JWST_image_processing`. Then:
   - `CLAUDE.md` loads the project rules automatically;
   - the SessionStart hook installs the Python stack (about 1 minute on a fresh container);
   - ask for a task, e.g. *"Do task 1 from docs/lab-roadmap/07-roadmap-and-backlog.md §27"*.
4. **Allow the archives through the network policy.** Cloud environments block most hosts by default; this audit found `mast.stsci.edu` blocked.
   - Where: environment settings → Network access → **Custom**.
   - Keep the default package-manager list.
   - Add, as needed per phase:

| Purpose | Hosts |
|---------|-------|
| MAST (JWST/HST/TESS/PS1) | `mast.stsci.edu`, `archive.stsci.edu`, `catalogs.mast.stsci.edu`, `ps1images.stsci.edu`, `stpubdata.s3.amazonaws.com` |
| JWST/HST reference files | `jwst-crds.stsci.edu`, `hst-crds.stsci.edu` |
| Documentation | `jwst-docs.stsci.edu`, `www.stsci.edu` |
| CDS (SIMBAD, VizieR, Sesame, XMatch, HiPS) | `simbad.cds.unistra.fr`, `vizier.cds.unistra.fr`, `cds.unistra.fr`, `cdsxmatch.u-strasbg.fr`, `alasky.cds.unistra.fr` |
| Gaia | `gea.esac.esa.int` |
| IRSA / NED | `irsa.ipac.caltech.edu`, `ned.ipac.caltech.edu` |
| Solar System | `ssd.jpl.nasa.gov`, `ssd-api.jpl.nasa.gov`, `vo.imcce.fr`, `minorplanetcenter.net` |
| Literature | `api.adsabs.harvard.edu`, `export.arxiv.org`, `arxiv.org` |

5. **Later (Phase 4+):** the platform's MCP server, reached through a VPN as a remote connector, lets the Claude app on the iPad call your lab's tools directly. Hardware tools are only exposed at the permission tier you grant.

## Sources checked for time-sensitive statements (accessed 2026-10-06)
- JWST pipeline releases: [PyPI `jwst`](https://pypi.org/project/jwst/), [JWST pipeline docs](https://jwst-pipeline.readthedocs.io/)
- MAST programmatic access: [MAST API access (JDox)](https://jwst-docs.stsci.edu/accessing-jwst-data/mast-api-access), [astroquery MastMissions downloads](https://archive.stsci.edu/contents/newsletters/february-2025/astroquery-now-supports-downloads-through-hst-and-jwst-search-interfaces), [JWST data in AWS](https://archive.stsci.edu/contents/newsletters/january-2025/jwst-data-in-aws-cloud)
- Program facts: [NGC 3132 ERO program 2733](https://www.stsci.edu/jwst-program-info/download/jwst/pdf/2733/), [DDT 2756 in Abell 2744 (Chen et al.)](https://arxiv.org/abs/2301.02179)
- Data releases: [Gaia DR4 news](https://www.cosmos.esa.int/web/gaia/news), [Euclid DR1 timeline](https://www.cosmos.esa.int/web/euclid/dr1-timeline), [Rubin EDP2](https://community.lsst.org/t/early-data-preview-2-edp2-release-date-2026-07-27/12226), [SDSS DR20](https://www.sdss.org/dr20/)
- Device standards: [ASCOM Platform 7.1](https://scopetrader.com/ascom-platform-7.1-released/amp/), [alpyca](https://pypi.org/project/alpyca), [pyindi-client](https://pypi.org/project/pyindi-client), [INDI docs](https://docs.indilib.org/), [PHD2 event monitoring](https://github.com/OpenPHDGuiding/phd2/wiki/EventMonitoring)
- Libraries: [photutils 3.0](https://photutils.readthedocs.io/en/stable/whats_new/3.0.html)
- Literature API: [ADS/SciX API](https://ui.adsabs.harvard.edu/blog/openapi-docs)

Not verified from this environment (`www.stsci.edu` program pages were blocked): the category of JWST
program 1063. The audit states only that it is not an ERS program.
