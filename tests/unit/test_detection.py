"""Tests for astroledger.imaging.detect (roadmap §27 task 12)."""

import hashlib

import numpy as np
import pytest
from astropy import units as u
from astropy.io import fits

import fits_factory as ff
from astroledger.imaging import detect
from astroledger.io import open_image

STARS = [(40.2, 50.7), (120.6, 30.1), (200.3, 150.8), (60.9, 200.4), (170.5, 90.2)]


def _field(path, *, stars=STARS, amplitude=2.0, noise=0.1, shape=(256, 256), seed=1, with_err=True):
    """Gaussian stars (sigma 1.2 px) on a flat background with white noise, MJy/sr."""
    ny, nx = shape
    yy, xx = np.mgrid[:ny, :nx]
    data = np.full(shape, 0.3)
    for x, y in stars:
        data += amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.2**2))
    data += np.random.default_rng(seed).normal(0, noise, shape)
    sci = fits.Header(
        {"BUNIT": "MJy/sr", "PIXAR_SR": 9.3e-14, **ff.tan_wcs((151.75, -40.44), 0.063, shape)}
    )
    hdus = [
        fits.PrimaryHDU(
            header=fits.Header({"TELESCOP": "JWST", "INSTRUME": "NIRCAM", "FILTER": "F356W"})
        ),
        fits.ImageHDU(data.astype("float32"), name="SCI", header=sci),
    ]
    if with_err:
        hdus.append(fits.ImageHDU(np.full(shape, noise, "float32"), name="ERR"))
    fits.HDUList(hdus).writeto(path)
    return open_image(path)


def test_recovers_injected_stars_with_few_false_positives(tmp_path):
    img = _field(tmp_path / "f.fits")
    before = hashlib.sha256(np.ascontiguousarray(img.data).tobytes()).hexdigest()
    det = detect(img)
    cat = det.catalog
    assert len(cat) == len(STARS)
    for x, y in STARS:
        d = np.hypot(cat["x"] - x, cat["y"] - y)
        assert d.min() < 0.2
    assert det.n_false_estimate == 0
    assert cat["flux"].unit == u.Jy and np.all(cat["snr"] > 20)
    assert "ra" in cat.colnames
    assert hashlib.sha256(np.ascontiguousarray(img.data).tobytes()).hexdigest() == before
    assert det.false_positive_positions().shape == (0, 2)


def test_masked_pixels_cannot_become_sources(tmp_path):
    img = _field(tmp_path / "f.fits")
    img.data[100:104, 100:104] = 1e4  # a bright artefact...
    img.mask[100:104, 100:104] = True  # ...that is flagged
    cat = detect(img).catalog
    assert not np.any((np.abs(cat["x"] - 101.5) < 4) & (np.abs(cat["y"] - 101.5) < 4))


def test_works_without_err(tmp_path):
    det = detect(_field(tmp_path / "f.fits", with_err=False))
    assert len(det.catalog) == len(STARS)
    assert "flux_err" not in det.catalog.colnames
    assert any("no ERR" in n for n in det.notes)


def test_negative_detections_are_located(tmp_path):
    img = _field(tmp_path / "f.fits", stars=[])
    img.data[60:66, 60:66] -= 3.0  # a negative artefact, e.g. over-subtracted background
    det = detect(img)
    pos = det.false_positive_positions()
    assert det.n_false_estimate >= 1
    assert np.hypot(pos[:, 0] - 62.5, pos[:, 1] - 62.5).min() < 2


@pytest.mark.parametrize("nsigma", [3.0, 5.0])
def test_parameters_are_recorded(tmp_path, nsigma):
    det = detect(_field(tmp_path / "f.fits"), nsigma=nsigma)
    assert det.catalog.meta["params"]["nsigma"] == nsigma
    assert det.params["threshold"] == "nsigma x unconvolved background RMS"
