"""Observing-mode router: decide from the header whether a product is a direct image.

Image analyses (detection, photometry, completeness, astrometry, colour composites) are only
meaningful for direct imaging. A dispersed spectrum, a coronagraphic image (star suppressed by a
mask) or a time series (cubes of integrations, often of a saturated-by-design bright star) read
as a 2-D array, but measuring them as an image gives nonsense. The router therefore *refuses*
everything it does not positively recognise as supported imaging (audit item S15).

Rules:

- **JWST:** ``EXP_TYPE`` (primary header). Supported: ``NRC_IMAGE``, ``MIR_IMAGE``,
  ``NIS_IMAGE``. Any exposure in a time-series visit (``TSOVISIT = T``) is refused. Other values
  are classified by their name (spectroscopy, coronagraphy, time series, aperture-masking
  interferometry, calibration or target acquisition) for the message, and refused; values not
  matching any rule are "unknown" and refused too.
- **HST:** ``OBSTYPE`` must be ``IMAGING``; grism and prism elements and coronagraphic
  apertures are refused even then.
- **Other telescopes** (e.g. your own camera): there is no standard mode keyword. Imaging is
  assumed, and the mode says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from astropy.io.fits import Header

from astroledger.core.errors import UnsupportedProductError

__all__ = ["ModeCategory", "ObservingMode", "observing_mode", "require_imaging"]


class ModeCategory(StrEnum):
    """Broad class of an observing mode."""

    IMAGING = "imaging"
    SPECTROSCOPY = "spectroscopy"
    CORONAGRAPHY = "coronagraphy"
    TIME_SERIES = "time series"
    INTERFEROMETRY = "aperture-masking interferometry"
    CALIBRATION = "calibration or target acquisition"
    UNKNOWN = "unknown"


#: JWST EXP_TYPE values supported for image analysis.
JWST_IMAGING = frozenset({"NRC_IMAGE", "MIR_IMAGE", "NIS_IMAGE"})

# Name fragments of JWST EXP_TYPE values, checked in this order (first match wins).
_JWST_RULES: tuple[tuple[tuple[str, ...], ModeCategory], ...] = (
    (
        ("TACQ", "TACONFIRM", "CONFIRM", "WATA", "MSATA", "TASLIT", "VERIFY", "BOTA"),
        ModeCategory.CALIBRATION,
    ),
    (
        (
            "DARK",
            "FLAT",
            "LED",
            "LAMP",
            "FOCUS",
            "MIMF",
            "AUTOWAVE",
            "AUTOFLAT",
            "EXTCAL",
            "CORONCAL",
        ),
        ModeCategory.CALIBRATION,
    ),
    (("_TS",), ModeCategory.TIME_SERIES),  # NRC_TSIMAGE, NRC_TSGRISM
    (("CORON", "LYOT", "4QPM"), ModeCategory.CORONAGRAPHY),
    (("AMI",), ModeCategory.INTERFEROMETRY),
    (
        ("WFSS", "GRISM", "SOSS", "MSASPEC", "IFU", "FIXEDSLIT", "MRS", "LRS", "BRIGHTOBJ"),
        ModeCategory.SPECTROSCOPY,
    ),
    (("_IMAGE",), ModeCategory.IMAGING),
)


@dataclass(frozen=True)
class ObservingMode:
    """The observing mode of a product and whether image analyses support it.

    Attributes
    ----------
    category : ModeCategory
    keyword : str or None
        Header keyword the decision rests on (``EXP_TYPE``, ``OBSTYPE``), or None.
    value : str or None
        Its value.
    supported : bool
        True only for direct imaging this package can analyse.
    reason : str
        Why, in one sentence.
    notes : tuple of str
        Extra facts (e.g. "imaging assumed: no mode keyword").
    """

    category: ModeCategory
    keyword: str | None
    value: str | None
    supported: bool
    reason: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        source = f"{self.keyword}={self.value}" if self.keyword else "no mode keyword"
        return f"{self.category.value} ({source})"


def _get(headers, key):
    for header in headers:
        if header is not None and key in header and header[key] not in (None, ""):
            return header[key]
    return None


def _jwst(headers) -> ObservingMode:
    value = _get(headers, "EXP_TYPE")
    if value is None:
        return ObservingMode(
            ModeCategory.UNKNOWN,
            "EXP_TYPE",
            None,
            False,
            "JWST product without EXP_TYPE: the observing mode cannot be established",
        )
    value = str(value).strip().upper()
    category = ModeCategory.UNKNOWN
    for fragments, candidate in _JWST_RULES:
        if any(fragment in value for fragment in fragments):
            category = candidate
            break
    tso = _get(headers, "TSOVISIT")
    if tso is True or str(tso).strip().upper() in ("T", "TRUE"):
        return ObservingMode(
            ModeCategory.TIME_SERIES,
            "EXP_TYPE",
            value,
            False,
            f"{value} exposure"
            + (f" ({category.value})" if category is not ModeCategory.TIME_SERIES else "")
            + " in a time-series visit (TSOVISIT = T)",
        )
    if value in JWST_IMAGING:
        return ObservingMode(category, "EXP_TYPE", value, True, f"{value} is direct imaging")
    if category is ModeCategory.IMAGING:
        reason = f"{value} is an imaging mode used for acquisition or verification, not science"
    elif category is ModeCategory.UNKNOWN:
        reason = f"EXP_TYPE {value} is not a mode this package recognises"
    else:
        reason = f"EXP_TYPE {value} is {category.value}, not direct imaging"
    return ObservingMode(category, "EXP_TYPE", value, False, reason)


def _hst(headers) -> ObservingMode:
    obstype = _get(headers, "OBSTYPE")
    if obstype is None:
        return ObservingMode(
            ModeCategory.UNKNOWN,
            "OBSTYPE",
            None,
            False,
            "HST product without OBSTYPE: the observing mode cannot be established",
        )
    obstype = str(obstype).strip().upper()
    elements = [
        str(_get(headers, key)).strip().upper()
        for key in ("FILTER", "FILTER1", "FILTER2", "OPT_ELEM")
        if _get(headers, key) is not None
    ]
    aperture = str(_get(headers, "APERTURE") or "").upper()
    dispersers = [e for e in elements if e.startswith(("G", "PR")) and any(c.isdigit() for c in e)]
    if obstype != "IMAGING":
        category = ModeCategory.SPECTROSCOPY if "SPEC" in obstype else ModeCategory.UNKNOWN
        return ObservingMode(
            category, "OBSTYPE", obstype, False, f"OBSTYPE {obstype} is not direct imaging"
        )
    if dispersers:
        return ObservingMode(
            ModeCategory.SPECTROSCOPY,
            "OBSTYPE",
            obstype,
            False,
            f"dispersing element {dispersers[0]} in the beam (grism or prism)",
        )
    if "CORON" in aperture:
        return ObservingMode(
            ModeCategory.CORONAGRAPHY,
            "OBSTYPE",
            obstype,
            False,
            f"coronagraphic aperture {aperture}",
        )
    return ObservingMode(ModeCategory.IMAGING, "OBSTYPE", obstype, True, "HST direct imaging")


def observing_mode(*headers: Header | None) -> ObservingMode:
    """Classify the observing mode from one or more headers (primary first).

    Accepts an :class:`~astroledger.core.product.ImageProduct` too (its primary and science
    headers are used).
    """
    if len(headers) == 1 and hasattr(headers[0], "primary_header"):
        product = headers[0]
        headers = (product.primary_header, product.header)
    telescope = str(_get(headers, "TELESCOP") or "").strip().upper()
    if telescope == "JWST":
        return _jwst(headers)
    if telescope == "HST":
        return _hst(headers)
    return ObservingMode(
        ModeCategory.IMAGING,
        None,
        None,
        True,
        "no mission mode keyword: direct imaging assumed",
        notes=(
            f"telescope {telescope or 'unknown'} has no standard mode keyword; "
            "imaging is assumed, not established",
        ),
    )


def require_imaging(image, operation: str) -> ObservingMode:
    """Return the image's mode, or raise if ``operation`` is not valid for it.

    Raises
    ------
    UnsupportedProductError
        For spectroscopic, coronagraphic, time-series, interferometric, calibration and
        unknown modes, with the reason and the keyword it rests on.
    """
    mode = observing_mode(image)
    if not mode.supported:
        name = getattr(getattr(image, "source", None), "filename", None) or "this product"
        raise UnsupportedProductError(
            f"{operation} refused for {name}: {mode.reason}. {operation} is only valid for "
            "direct images; use the instrument's official pipeline products for this mode."
        )
    return mode
