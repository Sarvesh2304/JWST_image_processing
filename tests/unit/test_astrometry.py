"""Tests for astroledger.astrometry and astroledger.crossmatch (roadmap §27 task 14).

All catalogues here are synthetic and generated in the test; authentic data are tested in
tests/science/test_astrometry_vs_gaia.py.
"""

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import QTable
from astropy.time import Time

from astroledger.astrometry import astrometric_qa, observation_epoch, plot_astrometric_qa, propagate
from astroledger.crossmatch import match_nearest

CENTRE = SkyCoord(151.757 * u.deg, -40.4365 * u.deg)
EPOCH = Time(59733.68478385996, format="mjd", scale="utc")  # an authentic JWST MJD-AVG


def _gaia(n=40, seed=0, radius_arcsec=80.0):
    """Synthetic Gaia-like table: positions at J2016.0 with proper motions and errors."""
    rng = np.random.default_rng(seed)
    r = radius_arcsec * np.sqrt(rng.uniform(0, 1, n))
    pa = rng.uniform(0, 360, n)
    pos = CENTRE.directional_offset_by(pa * u.deg, r * u.arcsec)
    t = QTable()
    t["source_id"] = np.arange(n, dtype=np.int64) + 1000
    t["ra"], t["dec"] = pos.ra.to(u.deg), pos.dec.to(u.deg)
    t["ra_error"] = rng.uniform(0.05, 0.5, n) * u.mas
    t["dec_error"] = rng.uniform(0.05, 0.5, n) * u.mas
    t["pmra"] = rng.normal(0, 15, n) * u.mas / u.yr
    t["pmdec"] = rng.normal(0, 15, n) * u.mas / u.yr
    t["pmra_error"] = rng.uniform(0.05, 0.5, n) * u.mas / u.yr
    t["pmdec_error"] = rng.uniform(0.05, 0.5, n) * u.mas / u.yr
    t["ref_epoch"] = np.full(n, 2016.0) * u.yr
    t["phot_g_mean_mag"] = rng.uniform(15, 21, n) * u.mag
    return t


def _observed(gaia, *, offset=(12.0, -7.0), rotation_arcsec=0.0, noise=2.0, seed=1):
    """Catalogue positions at EPOCH: true motion + shift + optional rotation + noise (mas)."""
    rng = np.random.default_rng(seed)
    truth = propagate(gaia, EPOCH)
    pos = SkyCoord(truth["ra_epoch"], truth["dec_epoch"])
    frame = CENTRE.skyoffset_frame()
    off = pos.transform_to(frame)
    xi, eta = off.lon.to_value(u.mas), off.lat.to_value(u.mas)
    theta = np.radians(rotation_arcsec / 3600)
    xi, eta = xi * np.cos(theta) - eta * np.sin(theta), xi * np.sin(theta) + eta * np.cos(theta)
    xi = xi + offset[0] + rng.normal(0, noise, len(xi))
    eta = eta + offset[1] + rng.normal(0, noise, len(eta))
    moved = SkyCoord(xi * u.mas, eta * u.mas, frame=frame).icrs
    return QTable({"ra": moved.ra.to(u.deg), "dec": moved.dec.to(u.deg)})


# --- epochs ---------------------------------------------------------------------------------


def test_observation_epoch_keywords():
    t, key = observation_epoch(fits.Header({"MJD-AVG": 59733.68478385996, "TIMESYS": "UTC"}))
    assert key == "MJD-AVG" and t.utc.isot.startswith("2022-06-03T16:26")
    t, key = observation_epoch(fits.Header({"EXPSTART": 60000.0, "EXPEND": 60000.5}))
    assert key == "EXPSTART/EXPEND" and t.mjd == pytest.approx(60000.25)
    t, key = observation_epoch(fits.Header({"DATE-OBS": "2023-01-02", "TIME-OBS": "03:04:05"}))
    assert key.startswith("DATE-OBS") and t.utc.isot == "2023-01-02T03:04:05.000"
    with pytest.raises(KeyError):
        observation_epoch(fits.Header({"OBJECT": "x"}))


