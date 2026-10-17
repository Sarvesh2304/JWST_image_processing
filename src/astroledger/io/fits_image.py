"""Read 2-D images from FITS files into :class:`~astroledger.core.product.ImageProduct`.

Science, uncertainty and data-quality arrays are found by ``EXTNAME``/``EXTVER``
(``SCI``, ``ERR``, ``DQ``), as in JWST and HST products. Plain single-image FITS files (e.g. from a
personal camera) are read from the one HDU that holds image data.

What the reader guarantees:

- Pixel values are returned exactly as stored. NaN stays NaN; nothing is filled, clipped,
  smoothed or rescaled.
- ``mask`` marks non-finite pixels plus data-quality flags that mean "do not use" (see
  ``bad_bits``). The raw ``DQ`` flags are kept on the product.
- ``unit`` comes from ``BUNIT``; if it is missing or not understood, the unit is None and a note
  says so. A unit is never assumed.
- ``wcs`` is the celestial WCS of the science header, or None if there is none.
- Warnings raised while reading (e.g. ``FITSFixedWarning``) are recorded in ``notes`` and logged,
  not discarded.
- Files the reader does not handle (cubes, ramps, ambiguous multi-image files) raise an error
  rather than being guessed at.
"""

from __future__ import annotations

import hashlib
import logging
import re
import warnings
from os import PathLike
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.nddata import StdDevUncertainty
from astropy.wcs import WCS

from astroledger.core.errors import AmbiguousProductError, UnsupportedProductError
from astroledger.core.product import ImageProduct, SourceInfo

__all__ = ["DEFAULT_BAD_BITS", "JWST_DO_NOT_USE", "open_image", "open_images", "parse_bunit"]

log = logging.getLogger(__name__)
_ROUTINE_FIX = re.compile(r"FITSFixedWarning: '(datfix|obsfix)'")

#: JWST data-quality bit 0: the pipeline's "do not use this pixel" flag.
JWST_DO_NOT_USE = 1

#: Data-quality bits treated as bad by default, per ``TELESCOP``. Telescopes not listed here
#: (HST, ground-based data) use the conservative default: any nonzero flag is bad.
#: JWST's other bits (e.g. SATURATED, JUMP_DET) are informational once ``DO_NOT_USE`` is set by
#: the pipeline, so only ``DO_NOT_USE`` is masked.
DEFAULT_BAD_BITS: dict[str, int] = {"JWST": JWST_DO_NOT_USE}

_UNIT_ALIASES = {
    "ELECTRON": u.electron,
    "ELECTRONS": u.electron,
    "COUNT": u.count,
    "COUNTS": u.count,
    "ADU": u.adu,
    "DN": u.DN,
}
_PER_SECOND = {"S", "SEC", "SECOND", "SECONDS"}


def parse_bunit(raw: object) -> tuple[u.UnitBase | None, str | None]:
    """Interpret a FITS ``BUNIT`` value.

    Parameters
    ----------
    raw : object
        The ``BUNIT`` header value, or None if absent.

    Returns
    -------
    unit : astropy.units.UnitBase or None
        The unit, or None if missing or not understood.
    note : str or None
        Explanation when the value was missing, needed an alias, or could not be parsed.

    Notes
    -----
    Besides strings astropy parses directly (``MJy/sr``, ``DN/s``, ``Jy/beam``), the uppercase
    forms used by HST and many cameras are accepted: ``ELECTRONS``, ``ELECTRONS/S``, ``COUNTS/S``,
    ``ADU``. An empty ``BUNIT`` is treated as unknown, not as dimensionless.
    """
    if raw is None or not str(raw).strip():
        return None, "BUNIT missing: unit unknown"
    text = str(raw).strip()
    # astropy reads an upper-case "S" as siemens ("DN/S" = DN per siemens); in BUNIT it always
    # means seconds, so such values go through the alias rules below, never the direct parse
    if "S" not in re.split(r"[\s/*.^()\d+-]+", text):
        try:
            return u.Unit(text, parse_strict="raise"), None
        except ValueError:
            pass
    parts = text.upper().replace(" ", "").split("/")
    base = _UNIT_ALIASES.get(parts[0])
    if base is not None and len(parts) == 1:
        return base, f"BUNIT {text!r} read as {base}"
    if len(parts) == 2 and parts[1] in _PER_SECOND:
        if base is None:
            try:
                base = u.Unit(text.split("/")[0].strip(), parse_strict="raise")
            except ValueError:
                base = None
        if base is not None:
            unit = base / u.s
            return unit, f"BUNIT {text!r} read as {unit}"
    return None, f"BUNIT {text!r} not understood: unit unknown"


