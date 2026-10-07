# Part 4: Personal Observatory: Integration, Interoperability, Planning, Safety, Procurement

> Report sections covered: **11** Telescope integration (including Parts XV scientific use, XIII natural-language
> control, XIV autonomy) · **12** Hardware interoperability strategy · **13** Observation-planning
> architecture · **19** Security and hardware-safety architecture · **22** Hardware procurement criteria.
>
> Standards status checked 2026-10-06:
> - **ASCOM Platform 7.1** (Update 2, Feb 2026). Interface version 4 adds asynchronous `Connect()`/`Disconnect()`/`Connecting` and `DeviceState`.
> - **Alpyca 3.x**, the Python Alpaca client, which supports Platform 7 additions.
> - **INDI 2.1.x** with **pyindi-client 2.1.x**.
> - **PHD2** event-monitoring server (JSON over TCP, port 4400).

---

## 11. Telescope integration

### 11.1 Layering

```
Personal telescope hardware
   │ USB / serial / Ethernet / Wi-Fi
   ▼
Device servers (not written by us)      INDI server + drivers   |  Alpaca devices / ASCOM Remote  | vendor SDK
   │ INDI XML over TCP 7624                 Alpaca REST/JSON over HTTP (+ UDP discovery 32227)
   ▼
HAL (ours): typed device interfaces     Mount, Camera, Focuser, FilterWheel, Rotator, Dome, Switch,
   │                                    ObservingConditions, SafetyMonitor, Guider (PHD2), PlateSolver
   ▼
Safety kernel (ours)                    limits, interlocks, permission tiers, watchdog, safe-state
   ▼
Sequencer (ours)                        validated plans, state machine, NL→DSL proposals, logging
   ▼
Acquisition + ingest (ours)             FITS writing with full headers → personal archive → science engine
```

**Strategic decision: decouple *getting science from the telescope* from *controlling the telescope*.**
1. In the first months after purchase, capture with established software: N.I.N.A. on Windows,
   KStars/Ekos on Linux/macOS, or the vendor's app.
2. The platform **ingests** those FITS files and logs (Phase 5).
3. The platform's own control layer (Phase 7+) is built against simulators in parallel. It takes
   over only when it is demonstrably safer and more capable for your science.

This avoids writing control software before you know your equipment, and it produces data from the first clear night.

### 11.2 Acquisition capabilities (Part XI) mapped to standard interfaces

