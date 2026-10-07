"""Tests for astroledger.imaging.completeness (roadmap §27 task 13)."""

import hashlib

import numpy as np
import pytest
from test_detection import STARS, _field

from astroledger.imaging import empirical_psf, injection_recovery
from astroledger.imaging.completeness import _crossing, _wilson
from astroledger.photometry import flux_conversion

NOISE = 0.1
SIGMA = 2.0 / 2.3548  # default injected PSF: Gaussian, FWHM 2 px


def _abmag_at_snr(image, snr):
    """AB magnitude of a Gaussian (FWHM 2 px) source with the given optimal S/N in white noise."""
    native = snr * NOISE * np.sqrt(4 * np.pi * SIGMA**2)
    factor, _ = flux_conversion(image)
    return 8.90 - 2.5 * np.log10(native * factor)


def test_wilson_interval_bounds_and_coverage():
    low, high = _wilson(np.array([0, 20, 40]), np.array([40, 40, 40]))
    assert low[0] == pytest.approx(0.0, abs=1e-12) and high[2] == pytest.approx(1.0)
    assert low[1] < 0.5 < high[1]
    assert np.all(high - low > 0)


def test_crossing_from_faint_side():
    mags = np.array([22.0, 23.0, 24.0, 25.0])
    comp = np.array([1.0, 0.8, 0.4, 0.0])
    assert _crossing(mags, comp, 0.5, magnitudes=True) == pytest.approx(23.75)
    assert _crossing(mags, comp, 0.9, magnitudes=True) == pytest.approx(22.5)
    assert _crossing(mags, np.zeros(4), 0.5, magnitudes=True) is None
    fluxes = np.array([1.0, 2.0, 3.0])
    assert _crossing(fluxes, np.array([0.0, 0.5, 1.0]), 0.9, magnitudes=False) == pytest.approx(2.8)


def test_completeness_on_white_noise(tmp_path):
    img = _field(tmp_path / "noise.fits", stars=[], noise=NOISE, seed=3)
    before = hashlib.sha256(np.ascontiguousarray(img.data).tobytes()).hexdigest()
    levels = [_abmag_at_snr(img, s) for s in (4.0, 60.0)]
    result = injection_recovery(img, levels, n_per_level=20, seed=1)
    table = result.table
    assert list(table["n_injected"]) == [20, 20]
    faint, bright = table["completeness"]
    assert faint <= 0.1 and bright >= 0.95
    assert 0.8 < table["median_flux_ratio"][1] <= 1.05  # isophotal flux of a bright source
    assert np.all(table["ci_low"] <= table["completeness"])
    assert np.all(table["completeness"] <= table["ci_high"])
    assert levels[1] < result.limits["50%"] < levels[0]  # brighter = smaller magnitude
    low, high = result.limit_ranges["50%"]
    assert levels[1] <= low <= result.limits["50%"] <= high <= levels[0]
    assert len(result.sources) == 40
    assert result.sources["recovered"].sum() == table["n_recovered"].sum()
    assert result.params["seed"] == 1 and table.meta["bandpass"]
    # the science image is never modified
    assert hashlib.sha256(np.ascontiguousarray(img.data).tobytes()).hexdigest() == before
    assert not any("injected" in note for note in img.notes)


def test_completeness_is_reproducible(tmp_path):
    img = _field(tmp_path / "noise.fits", stars=[], noise=NOISE, seed=3)
    level = [_abmag_at_snr(img, 12.0)]
    a = injection_recovery(img, level, n_per_level=15, seed=5)
    b = injection_recovery(img, level, n_per_level=15, seed=5)
    assert np.array_equal(a.sources["x"], b.sources["x"])
    assert a.table["n_recovered"][0] == b.table["n_recovered"][0]


def test_region_restricts_injections(tmp_path):
    img = _field(tmp_path / "noise.fits", stars=[], noise=NOISE, seed=3)
    region = np.zeros(img.data.shape, bool)
    region[:, 128:] = True
    result = injection_recovery(
        img, [_abmag_at_snr(img, 60.0)], n_per_level=8, region=region, seed=2
    )
    assert np.all(result.sources["x"] >= 127.5)


def test_empirical_psf_ignores_background_pedestal(tmp_path):
    """Regression: stars on a bright background must not give a PSF with a flat pedestal."""
    img = _field(tmp_path / "stars.fits", amplitude=50.0, noise=0.01, seed=4)
    img.data[...] += 5.0  # e.g. diffuse nebular emission under the stars
    psf = empirical_psf(img, np.array(STARS), size=25)
    yy, xx = np.mgrid[-12:13, -12:13]
    psf.x_0, psf.y_0, psf.flux = 0.0, 0.0, 1.0
    stamp = psf(xx, yy)
    assert stamp.sum() == pytest.approx(1.0, abs=0.02)
    # Gaussian sigma 1.2 px: peak fraction 1 / (2 pi sigma^2) = 0.1105 (sampling lowers it a bit)
    assert stamp.max() == pytest.approx(1 / (2 * np.pi * 1.2**2), rel=0.1)
    assert abs(np.median(stamp[np.hypot(xx, yy) > 10])) < 1e-4


def test_empirical_psf_needs_enough_stars(tmp_path):
    img = _field(tmp_path / "stars.fits", amplitude=50.0)
    with pytest.raises(ValueError, match="usable stars"):
        empirical_psf(img, np.array([[5.0, 5.0], [60.9, 200.4]]))
