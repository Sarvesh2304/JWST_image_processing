"""Astrometric QA of an authentic JWST pipeline catalogue against authentic Gaia DR3 (task 14).

Fixtures (see tests/data/real/README.md):
- 71 Gaia DR3 sources around NGC 3132, read from MAST's HATS copy;
- the 44 rows of the jwst 2.0.1 F405N catalogue within 1 arcsec of them;
- the observation epoch from the mosaic's own MJD-AVG keyword.

The numbers asserted here were measured on 2026-10-07 and are regression values. The
interpretation (an offset of about 28 mas between this mosaic's WCS and Gaia DR3 at the
observation epoch) is L1 for this product and pipeline version only.
"""

from pathlib import Path

import pytest
from astropy.table import QTable
from astropy.time import Time

from astroledger.astrometry import astrometric_qa, observation_epoch
from astroledger.io import open_image

REAL = Path(__file__).parent.parent / "data" / "real"


@pytest.fixture(scope="module")
def inputs():
    gaia = QTable.read(REAL / "gaia_dr3_ngc3132_cone.ecsv")
    catalog = QTable.read(REAL / "jw02733-o001_t001_nircam_f405n-f444w_cat_gaia_subset.ecsv")
    image = open_image(REAL / "jw02733-o001_t001_nircam_f405n-f444w_i2d_stamps.fits", extver=1)
    epoch, keyword = observation_epoch(image)
    return gaia, catalog, epoch, keyword


def test_epoch_comes_from_the_authentic_header(inputs):
    _, _, epoch, keyword = inputs
    assert keyword == "MJD-AVG"
    assert epoch.utc.isot == "2022-06-03T16:26:05.326"


def test_pipeline_catalogue_offset_from_gaia(inputs):
    gaia, catalog, epoch, _ = inputs
    qa = astrometric_qa(catalog, gaia, epoch=epoch)
    s = qa.summary
    assert s["n_used"] >= 25
    # coherent offset, measured to about 1 mas, with a few mas of star-to-star scatter
    assert s["median_dra_mas"] == pytest.approx(21.1, abs=2.0)
    assert s["median_ddec_mas"] == pytest.approx(19.5, abs=2.0)
    assert s["median_dra_err_mas"] < 1.5 and s["median_ddec_err_mas"] < 1.5
    assert s["robust_sigma_dra_mas"] < 6 and s["robust_sigma_ddec_mas"] < 6
    assert any("systematic RA* offset" in note for note in qa.notes)
    assert qa.fit is not None and qa.fit["rms_after_mas"] < 8


def test_epoch_propagation_is_needed_on_real_data(inputs):
    """At J2016.0 instead of the 2022 epoch, proper motions inflate the scatter several-fold."""
    gaia, catalog, epoch, _ = inputs
    at_epoch = astrometric_qa(catalog, gaia, epoch=epoch).summary
    stale = astrometric_qa(catalog, gaia, epoch=Time(2016.0, format="jyear", scale="tcb")).summary
    assert stale["robust_sigma_dra_mas"] > 3 * at_epoch["robust_sigma_dra_mas"]
    assert stale["robust_sigma_ddec_mas"] > 3 * at_epoch["robust_sigma_ddec_mas"]
