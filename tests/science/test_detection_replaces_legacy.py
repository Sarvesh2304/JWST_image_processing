"""Passing counterpart of legacy defect S6/S7 (roadmap §27 task 12).

Same input as test_legacy_defects.test_pure_noise_yields_few_false_detections: 1024x1024 white
noise, sigma 1, no sources. The legacy code finds ~600 "sources"; correct detection finds few.
"""

import numpy as np
from astropy.io import fits

from astroledger.imaging import detect
from astroledger.io import open_image


def test_pure_noise_yields_few_false_detections(tmp_path):
    noise = np.random.default_rng(1).normal(0.0, 1.0, (1024, 1024)).astype("float32")
    path = tmp_path / "noise.fits"
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(noise, name="SCI")]).writeto(path)
    det = detect(open_image(path), nsigma=3.0, n_pixels=5)
    assert len(det.catalog) <= 10
    assert det.n_false_estimate <= 10
