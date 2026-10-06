"""Typed data products.

An :class:`ImageProduct` is a 2-D image that carries everything needed to measure it honestly:
pixel values with their unit, a per-pixel uncertainty, a bad-pixel mask, the raw data-quality
flags, the celestial WCS, both FITS headers, and where it came from. Pixel values are exactly
those stored in the file: readers never fill, clip, smooth or rescale them.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io.fits import Header
from astropy.nddata import NDData, NDUncertainty
from astropy.units import UnitBase
from astropy.wcs import WCS

from astroledger.core.bandpass import Bandpass


@dataclass(frozen=True)
class SourceInfo:
    """Where a product's pixels came from.

    Attributes
    ----------
    path : pathlib.Path
        File as opened. The file name is the archive's own name and is never changed.
    sha256 : str or None
        Checksum of the whole file, or None if checksumming was disabled.
    extension : tuple of (str, int)
        ``(EXTNAME, EXTVER)`` of the science array, e.g. ``("SCI", 1)``. For files without
        named extensions, ``("PRIMARY", 1)`` or ``("HDU<n>", 1)``.
    """

    path: Path
    sha256: str | None
    extension: tuple[str, int]

    @property
    def filename(self) -> str:
        return self.path.name


class ImageProduct(NDData):
    """A 2-D image with unit, uncertainty, mask, data-quality flags, WCS, headers and source.

    Parameters
    ----------
    data : numpy.ndarray
        Pixel values exactly as stored in the file (NaN preserved).
    uncertainty : astropy.nddata.NDUncertainty, optional
        One-sigma uncertainty per pixel (from the ``ERR`` extension), or None if the file has none.
    mask : numpy.ndarray of bool, optional
        True where a pixel must not be used: NaN in ``data`` or a bad data-quality flag.
    wcs : astropy.wcs.WCS, optional
        Celestial WCS, or None when the header has none (never a placeholder).
    unit : astropy.units.UnitBase, optional
        Unit of ``data``, or None when ``BUNIT`` is missing or could not be interpreted.
    dq : numpy.ndarray, optional
        Raw data-quality bit flags (``DQ`` extension), kept unchanged for later decisions.
    header : astropy.io.fits.Header
        Header of the science extension.
    primary_header : astropy.io.fits.Header
        Primary header of the file (holds telescope, instrument and observation keywords).
    source : SourceInfo
        File path, checksum and extension the pixels were read from.
    notes : list of str, optional
        Reader notes and captured warnings (e.g. unparseable units, missing WCS). Never empty
        because something was suppressed: anything the reader noticed is recorded here.
    """

    def __init__(
        self,
        data: np.ndarray,
        *,
        uncertainty: NDUncertainty | None = None,
        mask: np.ndarray | None = None,
        wcs: WCS | None = None,
        unit: UnitBase | None = None,
        dq: np.ndarray | None = None,
        header: Header,
        primary_header: Header,
        source: SourceInfo,
        notes: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(data, uncertainty=uncertainty, mask=mask, wcs=wcs, unit=unit, meta=meta)
        self.dq = dq
        self.header = header
        self.primary_header = primary_header
        self.source = source
        self.notes = list(notes or [])

    def keyword(self, name: str, default: Any = None) -> Any:
        """Look up a FITS keyword in the science header, then the primary header."""
        for hdr in (self.header, self.primary_header):
            if name in hdr:
                return hdr[name]
        return default

    @property
    def telescope(self) -> str | None:
        return self.keyword("TELESCOP")

    @property
    def instrument(self) -> str | None:
        return self.keyword("INSTRUME")

    @property
    def detector(self) -> str | None:
        return self.keyword("DETECTOR")

    @cached_property
    def bandpass(self) -> Bandpass:
        """Bandpass resolved from the optical-element keywords (see :class:`Bandpass`)."""
        return Bandpass.from_header(self.primary_header, self.header)

    @property
    def n_masked(self) -> int:
        return 0 if self.mask is None else int(np.count_nonzero(self.mask))

    def __repr__(self) -> str:
        name, ver = self.source.extension
        shape = "x".join(str(n) for n in self.data.shape)
        unit = str(self.unit) if self.unit is not None else "unit unknown"
        origin = "/".join(str(v) for v in (self.telescope, self.instrument, self.detector) if v)
        band = self.bandpass.name or "band unknown"
        where = f"{self.source.filename}[{name},{ver}]"
        return (
            f"<ImageProduct {origin or 'unknown origin'} {band} {where} "
            f"{shape} {unit}, {self.n_masked} masked, wcs={'yes' if self.wcs else 'no'}>"
        )
