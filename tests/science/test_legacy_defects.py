"""Documented defects of the frozen legacy prototype (``legacy/``).

Each test asserts what a correct implementation must do and runs it against the legacy code,
where it fails. The tests are strict expected failures: if one ever passes, pytest reports an
error, because the legacy code is frozen and should not change.

They define acceptance behaviour for the replacement in ``src/astroledger``. When a new
implementation lands (roadmap §27), add an equivalent *passing* test for it, and cite the
audit item (S1-S19 in docs/lab-roadmap/01-repository-audit.md).
"""

import contextlib
import io

import numpy as np
import pytest

pytestmark = pytest.mark.legacy_defect


@pytest.fixture
def processor(legacy_path, tmp_path):
    from jwst_image_processor import JWSTImageProcessor

    return JWSTImageProcessor(data_dir=str(tmp_path / "legacy_out"))


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


@pytest.mark.xfail(
    raises=AssertionError,
    reason="S2: reads HDU 0; JWST pixels live in the SCI extension",
)
def test_loads_science_extension_of_jwst_file(processor, jwst_like_file):
    data, _header, _wcs = _quiet(processor.load_fits_file, str(jwst_like_file()))
    assert data is not None
    assert data.shape == (256, 256)


@pytest.mark.xfail(
    raises=AssertionError,
    reason="S6/S7: negative clipping + smoothed-image threshold create false sources",
)
def test_pure_noise_yields_few_false_detections(processor):
    noise = np.random.default_rng(1).normal(0.0, 1.0, (1024, 1024))
    calibrated = processor.basic_calibration(noise, {})
    smoothed = processor.denoise_image(calibrated, "gaussian")
    catalog = _quiet(processor.detect_sources, smoothed, threshold=3.0)
    n_false = 0 if catalog is None else len(catalog)
    # Measured on five 1024x1024 noise images (photutils 3.0, Gaussian kernel sigma=1, n_pixels=5):
    #   threshold 3x the *unconvolved* RMS, detecting on convolved data (photutils convention): 0
    #   threshold 3x the convolved image's own RMS:                                          38-49
    #   legacy (negative clipping + smoothed-image threshold):                               ~600
    assert n_false <= 10, f"{n_false} detections in pure noise"


@pytest.mark.xfail(
    raises=AssertionError,
    reason="S6: background subtraction must keep the noise symmetric about zero",
)
def test_background_subtraction_preserves_negative_noise(processor):
    noise = np.random.default_rng(2).normal(0.0, 1.0, (512, 512))
    calibrated = processor.basic_calibration(noise, {})
    assert np.mean(calibrated < 0) > 0.4


@pytest.mark.xfail(
    raises=AssertionError,
    reason="S3: bandpass taken from FILTER only; NIRISS uses PUPIL when FILTER=CLEAR",
)
def test_niriss_bands_are_kept_distinct(processor, jwst_like_file, monkeypatch):
    from astropy.io import fits

    paths = [
        str(jwst_like_file(f"n{i}.fits", pupil=b, seed=i))
        for i, b in enumerate(["F115W", "F150W", "F200W"])
    ]

    def load_sci(path):  # bypass the S2 defect to reach the bandpass logic
        with fits.open(path) as hdul:
            return hdul["SCI"].data.astype(float), hdul[0].header, None

    monkeypatch.setattr(processor, "load_fits_file", load_sci)
    result = _quiet(processor.process_multiple_filters, paths)
    bands = sorted(k for k in result if k != "composite")
    assert bands == ["F115W", "F150W", "F200W"]


@pytest.mark.xfail(
    raises=AssertionError,
    reason="S11: display stretch normalised by min/max is dominated by one hot pixel",
)
def test_display_stretch_robust_to_single_outlier(processor):
    image = np.random.default_rng(3).normal(0.0, 1.0, (64, 64))
    image[5, 5] = 1e6
    stretched = processor.enhance_contrast(image, "sqrt")
    assert np.percentile(stretched, 99) > 0.1


@pytest.mark.xfail(
    raises=TypeError,
    reason="Code review: ZScaleInterval passed as a matplotlib norm raises TypeError",
)
def test_multi_filter_plot_renders(legacy_path, tmp_path):
    import matplotlib.pyplot as plt
    from jwst_visualizer import JWSTVisualizer

    viz = JWSTVisualizer(data_dir=str(tmp_path / "viz"))
    rng = np.random.default_rng(4)
    fig = viz.plot_multiple_filters(
        {
            "F150W": {"enhanced_data": rng.random((32, 32))},
            "F200W": {"enhanced_data": rng.random((32, 32))},
        }
    )
    plt.close(fig)


@pytest.mark.xfail(
    raises=AssertionError,
    reason="Audit finding 2: legacy MAST search sends ra=0, dec=0 instead of the target position",
)
def test_mast_search_resolves_target_position(legacy_path, tmp_path, monkeypatch):
    import jwst_data_downloader

    captured = {}

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    def fake_post(url, json=None, **kwargs):
        captured["url"], captured["payload"] = url, json
        return _Response()

    monkeypatch.setattr(jwst_data_downloader.requests, "post", fake_post)
    downloader = jwst_data_downloader.JWSTDataDownloader(data_dir=str(tmp_path / "dl"))
    _quiet(downloader.search_observations, target="M51", instrument="NIRCam")
    params = captured["payload"]["params"]
    # M51 is near RA 202.5 deg, Dec +47.2 deg; a correct search must target that position.
    assert abs(params["ra"] - 202.47) < 1 and abs(params["dec"] - 47.20) < 1