def open_images(
    path: str | PathLike[str],
    *,
    bad_bits: int | None = None,
    checksum: bool = True,
) -> list[ImageProduct]:
    """Read every 2-D science image in a FITS file.

    Parameters
    ----------
    path : str or path-like
        FITS file. The file is read, never renamed or modified.
    bad_bits : int, optional
        Data-quality bits that mark a pixel as unusable. Default: from :data:`DEFAULT_BAD_BITS`
        by ``TELESCOP`` (JWST: ``DO_NOT_USE``); for other telescopes any nonzero flag.
    checksum : bool, default True
        Compute the SHA-256 of the file for provenance.

    Returns
    -------
    list of ImageProduct
        One product per ``SCI`` extension (e.g. two for an HST ACS/WFC ``flt``), in ``EXTVER``
        order; or the single image of a plain FITS file.

    Raises
    ------
    UnsupportedProductError
        If there is no image data, or the science array is not 2-D (e.g. JWST ``_uncal`` ramps).
    AmbiguousProductError
        If a file without ``SCI`` extensions holds several images.
    """
    path = Path(path)
    sha256 = _sha256(path) if checksum else None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with fits.open(path, memmap=False) as hdul:
            products = [
                _read_one(hdul, hdu, path, sha256, bad_bits) for hdu in _science_hdus(hdul, path)
            ]
    unrelated = [w for w in caught if issubclass(w.category, ResourceWarning | DeprecationWarning)]
    for w in unrelated:  # not about this file (e.g. garbage collection elsewhere): pass them on
        warnings.warn_explicit(w.message, w.category, w.filename, w.lineno)
    reader_warnings = _unique(
        f"{w.category.__name__}: {w.message}" for w in caught if w not in unrelated
    )
    for text in reader_warnings:
        # astropy's routine keyword standardisation (dates from MJD, site from OBSGEO-XYZ) is not
        # a problem with the file; it stays in the notes but is not logged as a warning
        level = logging.DEBUG if _ROUTINE_FIX.match(text) else logging.WARNING
        log.log(level, "%s: %s", path.name, text)
    for product in products:
        product.notes.extend(f"warning while reading: {text}" for text in reader_warnings)
    return products


def open_image(
    path: str | PathLike[str],
    *,
    extver: int | None = None,
    bad_bits: int | None = None,
    checksum: bool = True,
) -> ImageProduct:
    """Read one 2-D science image from a FITS file.

    Parameters
    ----------
    path : str or path-like
        FITS file.
    extver : int, optional
        ``EXTVER`` of the ``SCI`` extension to read. Required when the file holds several
        (e.g. ``extver=2`` for the second chip of an HST ACS/WFC or WFC3/UVIS exposure).
    bad_bits : int, optional
        See :func:`open_images`.
    checksum : bool, default True
        See :func:`open_images`.

    Raises
    ------
    AmbiguousProductError
        If the file has several science images and ``extver`` is not given.
    UnsupportedProductError
        See :func:`open_images`; also if ``extver`` does not exist.
    """
    products = open_images(path, bad_bits=bad_bits, checksum=checksum)
    versions = [p.source.extension for p in products]
    if extver is not None:
        for product in products:
            if product.source.extension[1] == extver:
                return product
        raise UnsupportedProductError(
            f"{Path(path).name}: no science extension with EXTVER={extver}; has {versions}"
        )
    if len(products) > 1:
        raise AmbiguousProductError(
            f"{Path(path).name} holds {len(products)} science images {versions}; "
            "pass extver=... (--extver on the command line) or use open_images()"
        )
    return products[0]


