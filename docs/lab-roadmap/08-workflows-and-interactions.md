# Part 8: End-to-End Workflows, Example AI Interactions, Long-Term Vision

> Report sections covered: **28** Example workflows · **29** Example AI interactions · **30** Long-term vision.
>
> **Reading note:** these are *designs*, not transcripts of a running system. Values in `[brackets]` are
> placeholders that the real system fills from measurements, headers or retrieved records. Constants
> quoted without brackets are instrument facts (e.g. F200W pivot ≈ 1.99 µm) or well-known coordinates.
> This follows the platform's own rule: no measurement or identifier is invented, even in an example.

---

## 28. Example workflows

### Workflow 1: "Find interesting JWST images of nearby galaxies and explain what is visible."

| Step | What happens | Component / call |
|------|-------------|------------------|
| Intent | Assistant drafts: `{class: galaxy, distance < 20 Mpc, JWST imaging, calib_level ≥ 3, public}` and shows it for edit | assistant |
| Discovery | Sample from NED distances or a curated list, or start from a known Treasury program: **PHANGS-JWST (GO 2107)** imaged 19 nearby star-forming galaxies with NIRCam + MIRI | `archives/ned`, `archives/mast` |
| Search | `Observations.query_criteria(obs_collection="JWST", proposal_id="2107", calib_level=3, dataproduct_type="image")`, plus PHANGS HLSPs | MAST adapter |
| Ranking | Group by galaxy, list bands (F200W, F300M, F335M, F360M, F770W, F1000W, F1130W, F2100W), depth, coverage. **Show the table; the user picks** (e.g. NGC 628). | planner-like ranking |
| Retrieval | Stage-3 `i2d` per band (or HLSP mosaics), checksums, provenance | `fetch` |
| Processing | Open with units/ERR/DQ, reproject to a common grid, Lupton RGB with chromatic ordering (display only) | `io`, `imaging`, `viz` |
| Analysis | Background, detection, photometry; Gaia stars flagged; band-ratio maps (e.g. F335M PAH excess, F770W/F2100W) | `photometry`, `imaging` |
| Interpretation | Evidence engine: L1 (bands, depths, structures measured); L2 (PAH-bright filaments trace dust associated with the ISM, supported by bandpass physics + cited PHANGS papers); L3 (e.g. "bubble-like cavities may be feedback-driven; test: compare with Hα/H II region catalogues and ages") | `interpret` |
| Literature | ADS: `bibcode` list for "PHANGS-JWST" + NGC 628, passages for each L2 claim; dataset ↔ paper links | `knowledge` |
| Output | Report + figures + reproducible notebook | `export_notebook` |

### Workflow 2: "What can I observe tonight?"

```
Site (lat, lon, elev, horizon mask) + now ─► astronomical night [start, end] (astroplan)
 ─► forecast: cloud/humidity/wind by hour (weather adapter) → usable windows, e.g. [21:10–02:30]
 ─► Moon: phase [x%], position → per-band separation constraints
 ─► candidates = project lists ∪ AAVSO alerts/campaigns ∪ transit predictions ∪ NEOCP ∪ bright TNS
 ─► for each: altitude curve, airmass, meridian, horizon → observable window
 ─► ETC (calibrated camera + sky SQM) → achievable S/N or mmag precision in the window
 ─► value model (priority × time-criticality × gap × learning) gated by feasibility
 ─► schedule (greedy/astroplan PriorityScheduler) → draft Plan + reasons for each choice
```

### Workflow 3: "Observe M51."

