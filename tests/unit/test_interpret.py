"""Tests for the evidence engine, astroledger.interpret (roadmap §27 task 18).

The image and Gaia table here are synthetic and built in the test. The checks follow the task's
"done when": zero fabricated identities, and every L2 statement has evidence.
"""

import json
import re

import numpy as np
import pytest
from astropy import units as u
from astropy.io import fits
from astropy.table import QTable
from astropy.time import Time

import fits_factory as ff
from astroledger.cli import main
from astroledger.core import UnsupportedProductError
from astroledger.interpret import (
    EvidenceError,
    EvidenceRef,
    Level,
    Statement,
    explain,
    format_explanation,
)
from astroledger.io import open_image

CATALOGUE_NAME = re.compile(r"\b(NGC|IC|HD|HIP|2MASS|SDSS|PN)\s?\d|\bM\s?\d{1,3}\b")
MJD = 59733.68478385996  # an authentic JWST MJD-AVG
SHAPE = (300, 300)
STARS = [
    (40.3, 50.6),
    (120.7, 40.2),
    (220.4, 60.8),
    (60.6, 150.3),
    (150.2, 140.7),
    (250.5, 160.4),
    (80.8, 250.6),
    (200.3, 240.2),
]
BLOB = (150.0, 220.0)


def _write(path, exp_type="NRC_IMAGE"):
    yy, xx = np.mgrid[: SHAPE[0], : SHAPE[1]]
    data = np.full(SHAPE, 0.2)
    for x, y in STARS:
        data += 40 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.2**2))
    data += 3 * np.exp(-((xx - BLOB[0]) ** 2 + (yy - BLOB[1]) ** 2) / (2 * 5.0**2))
    data += np.random.default_rng(2).normal(0, 0.05, SHAPE)
    primary = fits.Header(
        {
            "TELESCOP": "JWST",
            "INSTRUME": "NIRCAM",
            "FILTER": "F444W",
            "PUPIL": "F405N",
            "EXP_TYPE": exp_type,
            "TARGPROP": "MY-TARGET",
            "MJD-AVG": MJD,
            "TIMESYS": "UTC",
        }
    )
    sci = fits.Header(
        {"BUNIT": "MJy/sr", "PIXAR_SR": 9.3e-14, **ff.tan_wcs((151.75, -40.44), 0.063, SHAPE)}
    )
    fits.HDUList(
        [
            fits.PrimaryHDU(header=primary),
            fits.ImageHDU(data.astype("float32"), sci, name="SCI"),
            fits.ImageHDU(np.full(SHAPE, 0.05, "float32"), name="ERR"),
        ]
    ).writeto(path)
    return path


def _gaia(image):
    """Synthetic Gaia rows for stars 0-2: significant PM, insignificant PM, no PM."""
    epoch = Time(MJD, format="mjd", scale="utc")
    dt = epoch.tcb.jyear - 2016.0
    rows = []
    for k, (pmra, pmdec, err) in enumerate(
        [(8.0, -6.0, 0.1), (0.1, 0.1, 0.5), (np.nan, np.nan, np.nan)]
    ):
        now = image.wcs.pixel_to_world(*STARS[k])
        move = (0.0 if np.isnan(pmra) else -pmra * dt, 0.0 if np.isnan(pmdec) else -pmdec * dt)
        then = now.spherical_offsets_by(move[0] * u.mas, move[1] * u.mas)
        rows.append(
            (1000 + k, then.ra.deg, then.dec.deg, 0.2, 0.2, pmra, err, pmdec, err, 2016.0, 18.0)
        )
    t = QTable(
        rows=rows,
        names=(
            "source_id",
            "ra",
            "dec",
            "ra_error",
            "dec_error",
            "pmra",
            "pmra_error",
            "pmdec",
            "pmdec_error",
            "ref_epoch",
            "phot_g_mean_mag",
        ),
    )
    for name, unit in (
        ("ra", u.deg),
        ("dec", u.deg),
        ("ra_error", u.mas),
        ("dec_error", u.mas),
        ("pmra", u.mas / u.yr),
        ("pmra_error", u.mas / u.yr),
        ("pmdec", u.mas / u.yr),
        ("pmdec_error", u.mas / u.yr),
        ("ref_epoch", u.yr),
        ("phot_g_mean_mag", u.mag),
    ):
        t[name] = np.asarray(t[name], float) * unit
    centre = image.wcs.pixel_to_world(150, 150)
    t.meta.update({"center_deg": [centre.ra.deg, centre.dec.deg], "radius_arcsec": 30.0})
    return t


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    image = open_image(_write(tmp_path_factory.mktemp("img") / "synthetic_i2d.fits"))
    gaia = _gaia(image)
    return image, gaia, explain(image, gaia=gaia)


