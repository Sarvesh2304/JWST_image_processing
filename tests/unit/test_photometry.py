"""Tests for astroledger.photometry (roadmap §27 task 11)."""

import numpy as np
import pytest
from astropy import units as u
from astropy.io import fits

import fits_factory as ff
from astroledger.io import open_image
from astroledger.photometry import aperture_photometry_table, flux_conversion

PIXAR_SR = 9.336882e-14


def _star_image(path, *, flux_jy=1e-5, bkg=0.5, noise=0.01, unit="MJy/sr", extra=None, seed=0):
    """Gaussian star (sigma 1.5 px) of known total flux on a flat background, with ERR."""
    ny, nx = 81, 81
    yy, xx = np.mgrid[:ny, :nx]
    jy_per_pixel = flux_jy * np.exp(-((xx - 40.3) ** 2 + (yy - 39.7) ** 2) / (2 * 1.5**2))
    jy_per_pixel /= 2 * np.pi * 1.5**2
    data = jy_per_pixel / (PIXAR_SR * 1e6) + bkg  # MJy/sr
    data += np.random.default_rng(seed).normal(0, noise, data.shape)
    sci = fits.Header(
        {"BUNIT": unit, "PIXAR_SR": PIXAR_SR, **ff.tan_wcs((151.75, -40.44), 0.063, (ny, nx))}
    )
    sci.update(extra or {})
    fits.HDUList(
        [
            fits.PrimaryHDU(
                header=fits.Header(
                    {
                        "TELESCOP": "JWST",
                        "INSTRUME": "NIRCAM",
                        "FILTER": "F356W",
                        "EXP_TYPE": "NRC_IMAGE",
                    }
                )
            ),
            fits.ImageHDU(data.astype("float32"), name="SCI", header=sci),
            fits.ImageHDU(
                np.full(data.shape, noise, "float32"),
                name="ERR",
                header=fits.Header({"BUNIT": unit}),
            ),
        ]
    ).writeto(path)
    return open_image(path)


def test_recovers_injected_flux_with_honest_error(tmp_path):
    img = _star_image(tmp_path / "star_i2d.fits")
    t = aperture_photometry_table(img, np.array([[40.3, 39.7]]), 9.0, annulus=(14, 20))
    flux, err = t["flux"][0], t["flux_err"][0]
    assert t["flux"].unit == u.Jy
    # 9 px aperture holds 1 - exp(-0.5*(9/1.5)^2) of a Gaussian's flux (~100%)
    assert abs(flux - 1e-5 * u.Jy) < 3 * err
    expected_sum_err = np.sqrt(np.pi * 81) * 0.01 * PIXAR_SR * 1e6  # sqrt(area) * ERR, in Jy
    assert t["flux_err_aperture"][0].to_value(u.Jy) == pytest.approx(expected_sum_err, rel=0.01)
    assert t["flux_err"][0] >= t["flux_err_aperture"][0]
    assert t["bkg_per_pixel"][0].to_value(u.Jy) == pytest.approx(0.5 * PIXAR_SR * 1e6, rel=0.01)
    assert t["abmag"][0] == pytest.approx(-2.5 * np.log10(flux.to_value(u.Jy) / 3631), abs=1e-9)
    assert not t["bkg_unstable"][0]
    assert "correlated noise" in t.meta["caveats"][0]


def test_sky_positions_equal_pixel_positions(tmp_path):
    img = _star_image(tmp_path / "s.fits")
    sky = img.wcs.pixel_to_world(40.3, 39.7)
    a = aperture_photometry_table(img, np.array([[40.3, 39.7]]), 4.0)
    b = aperture_photometry_table(img, sky, 4.0)
    assert b["flux"][0].to_value(u.Jy) == pytest.approx(a["flux"][0].to_value(u.Jy), rel=1e-9)
    c = aperture_photometry_table(img, sky, 4 * 0.063 * u.arcsec)
    assert c.meta["aperture_radius_pix"] == pytest.approx(4.0, rel=1e-3)


def test_aperture_correction_is_explicit(tmp_path):
    img = _star_image(tmp_path / "s.fits")
    plain = aperture_photometry_table(img, np.array([[40.3, 39.7]]), 3.0)
    corrected = aperture_photometry_table(
        img, np.array([[40.3, 39.7]]), 3.0, aperture_correction=1.428
    )
    assert (corrected["flux"][0] / plain["flux"][0]).to_value("") == pytest.approx(1.428)
    assert not plain.meta["aperture_corrected"] and corrected.meta["aperture_corrected"]


def test_masked_pixels_are_reported(tmp_path):
    img = _star_image(tmp_path / "s.fits")
    img.mask[40, 41] = True
    t = aperture_photometry_table(img, np.array([[40.3, 39.7]]), 3.0)
    assert t["masked_fraction"][0] == pytest.approx(1 / (np.pi * 9), rel=0.05)


def test_hst_photfnu_and_photflam_conversions(tmp_path):
    img = _star_image(tmp_path / "hst.fits", unit="ELECTRONS/S", extra={"PHOTFNU": 1.5e-7})
    factor, how = flux_conversion(img)
    assert factor == pytest.approx(1.5e-7) and "PHOTFNU" in how
    img2 = _star_image(
        tmp_path / "hst2.fits", unit="ELECTRONS/S", extra={"PHOTFLAM": 1e-19, "PHOTPLAM": 5921.9}
    )
    factor2, _ = flux_conversion(img2)
    expected = (
        1e-19 * u.erg / u.s / u.cm**2 / u.AA * (5921.9 * u.AA) ** 2 / (2.99792458e18 * u.AA / u.s)
    ).to_value(u.Jy)
    assert factor2 == pytest.approx(expected, rel=1e-9)


def test_uncalibrated_units_give_no_magnitudes(tmp_path):
    img = _star_image(tmp_path / "raw.fits", unit="DN/s")
    t = aperture_photometry_table(img, np.array([[40.3, 39.7]]), 3.0)
    assert "abmag" not in t.colnames
    assert any("no flux calibration" in c for c in t.meta["caveats"])
