"""Tests for astroledger.viz (roadmap §27 task 7)."""

import hashlib

import matplotlib
import numpy as np
import pytest
from astropy.io import fits

import fits_factory as ff
from astroledger.io import open_image
from astroledger.viz import display_norm, make_rgb, show, show_rgb

matplotlib.use("Agg")


def _digest(img):
    return hashlib.sha256(np.ascontiguousarray(img.data).tobytes()).hexdigest()


def _band_file(path, band, crval, scale, seed, shape=ff.SHAPE):
    """NIRCam-like single-band image with a point source at the reference position."""
    ny, nx = shape
    data = np.random.default_rng(seed).normal(0.0, 0.05, shape).astype("float32")
    yy, xx = np.mgrid[:ny, :nx]
    data += 5.0 * np.exp(-(((xx - (nx - 1) / 2) ** 2 + (yy - (ny - 1) / 2) ** 2) / 8.0))
    data[0, 0] = np.nan
    pupil, filt = ("F405N", "F444W") if band == "F405N" else ("CLEAR", band)
    fits.HDUList(
        [
            fits.PrimaryHDU(
                header=fits.Header(
                    {"TELESCOP": "JWST", "INSTRUME": "NIRCAM", "FILTER": filt, "PUPIL": pupil}
                )
            ),
            fits.ImageHDU(
                data,
                name="SCI",
                header=fits.Header({"BUNIT": "MJy/sr", **ff.tan_wcs(crval, scale, shape)}),
            ),
        ]
    ).writeto(path)
    return open_image(path)


def test_display_norm_ignores_masked_pixels(tmp_path):
    img = open_image(ff.jwst_cal(tmp_path / "x_cal.fits"))
    img.data[30, 40] = 1e9  # finite outlier on a DO_NOT_USE (masked) pixel
    norm = display_norm(img, percentile=100)
    assert norm.vmax < 1e3


def test_show_does_not_modify_data_and_labels_units(tmp_path):
    img = open_image(ff.jwst_cal(tmp_path / "x_cal.fits"))
    before = _digest(img)
    fig = show(img)
    assert _digest(img) == before
    assert np.isnan(img.data[10, 20])  # NaN still NaN in the product
    labels = [t.get_text() for t in fig.texts]
    assert any("display only" in t for t in labels)
    assert any(ax.get_ylabel() == "MJy / sr" for ax in fig.axes)
    fig.savefig(tmp_path / "out.png")


def test_rgb_is_chromatically_ordered_and_reprojected(tmp_path):
    centre = (202.47, 47.20)
    f470 = _band_file(tmp_path / "a.fits", "F470N", centre, 0.063, 1)
    f356 = _band_file(tmp_path / "b.fits", "F356W", centre, 0.063, 2)
    # Different pixel scale and shape: must be reprojected onto the reference grid.
    f405 = _band_file(tmp_path / "c.fits", "F405N", centre, 0.031, 3, shape=(128, 160))
    digests = [_digest(i) for i in (f470, f356, f405)]

    comp = make_rgb([f405, f470, f356])  # deliberately out of order

    assert [c["colour"] for c in comp.channels] == ["red", "green", "blue"]
    assert [c["bandpass"] for c in comp.channels] == [
        "JWST/NIRCAM/F470N",
        "JWST/NIRCAM/F405N",
        "JWST/NIRCAM/F356W",
    ]
    assert comp.rgb.shape == (*ff.SHAPE, 3)  # grid of the reddest image
    assert np.nanmax(comp.rgb) <= 1 and np.nanmin(comp.rgb) >= 0
    # The source at the reference position is bright in every channel after alignment.
    ny, nx = ff.SHAPE
    centre_pixel = comp.rgb[(ny - 1) // 2, (nx - 1) // 2]
    assert (centre_pixel > 0.8).all()
    assert [_digest(i) for i in (f470, f356, f405)] == digests
    fig = show_rgb(comp, title="test")
    assert any("R: F470N" in t.get_text() for t in fig.texts)


def test_rgb_requires_three_images_with_wcs(tmp_path):
    img = open_image(ff.jwst_cal(tmp_path / "x_cal.fits"))
    with pytest.raises(ValueError, match="exactly 3"):
        make_rgb([img, img])
    rate = open_image(ff.jwst_rate(tmp_path / "x_rate.fits"))
    with pytest.raises(ValueError, match="WCS"):
        make_rgb([img, img, rate])