def _science_hdus(hdul: fits.HDUList, path: Path) -> list[fits.hdu.base.ExtensionHDU]:
    sci = [hdu for hdu in hdul if hdu.name == "SCI"]
    if sci:
        return sorted(sci, key=lambda hdu: hdu.ver)
    images = [
        hdu
        for hdu in hdul
        if isinstance(hdu, fits.PrimaryHDU | fits.ImageHDU | fits.CompImageHDU)
        and hdu.data is not None
    ]
    if not images:
        raise UnsupportedProductError(f"{path.name}: no image data in any HDU")
    if len(images) > 1:
        names = [f"{_hdu_name(hdul, hdu)},{hdu.ver}" for hdu in images]
        raise AmbiguousProductError(
            f"{path.name}: no SCI extension and several image HDUs {names}; cannot tell which is "
            "the science image"
        )
    return images


def _hdu_name(hdul: fits.HDUList, hdu: fits.hdu.base.ExtensionHDU) -> str:
    """EXTNAME, or ``PRIMARY`` / ``HDU<n>`` for an unnamed HDU (n = its index in the file)."""
    if hdu.name:
        return hdu.name
    index = hdul.index_of(hdu)
    return "PRIMARY" if index == 0 else f"HDU{index}"


def _read_one(
    hdul: fits.HDUList,
    hdu: fits.hdu.base.ExtensionHDU,
    path: Path,
    sha256: str | None,
    bad_bits: int | None,
) -> ImageProduct:
    name = _hdu_name(hdul, hdu)
    ver = hdu.ver
    label = f"{path.name}[{name},{ver}]"
    data = hdu.data
    if data.ndim != 2:
        raise UnsupportedProductError(
            f"{label} holds {data.ndim}-D data of shape {data.shape}; only 2-D images are "
            "supported (JWST _uncal ramps and _rateints cubes need the official pipeline first)"
        )

    primary_header = hdul[0].header
    header = hdu.header
    notes: list[str] = []

    unit, note = parse_bunit(header.get("BUNIT"))
    if note:
        notes.append(note)

    uncertainty = None
    err_hdu = _extension(hdul, "ERR", ver) if name == "SCI" else None
    err = _plane(err_hdu, data.shape, notes)
    if err_hdu is None:
        notes.append("no ERR extension: uncertainty unknown")
    elif err is None:
        notes.append("ERR extension has no usable array: uncertainty unknown")
    elif err.shape != data.shape:
        notes.append(f"ERR shape {err.shape} differs from SCI {data.shape}: ignored")
    else:
        err_unit, _ = parse_bunit(err_hdu.header.get("BUNIT"))
        if err_unit is None or unit is None or err_unit == unit:
            uncertainty = StdDevUncertainty(err, unit=unit)
        elif err_unit.is_equivalent(unit):
            factor = float(err_unit.to(unit))
            uncertainty = StdDevUncertainty(err * factor, unit=unit)
            notes.append(f"ERR unit {err_unit} converted to the SCI unit {unit} (x{factor:g})")
        else:
            notes.append(
                f"ERR unit {err_unit} is incompatible with the SCI unit {unit}: "
                "ERR ignored, uncertainty unknown"
            )

    mask = (
        ~np.isfinite(data) if np.issubdtype(data.dtype, np.floating) else np.zeros(data.shape, bool)
    )
    dq_hdu = _extension(hdul, "DQ", ver) if name == "SCI" else None
    dq = None
    dq_plane = _plane(dq_hdu, data.shape, notes)
    if dq_hdu is None:
        notes.append("no DQ extension: mask from non-finite pixels only")
    elif dq_plane is None:
        notes.append("DQ extension has no usable array: mask from non-finite pixels only")
    elif dq_plane.shape != data.shape:
        notes.append(f"DQ shape {dq_plane.shape} differs from SCI {data.shape}: ignored")
    else:
        dq = dq_plane
        bits = (
            bad_bits if bad_bits is not None else DEFAULT_BAD_BITS.get(_telescope(primary_header))
        )
        if bits is None:
            mask |= dq != 0
            notes.append("mask: non-finite pixels + any nonzero DQ flag")
        else:
            mask |= (dq.astype(np.int64) & bits) != 0
            notes.append(f"mask: non-finite pixels + DQ bits {bits:#x}")

    wcs = _celestial_wcs(header, hdul, notes)
    if (
        wcs is not None
        and _telescope(primary_header) == "JWST"
        and "ASDF" in hdul
        and "A_ORDER" in header
    ):
        notes.append("FITS WCS is the SIP approximation of the GWCS stored in the ASDF extension")

    return ImageProduct(
        data,
        uncertainty=uncertainty,
        mask=mask,
        wcs=wcs,
        unit=unit,
        dq=dq,
        header=header,
        primary_header=primary_header,
        source=SourceInfo(path=path, sha256=sha256, extension=(name, ver)),
        notes=notes,
        meta={"BUNIT": header.get("BUNIT")},
    )


