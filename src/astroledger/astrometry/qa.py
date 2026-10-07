"""Astrometric quality of an image's world coordinates, measured against Gaia DR3.

Method (roadmap project I1):

1. Propagate Gaia positions to the image's mid-exposure epoch (:func:`propagate`).
2. Match the image catalogue to Gaia one-to-one within ``match_radius``.
3. Residual = catalogue position minus Gaia position, as (ΔRA·cos Dec, ΔDec) in mas.
4. Exclude stars without a Gaia proper motion and, when the image is given, stars with flagged
   pixels within ``mask_radius`` (e.g. saturated cores, whose centroids are biased).
5. Clip iteratively around the median, in normalised 2-D distance with the same coverage as
   ``clip`` standard deviations in 1-D (robust standard deviations from the MAD).
6. Report: number used, median offset with its error, RMS, robust scatter, and a 4-parameter
   fit (shift, rotation, scale) over the field.

All numbers are L1 measurements of *this catalogue's* positions. They describe the image's WCS
only as far as the centroids are unbiased; the centroiding method is part of the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import QTable
from astropy.time import Time
from astropy.wcs.utils import proj_plane_pixel_scales
from scipy import ndimage
from scipy.special import erf
from scipy.stats import chi2

from astroledger.astrometry.epoch import observation_epoch, propagate
from astroledger.core.product import ImageProduct
from astroledger.crossmatch import match_nearest
from astroledger.provenance import step

__all__ = ["AstrometricQA", "astrometric_qa", "plot_astrometric_qa"]

_MAD_TO_SIGMA = 1.4826
_MEDIAN_EFFICIENCY = 1.2533  # error of a median = 1.2533 sigma / sqrt(N) for Gaussian data


@dataclass
class AstrometricQA:
    """Outcome of :func:`astrometric_qa`.

    Attributes
    ----------
    matches : astropy.table.QTable
        One row per catalogue/Gaia pair: ``source_id``, positions, ``dra``/``ddec`` residuals
        (mas), Gaia errors at the epoch, ``pm_missing``, ``near_mask``, ``clipped`` and ``used``.
    summary : dict
        ``n_matched``, ``n_used``, ``median_dra_mas``, ``median_ddec_mas`` and their errors,
        ``rms_mas`` (total, both axes), ``robust_sigma_dra_mas``, ``robust_sigma_ddec_mas``,
        ``median_gaia_error_mas``, ``epoch``, ``epoch_keyword``.
    fit : dict or None
        Shift (mas), rotation (arcsec), scale (ppm), each with an error, and post-fit RMS; None
        when fewer than ``min_fit`` stars are used.
    notes : list of str
        Caveats and interpretation hints.
    """

    matches: QTable
    summary: dict
    fit: dict | None
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        """Plain-text report (L1 measurements)."""
        s = self.summary
        lines = [
            f"epoch {s['epoch']} (from {s['epoch_keyword']})",
            f"matched {s['n_matched']}, used {s['n_used']}",
        ]
        if s["n_used"]:
            lines += [
                f"median offset dRA* = {s['median_dra_mas']:.1f} "
                f"± {s['median_dra_err_mas']:.1f} mas, "
                f"dDec = {s['median_ddec_mas']:.1f} ± {s['median_ddec_err_mas']:.1f} mas",
                f"RMS {s['rms_mas']:.1f} mas; robust sigma dRA* {s['robust_sigma_dra_mas']:.1f}, "
                f"dDec {s['robust_sigma_ddec_mas']:.1f} mas; "
                f"median Gaia error at epoch {s['median_gaia_error_mas']:.2f} mas",
            ]
        if self.fit:
            f = self.fit
            lines.append(
                f"fit: rotation {f['rotation_arcsec']:.3f} "
                f"± {f['rotation_err_arcsec']:.3f} arcsec, "
                f"scale {f['scale_ppm']:.1f} ± {f['scale_err_ppm']:.1f} ppm, "
                f"post-fit RMS {f['rms_after_mas']:.1f} mas"
            )
        return "\n".join(lines + [f"note: {n}" for n in self.notes])


def _catalog_coords(catalog: QTable) -> SkyCoord:
    if "sky_centroid" in catalog.colnames:
        return SkyCoord(catalog["sky_centroid"])
    return SkyCoord(u.Quantity(catalog["ra"], u.deg), u.Quantity(catalog["dec"], u.deg))


def _robust(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    return median, float(_MAD_TO_SIGMA * np.median(np.abs(values - median)))


def _similarity_fit(xi, eta, dra, ddec) -> dict:
    """Least-squares dRA = a + s·xi - r·eta, dDec = b + r·xi + s·eta (xi, eta in arcsec)."""
    n = len(xi)
    design = np.zeros((2 * n, 4))
    design[:n, 0], design[n:, 1] = 1.0, 1.0
    design[:n, 2], design[n:, 2] = xi, eta  # scale
    design[:n, 3], design[n:, 3] = -eta, xi  # rotation
    target = np.concatenate([dra, ddec])
    params, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = target - design @ params
    dof = max(2 * n - 4, 1)
    sigma2 = float(residual @ residual) / dof
    cov = sigma2 * np.linalg.inv(design.T @ design)
    err = np.sqrt(np.diag(cov))
    to_rad = 1e-3  # mas per arcsec -> dimensionless
    return {
        "shift_dra_mas": float(params[0]),
        "shift_dra_err_mas": float(err[0]),
        "shift_ddec_mas": float(params[1]),
        "shift_ddec_err_mas": float(err[1]),
        "scale_ppm": float(params[2] * to_rad * 1e6),
        "scale_err_ppm": float(err[2] * to_rad * 1e6),
        "rotation_arcsec": float(np.degrees(params[3] * to_rad) * 3600),
        "rotation_err_arcsec": float(np.degrees(err[3] * to_rad) * 3600),
        "rms_after_mas": float(np.sqrt(np.mean(residual**2) * 2)),
        "n": n,
    }


@step("astrometry.gaia_qa", version="1")
def astrometric_qa(
    catalog: QTable,
    gaia: QTable,
    *,
    image: ImageProduct | None = None,
    epoch: Time | None = None,
    match_radius: u.Quantity = 0.5 * u.arcsec,
    clip: float = 3.0,
    max_iter: int = 10,
    mask_radius: int = 3,
    exclude_no_pm: bool = True,
    min_fit: int = 6,
) -> AstrometricQA:
    """Compare catalogue positions with Gaia DR3 propagated to the observation epoch.

    Parameters
    ----------
    catalog : QTable
        Image catalogue with ``ra``/``dec`` or ``sky_centroid`` (e.g. from
        :func:`~astroledger.imaging.detect`, or a pipeline catalogue).
    gaia : QTable
        Gaia DR3 sources (e.g. from :func:`~astroledger.archives.gaia.gaia_cone`).
    image : ImageProduct, optional
        Source of the epoch, pixel positions and mask.
    epoch : astropy.time.Time, optional
        Observation epoch; required if ``image`` is not given.
    match_radius : Quantity
        Matching radius. Keep it below half the typical separation of Gaia stars.
    clip : float
        Rejection threshold, as a 1-D equivalent in robust standard deviations.
    mask_radius : int
        Pixels: stars with flagged pixels this close are excluded (needs ``image``).
    exclude_no_pm : bool
        Exclude Gaia two-parameter solutions (no proper motion, so no reliable epoch position).
    min_fit : int
        Minimum stars for the shift/rotation/scale fit.
    """
    if epoch is None:
        if image is None:
            raise ValueError("give an image or an epoch")
        epoch, keyword = observation_epoch(image)
    else:
        keyword = "given"
    reference = propagate(gaia, epoch)
    gaia_coords = SkyCoord(reference["ra_epoch"], reference["dec_epoch"])
    coords = _catalog_coords(catalog)
    i_cat, i_ref, _ = match_nearest(coords, gaia_coords, match_radius)

    matched_gaia = gaia_coords[i_ref]
    matched_cat = coords[i_cat]
    dra, ddec = matched_gaia.spherical_offsets_to(matched_cat)
    matches = QTable()
    matches["catalog_index"] = i_cat
    matches["source_id"] = np.asarray(reference["source_id"])[i_ref]
    matches["ra"], matches["dec"] = matched_cat.ra.to(u.deg), matched_cat.dec.to(u.deg)
    matches["ra_gaia"], matches["dec_gaia"] = matched_gaia.ra.to(u.deg), matched_gaia.dec.to(u.deg)
    matches["dra"], matches["ddec"] = dra.to(u.mas), ddec.to(u.mas)
    matches["gaia_ra_error"] = reference["ra_epoch_error"][i_ref]
    matches["gaia_dec_error"] = reference["dec_epoch_error"][i_ref]
    if "phot_g_mean_mag" in reference.colnames:
        matches["phot_g_mean_mag"] = reference["phot_g_mean_mag"][i_ref]
    matches["pm_missing"] = np.asarray(reference["pm_missing"])[i_ref]

    near_mask = np.zeros(len(matches), bool)
    if image is not None and image.wcs is not None:
        x, y = image.wcs.world_to_pixel(matched_cat)
        matches["x"], matches["y"] = x, y
        matches["x_gaia"], matches["y_gaia"] = image.wcs.world_to_pixel(matched_gaia)
        if image.mask is not None and len(matches):
            grown = ndimage.binary_dilation(image.mask, iterations=mask_radius)
            ix = np.clip(np.rint(x).astype(int), 0, image.mask.shape[1] - 1)
            iy = np.clip(np.rint(y).astype(int), 0, image.mask.shape[0] - 1)
            near_mask = grown[iy, ix]
    matches["near_mask"] = near_mask

    no_pm = np.asarray(matches["pm_missing"], bool)
    candidate = ~near_mask & (~no_pm if exclude_no_pm else np.ones(len(matches), bool))
    candidate &= np.isfinite(matches["dra"].value) & np.isfinite(matches["ddec"].value)
    used = candidate.copy()
    dx, dy = matches["dra"].to_value(u.mas), matches["ddec"].to_value(u.mas)
    # 2-D radius with the same coverage as +-clip sigma in 1-D (3 -> 3.44)
    radius_2d = float(np.sqrt(chi2.ppf(erf(clip / np.sqrt(2)), df=2)))
    for _ in range(max_iter):
        if used.sum() < 3:
            break
        mx, sx = _robust(dx[used])
        my, sy = _robust(dy[used])
        distance = np.hypot((dx - mx) / max(sx, 1e-6), (dy - my) / max(sy, 1e-6))
        new = candidate & (distance <= radius_2d)
        if np.array_equal(new, used):
            break
        used = new
    matches["clipped"] = candidate & ~used
    matches["used"] = used

    n_used = int(used.sum())
    summary = {
        "n_matched": len(matches),
        "n_used": n_used,
        "n_no_pm": int(np.sum(matches["pm_missing"])),
        "n_near_mask": int(near_mask.sum()),
        "n_clipped": int(np.sum(matches["clipped"])),
        "epoch": epoch.utc.isot,
        "epoch_keyword": keyword,
        "match_radius_arcsec": float(match_radius.to_value(u.arcsec)),
    }
    if image is not None and image.wcs is not None:
        summary["pixel_scale_arcsec"] = _pixel_scale_arcsec(image)
    fit = None
    notes = [
        "positions are the catalogue's centroids converted with the image WCS; centroid bias "
        "(e.g. from saturation, blending or nebulosity) appears as astrometric error",
        "Gaia positions propagated with proper motion only (parallax and RV ignored)",
    ]
    if n_used:
        mx, sx = _robust(dx[used])
        my, sy = _robust(dy[used])
        gaia_err = np.hypot(
            matches["gaia_ra_error"].to_value(u.mas), matches["gaia_dec_error"].to_value(u.mas)
        )
        summary.update(
            {
                "median_dra_mas": mx,
                "median_ddec_mas": my,
                "median_dra_err_mas": _MEDIAN_EFFICIENCY * sx / np.sqrt(n_used),
                "median_ddec_err_mas": _MEDIAN_EFFICIENCY * sy / np.sqrt(n_used),
                "rms_mas": float(np.sqrt(np.mean(dx[used] ** 2 + dy[used] ** 2))),
                "robust_sigma_dra_mas": sx,
                "robust_sigma_ddec_mas": sy,
                "median_gaia_error_mas": float(np.median(gaia_err[used])),
            }
        )
        if "x_gaia" in matches.colnames:  # the same offset in the image's pixel frame
            summary["median_dx_pix"] = float(np.median((matches["x"] - matches["x_gaia"])[used]))
            summary["median_dy_pix"] = float(np.median((matches["y"] - matches["y_gaia"])[used]))
        for axis, value, err in (
            ("RA*", mx, summary["median_dra_err_mas"]),
            ("Dec", my, summary["median_ddec_err_mas"]),
        ):
            if n_used >= 3 and abs(value) > 3 * err:
                notes.append(
                    f"systematic {axis} offset of {value:.1f} ± {err:.1f} mas (>3 sigma) "
                    "between this catalogue and Gaia DR3 at the image epoch"
                )
    if n_used < 5:
        notes.append(f"only {n_used} stars used: statistics are indicative only")
    if n_used >= min_fit:
        centre = SkyCoord(matches["ra_gaia"][used], matches["dec_gaia"][used])
        frame = SkyCoord(
            np.median(centre.ra.deg) * u.deg, np.median(centre.dec.deg) * u.deg
        ).skyoffset_frame()
        offsets = SkyCoord(matches["ra_gaia"], matches["dec_gaia"]).transform_to(frame)
        xi = offsets.lon.to_value(u.arcsec)
        eta = offsets.lat.to_value(u.arcsec)
        fit = _similarity_fit(xi[used], eta[used], dx[used], dy[used])
    return AstrometricQA(matches=matches, summary=summary, fit=fit, notes=notes)


def plot_astrometric_qa(qa: AstrometricQA, *, title: str = "", arrow_mas: float = 10.0):
    """Residuals vs Gaia: scatter (left) and, with pixel positions, the field (right).

    The left panel is centred on the used stars (points outside are counted in the legend).
    The right panel shows each used star's residual *after removing the median offset*, so
    rotation or distortion patterns stand out; the removed offset is given in its title.
    """
    m = qa.matches
    s = qa.summary
    has_xy = "x_gaia" in m.colnames and s["n_used"] > 0
    fig, axes = plt.subplots(1, 2 if has_xy else 1, figsize=(10, 4.4) if has_xy else (5, 4.4))
    axes = np.atleast_1d(axes)
    ink, muted, used_c, rej_c = "#0b0b0b", "#52514e", "#2a78d6", "#eb6834"
    fig.patch.set_facecolor("#fcfcfb")
    dx, dy = m["dra"].to_value(u.mas), m["ddec"].to_value(u.mas)
    used = np.asarray(m["used"], bool)
    ax = axes[0]
    ax.set_facecolor("#fcfcfb")
    if s["n_used"]:
        cx, cy = s["median_dra_mas"], s["median_ddec_mas"]
        half = max(6 * max(s["robust_sigma_dra_mas"], s["robust_sigma_ddec_mas"]), 15.0)
        half = max(half, 1.2 * np.hypot(cx, cy))  # keep the origin (Gaia) in view
        cx, cy = cx / 2, cy / 2
    else:
        cx, cy, half = 0.0, 0.0, 100.0
    inside = (np.abs(dx - cx) <= half) & (np.abs(dy - cy) <= half)
    n_out = int(np.sum(~used & ~inside))
    ax.scatter(
        dx[~used & inside],
        dy[~used & inside],
        s=18,
        marker="x",
        color=rej_c,
        label=f"excluded or clipped ({n_out} more outside)",
    )
    ax.scatter(dx[used], dy[used], s=18, color=used_c, label=f"used ({s['n_used']})")
    if s["n_used"]:
        ax.errorbar(
            s["median_dra_mas"],
            s["median_ddec_mas"],
            xerr=s["median_dra_err_mas"],
            yerr=s["median_ddec_err_mas"],
            color=ink,
            marker="+",
            markersize=12,
            label="median",
        )
    ax.axhline(0, color="#c9c8c3", lw=0.8, zorder=0)
    ax.axvline(0, color="#c9c8c3", lw=0.8, zorder=0)
    ax.set_xlim(cx + half, cx - half)  # east to the left, as on the sky
    ax.set_ylim(cy - half, cy + half)
    ax.set_aspect("equal")
    ax.set_xlabel("ΔRA·cos Dec (mas), catalogue minus Gaia", color=ink)
    ax.set_ylabel("ΔDec (mas)", color=ink)
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0.0, -0.16))
    ax.set_title(title, fontsize=9, color=ink, loc="left")
    if has_xy:
        ax = axes[1]
        ax.set_facecolor("#fcfcfb")
        x, y = np.asarray(m["x"]), np.asarray(m["y"])
        # pixel-frame residuals (catalogue minus Gaia) with the median removed
        rx = x - np.asarray(m["x_gaia"])
        ry = y - np.asarray(m["y_gaia"])
        rx, ry = rx - np.median(rx[used]), ry - np.median(ry[used])
        width = max(float(np.ptp(x)), 1.0)
        arrow_pix = arrow_mas / 1000.0 / s["pixel_scale_arcsec"]
        k = 0.06 * width / arrow_pix  # ``arrow_mas`` spans 6% of the plotted width
        style = {"angles": "xy", "scale_units": "xy", "scale": 1, "width": 0.004}
        ax.quiver(x[used], y[used], rx[used] * k, ry[used] * k, color=used_c, **style)
        ax.scatter(x[used], y[used], s=6, color=used_c)
        key_y = y.max() + 0.08 * width
        ax.quiver([x.min()], [key_y], [arrow_pix * k], [0], color=ink, **style)
        ax.annotate(f"{arrow_mas:.0f} mas", (x.min(), key_y + 0.025 * width), fontsize=8, color=ink)
        ax.set_aspect("equal")
        ax.set_xlabel("x (pixel)", color=ink)
        ax.set_ylabel("y (pixel)", color=ink)
        ax.set_title(
            "residuals after removing the median offset "
            f"({s['median_dra_mas']:.1f}, {s['median_ddec_mas']:.1f}) mas",
            fontsize=9,
            color=muted,
            loc="left",
        )
    for ax in axes:
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=muted, labelsize=8)
    fig.tight_layout()
    return fig


def _pixel_scale_arcsec(image: ImageProduct) -> float:
    return float(np.mean(proj_plane_pixel_scales(image.wcs.celestial))) * 3600.0
