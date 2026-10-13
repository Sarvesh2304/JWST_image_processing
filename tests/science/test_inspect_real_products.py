"""`astroledger inspect` on real NIRCam, NIRISS, MIRI, WFC3 and ACS metadata (roadmap task 10).

Each file is built from authentic archive headers (tests/data/headers) and a small synthetic
pixel array, except NIRCam, which uses the authentic pixel stamps in tests/data/real. The
metadata facts must match what the archive products state.
"""

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from astroledger.inspect import fact_sheet
from astroledger.io import open_image

HEADERS = Path(__file__).parent.parent / "data" / "headers"
REAL = Path(__file__).parent.parent / "data" / "real"


def _build(tmp_path, product, *, err=True):
    primary = fits.Header.fromtextfile(HEADERS / f"{product}.primary.txt")
    sci = fits.Header.fromtextfile(HEADERS / f"{product}.sci.txt")
    data = np.random.default_rng(0).normal(1.0, 0.1, (64, 64)).astype("float32")
    hdus = [fits.PrimaryHDU(header=primary), fits.ImageHDU(data, sci, name="SCI")]
    if err:
        hdus.append(fits.ImageHDU(np.full_like(data, 0.1), name="ERR"))
    path = tmp_path / product
    fits.HDUList(hdus).writeto(path)
    return open_image(path)


@pytest.mark.parametrize(
    ("product", "bandpass", "unit", "pivot_um", "scale_arcsec", "mode"),
    [
        (
            "jw02733002001_02101_00001_mirimage_cal.fits",
            "JWST/MIRI/F770W",
            "MJy / sr",
            None,
            0.110,
            "MIR_IMAGE",
        ),
        (
            "jw02736-o003_t001_niriss_clear-f115w_i2d.fits",
            "JWST/NIRISS/F115W",
            "MJy / sr",
            1.1495,
            0.0656,
            "NIS_IMAGE",
        ),
        ("ic0201010_drc.fits", "HST/WFC3/F658N", "electron / s", 0.65839, 0.0396, "IMAGING"),
        (
            "hst_14662_01_acs_wfc_f814w_jd8001ii_flc.fits",
            "HST/ACS/F814W",
            "electron",
            0.80455,
            0.050,
            "IMAGING",
        ),
    ],
)
def test_fact_sheet_matches_archive_metadata(
    tmp_path, product, bandpass, unit, pivot_um, scale_arcsec, mode
):
    sheet = fact_sheet(_build(tmp_path, product))
    obs = sheet["observation"]
    assert obs["bandpass"] == bandpass
    assert obs["mode"] == mode and obs["image_analysis"] == "supported"
    assert sheet["image"]["unit"] == unit
    if pivot_um is None:
        assert obs["pivot_wavelength_um"] is None
    else:
        assert obs["pivot_wavelength_um"] == pytest.approx(pivot_um, abs=2e-4)
    assert np.mean(sheet["image"]["pixel_scale_arcsec"]) == pytest.approx(scale_arcsec, rel=0.02)


def test_acs_wcs_without_lookup_tables_is_explained(tmp_path):
    image = _build(tmp_path, "hst_14662_01_acs_wfc_f814w_jd8001ii_flc.fits")
    assert image.wcs is not None
    assert any("distortion lookup tables" in note for note in image.notes)


def test_nircam_real_pixels(tmp_path):
    image = open_image(REAL / "jw02733-o001_t001_nircam_f405n-f444w_i2d_stamps.fits", extver=1)
    sheet = fact_sheet(image)
    assert sheet["observation"]["bandpass"] == "JWST/NIRCAM/F405N"
    assert sheet["observation"]["pivot_wavelength_um"] == pytest.approx(4.0529, abs=2e-4)
    assert sheet["image"]["unit"] == "MJy / sr"
    assert np.mean(sheet["image"]["pixel_scale_arcsec"]) == pytest.approx(0.0630, rel=0.01)
