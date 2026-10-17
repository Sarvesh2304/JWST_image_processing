"""Tests for astroledger.viz (roadmap §27 task 7)."""

import hashlib

import matplotlib
import numpy as np
import pytest
from astropy import units as u
from astropy.io import fits
from astropy.stats import sigma_clipped_stats

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
                    {
                        "TELESCOP": "JWST",
                        "INSTRUME": "NIRCAM",
                        "FILTER": filt,
                        "PUPIL": pupil,
                        "EXP_TYPE": "NRC_IMAGE",
                    }
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


def test_lupton_composite_uses_common_scaling_and_leaves_data_unchanged(tmp_path):
    centre = (202.47, 47.20)
    images = [
        _band_file(tmp_path / f"{band}.fits", band, centre, 0.063, seed)
        for seed, band in enumerate(("F470N", "F405N", "F356W"), start=1)
    ]
    digests = [_digest(i) for i in images]
    comp = make_rgb(images, stretch="lupton")
    assert comp.rgb.shape == (*ff.SHAPE, 3)
    assert 0 <= np.nanmin(comp.rgb) and np.nanmax(comp.rgb) <= 1
    assert "Lupton" in comp.method
    assert [c["colour"] for c in comp.channels] == ["red", "green", "blue"]
    assert all("lupton" in c["scale"] for c in comp.channels)
    ny, nx = ff.SHAPE
    source = comp.rgb[(ny - 1) // 2, (nx - 1) // 2].max()
    assert source > 5 * np.median(comp.rgb.max(axis=2))  # the shared source stands out
    assert [_digest(i) for i in images] == digests


def test_lupton_refuses_mixed_units(tmp_path):
    centre = (202.47, 47.20)
    images = [
        _band_file(tmp_path / f"{band}.fits", band, centre, 0.063, seed)
        for seed, band in enumerate(("F470N", "F405N", "F356W"), start=1)
    ]
    path = tmp_path / "jy.fits"
    _band_file(path, "F444W", centre, 0.063, 9)
    fits.setval(path, "BUNIT", value="Jy", extname="SCI")
    images[0] = open_image(path)
    assert images[0].unit == u.Jy
    with pytest.raises(ValueError, match="common unit"):
        make_rgb(images, stretch="lupton")


def test_lupton_white_point_is_the_stated_percentile(tmp_path):
    """Identical channels (grey): the brightest (100 - percentile)% of pixels reach white."""
    centre = (202.47, 47.20)
    images = [
        _band_file(tmp_path / f"{band}.fits", band, centre, 0.063, 1)
        for band in ("F470N", "F405N", "F356W")
    ]
    comp = make_rgb(images, stretch="lupton", percentile=99.0)
    white = np.mean(comp.rgb.max(axis=2) >= 254 / 255)
    assert 0.007 < white < 0.013
    low, high = comp.channels[0]["interval"]
    finite = images[0].data[np.isfinite(images[0].data)]
    sky = sigma_clipped_stats(finite, sigma=3.0)[1]
    assert low == pytest.approx(sky)
    assert 0.008 < np.mean(finite >= high) < 0.012  # grey pixels: white from the 99th percentile


def test_lupton_refuses_unknown_units(tmp_path):
    centre = (202.47, 47.20)
    paths = []
    for seed, band in enumerate(("F470N", "F405N", "F356W"), start=1):
        path = tmp_path / f"{band}.fits"
        _band_file(path, band, centre, 0.063, seed)
        fits.delval(path, "BUNIT", extname="SCI")
        paths.append(open_image(path))
    assert all(img.unit is None for img in paths)
    with pytest.raises(ValueError, match="known units"):
        make_rgb(paths, stretch="lupton")
