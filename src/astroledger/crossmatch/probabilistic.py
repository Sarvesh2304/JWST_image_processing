"""Error-based positional cross-matching with chance-coincidence and reliability estimates.

Method (roadmap §14.4):

1. **Radius from errors.** Each pair is searched within r = k·σ, where
   σ = √(σ_a² + σ_b² + σ_sys²) combines both positional errors (1-D, per coordinate) and a
   systematic term (e.g. the offset between two astrometric frames). For a true counterpart the
   separation follows a Rayleigh distribution, so a fraction 1 − exp(−k²/2) of true pairs lies
   inside r (k = 4: 99.97%).
2. **Local density.** ρ is the surface density of catalogue B counted in an annulus around each
   source of A, corrected for the part of the annulus outside B's footprint (convex hull).
3. **Chance coincidence.** P_chance = 1 − exp(−π s² ρ) is the probability that an *unrelated* B
   source lies at least as close as the observed separation s (Poisson). ``p_chance_radius`` uses
   r instead of s. Matches with P_chance above ``p_chance_limit`` (default 1%) are flagged.
4. **Reliability.** Likelihood ratio LR = f(s)/ρ with f the 2-D Gaussian of width σ, and
   reliability R_j = LR_j / (Σ LR + 1 − Q) over all candidates of one A source (Sutherland &
   Saunders 1992), where Q is the fraction of A sources that have a counterpart in B. Q is
   estimated from the number of A sources with no candidate unless given.
5. **Conflicts** are reported, never resolved silently: several plausible candidates for one
   source, one B source claimed by several A sources, and matches that chance cannot exclude.

A positional match is evidence level L1 ("positional coincidence"). No identity is assigned here;
columns copied from catalogue B are copied verbatim from the retrieved records.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import MaskedColumn, QTable
from astropy.utils.masked import Masked
from scipy.spatial import Delaunay, QhullError

from astroledger.provenance import step

__all__ = ["CrossMatch", "centroid_error", "crossmatch"]


def centroid_error(fwhm: u.Quantity, snr) -> u.Quantity:
    """Approximate 1-D centroid error, FWHM / (2.35 · S/N) (roadmap §14.4)."""
    return fwhm / (2.35 * np.asarray(snr, dtype=float))


@dataclass
class CrossMatch:
    """Outcome of :func:`crossmatch`.

    Attributes
    ----------
    best : astropy.table.QTable
        One row per source of A: ``b_index`` (-1 if none), ``sep``, ``sep_sigma``, ``radius``,
        ``p_chance``, ``p_chance_radius``, ``n_within_radius``, ``reliability``, ``density``,
        ``evidence_level`` and ``flags``; plus any copied columns of B (prefixed ``b_``).
    candidates : astropy.table.QTable
        Every pair within its radius, with ``lr``, ``reliability`` and ``rank``.
    conflicts : astropy.table.QTable
        One row per conflict: ``kind``, ``a_indices``, ``b_indices``, ``detail``.
    meta : dict
        Settings and estimates (k, σ_sys, density method, Q, expected completeness).
    notes : list of str
    """

    best: QTable
    candidates: QTable
    conflicts: QTable
    meta: dict
    notes: list[str] = field(default_factory=list)


def _coords(table: QTable) -> SkyCoord:
    if "sky_centroid" in table.colnames:
        return SkyCoord(table["sky_centroid"])
    return SkyCoord(u.Quantity(table["ra"], u.deg), u.Quantity(table["dec"], u.deg))


def _sigma(value, table: QTable) -> u.Quantity:
    """Per-source 1-D positional error: a column name or a scalar/array Quantity."""
    sigma = table[value] if isinstance(value, str) else value
    sigma = u.Quantity(sigma).to(u.arcsec)
    return np.full(len(table), sigma.value) * u.arcsec if sigma.isscalar else sigma


def _covered_fraction(centres, inner, outer, hull_coords, frame_centre) -> np.ndarray:
    """Fraction of each annulus inside the convex hull of catalogue B (tangent plane)."""
    frame = frame_centre.skyoffset_frame()
    pts = hull_coords.transform_to(frame)
    xy = np.column_stack([pts.lon.to_value(u.arcsec), pts.lat.to_value(u.arcsec)])
    try:
        hull = Delaunay(xy)
    except (QhullError, ValueError):
        return np.ones(len(centres))
    c = centres.transform_to(frame)
    cx, cy = c.lon.to_value(u.arcsec), c.lat.to_value(u.arcsec)
    # area-uniform deterministic sample of the annulus: 48 angles x 12 radii
    radii = np.sqrt(
        np.linspace(inner**2, outer**2, 12, endpoint=False) + (outer**2 - inner**2) / 24
    )
    angles = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    rr, aa = np.meshgrid(radii, angles)
    dx, dy = (rr * np.cos(aa)).ravel(), (rr * np.sin(aa)).ravel()
    fractions = np.empty(len(centres))
    for i in range(len(centres)):
        inside = hull.find_simplex(np.column_stack([cx[i] + dx, cy[i] + dy])) >= 0
        fractions[i] = inside.mean()
    return fractions


def _register(ca, cb, sa, sb, sys, radius):
    """Median offset of A relative to B from mutual nearest neighbours; returns shifted A."""
    i, sep, _ = ca.match_to_catalog_sky(cb)
    j, _, _ = cb.match_to_catalog_sky(ca)
    mutual = (j[i] == np.arange(len(ca))) & (sep <= radius)
    n = int(mutual.sum())
    if n < 5:
        return ca, sys, {"applied": False, "n_pairs": n, "reason": "fewer than 5 mutual pairs"}
    dra, ddec = cb[i[mutual]].spherical_offsets_to(ca[mutual])
    dx, dy = dra.to_value(u.arcsec), ddec.to_value(u.arcsec)
    used = np.ones(n, bool)
    clip = 3.44  # 2-D radius with the coverage of 3 sigma in 1-D
    for _ in range(10):  # iterative clipping: perturbed centroids must not set the scale
        mx, my = np.median(dx[used]), np.median(dy[used])
        spread = 1.4826 * np.median(np.abs(np.concatenate([dx[used] - mx, dy[used] - my])))
        new = np.hypot(dx - mx, dy - my) <= clip * max(spread, 1e-9)
        if new.sum() < 5 or np.array_equal(new, used):
            break
        used = new
    pair_a, pair_b = np.flatnonzero(mutual)[used], i[mutual][used]
    explained = np.sqrt(np.median(sa[pair_a].value ** 2 + sb[pair_b].value ** 2))
    calibrated = max(float(np.sqrt(max(spread**2 - explained**2, 0.0))), float(sys.value))
    shifted = ca.spherical_offsets_by(-mx * u.arcsec, -my * u.arcsec)
    info = {
        "applied": True,
        "n_pairs": n,
        "n_pairs_used": int(used.sum()),
        "offset_dra_arcsec": float(mx),
        "offset_ddec_arcsec": float(my),
        "offset_err_arcsec": float(1.2533 * spread / np.sqrt(used.sum())),
        "residual_scatter_arcsec": float(spread),
        "sigma_sys_calibrated_arcsec": calibrated,
    }
    return shifted, calibrated * u.arcsec, info


@step("crossmatch.match", version="1")
def crossmatch(
    a: QTable,
    b: QTable,
    *,
    sigma_a,
    sigma_b,
    sigma_sys: u.Quantity = 0 * u.arcsec,
    k: float = 4.0,
    annulus: tuple[u.Quantity, u.Quantity] | None = None,
    density: u.Quantity | None = None,
    prior: float | None = None,
    p_chance_limit: float = 0.01,
    ambiguity_limit: float = 0.1,
    copy_columns: Sequence[str] = (),
    register: bool = False,
    register_radius: u.Quantity = 0.3 * u.arcsec,
) -> CrossMatch:
    """Cross-match catalogue A against catalogue B with error-based radii.

    Parameters
    ----------
    a, b : QTable
        Catalogues with ``ra``/``dec`` (or ``sky_centroid``).
    sigma_a, sigma_b : str or Quantity
        1-D positional errors (per coordinate): a column name, or a scalar or per-row Quantity.
    sigma_sys : Quantity
        Systematic error between the two frames (added in quadrature).
    k : float
        Radius in units of the combined σ (roadmap: 3-5).
    annulus : (inner, outer) Quantity, optional
        Annulus for the local density of B. Default: inner = max(2 x largest radius, 1"),
        outer = inner + 30".
    density : Quantity, optional
        A fixed surface density of B (e.g. ``N / u.arcsec**2``) instead of the local estimate.
    prior : float, optional
        Q, the fraction of A sources with a counterpart in B; estimated when omitted.
    p_chance_limit : float
        Flag matches whose chance probability exceeds this (roadmap: 1%).
    ambiguity_limit : float
        Flag a source when its second-best candidate has at least this reliability.
    copy_columns : sequence of str
        Columns of B copied verbatim into ``best`` for matched rows (prefixed ``b_``).
    register : bool
        First remove a coherent offset between the two frames: take mutual nearest neighbours
        within ``register_radius``, clip outliers iteratively, shift A by the median offset of
        the rest, and set ``sigma_sys`` from
        the residual scatter not explained by ``sigma_a`` and ``sigma_b`` (never below the given
        ``sigma_sys``). The offset, its error and the calibrated ``sigma_sys`` are in ``meta``.
    register_radius : Quantity
        Pairing radius for the registration step.
    """
    ca, cb = _coords(a), _coords(b)
    sa, sb = _sigma(sigma_a, a), _sigma(sigma_b, b)
    sys = u.Quantity(sigma_sys).to(u.arcsec)
    registration = None
    if register and len(a) and len(b):
        ca, sys, registration = _register(ca, cb, sa, sb, sys, u.Quantity(register_radius))
    max_radius = k * np.sqrt(sa.max() ** 2 + sb.max() ** 2 + sys**2) if len(a) and len(b) else 0
    ia, ib, sep, _ = (
        cb.search_around_sky(ca, max_radius)
        if len(a) and len(b)
        else (np.array([], int), np.array([], int), np.array([]) * u.deg, None)
    )
    sep = sep.to(u.arcsec)
    sigma = np.sqrt(sa[ia] ** 2 + sb[ib] ** 2 + sys**2)
    keep = sep <= k * sigma
    ia, ib, sep, sigma = ia[keep], ib[keep], sep[keep], sigma[keep]

    # local density of B around each A source
    if density is not None:
        rho = np.full(len(a), u.Quantity(density).to_value(u.arcsec**-2))
        density_method = "given"
        annulus_used = None
    else:
        inner, outer = annulus or (max(2 * max_radius, 1 * u.arcsec), None)
        inner = u.Quantity(inner).to(u.arcsec)
        outer = u.Quantity(outer).to(u.arcsec) if outer is not None else inner + 30 * u.arcsec
        annulus_used = (float(inner.value), float(outer.value))
        counts = np.zeros(len(a))
        if len(a) and len(b):
            ja, _, d, _ = cb.search_around_sky(ca, outer)
            ring = d.to(u.arcsec) >= inner
            counts = np.bincount(ja[ring], minlength=len(a)).astype(float)
        frac = (
            _covered_fraction(ca, inner.value, outer.value, cb, cb[len(cb) // 2])
            if len(a) and len(b) >= 3
            else np.ones(len(a))
        )
        area = np.pi * (outer.value**2 - inner.value**2) * np.maximum(frac, 1e-3)
        rho = np.maximum(counts, 1.0) / area  # at least one source: never claim zero density
        density_method = "local annulus, edge-corrected; floor of 1 source"

    rho_pair = rho[ia]
    s2 = (sigma.to_value(u.arcsec)) ** 2
    lr = np.exp(-0.5 * (sep.value**2) / s2) / (2 * np.pi * s2) / rho_pair
    p_chance = 1 - np.exp(-np.pi * sep.value**2 * rho_pair)
    radius = k * sigma

    # Q: fraction of A with a counterpart, from the number of A sources with no candidate
    own_sigma = np.sqrt(sa**2 + np.median(sb) ** 2 + sys**2) if len(b) else sa
    p_empty = np.exp(-np.pi * (k * own_sigma.value) ** 2 * rho)  # no chance source in r
    missed = np.exp(-(k**2) / 2)  # true counterpart outside r
    n_none = len(a) - len(np.unique(ia))
    if prior is None and len(a):
        q = (p_empty.sum() - n_none) / ((1 - missed) * p_empty.sum())
        q = float(np.clip(q, 0.01, 1.0))
        q_method = "estimated from sources without candidates"
    else:
        q = float(prior) if prior is not None else 1.0
        q_method = "given"

    reliability = np.zeros(len(ia))
    rank = np.zeros(len(ia), int)
    for i in np.unique(ia):
        sel = np.flatnonzero(ia == i)
        reliability[sel] = lr[sel] / (lr[sel].sum() + 1 - q)
        rank[sel[np.argsort(-reliability[sel])]] = np.arange(1, len(sel) + 1)

    candidates = QTable()
    candidates["a_index"], candidates["b_index"] = ia, ib
    candidates["sep"], candidates["sigma"], candidates["radius"] = sep, sigma, radius
    candidates["sep_sigma"] = (sep / sigma).value
    candidates["p_chance"] = p_chance
    candidates["lr"], candidates["reliability"], candidates["rank"] = lr, reliability, rank

    best = QTable()
    best["a_index"] = np.arange(len(a))
    best["b_index"] = np.full(len(a), -1)
    for name, unit in (("sep", u.arcsec), ("radius", u.arcsec)):
        best[name] = np.full(len(a), np.nan) * unit
    for name in ("sep_sigma", "p_chance", "p_chance_radius", "reliability"):
        best[name] = np.full(len(a), np.nan)
    best["n_within_radius"] = np.bincount(ia, minlength=len(a))
    best["density"] = rho * u.arcsec**-2
    best["evidence_level"] = np.full(len(a), "", dtype="<U40")
    best["flags"] = np.full(len(a), "", dtype="<U120")
    top = np.flatnonzero(rank == 1)
    rows = ia[top]
    best["b_index"][rows] = ib[top]
    best["sep"][rows] = sep[top]
    best["radius"][rows] = radius[top]
    best["sep_sigma"][rows] = candidates["sep_sigma"][top]
    best["p_chance"][rows] = p_chance[top]
    best["p_chance_radius"][rows] = 1 - np.exp(-np.pi * radius[top].value ** 2 * rho_pair[top])
    best["reliability"][rows] = reliability[top]
    best["evidence_level"][rows] = "L1 positional coincidence"
    unmatched = np.asarray(best["b_index"]) < 0
    for name in copy_columns:  # verbatim from B; masked where there is no counterpart
        column = b[name][np.maximum(np.asarray(best["b_index"]), 0)]
        if isinstance(column, u.Quantity):
            best[f"b_{name}"] = Masked(column, mask=unmatched)
        else:
            best[f"b_{name}"] = MaskedColumn(np.asarray(column), mask=unmatched)

    conflicts = []
    flags: list[list[str]] = [[] for _ in range(len(a))]
    for i in range(len(a)):
        sel = np.flatnonzero(ia == i)
        if len(sel) == 0:
            flags[i].append(f"no counterpart within {k:g} sigma")
            continue
        if len(sel) > 1:
            second = np.sort(reliability[sel])[-2]
            if second >= ambiguity_limit:
                flags[i].append("ambiguous: several candidates")
                conflicts.append(
                    (
                        "several candidates",
                        [int(i)],
                        [int(j) for j in ib[sel]],
                        f"second-best reliability {second:.2f}",
                    )
                )
        if best["p_chance"][i] > p_chance_limit:
            flags[i].append(f"chance coincidence not excluded (P={best['p_chance'][i]:.3f})")
    claimed = best["b_index"][best["b_index"] >= 0]
    values, counts = np.unique(claimed, return_counts=True)
    for j in values[counts > 1]:
        owners = [int(i) for i in np.flatnonzero(best["b_index"] == j)]
        for i in owners:
            flags[i].append(f"counterpart shared with {len(owners) - 1} other source(s)")
        conflicts.append(("shared counterpart", owners, [int(j)], f"{len(owners)} sources"))
    best["flags"] = ["; ".join(f) for f in flags]

    conflict_table = (
        QTable(
            rows=[
                (kind, ",".join(map(str, ai)), ",".join(map(str, bi)), d)
                for kind, ai, bi, d in conflicts
            ],
            names=("kind", "a_indices", "b_indices", "detail"),
            dtype=("<U30", "<U200", "<U200", "<U80"),
        )
        if conflicts
        else QTable(
            names=("kind", "a_indices", "b_indices", "detail"),
            dtype=("<U30", "<U200", "<U200", "<U80"),
        )
    )
    meta = {
        "k": k,
        "expected_completeness": float(1 - np.exp(-(k**2) / 2)),
        "sigma_sys_arcsec": float(sys.value),
        "registration": registration,
        "density_method": density_method,
        "annulus_arcsec": annulus_used,
        "prior_q": q,
        "prior_method": q_method,
        "p_chance_limit": p_chance_limit,
        "n_a": len(a),
        "n_b": len(b),
        "n_matched": int(np.sum(best["b_index"] >= 0)),
        "n_conflicts": len(conflicts),
    }
    notes = [
        "matches are positional coincidences (L1); no identity is assigned",
        "positional errors are treated as circular Gaussians per coordinate",
        "near the edge of B's footprint the convex hull is slightly smaller than the true "
        "footprint, so local densities at its corners err high by about 13% (P_chance errs "
        "conservative); along straight edges the correction is unbiased",
    ]
    return CrossMatch(
        best=best, candidates=candidates, conflicts=conflict_table, meta=meta, notes=notes
    )