| Capability | ASCOM/Alpaca | INDI standard property | Notes |
|------------|--------------|------------------------|-------|
| Discover devices | Alpaca UDP discovery + `/management/v1/configureddevices` | Driver list from `indiserver`, `getProperties` | Discovery is a convenience. Configured devices are pinned in `configs/equipment/*.yaml`. |
| Connect / capabilities | `Connect()`, `Connected`, `Can*` flags, `InterfaceVersion`, `DeviceState` | `CONNECTION`, driver-specific `*_INFO` | Capabilities are cached and verified at session start |
| Read coordinates | `RightAscension`, `Declination`, `Altitude`, `Azimuth`, `SideOfPier` | `EQUATORIAL_EOD_COORD`, `HORIZONTAL_COORD`, `TELESCOPE_PIER_SIDE` | INDI mounts often report JNow (epoch of date); convert explicitly |
| Slew / track / sync | `SlewToCoordinatesAsync`, `Tracking`, `TrackingRate`, `SyncToCoordinates` | `ON_COORD_SET` (SLEW/TRACK/SYNC) + `EQUATORIAL_EOD_COORD` | Always via the safety kernel |
| Park / unpark / home | `Park`, `Unpark`, `FindHome`, `AtPark` | `TELESCOPE_PARK` | Park is a safe-state action (always permitted) |
| Abort | `AbortSlew` | `TELESCOPE_ABORT_MOTION` | Emergency path |
| Expose / readout | `StartExposure`, `ImageReady`, `ImageArray`/ImageBytes | `CCD_EXPOSURE` + `CCD1` BLOB | Prefer ImageBytes (Alpaca) for speed |
| Camera metadata | `Gain`, `Offset`, `CCDTemperature`, `SetCCDTemperature`, `BinX/Y`, `ReadoutMode`, `ElectronsPerADU`, `FullWellCapacity` | `CCD_GAIN`, `CCD_OFFSET`, `CCD_TEMPERATURE`, `CCD_BINNING`, `CCD_INFO` | **Gain in e⁻/ADU must be measured** (photon-transfer curve), not trusted from the driver |
| Focus | `Move`, `Position`, `Temperature`, `IsMoving` | `ABS_FOCUS_POSITION`, `FOCUS_TEMPERATURE` | Autofocus: HFR/FWHM V-curve in our code or the capture software |
| Filters | `Position`, `Names`, `FocusOffsets` | `FILTER_SLOT`, `FILTER_NAME` | Filter → bandpass mapping lives in our equipment config |
| Guiding | (no ASCOM guider standard) → **PHD2** event server | (Ekos internal guider or PHD2) | Monitor `GuideStep` RMS, `StarLost`, `Settling` |
| Plate solving | — → **ASTAP** / **astrometry.net** (local index) | Ekos uses local solvers | Solve → sync → re-slew to centre ("centre using plate solving") |
| Weather / safety | `ObservingConditions` (measurements) + `SafetyMonitor` (`IsSafe`) | `WEATHER_*` + weather status Ok/Warning/Alert; dome snoops weather | **Measurement and safety decision are separate objects** |
| Dome / roof | `Dome` (`OpenShutter`, `CloseShutter`, `Slaved`) | `DOME_SHUTTER`, `DOME_PARK` | Roof close must also be hardware-interlocked (§19) |
| Power | `Switch` | Power-box drivers (`SWITCH` properties) | Switchable dew heaters, cameras, mount |
| Time / site | GPS device or NTP; `UTCDate`, `SiteLatitude` | `TIME_UTC`, `GEOGRAPHIC_COORD` (GPS drivers) | Timing accuracy recorded per frame (needed for occultations and astrometry) |
| Observation metadata | — | — | **Our acquisition layer writes complete FITS headers** (§16) from device states at exposure start and end |

### 11.3 Personal observation database (Part XVI)

An observation is an **Activity** in the provenance store ([02](02-target-architecture.md) §18).

| Group | Fields (each with unit, source device, read time) |
|-------|----------------------------------------------------|
| Target | name as requested, resolved identifier (SIMBAD/Horizons), ICRS coordinates and epoch, ephemeris source for moving objects |
| Time | exposure start/mid/end (UTC + TDB), time source (GPS/NTP), estimated timing error |
| Site | latitude, longitude, elevation, horizon mask version |
| Optics | telescope, aperture, focal length (measured from plate solution), focal reducer, mount |
| Camera | model, serial, sensor, gain setting **and measured e⁻/ADU**, offset, read mode, binning, set-point and actual temperature, measured read noise, linearity/saturation level |
| Filter | wheel slot, filter name → bandpass definition (vendor curve file + hash) |
| Exposure | length, number in sequence, dither offset |
| Pointing | requested vs plate-solved centre, rotation, pixel scale, solve residual |
| Conditions | airmass, altitude, Moon separation/phase, sky brightness (SQM or measured from frame), FWHM/seeing (measured), cloud sensor, humidity, dew point, wind, temperature |
| Guiding | RMS RA/Dec (arcsec), star lost events |
| Calibration | linked master bias/dark/flat entity IDs (with their own provenance) |
| Files | raw path + SHA-256 (raw is immutable), reduced products |
| Processing | software versions, parameters (via provenance) |
| Derived | photometry, astrometry and analysis results, each linked back to the raw frames |

Storage: raw frames are content-addressed and read-only. Metadata goes in SQLite, then Postgres.
Nightly logs are kept as JSON Lines alongside.

### 11.4 Natural-language observatory control (Part XIII)

The language model never sends device commands. It **proposes a plan in a typed DSL**. The
sequencer **validates** it deterministically, the user **confirms** it (depending on permission
tier), and the sequencer **executes** it.