# Keywords of lookup-table distortions (HST D2IM / NPOL corrections), stored in other HDUs.
_TABLE_DISTORTION = re.compile(
    r"^(CPDIS\d|DP\d|CPERR\d|D2IMDIS\d|D2IM\d|D2IMERR\d|D2IMEXT|NPOLEXT)"
)


def _celestial_wcs(header: fits.Header, hdul: fits.HDUList, notes: list[str]) -> WCS | None:
    try:
        # fobj lets astropy resolve lookup-table distortions stored in other extensions (HST).
        wcs = WCS(header, fobj=hdul)
    except Exception as exc:  # malformed WCS headers raise many different exception types
        stripped = fits.Header(
            [card for card in header.cards if not _TABLE_DISTORTION.match(card.keyword)]
        )
        if len(stripped) == len(header):
            notes.append(f"WCS could not be built ({type(exc).__name__}: {exc}): no WCS")
            return None
        try:
            wcs = WCS(stripped)
        except Exception as exc2:
            notes.append(f"WCS could not be built ({type(exc2).__name__}: {exc2}): no WCS")
            return None
        notes.append(
            "distortion lookup tables referenced by the header are not in this file "
            f"({exc}); WCS built without them (core WCS and SIP polynomial kept), so the small "
            "tabular distortion corrections are not applied"
        )
    if not wcs.has_celestial:
        notes.append("no celestial WCS in the science header")
        return None
    if wcs.naxis != 2:
        notes.append(f"WCS has {wcs.naxis} axes: its celestial part is used")
        return wcs.celestial
    return wcs


def _plane(hdu, shape: tuple[int, ...], notes: list[str]) -> np.ndarray | None:
    """The array of an ERR/DQ HDU, or the constant plane HST stores as ``PIXVALUE``."""
    if hdu is None:
        return None
    if hdu.data is not None:
        return hdu.data
    header = hdu.header
    if "PIXVALUE" in header:
        size = tuple(header.get(f"NPIX{i}") for i in (2, 1))
        if size == tuple(shape):
            notes.append(f"{hdu.name} is constant: PIXVALUE = {header['PIXVALUE']}")
            dtype = np.int64 if hdu.name == "DQ" else np.float64
            return np.full(shape, header["PIXVALUE"], dtype=dtype)
    return None


def _extension(hdul: fits.HDUList, name: str, ver: int) -> fits.hdu.base.ExtensionHDU | None:
    try:
        return hdul[name, ver]
    except KeyError:
        return None


def _telescope(header: fits.Header) -> str:
    return str(header.get("TELESCOP", "")).strip().upper()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique(items) -> list[str]:
    return list(dict.fromkeys(items))
