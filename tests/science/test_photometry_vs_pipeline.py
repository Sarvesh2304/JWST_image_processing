"""Authentic-data regression: astroledger reproduces JWST pipeline aperture photometry.

Data: three real NGC 3132 NIRCam F405N stars and the pipeline's catalogue rows for them
(see tests/data/real/README.md).
"""

from pathlib import Path

import numpy as np
import pytest
from astropy.table import QTable

from astroledger.io import open_images
from astroledger.photometry import aperture_photometry_table

REAL = Path(__file__).resolve().parents[1] / "data" / "real"
STAMPS = REAL / "jw02733-o001_t001_nircam_f405n-f444w_i2d_stamps.fits"
CATALOG = REAL / "jw02733-o001_t001_nircam_f405n-f444w_cat_subset.ecsv"


@pytest.fixture(scope="module")
def stamps_and_catalog():
    return open_images(STAMPS), QTable.read(CATALOG)


@pytest.mark.parametrize(("index", "ee"), [(0, 30), (1, 50), (2, 70)])
def test_aperture_fluxes_match_pipeline(stamps_and_catalog, index, ee):
    stamps, cat = stamps_and_catalog
    params = cat.meta["aperture_params"]
    radius = params["aperture_radii"][index]
    annulus = (params["bkg_aperture_inner_radius"], params["bkg_aperture_outer_radius"])
    for stamp, row in zip(stamps, cat, strict=True):
        x = row["xcentroid"] - stamp.header["CUTX0"]
        y = row["ycentroid"] - stamp.header["CUTY0"]
        t = aperture_photometry_table(stamp, np.array([[x, y]]), radius, annulus=annulus)
        assert t["flux"][0].to_value("Jy") == pytest.approx(
            row[f"aper{ee}_flux"].to_value("Jy"), rel=1e-5
        )
        assert t["flux_err_aperture"][0].to_value("Jy") == pytest.approx(
            row[f"aper{ee}_flux_err"].to_value("Jy"), rel=1e-5
        )
        assert t["bkg_per_pixel"][0].to_value("Jy") == pytest.approx(
            row["aper_bkg_flux"].to_value("Jy"), rel=1e-5
        )


def test_total_flux_with_pipeline_aperture_correction(stamps_and_catalog):
    stamps, cat = stamps_and_catalog
    params = cat.meta["aperture_params"]
    for stamp, row in zip(stamps, cat, strict=True):
        xy = np.array(
            [[row["xcentroid"] - stamp.header["CUTX0"], row["ycentroid"] - stamp.header["CUTY0"]]]
        )
        t = aperture_photometry_table(
            stamp,
            xy,
            params["aperture_radii"][2],
            aperture_correction=params["aperture_corrections"][2],
        )
        assert t["flux"][0].to_value("Jy") == pytest.approx(
            row["aper_total_flux"].to_value("Jy"), rel=1e-5
        )
        assert t["abmag"][0] + 2.5 * np.log10(params["aperture_corrections"][2]) == pytest.approx(
            row["aper70_abmag"], abs=1e-4
        )


def test_stamps_are_real_archive_cutouts(stamps_and_catalog):
    stamps, _ = stamps_and_catalog
    assert stamps[0].primary_header["CUTSRC"] == "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits"
    assert stamps[0].bandpass.key == "JWST/NIRCAM/F405N"
    assert stamps[0].keyword("CAL_VER") == "2.0.1"