```
"Slew to M51, centre it with plate solving, take 20×300 s in H-alpha, then calibration frames."
        │  LLM → proposal (JSON, schema-validated)
        ▼
Plan(
  target = Resolve("M 51", source="SIMBAD") → ICRS 13h29m52.7s +47°11′43″ (record id kept),
  steps  = [Slew(target), CenterBySolve(tol=10″, max_iter=3), StartGuiding(settle=1.5″),
            Expose(filter="Ha", exp=300 s, count=20, dither_every=3),
            CalibrationFrames(darks=20×300 s @ −10 °C, flats="Ha" panel, bias=50)])
        │  Validator (deterministic, every check reported):
        ▼
✔ hardware connected (mount, camera, wheel, guider)    ✔ target alt 62° now, >30° until 02:40
✔ within mount limits / horizon mask / meridian plan   ✔ SafetyMonitor IsSafe = true
✔ camera at set-point −10.0 °C                         ✔ disk: 41 GB free, plan needs 1.3 GB
✔ total 1 h 52 min incl. overheads; ends before dawn   ⚠ Moon 64% illuminated, 48° away (OK for Hα)
        │  Plan preview + "Confirm?"   (tier: Assisted)
        ▼
Sequencer executes; telemetry streamed; any interlock → abort to safe state; log + provenance.
```

- **Consequential actions** (slewing, opening the roof, long or unattended exposures, cooling
  changes, anything moving away from a safe state) require explicit confirmation, unless a
  pre-approved plan is executing in Trusted Automation tier (§19).
- **Read-only questions** ("Is the camera cold?") need no confirmation.
- "Compare my observation with Hubble" and "Find papers" are science-engine and knowledge actions, not hardware actions.

### 11.5 Autonomous mode (Part XIV): optional, last

A finite-state machine with explicit transitions:

```
IDLE → STARTUP_CHECKS → WAIT_SAFE → OPENING → COOLING → [per target:
  SLEWING → CENTERING → FOCUSING? → GUIDE_START → EXPOSING ↔ FILTER_CHANGE/DITHER → TARGET_DONE]
 → CALIBRATION → PARKING → CLOSING → SHUTDOWN
ANY ─(unsafe | fault | watchdog | operator abort)→ SAFE_SHUTDOWN (park + close) → WAIT_SAFE
```

Continuous monitors, each with thresholds in versioned `safety_limits.yaml`:
- **Conditions:** rain (hardware sensor), clouds (sky − ambient IR temperature), humidity / dew-point margin, wind, gusts.
- **Image quality:** FWHM vs threshold, background jump (cloud), star count drop.
- **Tracking:** guide RMS, star lost; plate-solve drift between frames.
- **Hardware:** device faults, `DeviceState`/INDI Alert states, camera temperature excursion, focuser stall.
- **Resources:** disk space, power (UPS on battery).
- **Geometry:** target altitude vs limit, meridian-flip window, mount limits.

Recovery policy:
- Clouds → pause, keep tracking, wait up to N min. Then either re-acquire (solve + guide) or move to the next target.
- **Rain is always an immediate close.**

Prerequisite for enabling autonomy: at least 20–30 supervised nights with complete logs, and fault
injection tests on simulators (unplug the camera, kill the guider, fake rain).

### 11.6 Scientific use of the telescope (Part XV): an honest feasibility assessment

Numbers are idealised estimates from [`etc_estimates.py`](etc_estimates.py). A 200 mm aperture
reaches **V ≈ 18.8 (5σ, 60 s)** and **V ≈ 19.8 (5σ, 300 s)** under a 20 mag/arcsec² sky with
2.5″ seeing. A V = 12 star gives about **4 mmag per 60 s** including scintillation. Real-world
systematics (flat-field errors, comparison stars, red noise) typically add 1–3 mmag.