def _label_at(result, image, xy):
    """Label of the detection nearest a pixel position (via statement-free catalogue)."""
    from astroledger.imaging import detect

    cat = detect(image).catalog
    d = np.hypot(np.asarray(cat["x"]) - xy[0], np.asarray(cat["y"]) - xy[1])
    return int(cat["label"][np.argmin(d)])


# --- evidence rules ----------------------------------------------------------------------------


def test_levels_require_their_evidence():
    measured = EvidenceRef("measurement", "flux", "1 Jy")
    rule = EvidenceRef("rule", "R-X", "a rule")
    Statement("a", "measured", Level.L1_OBSERVATION, (measured,))
    with pytest.raises(EvidenceError):
        Statement("b", "no evidence", Level.L1_OBSERVATION)
    with pytest.raises(EvidenceError):
        Statement("c", "inference without a rule", Level.L2_INFERENCE, (measured,))
    with pytest.raises(EvidenceError):
        Statement("d", "inference without a measurement", Level.L2_INFERENCE, (rule,))
    Statement("e", "inference", Level.L2_INFERENCE, (measured, rule))
    with pytest.raises(EvidenceError):
        Statement("f", "hypothesis without a test", Level.L3_HYPOTHESIS)
    with pytest.raises(EvidenceError):
        EvidenceRef("hunch", "x")


def test_downgrade_only():
    s = Statement(
        "a", "x", Level.L2_INFERENCE, (EvidenceRef("measurement", "m"), EvidenceRef("rule", "r"))
    )
    assert s.downgrade(Level.L3_HYPOTHESIS, test="t").level is Level.L3_HYPOTHESIS
    with pytest.raises(EvidenceError):
        s.downgrade(Level.L1_OBSERVATION)


# --- engine ------------------------------------------------------------------------------------


def test_star_with_significant_proper_motion_is_l2(case):
    image, _, result = case
    label = _label_at(result, image, STARS[0])
    levels = {s.id: s for s in result.sources[label]}
    star = levels[f"SRC-{label}-4"]
    assert star.level is Level.L2_INFERENCE and "Gaia DR3 1000" in star.text
    kinds = {e.kind for e in star.evidence}
    assert {"measurement", "catalogue_record", "rule"} <= kinds


def test_gaia_source_without_significant_motion_stays_l3(case):
    image, _, result = case
    for k in (1, 2):
        label = _label_at(result, image, STARS[k])
        statement = {s.id: s for s in result.sources[label]}[f"SRC-{label}-4"]
        assert statement.level is Level.L3_HYPOTHESIS and statement.test


def test_unmatched_star_and_extended_blob_are_hypotheses(case):
    image, _, result = case
    star = {s.id: s for s in result.sources[_label_at(result, image, STARS[5])]}
    assert any(s.level is Level.L3_HYPOTHESIS and "without a Gaia" in s.text for s in star.values())
    blob = result.sources[_label_at(result, image, BLOB)]
    assert any("less concentrated than stars: extended" in s.text for s in blob)
    line = [s for s in blob if "Brackett-alpha" in s.text]
    assert line and line[0].level is Level.L3_HYPOTHESIS
    assert not any(s.level is Level.L2_INFERENCE for s in blob)  # no galaxy/nebula claims


def test_no_fabricated_identities(case):
    _, gaia, result = case
    known = {str(int(i)) for i in gaia["source_id"]}
    for statement in result.statements():
        for found in re.findall(r"Gaia DR3 (\d+)", statement.text):
            assert found in known
        if statement.id != "IMG-2":  # the observer's designation, quoted from the header
            assert "MY-TARGET" not in statement.text
            assert not CATALOGUE_NAME.search(statement.text)
    target = next(s for s in result.image if s.id == "IMG-2")
    assert "not an identification" in target.text


def test_every_l2_has_evidence(case):
    _, gaia, result = case
    known = {f"Gaia DR3 {int(i)}" for i in gaia["source_id"]}
    l2 = [s for s in result.statements() if s.level is Level.L2_INFERENCE]
    assert l2
    for s in l2:
        refs = {e.ref for e in s.evidence if e.kind == "catalogue_record"}
        assert refs and refs <= known
        assert any(e.kind == "rule" for e in s.evidence)
        assert any(e.kind == "measurement" for e in s.evidence)


def test_without_gaia_nothing_reaches_l2(case):
    image, _, _ = case
    result = explain(image)
    assert not any(s.level is Level.L2_INFERENCE for s in result.statements())
    assert any("Gaia DR3 not used" in n for n in result.notes)


def test_non_imaging_is_refused(tmp_path):
    image = open_image(_write(tmp_path / "coron.fits", exp_type="NRC_CORON"))
    with pytest.raises(UnsupportedProductError, match="interpretation refused"):
        explain(image)


