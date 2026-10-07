"""Detection completeness from injection-recovery tests.

Artificial point sources of known flux are added to a *copy* of the image, the detector is run
with the same settings as for science, and the fraction recovered at each flux level gives the
completeness curve. The original product is never modified.

Method:

- **PSF.** An empirical PSF built from bright, isolated stars in the same image
  (:func:`empirical_psf`, photutils ``EPSFBuilder``), or a circular Gaussian of given FWHM.
- **Positions.** Uniformly random within an allowed region. Positions avoid masked pixels, the
  image edges, existing detections (dilated by 6 px) and each other, so the curve describes
  sources in that region's background. An injection whose footprint merges with a neighbour is
  counted as missed, as a real source there would be; dense crowding is not modelled.
- **Recovery.** A detection within ``match_radius`` pixels of an injected position.
- **Uncertainty.** Wilson score interval (68%) on each recovered fraction.
- **Limits.** 50% and 90% completeness levels, interpolated from the faint side.

Known limitations:

- The empirical PSF is truncated at its stamp size (default 25 px), so light in the far wings
  (about 10% for NIRCam long-wavelength filters) is not injected. Injected sources are
  therefore slightly more compact than real ones of the same total flux.
- Where the background has structure on scales below the background mesh (e.g. a nebula), the
  background RMS, and hence the detection threshold, includes that structure. Completeness
  there can stay below 90% at bright levels; ``sources`` shows which injections were lost.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
from astropy import units as u
from astropy.table import QTable
from photutils.psf import CircularGaussianPRF, EPSFBuilder, extract_stars
from scipy import ndimage

from astroledger.core.product import ImageProduct
from astroledger.imaging.detection import detect
from astroledger.photometry.aperture import flux_conversion
from astroledger.provenance import step

__all__ = ["CompletenessResult", "empirical_psf", "injection_recovery", "plot_completeness"]

_STAMP = 12  # half-size (pixels) of the region each injected source is rendered into


@dataclass
class CompletenessResult:
    """Outcome of :func:`injection_recovery`.

    Attributes
    ----------
    table : astropy.table.QTable
        One row per flux level: ``flux`` (Jy if calibrated, else native), ``abmag`` (if
        calibrated), ``n_injected``, ``n_recovered``, ``completeness``, ``ci_low``, ``ci_high``
        (68% Wilson interval) and ``median_flux_ratio`` (measured / injected, recovered only).
    limits : dict
        ``{"50%": value, "90%": value}`` in AB mag (or native flux); None if not reached.
    limit_ranges : dict
        68% range of each limit, ``{"50%": (low, high), ...}``: where the lower and upper Wilson
        bounds cross the level (None where a bound never does). A wide range means a flat or
        noisy curve, and the limit should not be quoted as sharp.
    params : dict
        Settings of the test.
    notes : list of str
        Assumptions the user should know.
    sources : astropy.table.QTable
        One row per injected source: ``level``, ``x``, ``y``, ``recovered``, ``offset`` (pixels to
        the nearest detection), ``flux_ratio`` and ``area`` of that detection (NaN when missed),
        for inspecting why sources were lost.
    """

    table: QTable
    limits: dict
    params: dict
    notes: list[str] = field(default_factory=list)
    sources: QTable = field(default_factory=QTable)
    limit_ranges: dict = field(default_factory=dict)


def empirical_psf(
    image: ImageProduct,
    positions: np.ndarray,
    *,
    size: int = 25,
    oversampling: int = 2,
):
    """Build an empirical PSF from stars at ``positions`` (pixel ``(x, y)``) in the image.

    Choose bright, unsaturated, isolated stars. Each star's local background (sigma-clipped
    median of its stamp's outer ring) is subtracted first; without this the PSF inherits a
    pedestal from the sky or nebula and its wings are wrong. Returns a photutils ``ImagePSF``
    normalised to unit flux.
    """
    from astropy.nddata import NDData
    from astropy.stats import sigma_clipped_stats
    from astropy.table import Table

    data = np.where(image.mask, np.nan, np.asarray(image.data, dtype=float))
    half = size // 2
    yy, xx = np.mgrid[-half : half + 1, -half : half + 1]
    ring = np.hypot(xx, yy) >= half - 2
    stamps = []
    for x, y in np.asarray(positions, dtype=float):
        ix, iy = int(np.rint(x)), int(np.rint(y))
        if not (half <= ix < data.shape[1] - half and half <= iy < data.shape[0] - half):
            continue
        stamp = data[iy - half : iy + half + 1, ix - half : ix + half + 1]
        if np.isnan(stamp[~ring]).any():
            continue  # masked pixels in the core: unusable
        _, median, _ = sigma_clipped_stats(stamp[ring], sigma=3.0, maxiters=5)
        stamps.append((x - ix + half, y - iy + half, np.nan_to_num(stamp - median)))
    if len(stamps) < 3:
        raise ValueError(f"only {len(stamps)} usable stars for the empirical PSF (need >= 3)")
    # place background-subtracted stamps on separate tiles so extract_stars sees each once
    tile = size + 2
    mosaic = np.zeros((tile, tile * len(stamps)))
    table = Table({"x": np.zeros(len(stamps)), "y": np.zeros(len(stamps))})
    for i, (sx, sy, stamp) in enumerate(stamps):
        mosaic[1 : 1 + size, i * tile + 1 : i * tile + 1 + size] = stamp
        table["x"][i], table["y"][i] = i * tile + 1 + sx, 1 + sy
    stars = extract_stars(NDData(mosaic), table, size=(size, size))
    builder = EPSFBuilder(oversampling=oversampling, maxiters=10, progress_bar=False)
    result = builder(stars)
    return getattr(result, "epsf", result[0] if isinstance(result, tuple) else result)


def _with_data(image: ImageProduct, data: np.ndarray, note: str) -> ImageProduct:
    return ImageProduct(
        data,
        uncertainty=image.uncertainty,
        mask=None if image.mask is None else image.mask.copy(),
        wcs=image.wcs,
        unit=image.unit,
        dq=image.dq,
        header=image.header,
        primary_header=image.primary_header,
        source=image.source,
        notes=[*image.notes, note],
    )


def _wilson(k: np.ndarray, n: np.ndarray, z: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    p = np.where(n > 0, k / np.maximum(n, 1), np.nan)
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    low = np.where(k == 0, 0.0, np.clip(centre - half, 0.0, 1.0))  # exact at the ends
    high = np.where(k == n, 1.0, np.clip(centre + half, 0.0, 1.0))
    return low, high


def _crossing(x: np.ndarray, c: np.ndarray, level: float, magnitudes: bool) -> float | None:
    """Value of x where completeness first reaches ``level`` coming from the faint side."""
    order = np.argsort(x)[::-1] if magnitudes else np.argsort(x)  # faint -> bright
    xs, cs = x[order], c[order]
    for i in range(1, len(xs)):
        if cs[i - 1] < level <= cs[i]:
            frac = (level - cs[i - 1]) / (cs[i] - cs[i - 1])
            return float(xs[i - 1] + frac * (xs[i] - xs[i - 1]))
    return None


@step("imaging.injection_recovery", version="1")
def injection_recovery(
    image: ImageProduct,
    levels: Sequence[float],
    *,
    psf=None,
    fwhm: float = 2.0,
    n_per_level: int = 40,
    region: np.ndarray | None = None,
    match_radius: float = 1.5,
    min_separation: float = 25.0,
    avoid_sources: bool = True,
    seed: int = 0,
    detect_kwargs: dict | None = None,
) -> CompletenessResult:
    """Measure detection completeness by injecting and recovering point sources.

    Parameters
    ----------
    image : ImageProduct
        Image to test (not modified).
    levels : sequence of float
        AB magnitudes when the image is flux-calibrated, otherwise total fluxes in native units.
    psf : photutils PSF model, optional
        Model with ``flux``, ``x_0``, ``y_0`` parameters (e.g. from :func:`empirical_psf`).
        Default: circular Gaussian with FWHM ``fwhm`` pixels.
    n_per_level : int
        Sources injected per level (all in one image, spaced by ``min_separation`` pixels).
    region : boolean array, optional
        True where injections are allowed (e.g. clean sky vs. nebula).
    match_radius : float
        Recovery radius in pixels.
    avoid_sources : bool
        Keep injections off existing detections.
    seed : int
        Random seed (recorded, so the test is reproducible).
    detect_kwargs : dict, optional
        Settings passed to :func:`~astroledger.imaging.detect` (use the science settings).
    """
    rng = np.random.default_rng(seed)
    detect_kwargs = {**(detect_kwargs or {}), "estimate_false_positives": False}
    ny, nx = image.data.shape
    factor, conversion = flux_conversion(image)
    calibrated = factor is not None
    model = psf if psf is not None else CircularGaussianPRF(fwhm=fwhm)

    allowed = np.ones((ny, nx), bool) if region is None else np.asarray(region, bool).copy()
    if image.mask is not None:
        allowed &= ~ndimage.binary_dilation(image.mask, iterations=_STAMP // 2)
    allowed[:_STAMP], allowed[-_STAMP:], allowed[:, :_STAMP], allowed[:, -_STAMP:] = (
        False,
        False,
        False,
        False,
    )
    if avoid_sources:
        existing = detect(image, **detect_kwargs).segmentation
        if existing is not None:
            allowed &= ~ndimage.binary_dilation(existing.data > 0, iterations=6)
    candidates = np.argwhere(allowed)
    if len(candidates) == 0:
        raise ValueError("no allowed pixels for injection")

    yy, xx = np.mgrid[-_STAMP : _STAMP + 1, -_STAMP : _STAMP + 1]
    rows, per_source = [], []
    for level in levels:
        total = (10 ** (-0.4 * (level - 8.90)) / factor) if calibrated else float(level)
        positions = []
        for _ in range(50 * n_per_level):
            y, x = candidates[rng.integers(len(candidates))] + rng.uniform(-0.5, 0.5, 2)
            if all(np.hypot(x - px, y - py) >= min_separation for px, py in positions):
                positions.append((x, y))
            if len(positions) == n_per_level:
                break
        data = np.array(image.data, dtype=float, copy=True)
        for x, y in positions:
            ix, iy = int(np.rint(x)), int(np.rint(y))
            model.x_0, model.y_0, model.flux = x - ix, y - iy, total
            data[iy - _STAMP : iy + _STAMP + 1, ix - _STAMP : ix + _STAMP + 1] += model(xx, yy)
        injected = _with_data(image, data, f"{len(positions)} synthetic sources injected")
        catalog = detect(injected, **detect_kwargs).catalog
        recovered, ratios = 0, []
        for x, y in positions:
            offset, ratio, area = np.inf, np.nan, np.nan
            if len(catalog):
                d = np.hypot(np.asarray(catalog["x"]) - x, np.asarray(catalog["y"]) - y)
                j = int(np.argmin(d))
                offset = float(d[j])
                if offset <= match_radius:
                    recovered += 1
                    measured = catalog["flux"][j]
                    measured = (
                        measured.to_value(u.Jy) if calibrated else float(np.asarray(measured))
                    )
                    ratio = measured / (total * factor if calibrated else total)
                    area = float(np.asarray(catalog["area"][j]))
                    ratios.append(ratio)
            per_source.append((level, x, y, offset <= match_radius, offset, ratio, area))
        rows.append(
            (level, total, len(positions), recovered, np.median(ratios) if ratios else np.nan)
        )

    levels_arr = np.array([r[0] for r in rows], dtype=float)
    n = np.array([r[2] for r in rows])
    k = np.array([r[3] for r in rows])
    low, high = _wilson(k, n)
    table = QTable()
    if calibrated:
        table["abmag"] = levels_arr
        table["flux"] = np.array([r[1] * factor for r in rows]) * u.Jy
    else:
        table["flux"] = levels_arr
    table["n_injected"], table["n_recovered"] = n, k
    table["completeness"] = k / np.maximum(n, 1)
    table["ci_low"], table["ci_high"] = low, high
    table["median_flux_ratio"] = [r[4] for r in rows]
    limits = {
        f"{int(level * 100)}%": _crossing(
            levels_arr, np.asarray(table["completeness"]), level, calibrated
        )
        for level in (0.5, 0.9)
    }
    limit_ranges = {}
    for key, level in (("50%", 0.5), ("90%", 0.9)):
        ends = [_crossing(levels_arr, np.asarray(b), level, calibrated) for b in (low, high)]
        limit_ranges[key] = None if None in ends else (min(ends), max(ends))
    params = {
        "levels": list(map(float, levels)),
        "psf": type(model).__name__ + ("" if psf is not None else f"(fwhm={fwhm})"),
        "n_per_level": n_per_level,
        "match_radius_pix": match_radius,
        "min_separation_pix": min_separation,
        "avoid_sources": avoid_sources,
        "seed": seed,
        "detect": detect_kwargs,
        "unit_conversion": conversion,
        "region_pixels": int(allowed.sum()),
    }
    table.meta.update(
        {
            "params": params,
            "limits": limits,
            "limit_ranges": limit_ranges,
            "source_file": image.source.filename,
            "bandpass": image.bandpass.key,
        }
    )
    notes = [
        "point sources placed >= 6 px from existing detections; a merge with a neighbour counts "
        "as a miss, but dense crowding is not modelled",
        "completeness depends on the local background; test regions separately",
    ]
    sources = QTable(
        rows=per_source,
        names=("level", "x", "y", "recovered", "offset", "flux_ratio", "area"),
        dtype=(float, float, float, bool, float, float, float),
    )
    brightest = np.argmin(levels_arr) if calibrated else np.argmax(levels_arr)
    if len(rows) and table["completeness"][brightest] < 0.9:
        notes.append(
            "completeness is below 90% even at the brightest level: the local detection "
            "threshold (background RMS, which includes small-scale structure) or blending with "
            "neighbours limits recovery here; inspect `sources`"
        )
    return CompletenessResult(
        table=table,
        limits=limits,
        params=params,
        notes=notes,
        sources=sources,
        limit_ranges=limit_ranges,
    )


def plot_completeness(
    results: Sequence[CompletenessResult],
    labels: Sequence[str],
    *,
    title: str = "",
) -> plt.Figure:
    """Completeness vs magnitude (or flux) with 68% intervals, one curve per result."""
    colours = ("#2a78d6", "#eb6834", "#1baf7a")  # categorical slots 1-3, fixed order
    fig, ax = plt.subplots(figsize=(6.6, 4.2), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    magnitudes = "abmag" in results[0].table.colnames
    for result, label, colour in zip(results, labels, colours, strict=False):
        t = result.table
        x = np.asarray(t["abmag"] if magnitudes else t["flux"])
        c = np.asarray(t["completeness"])
        ax.fill_between(x, t["ci_low"], t["ci_high"], color=colour, alpha=0.15, linewidth=0)
        parts = []
        for key, value in result.limits.items():
            span = result.limit_ranges.get(key)
            if value is None:
                parts.append(f"{key}: not reached")
            elif span is None:
                parts.append(f"{key}: {value:.2f}")
            else:
                parts.append(f"{key}: {value:.2f} [{span[0]:.2f}, {span[1]:.2f}]")
        limits = ", ".join(parts)
        ax.plot(
            x, c, color=colour, linewidth=2, marker="o", markersize=4, label=f"{label} ({limits})"
        )
        for key, value in result.limits.items():
            if value is not None:
                level = float(key.rstrip("%")) / 100
                ax.plot([value, value], [level - 0.04, level + 0.04], color=colour, linewidth=2)
    for level in (0.5, 0.9):
        ax.axhline(level, color="#c9c8c3", linewidth=0.8, zorder=0)
        ax.annotate(
            f"{level:.0%}",
            (1.0, level),
            xycoords=("axes fraction", "data"),
            xytext=(3, 0),
            textcoords="offset points",
            va="center",
            fontsize=7,
            color="#52514e",
        )
    ax.set_ylim(-0.02, 1.05)
    ax.set_ylabel("fraction recovered", color="#0b0b0b")
    ax.set_xlabel("injected AB magnitude" if magnitudes else "injected flux", color="#0b0b0b")
    if magnitudes:
        ax.invert_xaxis()
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9a9994")
    ax.tick_params(colors="#52514e", labelsize=8)
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0.0, -0.16))
    ax.set_title(title, fontsize=9, color="#0b0b0b", loc="left")
    return fig
