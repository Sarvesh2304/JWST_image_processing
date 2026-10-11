"""Tests for astroledger.io.open_image / open_images (roadmap §27 task 5)."""

import hashlib

import numpy as np
import pytest
from astropy import units as u
from astropy.io import fits
from astropy.nddata import StdDevUncertainty

import fits_factory as ff
from astroledger.core import AmbiguousProductError, ImageProduct, UnsupportedProductError
from astroledger.io import open_image, open_images, parse_bunit


def _raw(path, ext):
    with fits.open(path) as hdul:
        return hdul[ext].data.copy()


# --- JWST -----------------------------------------------------------------------------------


def test_jwst_cal_reads_sci_err_dq_unit_wcs(tmp_path):
    path = ff.jwst_cal(tmp_path / "jw01234001001_02101_00001_nrca1_cal.fits")
    img = open_image(path)

    assert isinstance(img, ImageProduct)
    assert img.source.extension == ("SCI", 1)
    assert img.data.shape == ff.SHAPE
    assert img.unit == u.MJy / u.sr
    assert isinstance(img.uncertainty, StdDevUncertainty)
    np.testing.assert_array_equal(img.uncertainty.array, _raw(path, "ERR"))
    assert img.telescope == "JWST" and img.instrument == "NIRCAM" and img.detector == "NRCA1"
    assert img.primary_header["CRDS_CTX"] == "jwst_1581.pmap"


def test_pixel_values_are_returned_unmodified(tmp_path):
    """Audit S4/S6: no filling of NaN, no clipping, no rescaling, dtype preserved."""
    path = ff.jwst_cal(tmp_path / "x_cal.fits")
    img = open_image(path)
    raw = _raw(path, "SCI")
    assert img.data.dtype == raw.dtype
    np.testing.assert_array_equal(img.data, raw)  # NaN compare equal positionally
    assert np.isnan(img.data[10, 20])


def test_jwst_mask_uses_nan_and_do_not_use_only(tmp_path):
    img = open_image(ff.jwst_cal(tmp_path / "x_cal.fits"))
    assert img.mask[10:12, 20:22].all()  # NaN + DO_NOT_USE
    assert img.mask[30, 40]  # DO_NOT_USE on a finite pixel
    assert not img.mask[5, 5]  # SATURATED only: informational, not masked by default
    assert img.dq[5, 5] == 2  # ...but the raw flag is kept
    assert img.n_masked == 5


def test_bad_bits_override(tmp_path):
    img = open_image(ff.jwst_cal(tmp_path / "x_cal.fits"), bad_bits=0b11)
    assert img.mask[5, 5]


def test_jwst_wcs_matches_header_and_notes_sip_approximation(tmp_path):
    img = open_image(ff.jwst_cal(tmp_path / "x_cal.fits"))
    ny, nx = ff.SHAPE
    centre = img.wcs.pixel_to_world((nx + 1) / 2 - 1, (ny + 1) / 2 - 1)  # FITS 1-based → 0-based
    assert centre.ra.deg == pytest.approx(202.47) and centre.dec.deg == pytest.approx(47.20)
    assert any("SIP approximation" in n for n in img.notes)


def test_jwst_i2d_without_dq(tmp_path):
    img = open_image(ff.jwst_i2d(tmp_path / "x_i2d.fits"))
    assert img.dq is None
    assert img.mask[:, :5].all() and not img.mask[:, 5:].any()
    assert any("no DQ extension" in n for n in img.notes)
    # Resampled mosaics have an exact TAN WCS, not a SIP approximation, despite the ASDF extension.
    assert not any("SIP approximation" in n for n in img.notes)


def test_jwst_rate_has_no_wcs_and_counts_unit(tmp_path):
    img = open_image(ff.jwst_rate(tmp_path / "x_rate.fits"))
    assert img.wcs is None
    assert img.unit == u.DN / u.s
    assert any("no celestial WCS" in n for n in img.notes)


def test_jwst_uncal_ramps_are_refused(tmp_path):
    with pytest.raises(UnsupportedProductError, match="4-D"):
        open_image(ff.jwst_uncal(tmp_path / "x_uncal.fits"))


# --- HST ------------------------------------------------------------------------------------