| Step | Check / action | Tier |
|------|----------------|------|
| Resolve | SIMBAD: M 51 = NGC 5194, ICRS 13h29m52.7s +47°11′43″ (record ID kept) | 0 |
| Visibility | Current alt/az, time above limit, meridian time, Moon separation | 0 |
| Pre-flight | Devices connected; `IsSafe`; roof state; camera at set-point; disk; mount limits; dawn margin | 0 |
| Proposal | `Plan(Slew → CenterBySolve → Guide → Expose(L/R/G/B or Hα…) → Calibration)` with durations | 0 (proposal) |
| Confirm | User confirms the plan diff | **1** |
| Slew | Safety kernel mints token → HAL `slew` | 1 |
| Plate solve and centre | Solve → offset → sync/re-slew until < 10″ | 1 |
| Focus | Autofocus (HFR V-curve) if temperature drift > threshold | 1 |
| Guide | PHD2 start, settle < 1.5″ | 1 |
| Expose | Sequence with dithers; per-frame QA (FWHM, background, star count); abort rules | 1 |
| Calibration | Flats (panel/twilight), darks at matching temperature and exposure, bias | 1 |
| Park / close | Safe-state actions | 3 (always allowed) |
| Store | Raw frames (immutable, hashed) + observing log → personal archive; provenance Activity | — |

### Workflow 4: "Analyse my M51 observations."

```
raw frames ─► masters (bias/dark/flat; ccdproc) ─► calibrated frames (+ uncertainty from gain/read noise)
 ─► per-frame QA (FWHM, ellipticity, background, transparency) → reject outliers (recorded)
 ─► plate solve each frame (WCS) ─► registration (reproject to a reference grid)
 ─► stack (sigma-clipped mean with weights; record the combine parameters)
 ─► photometric calibration: field stars × Gaia DR3 XP synthetic photometry → zero point + colour term
 ─► source detection (FP-controlled) → photometry with errors
 ─► cross-match (Gaia stars = foreground; SIMBAD/NED for M51/NGC 5195 and catalogued H II regions or clusters)
 ─► surface-brightness profile / colour map (with depth stated)
 ─► interpretation (L1/L2/L3) with explicit seeing-limited caveats
```

### Workflow 5: "Compare my M51 observation with Hubble and JWST."

| Step | Detail |
|------|--------|
| Archive search | MAST: HST ACS/WFC M51 mosaic (Hubble Heritage) and other HST programmes; JWST NIRCam/MIRI programmes covering M51 (e.g. the FEAST programme). Each listed with program ID, bands and depth as returned by MAST. |
| Retrieval | Stage-3/HLSP products; cutouts over your field |
| Wavelength comparison | Bandpass table: your V/r′/Hα vs HST F435W/F555W/F658N/F814W vs JWST F200W/F335M/F770W… What each traces: young stars, ionised gas (Hα), old stars, dust/PAH. |
| Resolution comparison | Your measured FWHM (e.g. `[2.6″]`) vs HST (~0.1″) vs NIRCam F200W (~0.064″) vs MIRI F770W (~0.27″); physical scales from a cited distance |
| Matched views | Professional images convolved to your PSF and resampled to your pixels; difference maps |
| Interpretation | What you reproduce (spiral arms, integrated colours, bright H II complexes in Hα); what you cannot (individual clusters, dust-embedded star formation seen in MIRI); where your data **adds** value (time-domain monitoring, for example of a future supernova) |

### Workflow 6: "Can I do a meaningful project on this object?"

```
object + your data + your equipment
 ─► what exists: archive coverage table (missions, bands, epochs), SIMBAD/NED bibliography count by year
 ─► literature map: top-cited + recent papers (ADS), with passages on open questions ("future work")
 ─► existing measurements (catalogues: VizieR) and their precision
 ─► gap candidates (each L3, with the evidence for the gap and the queries run)
 ─► feasibility vs your ETC (precision, cadence, baseline) → feasible / marginal / infeasible
 ─► proposed methodology (platform functions), expected precision, risks, outputs (RNAAS/JAAVSO/MPB/paper)
```

---

## 29. Example AI interactions (designed behaviour)

### 29.1 "What can I observe tonight?"