def test_propagate_moves_along_proper_motion_and_grows_errors():
    g = _gaia(3)
    g["pmra"][0], g["pmdec"][0] = 100.0 * u.mas / u.yr, -50.0 * u.mas / u.yr
    g["pmra"][1] = np.nan * u.mas / u.yr  # two-parameter solution
    g["pmdec"][1] = np.nan * u.mas / u.yr
    epoch = Time(2026.0, format="jyear", scale="tcb")
    p = propagate(g, epoch)
    start = SkyCoord(g["ra"][0], g["dec"][0])
    dra, ddec = start.spherical_offsets_to(SkyCoord(p["ra_epoch"][0], p["dec_epoch"][0]))
    assert dra.to_value(u.mas) == pytest.approx(1000.0, abs=0.01)
    assert ddec.to_value(u.mas) == pytest.approx(-500.0, abs=0.01)
    expected = np.hypot(g["ra_error"][0].value, 10 * g["pmra_error"][0].value)
    assert p["ra_epoch_error"][0].to_value(u.mas) == pytest.approx(expected)
    assert p["pm_missing"][1] and not p["pm_missing"][0]
    assert p["ra_epoch"][1] == g["ra"][1]  # unknown motion: left at ref_epoch, flagged
    assert p.meta["epoch"]["target_jyear_tcb"] == pytest.approx(2026.0)
    assert "ra_epoch" not in g.colnames  # input untouched


# --- matching -------------------------------------------------------------------------------


def test_match_nearest_is_one_to_one():
    ref = SkyCoord([10.0, 10.001] * u.deg, [0.0, 0.0] * u.deg)
    cat = SkyCoord([10.0, 10.0000278, 10.5] * u.deg, [0.0, 0.0, 0.0] * u.deg)
    i, j, sep = match_nearest(cat, ref, 0.5 * u.arcsec)
    assert list(i) == [0] and list(j) == [0]  # the farther claimant of ref 0 is dropped
    assert sep[0] < 1e-6 * u.arcsec
    empty = match_nearest(cat[:0], ref, 1 * u.arcsec)
    assert len(empty[0]) == 0


# --- QA ---------------------------------------------------------------------------------------


def test_qa_recovers_known_offset_and_clips_outliers():
    g = _gaia(40)
    cat = _observed(g, offset=(12.0, -7.0), noise=2.0)
    # two badly centroided stars (e.g. blends)
    for k, shift in ((3, 150.0), (7, -120.0)):
        c = SkyCoord(cat["ra"][k], cat["dec"][k]).spherical_offsets_by(shift * u.mas, 0 * u.mas)
        cat["ra"][k], cat["dec"][k] = c.ra, c.dec
    qa = astrometric_qa(cat, g, epoch=EPOCH)
    s = qa.summary
    assert s["n_matched"] == 40 and s["n_used"] >= 35
    assert s["median_dra_mas"] == pytest.approx(12.0, abs=3 * s["median_dra_err_mas"])
    assert s["median_ddec_mas"] == pytest.approx(-7.0, abs=3 * s["median_ddec_err_mas"])
    assert 1.2 < s["robust_sigma_dra_mas"] < 3.0
    assert not qa.matches["used"][3] and not qa.matches["used"][7]
    assert any("systematic RA* offset" in n for n in qa.notes)
    assert qa.fit is not None and abs(qa.fit["rotation_arcsec"]) < 4 * qa.fit["rotation_err_arcsec"]
    assert qa.fit["rms_after_mas"] == pytest.approx(2.0, rel=0.3)
    assert "median offset" in qa.report()


def test_qa_without_propagation_is_worse():
    """With real proper motions, ignoring the epoch inflates the scatter: propagation matters."""
    g = _gaia(40)
    cat = _observed(g, noise=1.0)
    good = astrometric_qa(cat, g, epoch=EPOCH).summary
    stale = astrometric_qa(cat, g, epoch=Time(2016.0, format="jyear", scale="tcb")).summary
    assert stale["robust_sigma_dra_mas"] > 10 * good["robust_sigma_dra_mas"]


def test_qa_fit_recovers_rotation():
    g = _gaia(60, radius_arcsec=120)
    qa = astrometric_qa(
        _observed(g, offset=(0, 0), rotation_arcsec=20.0, noise=0.5), g, epoch=EPOCH
    )
    assert qa.fit["rotation_arcsec"] == pytest.approx(20.0, abs=4 * qa.fit["rotation_err_arcsec"])
    assert abs(qa.fit["scale_ppm"]) < 4 * qa.fit["scale_err_ppm"] + 1


def test_qa_excludes_stars_without_proper_motion():
    g = _gaia(20)
    cat = _observed(g)
    g["pmra"][:5] = np.nan * u.mas / u.yr
    qa = astrometric_qa(cat, g, epoch=EPOCH)
    assert qa.summary["n_no_pm"] == 5
    assert not np.any(qa.matches["used"][qa.matches["pm_missing"]])


def test_qa_needs_epoch_or_image():
    g = _gaia(5)
    with pytest.raises(ValueError, match="epoch"):
        astrometric_qa(_observed(g), g)


def test_plot_without_image():
    g = _gaia(20)
    fig = plot_astrometric_qa(astrometric_qa(_observed(g), g, epoch=EPOCH), title="synthetic")
    assert len(fig.axes) == 1
