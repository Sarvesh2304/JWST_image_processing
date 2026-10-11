"""Passing counterparts of legacy defects fixed by astroledger.io (roadmap §27 task 5).

Each test uses the same input as its expected-failure twin in test_legacy_defects.py.
"""

import numpy as np

from astroledger.io import open_image


def test_loads_science_extension_of_jwst_file(jwst_like_file):
    """Audit S2 (legacy: test_loads_science_extension_of_jwst_file)."""
    img = open_image(jwst_like_file())
    assert img.data is not None
    assert img.data.shape == (256, 256)
    assert img.source.extension == ("SCI", 1)


def test_flagged_pixels_are_masked_not_zero_filled(jwst_like_file):
    """Audit S4: legacy nan_to_num turned flagged pixels into zeros that entered statistics."""
    img = open_image(jwst_like_file())
    assert np.isnan(img.data[100:103, 100:103]).all()
    assert img.mask[100:103, 100:103].all()
    assert img.n_masked == 9
