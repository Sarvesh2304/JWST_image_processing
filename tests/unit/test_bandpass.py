"""Tests for astroledger.core.Bandpass (roadmap §27 task 6)."""

from pathlib import Path

import pytest
from astropy import units as u
from astropy.io.fits import Header

from astroledger.core import Bandpass

HEADERS = Path(__file__).resolve().parents[1] / "data" / "headers"


def real(name: str, ext: str = "primary") -> Header:
    return Header.fromtextfile(HEADERS / f"{name}.{ext}.txt")


def hdr(**cards) -> Header:
    h = Header()
    h.update(cards)
    return h


# --- Authentic JWST headers (program 2733, NGC 3132) -----------------------------------------


@pytest.mark.parametrize(
    ("product", "expected", "elements"),
    [
        (
            "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits",
            "F405N",
            {"FILTER": "F444W", "PUPIL": "F405N"},
        ),
        (
            "jw02733-o001_t001_nircam_f444w-f470n_i2d.fits",
            "F470N",
            {"FILTER": "F444W", "PUPIL": "F470N"},
        ),
        (
            "jw02733-o001_t001_nircam_clear-f356w_i2d.fits",
            "F356W",
            {"FILTER": "F356W", "PUPIL": "CLEAR"},
        ),
        (
            "jw02733-o001_t001_nircam_clear-f187n_i2d.fits",
            "F187N",
            {"FILTER": "F187N", "PUPIL": "CLEAR"},
        ),
        (
            "jw02733-o001_t001_nircam_clear-f090w_i2d.fits",
            "F090W",
            {"FILTER": "F090W", "PUPIL": "CLEAR"},
        ),
        ("jw02733-o002_t001_miri_f1130w_i2d.fits", "F1130W", {"FILTER": "F1130W"}),
    ],
)
def test_real_jwst_headers(product, expected, elements):
    band = Bandpass.from_header(real(product))
    assert band.name == expected
    assert band.elements == elements
    assert band.mode == "imaging"


def test_real_narrow_bands_sharing_f444w_stay_distinct():
    """Both NGC 3132 narrow-band mosaics have FILTER=F444W; legacy code merged them."""
    names = {
        Bandpass.from_header(real(p)).key
        for p in (
            "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits",
            "jw02733-o001_t001_nircam_f444w-f470n_i2d.fits",
        )
    }
    assert names == {"JWST/NIRCAM/F405N", "JWST/NIRCAM/F470N"}


def test_real_miri_cal_nominal_wavelength():
    name = "jw02733002001_02101_00001_mirimage_cal.fits"
    band = Bandpass.from_header(real(name), real(name, "sci"))
    assert band.key == "JWST/MIRI/F770W"
    assert band.nominal_wavelength.to_value(u.um) == pytest.approx(7.70)
    assert band.pivot is None  # JWST headers carry no pivot keyword; nothing is guessed


# --- Instrument rules -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filt", "pupil", "expected", "mode"),
    [
        ("CLEAR", "F150W", "F150W", "imaging"),
        ("CLEAR", "F090W", "F090W", "imaging"),
        ("F444W", "CLEARP", "F444W", "imaging"),
        ("F480M", "CLEARP", "F480M", "imaging"),
        ("GR150R", "F200W", "F200W", "grism"),
        ("CLEAR", "GR700XD", "CLEAR", "grism (SOSS)"),
        ("F480M", "NRM", "F480M", "aperture masking (AMI)"),
    ],
)
def test_niriss(filt, pupil, expected, mode):
    band = Bandpass.from_header(hdr(TELESCOP="JWST", INSTRUME="NIRISS", FILTER=filt, PUPIL=pupil))
    assert (band.name, band.mode) == (expected, mode)


def test_three_niriss_bands_have_three_keys():
    """Audit S3 (legacy: test_niriss_bands_are_kept_distinct)."""
    keys = {
        Bandpass.from_header(hdr(TELESCOP="JWST", INSTRUME="NIRISS", FILTER="CLEAR", PUPIL=p)).key
        for p in ("F115W", "F150W", "F200W")
    }
    assert keys == {"JWST/NIRISS/F115W", "JWST/NIRISS/F150W", "JWST/NIRISS/F200W"}


@pytest.mark.parametrize(
    ("filt", "pupil", "expected", "mode"),
    [
        ("F150W2", "F164N", "F164N", "imaging"),
        ("F322W2", "F323N", "F323N", "imaging"),
        ("F444W", "F466N", "F466N", "imaging"),
        ("F444W", "GRISMR", "F444W", "grism"),
        ("F335M", "MASKRND", "F335M", "coronagraph"),
    ],
)
def test_nircam(filt, pupil, expected, mode):
    band = Bandpass.from_header(hdr(TELESCOP="JWST", INSTRUME="NIRCAM", FILTER=filt, PUPIL=pupil))
    assert (band.name, band.mode) == (expected, mode)


def test_nircam_unexpected_pairing_is_noted():
    band = Bandpass.from_header(
        hdr(TELESCOP="JWST", INSTRUME="NIRCAM", FILTER="F356W", PUPIL="F405N")
    )
    assert band.name == "F405N"
    assert any("unexpected pairing" in n for n in band.notes)


def test_hst_acs_two_wheels_and_pivot_from_photplam():
    band = Bandpass.from_header(
        hdr(TELESCOP="HST", INSTRUME="ACS", DETECTOR="WFC", FILTER1="F606W", FILTER2="CLEAR2L"),
        hdr(PHOTPLAM=5921.9),
    )
    assert band.key == "HST/ACS/F606W"
    assert band.nominal_wavelength.to_value(u.um) == pytest.approx(0.606)
    assert band.pivot.to_value(u.um) == pytest.approx(0.59219)


@pytest.mark.parametrize(
    ("detector", "filt", "nominal_um"),
    [("IR", "F160W", 1.60), ("UVIS", "F814W", 0.814), ("UVIS", "F275W", 0.275)],
)
def test_hst_wfc3_nominal_wavelength_convention(detector, filt, nominal_um):
    band = Bandpass.from_header(
        hdr(TELESCOP="HST", INSTRUME="WFC3", DETECTOR=detector, FILTER=filt)
    )
    assert band.nominal_wavelength.to_value(u.um) == pytest.approx(nominal_um)


def test_unknown_instrument_keeps_filter_but_no_wavelength():
    band = Bandpass.from_header(hdr(INSTRUME="Generic CMOS", FILTER="Ha"))
    assert band.name == "HA" and band.nominal_wavelength is None


def test_missing_filter_is_unknown():
    band = Bandpass.from_header(hdr(TELESCOP="JWST", INSTRUME="MIRI"))
    assert band.name is None and band.mode == "unknown" and band.key == "JWST/MIRI/UNKNOWN"


def test_image_product_exposes_bandpass(tmp_path):
    import fits_factory as ff
    from astroledger.io import open_image

    img = open_image(ff.jwst_rate(tmp_path / "x_rate.fits"))  # NIRISS CLEAR + F150W
    assert img.bandpass.key == "JWST/NIRISS/F150W"
    assert "F150W" in repr(img)


def test_str_with_and_without_wavelength():
    jwst = Bandpass.from_header(hdr(TELESCOP="JWST", INSTRUME="MIRI", FILTER="F770W"))
    assert str(jwst) == "JWST/MIRI/F770W (7.7 um nominal)"
    generic = Bandpass.from_header(hdr(INSTRUME="CAM", FILTER="V"))
    assert str(generic) == "UNKNOWN/CAM/V"