| Area | Project | Feasible with A / B / C? | Real scientific value | Where it goes | Honest limits |
|------|---------|:------------------------:|------------------------|---------------|---------------|
| Photometry | Variable stars (eclipsing binaries, CVs, Miras, RR Lyrae, δ Scuti) | ✅ / ✅ / ✅ | **Yes**, especially times of minima (O−C) and neglected stars | AAVSO (AID), BAV, JAAVSO | Must use standard filters and comparison-star sequences (AAVSO VSP) |
| Photometry | Exoplanet transits | ✅ for depth ≳ 5 mmag, V < 13 / ✅ ≳ 3 mmag / ✅ ≳ 2 mmag | **Yes**: ephemeris maintenance (ExoClock for Ariel), TTV monitoring, TESS follow-up (TFOP SG1 by membership) | ExoClock, Exoplanet Watch, ETD, TFOP | Will not discover planets. Sub-mmag work needs larger apertures and excellent sites. |
| Photometry | Supernova monitoring | ⚠ follow-up of bright SNe (< 16 mag) / ✅ / ✅ | Modest: light curves of bright SNe; independent discovery is now rare against ATLAS, ZTF, ASAS-SN and Rubin | AAVSO, TNS (as follow-up) | Host-galaxy subtraction needs good templates |
| Photometry | AGN variability (bright Seyferts) | ⚠ / ✅ / ✅ | Modest: long baselines for bright AGN | Collaborations | Seeing-dependent host contamination; needs careful aperture or difference photometry |
| Photometry | Stellar flares (M dwarfs) | ⚠ / ✅ / ✅ | Modest | Papers in collaboration | Bright, nearby flare stars only; blue filters are better |
| Astrometry | Minor planets, NEO confirmation | ✅ / ✅ / ✅ | **Yes**: MPC astrometry, NEOCP follow-up | MPC (ADES format, observatory code) | Timing accuracy (GPS/NTP) and reference catalogue (Gaia) required |
| Astrometry | Comets (positions, Afρ activity) | ✅ / ✅ / ✅ | **Yes** | MPC, comet groups | Coma-centroid systematics |
| Astrometry | Proper motion / parallax of nearby stars (e.g. Barnard's Star) | ⚠ educational / ✅ / ✅ | Educational (Gaia is far superior) | Teaching, notebooks | No new science vs Gaia |
| Timing | **Asteroid occultations** | ✅ (fast camera + GPS) | **High**: asteroid sizes and shapes, binary detection | IOTA / IOTA-ES / regional networks | Needs travel to the shadow path and precise timing |
| Imaging | Low-surface-brightness tidal features of nearby galaxies | ⚠ / ✅ / ✅ | **Yes**: published pro-am precedent (Martínez-Delgado et al. 2010, AJ 140, 962) | Collaboration papers | Requires excellent flats, dark sky and long integrations (~28 mag/arcsec² needs many hours) |
| Imaging | Morphology/structure of bright galaxies | ✅ | Educational | — | Seeing-limited (2″ ≈ 80 pc at M51's distance) |
| Spectroscopy | Low-res (R≈100 grating) classification, bright SN/nova types | ✅ (V < 10–11) | Educational plus modest | ARAS | Slitless, so blended spectra |
| Spectroscopy | Slit R≈1000: Be stars, symbiotics, novae, bright quasars (3C 273 redshift) | ⚠ / ✅ / ✅ | **Yes** for Be/symbiotic monitoring (BeSS, ARAS databases) | BeSS, ARAS, collaborations | Limiting mag ~11–13 at B, ~13–14 at C for useful S/N in an hour |
| Spectroscopy | Echelle R≈10 000: radial velocities of bright binaries | ✗ / ⚠ / ✅ | Yes for bright stars (km/s-level RVs) | Collaborations | Will **not** detect exoplanets by RV (needs m/s) |
| Time domain | Rubin/ZTF alert follow-up | ⚠ / ✅ / ✅ (bright alerts only) | Modest: bright transient colours and light curves | Brokers, TNS | Most alerts are fainter than 19–20 mag |

What amateur equipment **cannot** do, and the assistant must say so:
- diffraction-limited resolution;
- infrared beyond ~1 µm (silicon cutoff);
- absolute photometry better than ~1–2% without exceptional care;
- precision RV;
- discovery-class surveys competitive with professional facilities.

---

## 12. Hardware interoperability strategy

### 12.1 ASCOM/Alpaca vs INDI

| Aspect | ASCOM (COM) + **Alpaca** | **INDI** |
|--------|--------------------------|----------|
| Platform | COM: Windows only. **Alpaca: any OS** (HTTP REST/JSON) | Linux and macOS native (servers often run on a Raspberry Pi or mini-PC) |
| Model | Typed interfaces with versioned semantics (`ITelescopeV4`, `ICameraV4`, …) | Generic property vectors (Number/Switch/Text/Light/BLOB) with standard names and states (Idle/Ok/Busy/Alert) |
| Communication | Request/response; poll for state | **Event-driven push** of property updates (good for monitoring) |
| Discovery | UDP 32227 discovery + management API | Server exposes all drivers' properties |
| Ecosystem | Very large Windows driver base. Native Alpaca devices are growing. **ASCOM Remote** exposes COM drivers as Alpaca. | Large Linux driver base (mounts, cameras, focusers, domes, weather). KStars/Ekos. Dedicated devices like StellarMate/Astroberry. |
| Python client | **alpyca** (official, pure Python) | **pyindi-client** (SWIG over the C++ client); pure-Python clients also exist |
| Testing | **Alpaca Omni Simulators**; **ConformU** conformance checker | Built-in simulator drivers (telescope, CCD, focuser, wheel, dome, weather, GPS) |
| Safety semantics | Separate `ObservingConditions` (measurements) and `SafetyMonitor` (`IsSafe`) | Weather drivers with parameter ranges → Ok/Warning/Alert; domes "snoop" weather |
| Security | Plain HTTP; **no meaningful auth/encryption in practice**, so trusted LAN only | Plain TCP; no auth, so trusted LAN only |

### 12.2 Decision

**Support both, behind our own HAL, with ASCOM-shaped interface semantics.**

1. **Own HAL interfaces modelled on ASCOM interface definitions.** They are explicit, versioned and
   well documented (`CanSlewAsync`, `DeviceState`, `IsSafe`), which suits a safety kernel that
   needs precise semantics. INDI properties are mapped onto them.
2. **Two first-class backends:**
   - **Alpaca:** cross-platform, trivially testable with OmniSim. **Development starts here** in Phase 7.
   - **INDI:** the recommended runtime on a Linux observatory controller, which is more robust headless and has a broad driver base.

   Neither standard is "primary" in the abstract. The primary for a given device is **whichever
   driver is better maintained for that device**, recorded in the equipment config.
3. **Vendor SDKs only as a last resort**, wrapped as a HAL backend for features the standards do not
   expose (e.g. some camera readout modes), never used directly by the sequencer.
4. **Do not write drivers, a guider or a plate solver.** Use PHD2 (event server API), ASTAP or
   astrometry.net, and existing INDI/ASCOM drivers.
5. **Hardware purchase rule:** prefer devices with **both** an INDI driver and an ASCOM/Alpaca driver
   (or native Alpaca), verified against **ConformU**. That keeps the OS choice and the capture-software
   choice open forever.

### 12.3 HAL interface sketch

```python
class Mount(Protocol):
    def capabilities(self) -> MountCaps: ...          # can_park, can_sync, can_slew_async, pier_side...
    def state(self) -> MountState: ...                # ICRS/JNow coords, alt/az, tracking, slewing, at_park
    async def slew(self, target: ICRS, *, token: SafetyToken) -> None: ...   # token issued by safety kernel
    async def park(self) -> None: ...                 # safe-state: no token required
    def abort(self) -> None: ...                      # emergency: no token required
```

Every motion method needs a `SafetyToken` minted by the safety kernel after validation. Safe-state
methods (park, close, abort, stop exposure) need none. This makes the asymmetry in §19 structural,
not a convention.

---

## 13. Observation-planning architecture

### 13.1 Inputs
- **Site profile:** coordinates, elevation, horizon mask (measured), light pollution (SQM or World Atlas estimate), time zone.
- **Equipment profiles:** aperture, focal length, camera (pixel size, QE curve, read noise, gain, full well), filters (bandpass curves), mount limits, FOV and pixel scale (computed).
- **Conditions:** cloud, humidity and wind forecasts (e.g. Open-Meteo or your national met service); seeing forecasts where available; real-time ObservingConditions.
- **Sky:** Sun and Moon positions, twilight, Moon phase and separation (astroplan/skyfield).
- **Target sources:**
  - SIMBAD/OpenNGC for deep-sky objects;
  - AAVSO alerts, campaigns and target tool;
  - ExoClock/ETD transit predictions (computed from ephemerides with uncertainties);
  - MPC NEOCP and Horizons ephemerides;
  - TNS bright transients;
  - your own project target lists.

### 13.2 Scoring: physics first, then value

For each candidate and time window:
1. **Observability:** altitude above limit and horizon mask, airmass < X_max, outside meridian
   no-go, Moon separation above a band-dependent minimum, within dark time or a usable twilight.
2. **Feasibility** (exposure-time calculator, §13.4): can the required S/N be reached in the
   available window? For a transit: is the full event plus baseline observable?
3. **Value model** (explicit, editable weights): project priority, time-criticality (a transit
   tonight, NEOCP urgency, a variable-star campaign), scientific gap (how many observations exist in
   AAVSO or ExoClock recently), learning value.
4. **Score:** feasibility gates value. An infeasible target scores 0 regardless of value.

Scheduler:
- **MVP:** greedy with constraints; astroplan's `PriorityScheduler`/`SequentialScheduler`.
- **Later:** an integer-programming scheduler (OR-Tools) once there are many projects.

Output: a ranked list with **reasons** (the computed numbers), and a draft `Plan` the sequencer can validate.

### 13.3 "What can I observe tonight?" pipeline

```
site + date → night window (astronomical twilight) → weather windows (forecast cloud < threshold)
 → candidate targets (project lists ∪ alerts ∪ time-critical events)
 → visibility curves → ETC per target → value scoring → schedule → explanation
```

### 13.4 Signal-to-noise (the CCD equation): used by the planner and the analysis

```
S/N = S·t / sqrt( S·t + n_pix·(B·t + D·t + R²) + (σ_scint·S·t)² )
S: source e⁻/s in aperture, B: sky e⁻/s/pixel, D: dark e⁻/s/pixel, R: read noise e⁻,
n_pix: aperture pixels, σ_scint ≈ 1.5 × 0.09 D_cm^(−2/3) X^1.75 e^(−h/8000 m) (2t)^(−1/2)
(Young 1967; ×1.5 empirical correction per Osborn et al. 2015)
```

Sky brightness B comes from SQM/forecast, scaled to the bandpass and Moon. Gain and read noise
come from the camera's **measured** photon-transfer curve.

---

## 19. Security and hardware-safety architecture

### 19.1 Permission tiers (enforced by the safety kernel, not by prompts)

| Tier | Who / what | Allowed | Requires |
|------|-----------|---------|----------|
| **0 Read-only** (default for AI) | Assistant, remote viewers | Read device state, images, logs, conditions | Authenticated session |
| **1 Assisted control** | Assistant proposes; **user confirms each consequential step** | Slew, expose, filter, focus, cooling, open roof | Validated plan + interactive confirmation (with the plan diff shown) |
| **2 Trusted automation** | Sequencer executing a **pre-approved, signed plan** | Only the steps and envelope in the approved plan (targets, alt limits, max exposure, time window, conditions) | Plan hash signed by the user. Any deviation (new target, longer window) means re-approval. Expires at plan end or dawn. |
| **3 Emergency safety** | Safety kernel (and any tier, *in the safe direction only*) | Abort slew, stop exposure, park, close roof, power down | Nothing. Always available, including without the network or AI. |

**Asymmetry principle:** actions toward a safe state need *less* authorisation than actions away
from it. The AI may always *request* a park or close. It may never open, unpark or slew without the
tier allowing it.

### 19.2 Defence in depth for physical safety

1. **Hardware interlocks independent of all software:** a rain sensor wired to the roof controller's
   close input. Limit switches on the roof and mount. Thermal fuses on dew heaters.
2. **Controller watchdog / dead-man:** the roof or dome controller closes if it loses its heartbeat
   from the observatory computer for N minutes.
3. **Safety kernel:**
   - validates every motion against the horizon mask, mount limits (altitude, meridian, pier-collision and cable-wrap zones), Sun-avoidance (never point within X° of the Sun) and the `IsSafe` state;
   - holds the only code path that mints `SafetyToken`s.
4. **Sequencer:** state machine with timeouts on every operation (slew, exposure readout, plate solve, guiding settle).
5. **Physical emergency stop:** a switch that cuts mount and roof motor power. It is documented that
   this leaves the mount unparked; recovery is a manual procedure.
6. **Monitoring:** alerts (phone push or e-mail) on unsafe conditions, faults or failed safe-state transitions.

### 19.3 Network and access security

| Concern | Measure |
|---------|---------|
| Device protocols (INDI 7624, Alpaca HTTP) | **Never exposed beyond the observatory LAN/VLAN.** Firewall them to the controller host only. |
| Remote access (including iPad) | WireGuard/Tailscale VPN to the lab or controller. No port forwarding. MFA on the VPN identity. |
| Platform API / MCP server | Authenticated (OIDC or per-device tokens), TLS, scoped tokens per permission tier; the AI's token defaults to Tier 0 |
| Secrets (ADS token, LLM API key, VPN keys) | OS keychain or `.env` outside Git; `sops`/age for anything committed; never in notebooks or logs |
| Command validation | JSON-schema-validated DSL. No free-text to devices. Units required on all quantities. |
| Audit log | Append-only, hash-chained (each entry includes the previous hash). Records who/what requested, validator result, confirmation, execution and outcome. |
| Updates | Firmware and driver updates only on daytime maintenance windows, followed by a simulator plus a supervised check |

---

## 22. Hardware procurement criteria

### 22.1 Selection framework (derived from the science and software requirements)

| Criterion | Requirement | Why |
|-----------|-------------|-----|
| **Interoperability** | INDI **and** ASCOM/Alpaca drivers (native Alpaca a plus), checked with ConformU; no cloud-account lock-in for raw data | Keeps OS and software choice open; the platform depends on standard interfaces |
| **Raw data access** | Full-resolution FITS with complete headers; no forced in-camera processing | Science needs raw linear data |
| **Mount** | Payload ≥ 1.5–2× imaging train; periodic error low or **absolute encoders**; reliable park/home; meridian-flip support; good INDI/ASCOM drivers | Tracking quality and reliable safe-state are prerequisites for automation |
| **Optics** | Flat, corrected field over the sensor; focal length chosen for **pixel scale ≈ FWHM/2 to FWHM/3** at your typical seeing (≈ 0.8–1.3″/px for 2.5″ seeing) | Proper sampling for photometry and astrometry |
| **Aperture** | As large as mount, site and budget allow **after** sampling and mount criteria are met | Sets limiting magnitude and scintillation floor (∝ D^−2/3) |
| **Camera** | Monochrome, cooled (regulated set-point), documented gain/read noise, good linearity, **≥ 14-bit**, accurate exposure timing; global shutter or GPS timing if occultations are planned | Photometric stability; colour (OSC) cameras complicate standard photometry |
| **Filters** | Photometric set first: Johnson **V** + Sloan **r′** (or BVRI / g′r′i′), then Hα / [O III] / [S II] for nebulae; parfocal | Standard-system photometry and AAVSO compatibility; narrowband for morphology |
| **Focusing** | Electronic focuser with temperature sensor and absolute positioning | Autofocus and repeatability |
| **Guiding** | Off-axis guider (long focal length) or guide scope (short); PHD2-compatible guide camera | Long exposures and spectroscopy slit-holding |
| **Timing** | GPS or disciplined NTP; timestamps recorded with uncertainty | Occultations, astrometry, transit timing |
| **Environment** | Cloud sensor (IR sky temperature), rain sensor (hardware output), humidity/dew-point, wind, SQM | Safety and data-quality metadata |
| **Upgradeability** | Standard back-focus/adapters, dovetails, payload headroom, spare USB/power capacity | Spectrograph, rotator and larger camera later |

**Avoid as the research core:**
- Integrated "smart telescopes". They are useful for outreach and learning, but have small apertures, colour sensors and limited raw/standard-interface access, even when some now expose Alpaca.
- Any device whose control or raw data requires a vendor cloud account.

### 22.2 Three conceptual configurations

Costs are rough 2026 orders of magnitude (USD, new), they vary strongly by region, and they exclude
the computer and building.

#### A: Entry Research Observatory (≈ $3–7k)

- **Hardware:**
  - 150–200 mm f/4–5 Newtonian astrograph with coma corrector (or an 80–100 mm apochromatic refractor if portability or simplicity dominates);
  - EQ mount with 15–20 kg payload and an INDI/ASCOM driver;
  - cooled mono CMOS (APS-C class, 3.76 µm pixels);
  - 5–7 position filter wheel with **V** and **r′** first, Hα later;
  - guide scope + guide camera;
  - electronic focuser;
  - small Linux mini-PC running the INDI server (or Windows + ASCOM);
  - SQM;
  - flat panel.
- **Capability** (computed: 200 mm, 0.97″/px, 1.7°×1.1° FOV):
  - 5σ V ≈ 18.8 in 60 s, ≈ 19.8 in 300 s;
  - S/N = 100 at V ≈ 14.5 in 60 s;
  - ~4 mmag per minute on V = 12 stars (idealised).
- **Science:** variable stars, bright exoplanet transits (≥ 5 mmag), asteroid and comet astrometry, occultations (with GPS and a fast camera), galaxy and nebula imaging, R≈100 slitless spectroscopy of bright stars.
- **Limits:** portable setup means re-alignment each night; limited automation; no slit spectroscopy.
- **Automation potential:** assisted control, scripted sequences. Unattended operation is not recommended without a fixed pier and roof.
- **Upgrade path:** keep the camera, wheel, focuser and computer; upgrade the mount first, then the optics.

#### B: Serious Prosumer Research Observatory (≈ $12–30k)

- **Hardware:**
  - 250–300 mm optics: corrected SCT/RC/CDK at ~f/7, ~2 m focal length (bin 2×2 for ≈ 0.8″/px);
  - mount with 30–50 kg payload, **absolute encoders** preferred;
  - cooled mono CMOS (larger sensor);
  - 7–8 slot wheel (BVRI or g′r′i′ + Hα/[O III]/[S II]);
  - off-axis guider;
  - focuser with temperature compensation;
  - optional rotator;
  - **permanent pier + roll-off roof** with ASCOM/INDI roof control;
  - weather station + cloud and rain sensors + SafetyMonitor;
  - GPS;
  - switchable power box;
  - UPS;
  - optional slit spectrograph at R≈1000.
- **Capability** (computed: 280 mm, 0.79″/px):
  - 5σ V ≈ 19.4 in 60 s, ≈ 20.3 in 300 s;
  - ~3 mmag per minute on V = 12 (idealised).
- **Science:**
  - all of A, with better precision;
  - TESS follow-up-grade transits (≥ 3 mmag);
  - low-surface-brightness imaging (with excellent flats);
  - Be/symbiotic star spectroscopy;
  - bright SN and nova spectra.
- **Limits:** a fixed site's weather and light pollution dominate; spectroscopy limiting magnitude is ~11–13 for good S/N.
- **Automation potential:** full Trusted Automation for pre-approved plans. Autonomous operation is feasible after the safety prerequisites (§11.5).
- **Upgrade path:** larger camera, echelle spectrograph on a second port, dome.

#### C: Advanced Personal Observatory (≈ $40–120k+)

- **Hardware:**
  - 400–450 mm CDK/RC;
  - direct-drive or high-end mount with absolute encoders (≥ 100 kg payload);
  - large-format cooled CMOS/CCD (e.g. 9 µm pixels);
  - rotator;
  - dome or roll-off roof with hardware interlocks;
  - all-sky camera;
  - full weather/safety suite;
  - **fibre-fed echelle (R≈10 000) and/or slit spectrograph** on a second port;
  - optionally at a remote dark-sky hosting site.
- **Capability** (computed: 430 mm, 0.64″/px):
  - 5σ V ≈ 20.3 in 60 s, ≈ 21.2 in 300 s;
  - ~2 mmag per minute on V = 12 (idealised);
  - spectroscopy to V ≈ 13–14 at R≈1000.
- **Science:**
  - research-grade time-domain programmes;
  - km/s radial velocities of bright binaries;
  - sustained AAVSO, ExoClock and TFOP contribution;
  - deep low-surface-brightness imaging;
  - spectroscopic monitoring campaigns.
- **Limits:** still seeing-limited and not competitive with professional surveys for discovery. Value comes from cadence, flexibility and long-term monitoring.
- **Automation potential:** fully autonomous, unattended nights within the §19 safety architecture.
- **Upgrade path:** network with other observatories through the federated controller model.

**Recommendation:** buy **A's camera, filter wheel, focuser and controller to B-grade specifications**.
They transfer to any later optics. Spend the remaining money on the **mount**, because mount quality
determines automation potential more than any other component. Choose the optics last, from the
pixel-scale rule applied to your measured site seeing.
