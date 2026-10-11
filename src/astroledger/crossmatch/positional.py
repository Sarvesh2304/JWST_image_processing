"""Nearest-neighbour positional matching.

This is the simple, deterministic matcher used for astrometric QA, where the reference
catalogue (Gaia) is sparse compared with the matching radius. Probabilistic matching with
chance-coincidence estimates is a separate task (roadmap §27 task 17).
"""

from __future__ import annotations

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

__all__ = ["match_nearest"]


def match_nearest(
    coords: SkyCoord, reference: SkyCoord, radius: u.Quantity
) -> tuple[np.ndarray, np.ndarray, u.Quantity]:
    """One-to-one nearest-neighbour matches within ``radius``.

    Each source in ``coords`` is paired with its nearest ``reference`` source. If several sources
    claim the same reference source, only the closest pair is kept.

    Returns
    -------
    index_coords, index_reference : numpy.ndarray
        Indices of matched pairs, sorted by ``index_coords``.
    separation : astropy.units.Quantity
        Pair separations.
    """
    if len(coords) == 0 or len(reference) == 0:
        return np.array([], int), np.array([], int), np.array([]) * u.arcsec
    index, separation, _ = coords.match_to_catalog_sky(reference)
    candidates = np.flatnonzero(separation <= radius)
    order = candidates[np.argsort(separation[candidates])]
    taken: set[int] = set()
    keep = []
    for i in order:
        if int(index[i]) not in taken:
            taken.add(int(index[i]))
            keep.append(i)
    keep = np.sort(np.array(keep, dtype=int))
    return keep, index[keep].astype(int), separation[keep].to(u.arcsec)
