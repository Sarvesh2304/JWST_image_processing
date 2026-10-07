"""Passing counterpart of audit item S15, observing mode (roadmap §27 task 15).

The legacy code treats every file as a 2-D image. A JWST coronagraphic Stage-3 product is a 2-D
``_i2d`` image on disk, but its star sits behind a mask, so detection, photometry and astrometry
on it are meaningless. Each file here carries an authentic primary header (tests/data/headers)
and a small synthetic SCI array; the header alone must decide.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import QTable

import fits_factory as ff
from astroledger.astrometry import astrometric_qa
from astroledger.cli import main
from astroledger.core import UnsupportedProductError
from astroledger.imaging import detect, empirical_psf, injection_recovery
from astroledger.io import open_image
from astroledger.photometry import aperture_photometry_table
from astroledger.viz import make_rgb

HEADERS = Path(__file__).parent.parent / "data" / "headers"
REFUSED = [
    "jw01386-c1020_t001_nircam_f444w-maskrnd-sub320a335r_i2d.fits",  # NRC_CORON
    "jw01386-c1021_t001_miri_f1140c-mask1140_i2d.fits",  # MIR_4QPM
    "jw01386-o013_t004_nirspec_g140h-f100lp_s3d.fits",  # NRS_IFU
    "jw01366-o002_t001_nircam_f322w2-grismr-subgrism256_x1dints.fits",  # NRC_TSGRISM, TSO
]
ACCEPTED = "jw02736-o003_t001_niriss_clear-f115w_i2d.fits"  # NIS_IMAGE


def _file(tmp_path, product):
    """Authentic primary header + synthetic 64x64 SCI (a star on noise), MJy/sr with WCS."""
    primary = fits.Header.fromtextfile(HEADERS / f"{product}.primary.txt")
    yy, xx = np.mgrid[:64, :64]
    data = 5 * np.exp(-((xx - 32.3) ** 2 + (yy - 30.6) ** 2) / 4.0)
    data += np.random.default_rng(0).normal(0, 0.05, data.shape)
    sci = fits.Header(
        {"BUNIT": "MJy/sr", "PIXAR_SR": 9.3e-14, **ff.tan_wcs((10.0, -30.0), 0.063, data.shape)}
    )
    path = tmp_path / product
    fits.HDUList(
        [fits.PrimaryHDU(header=primary), fits.ImageHDU(data.astype("float32"), sci, name="SCI")]
    ).writeto(path)
    return path


@pytest.mark.parametrize("product", REFUSED)
def test_non_imaging_products_are_refused_everywhere(tmp_path, product):
    image = open_image(_file(tmp_path, product))  # reading is allowed; analysis is not
    exp_type = image.primary_header["EXP_TYPE"]
    calls = {
        "source detection": lambda: detect(image),
        "aperture photometry": lambda: aperture_photometry_table(
            image, np.array([[32.0, 30.0]]), 3
        ),
        "PSF building": lambda: empirical_psf(image, np.array([[32.0, 30.0]] * 3)),
        "injection-recovery": lambda: injection_recovery(image, [20.0]),
        "astrometric QA": lambda: astrometric_qa(
            QTable({"ra": [10.0] * u.deg, "dec": [-30.0] * u.deg}), QTable(), image=image
        ),
        "colour composite": lambda: make_rgb([image, image, image]),
    }
    for operation, call in calls.items():
        with pytest.raises(UnsupportedProductError, match=rf"{operation} refused.*{exp_type}"):
            call()


def test_inspect_reports_the_refusal(tmp_path, capsys):
    path = _file(tmp_path, REFUSED[0])
    assert main(["inspect", "--json", str(path)]) == 0
    observation = json.loads(capsys.readouterr().out)["observation"]
    assert observation["mode"] == "NRC_CORON"
    assert observation["mode_category"] == "coronagraphy"
    assert observation["image_analysis"].startswith("refused")


def test_authentic_imaging_header_is_accepted(tmp_path):
    image = open_image(_file(tmp_path, ACCEPTED))
    assert image.mode.supported and image.mode.value == "NIS_IMAGE"
    table = aperture_photometry_table(image, SkyCoord(*image.wcs.wcs.crval, unit="deg"), 3)
    assert len(table) == 1
