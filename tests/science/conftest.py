"""Fixtures for science tests: synthetic JWST-like files and access to the frozen legacy code."""

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pytest
from astropy.io import fits

matplotlib.use("Agg")

LEGACY = Path(__file__).resolve().parents[2] / "legacy"


@pytest.fixture(scope="session")
def legacy_path():
    """Make the frozen legacy scripts importable (they import each other by bare module name)."""
    if str(LEGACY) not in sys.path:
        sys.path.insert(0, str(LEGACY))
    return LEGACY


def write_jwst_like(
    path, *, filt="CLEAR", pupil="F150W", instrument="NIRISS", seed=0, shape=(256, 256)
):
    """Write a JWST-style multi-extension FITS file: empty primary HDU, pixels in SCI/ERR/DQ.

    Contains pure Gaussian noise (no sources) and a block of NaN pixels, as flagged
    pixels appear in JWST calibrated products.
    """
    rng = np.random.default_rng(seed)
    sci = rng.normal(0.0, 1.0, shape).astype("float32")
    sci[100:103, 100:103] = np.nan
    primary = fits.PrimaryHDU()
    primary.header.update(TELESCOP="JWST", INSTRUME=instrument, FILTER=filt, PUPIL=pupil)
    sci_hdu = fits.ImageHDU(sci, name="SCI")
    sci_hdu.header["BUNIT"] = "MJy/sr"
    fits.HDUList(
        [
            primary,
            sci_hdu,
            fits.ImageHDU(np.ones_like(sci), name="ERR"),
            fits.ImageHDU(np.zeros(shape, "uint32"), name="DQ"),
        ]
    ).writeto(path, overwrite=True)
    return path


@pytest.fixture
def jwst_like_file(tmp_path):
    return lambda name="x_cal.fits", **kw: write_jwst_like(tmp_path / name, **kw)