> **User:** What can I observe tonight?
>
> **Assistant:** From your site profile and tonight's forecast, you have about **[3 h 50 min]** of
> usable dark time, **[21:40–01:30]** local. Cloud cover is forecast to rise above 60% after **[01:30]**.
> The Moon is **[38%]** illuminated and sets at **[23:05]**. Ranked for your configuration
> (200 mm f/4, 0.97″/px, V and r′ filters):
>
> 1. **[Transit of an ExoClock target, depth ≈ 9 mmag]**, *time-critical*. Ingress **[22:12]**, egress **[00:31]**, and the target stays above 35° throughout. Your ETC predicts ≈ **[3 mmag]** per 60 s in r′, which gives timing precision of about **[±1 min]**. The ExoClock priority flag is **[high: last observation more than 1 year ago]**.
> 2. **[Eclipsing binary from your AAVSO list]**. Primary minimum at **[23:40]**. Your previous O−C point was **[N]** days ago.
> 3. **[NEOCP object]**, V ≈ **[18.4]**, at your 5σ limit in 120 s. The S/N is marginal, so I rank it third and recommend it only if transparency stays good.
>
> Not recommended: M51 deep imaging. The Moon is above the horizon until 23:05, and M51 drops below
> 40° after **[00:20]**, so you would get about an hour of moonless time on it.
>
> Shall I draft a plan for 1 then 2? It would need your confirmation before anything moves.

### 29.2 "What am I looking at?" (JWST file)

> **User:** *[uploads `jw02107-…_nircam_clear-f200w_i2d.fits`]* What am I looking at?
>
> **Assistant:** This is a **Stage-3 combined, calibrated JWST NIRCam image** (`i2d`, pipeline
> `CAL_VER [x.y.z]`, CRDS context `[jwst_xxxx.pmap]`). It comes from program **2107** (PHANGS-JWST)
> and was taken through **F200W** (pivot ≈ 1.99 µm, near-infrared). Units are MJy/sr.
>
> **Observed (L1), from metadata and measurements:**
> - Footprint centred at RA **[…]**, Dec **[…]**. The observer's target designation is **[NGC 628]**. That is the proposal's label, not an identification of every object in the frame.
> - Exposure **[EFFEXPTM]** s. Measured PSF FWHM **[0.07″]** on **[N]** unsaturated stars. 5σ point-source depth **[x]** AB mag (from source-masked random apertures).
> - **[N]** sources detected at an estimated false-positive rate of **[≤ k]** (negative-image test). **[m]** are point-like, **[n]** resolved.
> - Astrometry vs Gaia DR3 (epoch-propagated): residual RMS **[x]** mas.
>
> **Inferred (L2), with evidence:**
> - The extended emission belongs to the nearby spiral galaxy NGC 628 (M74). Evidence: SIMBAD/NED identification at the field centre, separation **[x″]**. At 2 µm the light is dominated by evolved stellar populations (bandpass physics; supporting PHANGS paper: **[bibcode, passage]**).
> - **[k]** point sources with significant Gaia parallaxes are foreground Milky Way stars.
>
> **Uncertain (L3), and how to test:**
> - **[j]** compact red sources could be embedded young clusters *or* background galaxies. F200W alone cannot distinguish them. The test is colours with F335M/F770W from the same program, plus a cross-match with PHANGS cluster catalogues.
> - A faint arc-like feature at **[x, y]** coincides with a **known NIRCam wisp location** for this detector. Treat it as a likely artefact unless it also appears in a different dither or epoch.
>
> Provenance ID `[prov:01J…]`. Ask "generate the notebook" to reproduce every number above.

### 29.3 "Can I measure something scientifically from my image?"

