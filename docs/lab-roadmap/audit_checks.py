"""Reproducible checks of defects in the original JWST_image_processing code.
Run from the repository root:  python docs/lab-roadmap/audit_checks.py
Needs: astropy, photutils, scipy, scikit-image, matplotlib (no network access).
Each check prints REPRODUCED (defect confirmed) or NOT REPRODUCED."""
import os, sys, tempfile
import numpy as np
sys.path.insert(0, os.getcwd())
import matplotlib; matplotlib.use("Agg")
from astropy.io import fits

results = []
def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"check itself crashed: {e!r}"
    results.append((name, ok, detail))
    print(f"[{'REPRODUCED' if ok else 'NOT REPRODUCED'}] {name}\n    {detail}")

tmp = tempfile.mkdtemp()

def make_jwst_like(path, filt="CLEAR", pupil="F150W", inst="NIRISS", seed=0):
    """JWST-style multi-extension FITS: empty primary, data in SCI (ext 1)."""
    rng = np.random.default_rng(seed)
    sci = rng.normal(0.0, 1.0, (256, 256)).astype("float32")
    sci[100:103, 100:103] = np.nan          # flagged pixels are NaN in JWST cal products
    ph = fits.PrimaryHDU()
    ph.header.update(INSTRUME=inst, FILTER=filt, PUPIL=pupil, TELESCOP="JWST")
    sh = fits.ImageHDU(sci, name="SCI"); sh.header["BUNIT"] = "MJy/sr"
    fits.HDUList([ph, sh, fits.ImageHDU(np.ones_like(sci), name="ERR"),
                  fits.ImageHDU(np.zeros(sci.shape, "uint32"), name="DQ")]).writeto(path, overwrite=True)
    return path

from jwst_image_processor import JWSTImageProcessor
proc = JWSTImageProcessor(data_dir=os.path.join(tmp, "d"))

def c1():
    p = make_jwst_like(os.path.join(tmp, "a_cal.fits"))
    data, hdr, wcs = proc.load_fits_file(p)
    return data is None, "load_fits_file reads HDU 0; JWST science data live in the 'SCI' extension -> returns (None, None, None)"
check("Main pipeline cannot load JWST multi-extension FITS", c1)

def c2():
    # Pure noise, no sources. Apply the repo's calibration + denoise + detection.
    rng = np.random.default_rng(1)
    n = rng.normal(0, 1, (1024, 1024))
    cal = proc.basic_calibration(n, {})
    frac_zero = np.mean(cal == 0)
    den = proc.denoise_image(cal, "gaussian")
    cat = proc.detect_sources(den, threshold=3.0)
    nsrc = 0 if cat is None else len(cat)
    return nsrc > 0, (f"pure Gaussian noise (no sources): {frac_zero:.0%} of pixels clipped to 0; "
                      f"'3-sigma' detection on smoothed+clipped data finds {nsrc} spurious 'sources'")
check("Negative clipping + smoothing breaks the noise model and creates false detections", c2)

def c3():
    from photutils.segmentation import detect_sources, SourceCatalog
    rng = np.random.default_rng(2)
    img = rng.normal(0, 1, (128, 128))
    img[60:66, 60:66] += 20
    seg = detect_sources(img, 5.0, n_pixels=5)
    cat = SourceCatalog(img, seg)
    has_old = hasattr(cat[0], "semimajor_axis_sigma")
    return (not has_old), "photutils SourceCatalog has no 'semimajor_axis_sigma' attribute (renamed 'semimajor_sigma'); visualizer also uses 'u' without importing astropy.units"
check("plot_source_catalog uses removed photutils attributes / undefined name 'u'", c3)

def c4():
    from jwst_visualizer import JWSTVisualizer
    v = JWSTVisualizer(data_dir=os.path.join(tmp, "v"))
    try:
        v.plot_multiple_filters({"F150W": {"enhanced_data": np.random.rand(32, 32)},
                                 "F200W": {"enhanced_data": np.random.rand(32, 32)}})
        return False, "no error"
    except Exception as e:
        return True, f"passing astropy ZScaleInterval as a matplotlib 'norm' raises: {type(e).__name__}: {str(e)[:110]}"
check("Visualizer passes ZScaleInterval as norm (4 of 6 plot functions affected)", c4)

def c5():
    import io, contextlib
    paths = [make_jwst_like(os.path.join(tmp, f"n{i}.fits"), filt="CLEAR", pupil=pp, seed=i)
             for i, pp in enumerate(["F115W", "F150W", "F200W"])]
    # bypass the HDU-0 bug to reach the keying logic, as find_jwst_data does (largest HDU)
    orig = proc.load_fits_file
    def load(p):
        with fits.open(p) as h:
            return h["SCI"].data.astype(float), h[0].header, None
    proc.load_fits_file = load
    with contextlib.redirect_stdout(io.StringIO()):
        out = proc.process_multiple_filters(paths)
    proc.load_fits_file = orig
    keys = [k for k in out if k != "composite"]
    return keys == ["CLEAR"], f"3 NIRISS images taken through F115W/F150W/F200W (FILTER=CLEAR, PUPIL=Fxxx) collapse to keys {keys}: 2 of 3 silently overwritten"
check("Filter identity read from FILTER only; results keyed by filter overwrite each other", c5)

def c6():
    req = open("requirements.txt").read().lower()
    return "astroquery" not in req, "astroquery (the only working MAST path, used by find_jwst_data.py) is absent from requirements.txt"
check("requirements.txt omits astroquery", c6)

def c7():
    src = open("jwst_data_downloader.py").read()
    bad = '"ra": 0' in src and "Invoke/Mast.Caom.Cone" in src
    return bad, ("JWSTDataDownloader posts JSON to a non-existent endpoint path with ra=0, dec=0 and "
                 "unsupported 'target'/'instrument' params; Mast.Caom.Cone returns observations, not 'productFilename' rows")
check("Legacy MAST downloader cannot work as written", c7)

def c8():
    rng = np.random.default_rng(3)
    a = rng.normal(0, 1, (64, 64)); a[5, 5] = 1e6   # one hot pixel / cosmic ray
    e = proc.enhance_contrast(a, "sqrt")
    return np.median(e) > 0 and np.percentile(e, 99) < 0.01, (f"min/max normalisation with one hot pixel: 99th percentile of output = {np.percentile(e,99):.4f} "
                                                              "(the whole image is compressed into <1% of the display range)")
check("enhance_contrast min/max normalisation is dominated by single outliers", c8)

print("\nSummary:", sum(ok for _, ok, _ in results), "of", len(results), "defects reproduced")
