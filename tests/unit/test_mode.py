"""Tests for the observing-mode router, astroledger.core.mode (roadmap §27 task 15).

JWST cases use authentic primary headers from tests/data/headers. The HST and non-mission cases
use small synthetic headers with the documented keywords (OBSTYPE, FILTER, APERTURE).
"""

from pathlib import Path

import pytest
from astropy.io import fits

from astroledger.core import ModeCategory, UnsupportedProductError, observing_mode, require_imaging

HEADERS = Path(__file__).parent.parent / "data" / "headers"


def _header(name):
    return fits.Header.fromtextfile(HEADERS / f"{name}.primary.txt")


@pytest.mark.parametrize(
    ("product", "category", "supported"),
    [
        ("jw02733-o001_t001_nircam_f405n-f444w_i2d.fits", ModeCategory.IMAGING, True),
        ("jw02733002001_02101_00001_mirimage_cal.fits", ModeCategory.IMAGING, True),
        ("jw02736-o003_t001_niriss_clear-f115w_i2d.fits", ModeCategory.IMAGING, True),
        (
            "jw01386-c1020_t001_nircam_f444w-maskrnd-sub320a335r_i2d.fits",
            ModeCategory.CORONAGRAPHY,
            False,
        ),
        ("jw01386-c1021_t001_miri_f1140c-mask1140_i2d.fits", ModeCategory.CORONAGRAPHY, False),
        (
            "jw01386-c1023_t001_niriss_f380m-nrm-sub80_aminorm-oi.fits",
            ModeCategory.INTERFEROMETRY,
            False,
        ),
        ("jw01386-o013_t004_nirspec_g140h-f100lp_s3d.fits", ModeCategory.SPECTROSCOPY, False),
        (
            "jw01366-o001_t001_niriss_clear-gr700xd-substrip256_x1dints.fits",
            ModeCategory.TIME_SERIES,
            False,
        ),
        (
            "jw01366-o002_t001_nircam_f322w2-grismr-subgrism256_x1dints.fits",
            ModeCategory.TIME_SERIES,
            False,
        ),
        (
            "jw01366-o004_t001_nirspec_clear-prism-s1600a1-sub512_x1dints.fits",
            ModeCategory.TIME_SERIES,
            False,
        ),
        (
            "jw01366-o011_t002_miri_p750l-slitlessprism_x1dints.fits",
            ModeCategory.TIME_SERIES,
            False,
        ),
    ],
)
def test_authentic_jwst_headers(product, category, supported):
    header = _header(product)
    mode = observing_mode(header)
    assert mode.category is category
    assert mode.supported is supported
    assert mode.keyword == "EXP_TYPE" and mode.value == header["EXP_TYPE"]
    assert header["EXP_TYPE"] in mode.reason


def test_time_series_spectroscopy_names_both():
    mode = observing_mode(
        _header("jw01366-o001_t001_niriss_clear-gr700xd-substrip256_x1dints.fits")
    )
    assert "spectroscopy" in mode.reason and "TSOVISIT" in mode.reason


@pytest.mark.parametrize(
    ("exp_type", "category"),
    [
        ("NRC_TSIMAGE", ModeCategory.TIME_SERIES),
        ("NRC_WFSS", ModeCategory.SPECTROSCOPY),
        ("MIR_MRS", ModeCategory.SPECTROSCOPY),
        ("MIR_LYOT", ModeCategory.CORONAGRAPHY),
        ("NRC_TACQ", ModeCategory.CALIBRATION),
        ("NRC_DARK", ModeCategory.CALIBRATION),
        ("NRS_IMAGE", ModeCategory.IMAGING),  # acquisition imaging: imaging, but refused
        ("XYZ_NEW", ModeCategory.UNKNOWN),
    ],
)
def test_jwst_rules_refuse_everything_but_science_imaging(exp_type, category):
    mode = observing_mode(fits.Header({"TELESCOP": "JWST", "EXP_TYPE": exp_type}))
    assert mode.category is category and not mode.supported


def test_jwst_without_exp_type_is_refused():
    mode = observing_mode(fits.Header({"TELESCOP": "JWST", "INSTRUME": "NIRCAM"}))
    assert mode.category is ModeCategory.UNKNOWN and not mode.supported


@pytest.mark.parametrize(
    ("cards", "category", "supported"),
    [
        ({"OBSTYPE": "IMAGING", "FILTER": "F160W"}, ModeCategory.IMAGING, True),
        (
            {"OBSTYPE": "IMAGING", "FILTER1": "CLEAR1L", "FILTER2": "F814W"},
            ModeCategory.IMAGING,
            True,
        ),
        ({"OBSTYPE": "SPECTROSCOPIC", "OPT_ELEM": "G430L"}, ModeCategory.SPECTROSCOPY, False),
        ({"OBSTYPE": "IMAGING", "FILTER": "G141"}, ModeCategory.SPECTROSCOPY, False),
        ({"OBSTYPE": "IMAGING", "FILTER1": "G800L"}, ModeCategory.SPECTROSCOPY, False),
        (
            {"OBSTYPE": "IMAGING", "FILTER": "F606W", "APERTURE": "HRC-CORON1.8"},
            ModeCategory.CORONAGRAPHY,
            False,
        ),
        ({"FILTER": "F606W"}, ModeCategory.UNKNOWN, False),
    ],
)
def test_hst_rules(cards, category, supported):
    mode = observing_mode(fits.Header({"TELESCOP": "HST", **cards}))
    assert mode.category is category and mode.supported is supported


def test_other_telescopes_assume_imaging_and_say_so():
    mode = observing_mode(fits.Header({"TELESCOP": "Celestron C8", "INSTRUME": "ASI2600MM"}))
    assert mode.supported and mode.keyword is None
    assert "assumed" in mode.reason and any("not established" in n for n in mode.notes)


def test_require_imaging_message_is_explicit():
    class Fake:
        primary_header = _header("jw01386-c1020_t001_nircam_f444w-maskrnd-sub320a335r_i2d.fits")
        header = fits.Header()

    with pytest.raises(UnsupportedProductError, match=r"source detection refused.*NRC_CORON"):
        require_imaging(Fake(), "source detection")