def test_hst_two_chip_flt_gives_two_products(tmp_path):
    path = ff.hst_flt_two_chip(tmp_path / "j8xi01abq_flt.fits")
    chips = open_images(path)
    assert [c.source.extension for c in chips] == [("SCI", 1), ("SCI", 2)]
    for chip in chips:
        assert chip.unit == u.electron
        assert chip.uncertainty is not None
    np.testing.assert_array_equal(chips[1].data, _raw(path, ("SCI", 2)))
    dec = [c.wcs.pixel_to_world(0, 0).dec.deg for c in chips]
    assert dec[0] != pytest.approx(dec[1])  # each chip keeps its own WCS
    assert chips[0].header["CCDCHIP"] == 2 and chips[1].header["CCDCHIP"] == 1


def test_hst_two_chip_requires_explicit_extver(tmp_path):
    path = ff.hst_flt_two_chip(tmp_path / "j8xi01abq_flt.fits")
    with pytest.raises(AmbiguousProductError, match="extver"):
        open_image(path)
    assert open_image(path, extver=2).source.extension == ("SCI", 2)
    with pytest.raises(UnsupportedProductError, match="EXTVER=3"):
        open_image(path, extver=3)


def test_hst_masks_any_nonzero_dq_by_default(tmp_path):
    chip1 = open_image(ff.hst_flt_two_chip(tmp_path / "x_flt.fits"), extver=1)
    assert chip1.mask[3, 5] and chip1.n_masked == 1


def test_hst_drz_counts_rate_unit_and_no_uncertainty(tmp_path):
    img = open_image(ff.hst_drz(tmp_path / "x_drz.fits"))
    assert img.unit == u.electron / u.s
    assert img.uncertainty is None
    assert any("no ERR extension" in n for n in img.notes)


# --- Plain FITS, units, provenance -----------------------------------------------------------


def test_camera_frame_from_primary_hdu(tmp_path):
    img = open_image(ff.camera_frame(tmp_path / "light_0001.fits"))
    assert img.source.extension == ("PRIMARY", 1)
    assert img.unit == u.adu
    assert img.data.dtype == np.uint16
    assert img.wcs is None and img.n_masked == 0


def test_missing_bunit_means_unknown_unit_not_dimensionless(tmp_path):
    img = open_image(ff.camera_frame(tmp_path / "light.fits", bunit=None))
    assert img.unit is None
    assert "BUNIT missing: unit unknown" in img.notes


def test_two_unnamed_images_are_ambiguous(tmp_path):
    with pytest.raises(AmbiguousProductError, match="several image HDUs"):
        open_images(ff.two_unnamed_images(tmp_path / "odd.fits"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MJy/sr", u.MJy / u.sr),
        ("DN/s", u.DN / u.s),
        ("ELECTRONS", u.electron),
        ("ELECTRONS/S", u.electron / u.s),
        ("electrons/sec", u.electron / u.s),
        ("COUNTS/S", u.count / u.s),
        ("ADU", u.adu),
        ("Jy/beam", u.Jy / u.beam),
    ],
)
def test_parse_bunit_known_forms(raw, expected):
    unit, _ = parse_bunit(raw)
    assert unit == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "FOO/BAR"])
def test_parse_bunit_unknown_forms_give_none(raw):
    unit, note = parse_bunit(raw)
    assert unit is None and "unknown" in note


def test_source_keeps_archive_filename_and_checksum(tmp_path):
    path = ff.jwst_cal(tmp_path / "jw02733001001_02101_00001_nrcb1_cal.fits")
    img = open_image(path)
    assert img.source.filename == "jw02733001001_02101_00001_nrcb1_cal.fits"
    assert img.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert open_image(path, checksum=False).source.sha256 is None


def test_reader_warnings_are_recorded_not_discarded(tmp_path):
    path = tmp_path / "odd_wcs.fits"
    hdu = fits.PrimaryHDU(np.zeros(ff.SHAPE, "float32"))
    hdu.header.update(ff.tan_wcs((10.0, 10.0), 1.0))
    hdu.header["RADESYS"] = "FK5"
    hdu.header["EQUINOX"] = 1950.0  # inconsistent with FK5 default: astropy warns/fixes
    hdu.header["DATE-OBS"] = "2020/01/01"  # non-ISO date: FITSFixedWarning
    hdu.writeto(path)
    img = open_image(path)
    assert any(n.startswith("warning while reading:") for n in img.notes)


def test_repr_is_informative(tmp_path):
    text = repr(open_image(ff.jwst_cal(tmp_path / "x_cal.fits")))
    assert "JWST/NIRCAM/NRCA1" in text and "MJy / sr" in text and "[SCI,1]" in text
