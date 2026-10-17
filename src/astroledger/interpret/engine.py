"""Evidence engine v1: deterministic rules from measurements to graded statements.

For one image this produces image-level facts (L1) and, per detected source, statements at the
strongest level the evidence supports (roadmap §14.3):

- **L1**: position and flux, size compared with the measured PSF, coincidence with a Gaia DR3
  record (separation, chance probability).
- **L2 star**: point-like **and** a Gaia DR3 counterpart whose proper motion is significant at
  more than 5σ (rule R-STAR-PM).
- **L2 galaxy** (with SIMBAD records): extended **and** coinciding with a record of a galaxy
  type, chance probability ≤ 1% and reliability ≥ 0.9 (rule R-GAL-CAT).
- **L2 nebula** (image level, with SIMBAD records): extended sources that are not galaxies, in
  a band containing a diagnostic line, and a nebula record whose position is inside the image
  (rule R-NEB-CAT).
- **L3**, each with the test that would decide it:
  - point-like sources without such evidence;
  - extended sources (galaxy, nebular structure or blend);
  - extended emission in a band that contains a diagnostic line;
  - possible PSF artefacts near bright stars.

  Without SIMBAD records, galaxies and nebulae stay at L3.

Identities are never generated: the only identifiers in the output are Gaia DR3 ``source_id``
values and SIMBAD ``main_id`` / ``otype`` values copied from the input tables, and the
observer's target designation from the header, which is reported as a label, not as an
identification.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import QTable
from astropy.wcs.utils import proj_plane_pixel_scales

from astroledger.astrometry import observation_epoch, propagate
from astroledger.core.mode import require_imaging
from astroledger.core.product import ImageProduct
from astroledger.crossmatch import centroid_error, crossmatch
from astroledger.imaging import detect
from astroledger.interpret.evidence import EvidenceRef, Level, Statement
from astroledger.photometry import aperture_photometry_table
from astroledger.provenance import step

__all__ = ["RULES", "Explanation", "explain", "format_explanation"]

#: Knowledge rules used by the engine. Each is a physical statement, not a measurement.
RULES = {
    "R-STAR-PM": (
        "Objects outside the Milky Way have proper motions far below Gaia's precision, so a "
        "proper motion measured at more than 5 sigma marks a Galactic object; a point-like "
        "Galactic object is a star."
    ),
    "R-PSF-SIZE": (
        "A source whose light is as concentrated as that of stars (the PSF) is unresolved; one "
        "significantly less concentrated is extended."
    ),
    "R-GAL-CAT": (
        "An extended source that coincides with a catalogue record classified as a galaxy, with "
        "a chance-coincidence probability below 1%, is that catalogued galaxy."
    ),
    "R-NEB-CAT": (
        "Extended emission in a band containing a diagnostic emission line, in an image whose "
        "footprint contains the catalogue position of a nebula, is attributed to that nebula; "
        "whether it is line or continuum emission still needs a continuum-subtracted image."
    ),
}

#: SIMBAD object-type codes treated as galaxies / nebulae (condensed ``otype`` codes, as in
#: SIMBAD's object classification). Candidate types (codes ending in "?") never qualify. A code
#: missing here only prevents an L2 statement; it can never create one.
SIMBAD_GALAXY_TYPES = frozenset(
    {
        "G",
        "GiC",
        "GiG",
        "GiP",
        "BiC",
        "IG",
        "PaG",
        "SBG",
        "SyG",
        "Sy1",
        "Sy2",
        "AGN",
        "LSB",
        "EmG",
        "H2G",
        "bCG",
        "rG",
        "LIN",
    }
)
SIMBAD_NEBULA_TYPES = frozenset({"PN", "HII", "RNe", "SNR", "GNe", "EmO", "SFR"})

#: Diagnostic lines inside narrow bands (rest wavelengths, micron).
LINES_IN_BAND = {
    "F187N": ("Paschen-alpha (H I)", 1.8756),
    "F212N": ("H2 1-0 S(1)", 2.1218),
    "F405N": ("Brackett-alpha (H I)", 4.0523),
    "F470N": ("H2 0-0 S(9)", 4.6947),
}

PM_SIGNIFICANCE = 5.0
SPREAD_FLOOR = 0.03  # minimum star-to-star spread of the concentration, as a fraction


@dataclass
class Explanation:
    """Statements about one image and its sources."""

    image: list[Statement]
    sources: dict[int, list[Statement]]
    summary: dict
    notes: list[str] = field(default_factory=list)

    def ranked_sources(self) -> list[tuple[int, list[Statement]]]:
        """Sources with an L2 inference first, then by label (every source has L1 statements)."""
        return sorted(
            self.sources.items(),
            key=lambda kv: (not any(st.level is Level.L2_INFERENCE for st in kv[1]), kv[0]),
        )

    def statements(self) -> list[Statement]:
        out = list(self.image)
        for items in self.sources.values():
            out.extend(items)
        return out

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "image": [s.to_dict() for s in self.image],
            "sources": {str(k): [s.to_dict() for s in v] for k, v in self.sources.items()},
            "notes": self.notes,
        }


def _value(x) -> float:
    """Plain float from a (possibly masked) Quantity element, in its own unit."""
    x = getattr(x, "unmasked", x)
    return float(getattr(x, "value", x))


def _concentration(image, catalog):
    """Concentration F(1.5 px)/F(4 px) per source, its error, and the stars' reference value.

    Isophotal sizes depend on S/N (faint sources look small); a ratio of aperture fluxes does
    not, so it decides resolved versus unresolved. Its error ignores the (positive) correlation
    between the two apertures, which overestimates it: conservative.
    """
    if len(catalog) == 0 or "snr" not in catalog.colnames:  # no ERR array: no errors, no S/N
        return np.full(len(catalog), np.nan), np.full(len(catalog), np.nan), None
    xy = np.column_stack([np.asarray(catalog["x"], float), np.asarray(catalog["y"], float)])
    inner = aperture_photometry_table(image, xy, 1.5, annulus=(8.0, 13.0))
    outer = aperture_photometry_table(image, xy, 4.0, annulus=(8.0, 13.0))
    f1, f4 = (np.asarray(u.Quantity(t["flux"]).value, float) for t in (inner, outer))
    e1, e4 = (np.asarray(u.Quantity(t["flux_err"]).value, float) for t in (inner, outer))
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(f4 > 0, f1 / f4, np.nan)
        ce = np.abs(c) * np.hypot(e1 / f1, e4 / f4)
    clean = (np.asarray(inner["masked_fraction"]) < 1e-6) & (
        np.asarray(outer["masked_fraction"]) < 1e-6
    )
    c = np.where(clean, c, np.nan)  # masked (e.g. saturated) pixels bias the ratio
    stars = _reference_stars(catalog) & np.isfinite(c)
    if stars.sum() < 5:
        return c, ce, None
    centre = float(np.median(c[stars]))
    spread = float(1.4826 * np.median(np.abs(c[stars] - centre)))
    reference = {
        "c": centre,
        # floor: pixel phase and PSF changes across the field move a star's concentration by a
        # few per cent even without noise (measured spread on NGC 3132 F405N: 4.2%)
        "spread": max(spread, SPREAD_FLOOR * centre),
        "spread_measured": spread,
        "n": int(stars.sum()),
    }
    return c, ce, reference


def _reference_stars(catalog: QTable) -> np.ndarray:
    """Bright, round, unflagged sources: the PSF reference set."""
    good = (np.asarray(catalog["ellipticity"]) < 0.15) & ~np.asarray(catalog["near_bright_source"])
    return good & (np.asarray(catalog["snr"]) > 50)


def _gaia_matches(image, catalog, gaia, scale_arcsec):
    """Cross-match detections with Gaia DR3 propagated to the image epoch."""
    epoch, keyword = observation_epoch(image)
    moved = propagate(gaia, epoch)
    ref = QTable(
        {
            "ra": moved["ra_epoch"],
            "dec": moved["dec_epoch"],
            "source_id": moved["source_id"],
            "pmra": moved["pmra"],
            "pmdec": moved["pmdec"],
            "pmra_error": moved["pmra_error"],
            "pmdec_error": moved["pmdec_error"],
            "pm_missing": moved["pm_missing"],
            "pos_err": np.hypot(moved["ra_epoch_error"], moved["dec_epoch_error"]) / np.sqrt(2),
        }
    )
    det = QTable({"ra": catalog["ra"], "dec": catalog["dec"]})
    fwhm = u.Quantity(catalog["fwhm"]).value * scale_arcsec * u.arcsec
    if "snr" in catalog.colnames:
        det["pos_err"] = centroid_error(fwhm, np.maximum(np.asarray(catalog["snr"]), 1.0))
    else:
        det["pos_err"] = np.full(len(det), 0.1 * scale_arcsec) * u.arcsec
    result = crossmatch(
        det,
        ref,
        sigma_a="pos_err",
        sigma_b="pos_err",
        sigma_sys=30 * u.mas,
        k=4.0,
        register=True,
        copy_columns=("source_id", "pmra", "pmdec", "pmra_error", "pmdec_error", "pm_missing"),
    )
    covered = np.ones(len(catalog), bool)
    meta = gaia.meta or {}
    if "center_deg" in meta and "radius_arcsec" in meta:
        centre = SkyCoord(*meta["center_deg"], unit="deg")
        sky = SkyCoord(u.Quantity(catalog["ra"], u.deg), u.Quantity(catalog["dec"], u.deg))
        covered = sky.separation(centre).arcsec < meta["radius_arcsec"]
    return result, covered, f"{epoch.utc.isot} (from {keyword})"


def _catalogue_records(catalogue: QTable | None) -> QTable | None:
    """Records with the columns the rules need, or None."""
    if catalogue is None or len(catalogue) == 0:
        return None
    missing = {"main_id", "otype", "ra", "dec"} - set(catalogue.colnames)
    if missing:
        raise ValueError(f"catalogue lacks columns {sorted(missing)}")
    return catalogue


def _otype(value) -> str:
    return str(value).strip()


def _galaxy_matches(catalog: QTable, records: QTable, scale_arcsec: float) -> dict:
    """row -> (main_id, otype, separation arcsec, P_chance) for sources matching a galaxy."""
    galaxies = records[[_otype(t) in SIMBAD_GALAXY_TYPES for t in records["otype"]]]
    if len(galaxies) == 0 or len(catalog) == 0:
        return {}
    det = QTable({"ra": catalog["ra"], "dec": catalog["dec"]})
    # an extended source's centroid and a catalogue position differ by a fraction of its size
    size = np.asarray(u.Quantity(catalog["semimajor_axis"]).value, float) * scale_arcsec
    det["pos_err"] = np.maximum(0.25 * np.nan_to_num(size, nan=0.0), 0.1) * u.arcsec
    ref = QTable(
        {"ra": u.Quantity(galaxies["ra"], u.deg), "dec": u.Quantity(galaxies["dec"], u.deg)}
    )
    if "coo_err_maj" in galaxies.colnames:
        err = np.asarray(u.Quantity(galaxies["coo_err_maj"], u.mas).to_value(u.arcsec), float)
    else:
        err = np.full(len(galaxies), 0.1)
    ref["pos_err"] = np.where(np.isfinite(err) & (err > 0), err, 0.1) * u.arcsec
    result = crossmatch(det, ref, sigma_a="pos_err", sigma_b="pos_err", k=4.0, prior=0.5)
    out = {}
    for row in range(len(catalog)):
        best = result.best[row]
        if best["b_index"] < 0 or best["p_chance"] > 0.01 or best["reliability"] < 0.9:
            continue
        if "counterpart shared" in str(best["flags"]):  # two detections, one record: no identity
            continue
        rec = galaxies[int(best["b_index"])]
        out[row] = (
            str(rec["main_id"]).strip(),
            _otype(rec["otype"]),
            float(best["sep"].to_value(u.arcsec)),
            float(best["p_chance"]),
        )
    return out


def _nebula_statement(
    records: QTable | None, band, image: ImageProduct, extended: list[SkyCoord]
) -> Statement | None:
    """Image-level L2: extended emission in a line band, in a field with a catalogued nebula.

    ``extended`` holds the positions of the extended sources not already identified as
    galaxies. Only nebula records whose catalogue position lies inside the image footprint
    count; the one nearest the extended emission is cited.
    """
    if records is None or not extended or band.name not in LINES_IN_BAND or image.wcs is None:
        return None
    nebulae = [r for r in records if _otype(r["otype"]) in SIMBAD_NEBULA_TYPES]
    if not nebulae:
        return None
    where = SkyCoord(
        [u.Quantity(r["ra"], u.deg).value for r in nebulae] * u.deg,
        [u.Quantity(r["dec"], u.deg).value for r in nebulae] * u.deg,
    )
    inside = np.asarray(image.wcs.footprint_contains(where), bool)
    if not inside.any():
        return None
    emission = SkyCoord(extended)
    centre = SkyCoord(*emission.cartesian.xyz.mean(axis=1), representation_type="cartesian")
    centre = SkyCoord(centre.spherical.lon, centre.spherical.lat)
    distance = np.where(inside, where.separation(centre).arcsec, np.inf)
    best = int(np.argmin(distance))
    rec = nebulae[best]
    name, otype = str(rec["main_id"]).strip(), _otype(rec["otype"])
    line, wavelength = LINES_IN_BAND[band.name]
    n_extended = len(extended)
    return Statement(
        "IMG-5",
        f"The extended emission ({n_extended} extended sources not identified as galaxies) lies "
        f"in a field containing the catalogued nebula SIMBAD '{name}' (otype {otype}), whose "
        f"catalogue position is in this image, {distance[best]:.0f} arcsec from the centre of "
        f"that emission; {band.name} contains {line} ({wavelength} micron). Line versus "
        "continuum emission is not yet separated.",
        Level.L2_INFERENCE,
        (
            EvidenceRef("measurement", "extended sources", str(n_extended)),
            EvidenceRef("metadata", "bandpass", band.key),
            EvidenceRef("catalogue_record", f"SIMBAD {name}", f"otype {otype}"),
            EvidenceRef("rule", "R-NEB-CAT", RULES["R-NEB-CAT"]),
        ),
    )


def _image_statements(image, psf, n, scale_arcsec) -> list[Statement]:
    band = image.bandpass
    out = [
        Statement(
            "IMG-1",
            f"{image.telescope or 'unknown telescope'} {image.instrument or ''} image in "
            f"{band.key} ({image.mode}).".replace("  ", " "),
            Level.L1_OBSERVATION,
            (
                EvidenceRef(
                    "metadata", "TELESCOP/INSTRUME", f"{image.telescope}/{image.instrument}"
                ),
                EvidenceRef("metadata", "bandpass", band.key),
                EvidenceRef("metadata", str(image.mode.keyword), str(image.mode.value)),
            ),
        )
    ]
    target = image.keyword("TARGPROP") or image.keyword("TARGNAME")
    if target:
        out.append(
            Statement(
                "IMG-2",
                f"The observer's target designation is '{target}'. This labels the pointing; it "
                "is not an identification of any source in the image.",
                Level.L1_OBSERVATION,
                (EvidenceRef("metadata", "TARGPROP/TARGNAME", str(target)),),
            )
        )
    if psf is not None:
        out.append(
            Statement(
                "IMG-3",
                f"Point-source light concentration F(1.5 px)/F(4 px) = {psf['c']:.3f} "
                f"(spread {psf['spread']:.3f}), measured on {psf['n']} bright, round, unflagged "
                f"sources ({scale_arcsec:.4f} arcsec per pixel).",
                Level.L1_OBSERVATION,
                (EvidenceRef("measurement", "psf_concentration", f"{psf['c']:.3f}"),),
            )
        )
    out.append(
        Statement(
            "IMG-4",
            f"{n} sources detected.",
            Level.L1_OBSERVATION,
            (EvidenceRef("measurement", "imaging.detect", str(n)),),
        )
    )
    return out


@step("interpret.explain", version="1")
def explain(
    image: ImageProduct,
    *,
    gaia: QTable | None = None,
    catalogue: QTable | None = None,
    detect_kwargs: dict | None = None,
) -> Explanation:
    """Graded statements about an image and every source detected in it.

    Parameters
    ----------
    image : ImageProduct
        A direct image (other modes are refused).
    gaia : QTable, optional
        Gaia DR3 sources covering the field (e.g. from
        :func:`~astroledger.archives.gaia.gaia_cone`), positions at ``ref_epoch``.
    catalogue : QTable, optional
        SIMBAD records covering the field, as retrieved by
        :func:`~astroledger.archives.cds.simbad_cone` (columns ``main_id``, ``otype``, ``ra``,
        ``dec``, ``coo_err_maj``). Galaxy and nebula statements reach L2 only with it; names and
        object types are quoted verbatim from these records.
    detect_kwargs : dict, optional
        Settings for :func:`~astroledger.imaging.detect`.
    """
    require_imaging(image, "interpretation")
    catalog = detect(image, **(detect_kwargs or {})).catalog
    scale = float(np.mean(proj_plane_pixel_scales(image.wcs.celestial))) * 3600.0
    conc, conc_err, psf = _concentration(image, catalog)
    band = image.bandpass
    notes = []
    gaia_result, covered, epoch_text = None, np.zeros(len(catalog), bool), None
    if gaia is not None and len(gaia) and len(catalog):
        gaia_result, covered, epoch_text = _gaia_matches(image, catalog, gaia, scale)
        notes.append(f"Gaia DR3 positions propagated to {epoch_text}")
    else:
        notes.append("Gaia DR3 not used: no star can be established (L2) without it")
    records = _catalogue_records(catalogue)
    galaxy_match = _galaxy_matches(catalog, records, scale) if records is not None else {}
    if catalogue is None:
        notes.append("no SIMBAD records given: galaxies and nebulae stay hypotheses (L3)")
    elif records is None:
        notes.append(
            "the SIMBAD table has no records for this field: galaxies and nebulae stay "
            "hypotheses (L3)"
        )
    if psf is None:
        notes.append(
            "sizes not assessed: "
            + (
                "the image has no ERR array, so measurement errors are unknown"
                if "snr" not in catalog.colnames
                else "fewer than 5 bright, round, unflagged sources to define the PSF"
            )
            + "; without a size, no source is established as a star (L2)"
        )

    sources: dict[int, list[Statement]] = {}
    nebular_candidates: list[SkyCoord] = []  # extended sources not identified as galaxies
    counts = {
        "L2_galaxy": 0,
        "L2_nebula": 0,
        "point_like": 0,
        "extended": 0,
        "gaia_match": 0,
        "L2_star": 0,
        "artefact_candidate": 0,
    }
    flux = u.Quantity(catalog["flux"])
    flux_err = u.Quantity(catalog["flux_err"]) if "flux_err" in catalog.colnames else None
    for row in range(len(catalog)):
        label = int(catalog["label"][row])
        sid = f"SRC-{label}"
        items: list[Statement] = []
        ra, dec = (
            float(u.Quantity(catalog["ra"][row], u.deg).value),
            float(u.Quantity(catalog["dec"][row], u.deg).value),
        )
        f = flux[row]
        text = f"Source {label} at RA {ra:.6f}, Dec {dec:.6f} (ICRS): flux {f:.4g}"
        if flux_err is not None and np.isfinite(flux_err[row].value):
            text += f" ± {flux_err[row].value:.2g}"
        if f.unit == u.Jy and f.value > 0:
            text += f" ({f.to(u.ABmag).value:.2f} AB)"
        evidence = [
            EvidenceRef("measurement", f"imaging.detect label {label}", f"{f:.4g}"),
            EvidenceRef("metadata", "bandpass", band.key),
        ]
        items.append(
            Statement(f"{sid}-1", text + f" in {band.key}.", Level.L1_OBSERVATION, tuple(evidence))
        )

        size_ev = None
        point_like = extended = False
        if psf is not None and np.isfinite(conc[row]):
            c, ce = conc[row], conc_err[row]
            spread = psf["spread"]
            scale_err = float(np.hypot(ce if np.isfinite(ce) else 0.0, spread))
            z = (psf["c"] - c) / max(scale_err, 1e-6)
            size_ev = EvidenceRef(
                "measurement",
                f"concentration label {label}",
                f"F(1.5px)/F(4px) = {c:.3f}"
                + (f" ± {ce:.3f}" if np.isfinite(ce) else " (no error)")
                + f"; stars {psf['c']:.3f} ± {spread:.3f}",
            )
            if not np.isfinite(ce):
                kind = "not classified: no measurement error (the image has no ERR array)"
            elif ce > 0.25 * psf["c"]:
                kind = "too faint to tell whether it is resolved"
            elif z > 3:
                kind, extended = "less concentrated than stars: extended", True
            elif z < -3:
                kind = "more concentrated than stars (sharper than the PSF)"
            elif abs(z) <= 2:
                kind, point_like = "as concentrated as stars: unresolved", True
            else:
                kind = "marginally less concentrated than stars"
            items.append(
                Statement(
                    f"{sid}-2",
                    f"Light concentration F(1.5 px)/F(4 px) = {c:.3f}"
                    + (f" ± {ce:.3f}" if np.isfinite(ce) else "")
                    + f" against {psf['c']:.3f} for stars"
                    + (f" ({z:+.1f} sigma)" if np.isfinite(ce) else "")
                    + f": {kind}.",
                    Level.L1_OBSERVATION,
                    (size_ev, EvidenceRef("rule", "R-PSF-SIZE", RULES["R-PSF-SIZE"])),
                )
            )
            if z < -3 and np.isfinite(ce) and ce <= 0.25 * psf["c"]:
                counts["artefact_candidate"] += 1
                items.append(
                    Statement(
                        f"{sid}-8",
                        "Sharper than the PSF: possibly a residual cosmic ray, hot pixel or other "
                        "detector artefact rather than an astronomical source.",
                        Level.L3_HYPOTHESIS,
                        test="check the DQ flags and the individual exposures: a real source "
                        "appears in every exposure with the PSF's shape",
                    )
                )
            counts["point_like"] += point_like
            counts["extended"] += extended

        match = None
        if gaia_result is not None:
            best = gaia_result.best[row]
            ok = (
                best["b_index"] >= 0
                and best["reliability"] >= 0.9
                and best["p_chance"] <= gaia_result.meta["p_chance_limit"]
            )
            if ok:
                match = best
                counts["gaia_match"] += 1
                gid = f"Gaia DR3 {int(best['b_source_id'])}"
                sep_ev = EvidenceRef(
                    "measurement",
                    f"separation label {label}",
                    f"{best['sep'].to_value(u.mas):.1f} mas",
                )
                items.append(
                    Statement(
                        f"{sid}-3",
                        f"Coincides with {gid} at {best['sep'].to_value(u.mas):.1f} mas "
                        f"({best['sep_sigma']:.1f} sigma; "
                        f"chance probability {best['p_chance']:.1e}).",
                        Level.L1_OBSERVATION,
                        (sep_ev, EvidenceRef("catalogue_record", gid, "positional match")),
                        caveats=tuple(f for f in [str(best["flags"])] if f),
                    )
                )
                pm_missing = bool(best["b_pm_missing"])
                # one Gaia record matched by several detections identifies none of them
                shared = "counterpart shared" in str(best["flags"])
                if not pm_missing:
                    pmra, pmdec = _value(best["b_pmra"]), _value(best["b_pmdec"])
                    pm = float(np.hypot(pmra, pmdec))
                    pm_err = float(
                        np.hypot(
                            pmra * _value(best["b_pmra_error"]),
                            pmdec * _value(best["b_pmdec_error"]),
                        )
                        / max(pm, 1e-9)
                    )
                    significance = pm / max(pm_err, 1e-9)
                else:
                    significance = 0.0
                if point_like and not pm_missing and not shared and significance > PM_SIGNIFICANCE:
                    counts["L2_star"] += 1
                    items.append(
                        Statement(
                            f"{sid}-4",
                            f"A star in the Milky Way: unresolved, and {gid} has a proper motion "
                            f"of {pm:.2f} ± {pm_err:.2f} mas/yr ({significance:.0f} sigma).",
                            Level.L2_INFERENCE,
                            (
                                size_ev,
                                sep_ev,
                                EvidenceRef(
                                    "catalogue_record", gid, f"pm {pm:.2f} ± {pm_err:.2f} mas/yr"
                                ),
                                EvidenceRef("rule", "R-STAR-PM", RULES["R-STAR-PM"]),
                            ),
                            uncertainty=f"proper-motion significance {significance:.0f} sigma",
                        )
                    )
                elif point_like and shared:
                    items.append(
                        Statement(
                            f"{sid}-4",
                            f"Possibly {gid}, but that record also matches another detection, "
                            "so neither is identified with it.",
                            Level.L3_HYPOTHESIS,
                            test="deblend the detections or compare at higher resolution, then "
                            "repeat the match",
                        )
                    )
                elif point_like:
                    items.append(
                        Statement(
                            f"{sid}-4",
                            f"Probably a star, or a compact extragalactic object: {gid} has no "
                            "significant proper motion"
                            + (" (no proper motion in DR3)." if pm_missing else "."),
                            Level.L3_HYPOTHESIS,
                            test="a significant Gaia parallax or proper motion (later release), "
                            "stellar colours across bands, or a spectrum",
                        )
                    )
        if match is None and point_like:
            if covered[row] and gaia_result is not None:
                items.append(
                    Statement(
                        f"{sid}-4",
                        "Unresolved without a Gaia DR3 counterpart: a star fainter than Gaia's "
                        "limit (about G = 21), a compact galaxy, a compact nebular knot or noise.",
                        Level.L3_HYPOTHESIS,
                        test="colours across bands, morphology at higher resolution, a deeper "
                        "astrometric catalogue or a spectrum",
                    )
                )
            else:
                items.append(
                    Statement(
                        f"{sid}-4",
                        "Unresolved; not checked against Gaia DR3 (outside the queried area "
                        "or no Gaia table given).",
                        Level.L3_HYPOTHESIS,
                        test="cross-match with Gaia DR3 at the image epoch",
                    )
                )
        galaxy_record = galaxy_match.get(row)
        if extended and galaxy_record is not None:
            counts["L2_galaxy"] += 1
            name, otype, sep_arcsec, p_chance = galaxy_record
            items.append(
                Statement(
                    f"{sid}-9",
                    f"A galaxy: extended, and it coincides with SIMBAD record '{name}' (otype "
                    f"{otype}) at {sep_arcsec:.2f} arcsec (chance probability {p_chance:.1e}).",
                    Level.L2_INFERENCE,
                    (
                        size_ev,
                        EvidenceRef(
                            "measurement", f"separation label {label}", f"{sep_arcsec:.2f} arcsec"
                        ),
                        EvidenceRef("catalogue_record", f"SIMBAD {name}", f"otype {otype}"),
                        EvidenceRef("rule", "R-GAL-CAT", RULES["R-GAL-CAT"]),
                    ),
                )
            )
        elif extended:
            nebular_candidates.append(SkyCoord(ra * u.deg, dec * u.deg))
            items.append(
                Statement(
                    f"{sid}-5",
                    "Extended: a galaxy, a nebular structure, or a blend of sources.",
                    Level.L3_HYPOTHESIS,
                    test="a NED/SIMBAD record at this position, colours and morphology across "
                    "bands, or deblending at higher resolution",
                )
            )
            if band.name in LINES_IN_BAND:
                line, wavelength = LINES_IN_BAND[band.name]
                items.append(
                    Statement(
                        f"{sid}-6",
                        f"Its emission may be {line} ({wavelength} micron at rest), which lies in "
                        f"{band.name}; continuum emission would look the same in this band alone.",
                        Level.L3_HYPOTHESIS,
                        test=f"subtract the continuum measured in an adjacent band and look for "
                        f"an excess in {band.name}",
                    )
                )
        if bool(catalog["near_bright_source"][row]):
            counts["artefact_candidate"] += 1
            items.append(
                Statement(
                    f"{sid}-7",
                    "May be a PSF feature (diffraction spike or wing fragment) of a much brighter "
                    "nearby star rather than a separate source.",
                    Level.L3_HYPOTHESIS,
                    test="compare with an image at another roll angle or wavelength: PSF features "
                    "move or change with the PSF, real sources stay fixed on the sky",
                )
            )
        sources[label] = items

    image_statements = _image_statements(image, psf, len(catalog), scale)
    nebula = _nebula_statement(records, band, image, nebular_candidates)
    if nebula is not None:
        image_statements.append(nebula)
        counts["L2_nebula"] = 1
    summary = {
        "file": image.source.filename,
        "bandpass": band.key,
        "n_sources": len(catalog),
        "psf_concentration": psf,
        **counts,
        "levels": {
            level.name: sum(
                1
                for s in image_statements + [x for v in sources.values() for x in v]
                if s.level is level
            )
            for level in Level
        },
    }
    return Explanation(image=image_statements, sources=sources, summary=summary, notes=notes)


def format_explanation(explanation: Explanation, *, limit: int = 20) -> str:
    """Readable report: image facts, then per-source statements grouped by level."""
    s = explanation.summary
    lines = [f"{s['file']}  ({s['bandpass']})", ""]
    lines += ["Image (L1 observations)"] + [f"  [{x.id}] {x.text}" for x in explanation.image]
    lines += [
        "",
        f"Sources: {s['n_sources']} detected; {s['point_like']} unresolved, {s['extended']} "
        f"extended; {s['gaia_match']} coincide with Gaia DR3; {s['L2_star']} established as "
        f"stars (L2); {s['artefact_candidate']} possible PSF artefacts.",
    ]
    shown = explanation.ranked_sources()[:limit]
    for label, items in shown:
        lines.append(f"\n  Source {label}")
        for st in items:
            tag = {1: "L1", 2: "L2", 3: "L3"}[int(st.level)]
            lines.append(f"    {tag} [{st.id}] {st.text}")
            if st.level is Level.L3_HYPOTHESIS:
                lines.append(f"       test: {st.test}")
            for caveat in st.caveats:
                lines.append(f"       caveat: {caveat}")
    if len(explanation.sources) > limit:
        lines.append(f"\n  ... {len(explanation.sources) - limit} more sources (use --json)")
    lines += ["", "Notes"] + [f"  - {n}" for n in explanation.notes]
    lines.append(
        "  - L1 = measured; L2 = inferred from measurements and a stated rule or catalogue "
        "record; L3 = hypothesis with the test that would decide it"
    )
    return "\n".join(lines)