> **User:** I took 40×120 s of a field around a variable star with my 200 mm. Can I measure anything scientifically?
>
> **Assistant:** I checked the frames:
> - the median FWHM is **[2.8″]**, about 2.9 px, so the sampling is good;
> - the background RMS matches your camera's read noise plus sky to within **[10%]**, so the frames behave as expected;
> - **[3]** frames have a transparency drop above 0.2 mag, and I have excluded them (recorded);
> - your flats are 6 days old and taken through a different filter position, which is a likely systematic.
>
> - **Photometry: yes.** The target (V ≈ **[13.1]**) reaches S/N ≈ **[150]** per frame, which is ≈ **[7 mmag]**. With **[12]** Gaia-XP-calibrated comparison stars of similar colour, the expected light-curve scatter is **[8–10 mmag]** per point. That is good enough for times of minimum and AAVSO submission (V band, with the transformation coefficients derived tonight).
> - **Astrometry: yes, but not useful here.** Gaia fits give **[0.15″]** RMS, but no moving objects are in the field (SkyBoT checked at the exposure mid-times).
> - **Morphology: no.** There is no resolved target of interest, and you are seeing-limited.
> - **Variability of other stars: possible.** **[2]** field stars show scatter well above expectation, which makes them L3 variable candidates. VSX lists **[1]** of them as a known variable, **[ID]**. The other has no VSX entry within **[3″]**, so it would need more nights.
>
> Main limitation: the flat-field mismatch. I recommend new flats in the same filter before the next session.

### 29.4 "Find me a research project."

> **User:** Find me a research project.
>
> **Assistant:** Based on your equipment (configuration A, V/r′ filters, GPS time), your skills
> (completed B1–B6 and I4), the data available and feasibility, here are three options ranked by
> feasibility × scientific value:
>
> 1. **Transit ephemeris maintenance for [N] TESS planets with stale ephemerides** (R1, scaled down). Depths are ≥ **[6 mmag]** and hosts V < **[12.5]**, so your predicted per-transit timing precision is **[±0.8–1.5 min]**. ExoClock shows **[k]** of them with no observations in **[>1 yr]**. Output: ExoClock contributions, then a note on any drift beyond 3σ. Feasibility: **high**.
> 2. **Asteroid rotation periods** (R6) for **[m]** objects brighter than V **[15.5]** this season with no entry, or a low-quality entry, in ALCDEF (queries shown). Output: Minor Planet Bulletin notes. Feasibility: **high**, but it needs 3–5 nights per object.
> 3. **Low-surface-brightness features** (R2). **Not feasible yet.** Your measured sky is **[19.6 mag/arcsec²]**, and your flats currently limit you to about **[26]** mag/arcsec². Revisit with configuration B at a darker site.
>
> I found no published work specifically covering option 1's **[N]** targets after **[year]** in ADS
> (queries listed). That is *not* proof that no such work exists; I recommend asking the ExoClock team before starting.

### 29.5 Refusal example (scientific reliability)

> **User:** *[uploads a PNG screenshot]* Which galaxy is this, and how far away is it?
>
> **Assistant:** This PNG has no WCS or AVM metadata, and the blind plate solve failed. It may be too
> small a field, too processed, or a non-astronomical crop. I can't identify the object reliably, and
> I won't guess a name or a distance. Visually (unverified) it shows a disc-like extended source with
> spiral structure.
>
> If you can share the original FITS file, the source page, or approximate coordinates, I'll
> identify it from catalogues and give a cited distance with its uncertainty.

---

## 30. Long-term vision

In five or more years, the platform could be:

1. **A personal research environment** where the path from *question* to *published, reproducible
   result* runs through a single provenance graph: learning notebooks, archive data, your
   observations, simulations, literature and the final paper.
2. **A small, well-instrumented observatory** (configuration B/C) running trusted-automation
   programmes: ephemerides, variable stars, asteroid lightcurves, spectroscopic monitoring. It
   contributes to AAVSO, MPC, ExoClock and BeSS, and publishes its own data through IVOA services (DaCHS).
3. **An evidence-graded interpretation engine**, released as open source with a public benchmark,
   that other people use to make AI image explanations trustworthy (R4).
4. **A teaching system** whose explanations are tied to real data and checked derivations, taking a
   learner from first principles to research practice.
5. **A node in a network:**
   - federated with other amateur and professional observatories through request-based scheduling;
   - reacting to Rubin alerts for bright transients;
   - running analyses next to the archives in the cloud when the data are too large to download.

What keeps that ambition credible is the same discipline as Phase 0:
- every number has an uncertainty and a provenance;
- every identification has a catalogue record;
- every claim has a level and a citation;
- every physical action passes a safety kernel that the AI cannot bypass.