def test_text_report_and_cli(case, tmp_path, capsys):
    _, gaia, result = case
    text = format_explanation(result, limit=3)
    assert "Image (L1 observations)" in text and "test:" in text
    path = _write(tmp_path / "cli_i2d.fits")
    gaia_path = tmp_path / "gaia.ecsv"
    gaia.write(gaia_path, format="ascii.ecsv")
    assert main(["explain", str(path), "--gaia", str(gaia_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["L2_star"] == 1
    assert main(["explain", str(path), "--limit", "2"]) == 0
    assert "Sources:" in capsys.readouterr().out


def test_text_report_lists_l2_sources_first(case):
    _, _, result = case
    first = format_explanation(result, limit=1).split("  Source ")[1]
    assert " L2 [" in first


# --- catalogue rules (SIMBAD records; synthetic here) -----------------------------------------


def _records(image, rows):
    """Synthetic SIMBAD-like records at pixel positions: (name, otype, (x, y))."""
    from astropy import units as u

    names, otypes, ras, decs = [], [], [], []
    for name, otype, xy in rows:
        sky = image.wcs.pixel_to_world(*xy)
        names.append(name)
        otypes.append(otype)
        ras.append(sky.ra.deg)
        decs.append(sky.dec.deg)
    return QTable(
        {
            "main_id": np.array(names, dtype=object),
            "otype": np.array(otypes, dtype=object),
            "ra": np.array(ras) * u.deg,
            "dec": np.array(decs) * u.deg,
            "coo_err_maj": np.full(len(rows), 50.0) * u.mas,
        }
    )


def test_extended_source_matching_a_catalogued_galaxy_is_l2(case):
    image, gaia, _ = case
    records = _records(image, [("SYNTH GAL 1", "G", BLOB), ("SYNTH STAR", "*", STARS[5])])
    result = explain(image, gaia=gaia, catalogue=records)
    blob = result.sources[_label_at(result, image, BLOB)]
    galaxy = [s for s in blob if s.level is Level.L2_INFERENCE]
    assert galaxy and "SYNTH GAL 1" in galaxy[0].text and "otype G" in galaxy[0].text
    refs = {e.ref for e in galaxy[0].evidence if e.kind == "catalogue_record"}
    assert refs == {"SIMBAD SYNTH GAL 1"}
    assert result.summary["L2_galaxy"] == 1


def test_candidate_types_never_reach_l2(case):
    image, gaia, _ = case
    records = _records(image, [("SYNTH GAL 1", "G?", BLOB)])
    result = explain(image, gaia=gaia, catalogue=records)
    blob = result.sources[_label_at(result, image, BLOB)]
    assert not any(s.level is Level.L2_INFERENCE for s in blob)


def test_nebula_rule_needs_line_band_and_catalogued_nebula(case):
    image, gaia, _ = case
    with_nebula = explain(
        image, gaia=gaia, catalogue=_records(image, [("SYNTH PN", "PN", (150, 150))])
    )
    neb = [s for s in with_nebula.image if s.id == "IMG-5"]
    assert neb and neb[0].level is Level.L2_INFERENCE and "SYNTH PN" in neb[0].text
    assert "Brackett-alpha" in neb[0].text and "not yet separated" in neb[0].text
    without = explain(image, gaia=gaia, catalogue=_records(image, [("SYNTH GAL", "G", (5, 5))]))
    assert not [s for s in without.image if s.id == "IMG-5"]


def test_catalogue_names_only_from_records(case):
    image, gaia, _ = case
    records = _records(image, [("SYNTH GAL 1", "G", BLOB), ("SYNTH PN", "PN", (150, 150))])
    result = explain(image, gaia=gaia, catalogue=records)
    allowed = {f"SIMBAD {n}" for n in records["main_id"]} | {
        f"Gaia DR3 {int(i)}" for i in gaia["source_id"]
    }
    for s in result.statements():
        for e in s.evidence:
            if e.kind == "catalogue_record":
                assert e.ref in allowed
        for quoted in re.findall(r"SIMBAD(?: record)? '([^']+)'", s.text):
            assert quoted in set(records["main_id"])


def test_catalogue_without_required_columns_is_refused(case):
    image, _, _ = case
    with pytest.raises(ValueError, match="lacks columns"):
        explain(image, catalogue=QTable({"main_id": ["x"]}))


def test_cli_reads_a_simbad_table_written_as_ecsv(case, tmp_path, capsys):
    image, _, _ = case
    path = _write(tmp_path / "cli_i2d.fits")
    records_path = tmp_path / "simbad.ecsv"
    _records(image, [("SYNTH GAL 1", "G", BLOB)]).write(records_path, format="ascii.ecsv")
    assert main(["explain", str(path), "--catalogue", str(records_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["L2_galaxy"] == 1
    texts = [
        s["text"] for v in payload["sources"].values() for s in v if s["level"] == "L2_INFERENCE"
    ]
    assert any("SYNTH GAL 1" in t for t in texts)
