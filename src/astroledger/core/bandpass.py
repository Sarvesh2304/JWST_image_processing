"""Resolve which bandpass an image was taken through, from its FITS headers.

The filter keyword alone is not enough:

- **NIRISS** imaging records ``FILTER=CLEAR`` and the bandpass in ``PUPIL`` (F090W ... F200W), or
  ``PUPIL=CLEARP`` and the bandpass in ``FILTER`` (F277W ... F480M).
- **NIRCam** narrow and medium filters in the pupil wheel are used together with a broad
  filter-wheel element: ``FILTER=F444W, PUPIL=F405N`` is an F405N (Brackett-alpha) image.
- **HST ACS** has two filter wheels (``FILTER1``, ``FILTER2``); one is normally a CLEAR position.

Wavelengths
-----------
``nominal_wavelength`` comes from the instruments' published naming convention (the digits of
the filter name): JWST ``F405N`` = 4.05 um, ``F1130W`` = 11.30 um; HST UVIS/optical ``F606W`` =
606 nm, HST infrared ``F160W`` = 1.60 um. It is good for ordering and labelling, not for
photometry.

``pivot`` comes from an authentic source and is never guessed:

- HST: the ``PHOTPLAM`` header keyword;
- JWST NIRCam and NIRISS: ``core/data/jwst_pivots.ecsv``, computed with
  ``scripts/build_jwst_pivots.py`` from STScI's throughput tables (``mirage`` 2.5.0). NIRCam
  pivots differ slightly between modules A and B. The module comes from ``DETECTOR``; for a
  multi-module mosaic (``DETECTOR=MULTIPLE``) the mean of the two is used, and a note says so;
- MIRI and anything else: none (no authentic table available here).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from astropy import units as u
from astropy.io.fits import Header

__all__ = ["NIRCAM_PUPIL_FILTER_PAIRS", "Bandpass"]

#: NIRCam pupil-wheel filters and the filter-wheel element each is used with.
NIRCAM_PUPIL_FILTER_PAIRS: dict[str, str] = {
    "F162M": "F150W2",
    "F164N": "F150W2",
    "F323N": "F322W2",
    "F405N": "F444W",
    "F466N": "F444W",
    "F470N": "F444W",
}
_NIRCAM_CLEAR_PUPILS = {"CLEAR", "CLEARP"}
_NIRCAM_NONFILTER_PUPILS = {
    "GRISMR": "grism",
    "GRISMC": "grism",
    "MASKRND": "coronagraph",
    "MASKBAR": "coronagraph",
    "WLP8": "weak lens",
    "WLM8": "weak lens",
}
_NIRISS_SPECIAL = {
    "GR150R": "grism",
    "GR150C": "grism",
    "GR700XD": "grism (SOSS)",
    "NRM": "aperture masking (AMI)",
}
_FILTER_NAME = re.compile(r"^F(\d{3,4})(W2|LP|W|M|N|X|C|L)?$")


@dataclass(frozen=True)
class Bandpass:
    """The bandpass of an image, resolved from its optical elements.

    Attributes
    ----------
    name : str or None
        Resolved bandpass, e.g. ``"F405N"``; None when it cannot be determined.
    telescope, instrument : str or None
        From ``TELESCOP`` and ``INSTRUME``.
    elements : dict
        Raw optical-element keywords used, e.g. ``{"FILTER": "F444W", "PUPIL": "F405N"}``.
    mode : str
        ``"imaging"`` or the special element type (grism, coronagraph, ...), or ``"unknown"``.
    nominal_wavelength : astropy.units.Quantity or None
        Wavelength encoded in the filter name (see module notes).
    pivot : astropy.units.Quantity or None
        Pivot wavelength from a header keyword, or None.
    notes : tuple of str
        How the bandpass was resolved and anything unusual.
    """

    name: str | None
    telescope: str | None
    instrument: str | None
    elements: dict[str, str] = field(default_factory=dict)
    mode: str = "unknown"
    nominal_wavelength: u.Quantity | None = None
    pivot: u.Quantity | None = None
    notes: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """Identifier that is unique across instruments, e.g. ``"JWST/NIRCAM/F405N"``."""
        return "/".join(p or "UNKNOWN" for p in (self.telescope, self.instrument, self.name))

    @property
    def width_class(self) -> str | None:
        """Suffix of the filter name: W (wide), M (medium), N (narrow), W2, LP, ..."""
        match = _FILTER_NAME.match(self.name or "")
        return match.group(2) if match else None

    def __str__(self) -> str:
        wavelength = ""
        if self.nominal_wavelength is not None:
            wavelength = f" ({self.nominal_wavelength:.3g} nominal)"
        return f"{self.key}{wavelength}"

    @classmethod
    def from_header(cls, primary: Header, science: Header | None = None) -> Bandpass:
        """Resolve the bandpass from a primary header (and optionally the science header).

        Parameters
        ----------
        primary : astropy.io.fits.Header
            Primary header, which holds the optical-element keywords for JWST and HST.
        science : astropy.io.fits.Header, optional
            Science-extension header, checked for ``PHOTPLAM`` and for keywords missing from
            the primary header.
        """
        science = science if science is not None else Header()

        def get(key: str) -> str | None:
            for header in (primary, science):
                value = header.get(key)
                if value not in (None, ""):
                    return str(value).strip().upper()
            return None

        telescope, instrument = get("TELESCOP"), get("INSTRUME")
        if telescope == "JWST" and instrument == "NIRCAM":
            result = _nircam(get("FILTER"), get("PUPIL"))
        elif telescope == "JWST" and instrument == "NIRISS":
            result = _niriss(get("FILTER"), get("PUPIL"))
        elif telescope == "JWST" and instrument == "MIRI":
            result = _single("FILTER", get("FILTER"))
        elif telescope == "HST" and instrument == "ACS":
            result = _acs(get("FILTER1"), get("FILTER2"))
        elif telescope == "HST":
            result = _single("FILTER", get("FILTER"))
        else:
            result = _single("FILTER", get("FILTER"), generic=True)
        name, mode, elements, notes = result

        pivot = None
        photplam = science.get("PHOTPLAM", primary.get("PHOTPLAM"))
        if photplam:
            pivot = (float(photplam) * u.AA).to(u.um)
            notes = (*notes, "pivot from PHOTPLAM header keyword")
        elif telescope == "JWST" and instrument in ("NIRCAM", "NIRISS") and name:
            pivot, note = _jwst_pivot(
                instrument, name, elements, get("DETECTOR"), get("FILENAME") or ""
            )
            if note:
                notes = (*notes, note)

        return cls(
            name=name,
            telescope=telescope,
            instrument=instrument,
            elements=elements,
            mode=mode,
            nominal_wavelength=_nominal_wavelength(name, telescope, instrument, get("DETECTOR")),
            pivot=pivot,
            notes=tuple(notes),
        )


_PIVOT_TABLE = Path(__file__).parent / "data" / "jwst_pivots.ecsv"


@lru_cache(maxsize=1)
def _pivot_rows() -> tuple[tuple[str, str, str, str, str, float], ...]:
    from astropy.table import Table

    table = Table.read(_PIVOT_TABLE, format="ascii.ecsv")
    return tuple(
        (
            str(r["instrument"]),
            str(r["filter_wheel"] or ""),
            str(r["pupil_wheel"] or ""),
            str(r["bandpass"]),
            str(r["module"] or ""),
            float(r["pivot_um"]),
        )
        for r in table
    )


_COMBINED_PRODUCT = re.compile(r"^JW\d{5}-[OC]\d+", re.IGNORECASE)


def _jwst_pivot(
    instrument: str,
    name: str,
    elements: dict[str, str],
    detector: str | None,
    filename: str = "",
) -> tuple[u.Quantity | None, str | None]:
    """Pivot from the bundled STScI-derived table; (None, None) when not covered.

    The NIRCam module is taken from ``DETECTOR`` only for single-exposure products. Stage-3
    association products (``jwNNNNN-o...``, ``jwNNNNN-c...``) inherit ``DETECTOR`` from one
    input exposure although they may combine both modules, so the module mean is used.
    """
    rows = [r for r in _pivot_rows() if r[0] == instrument and r[3] == name]
    if instrument == "NIRCAM":
        filt, pupil = elements.get("FILTER", ""), elements.get("PUPIL", "CLEAR") or "CLEAR"
        exact = [r for r in rows if r[1] == filt and r[2] == pupil]
        rows = exact or rows
        modules = {r[4]: r[5] for r in rows}
        if not modules:
            return None, None
        combined = bool(_COMBINED_PRODUCT.match(Path(filename).name))
        det = detector or ""
        module = "A" if det.startswith("NRCA") else "B" if det.startswith("NRCB") else None
        if module in modules and not combined:
            return modules[module] * u.um, f"pivot: STScI throughput table, module {module}"
        values = list(modules.values())
        spread = (max(values) - min(values)) / (sum(values) / len(values))
        why = (
            "combined product, modules not recorded"
            if combined
            else f"DETECTOR={detector or 'unknown'}"
        )
        return sum(values) / len(values) * u.um, (
            f"pivot: mean of NIRCam modules {'/'.join(sorted(modules))} from STScI throughput "
            f"tables ({why}); modules differ by {spread:.2%}"
        )
    if rows:
        return rows[0][5] * u.um, "pivot: STScI throughput table"
    return None, None


_Resolved = tuple[str | None, str, dict[str, str], tuple[str, ...]]


def _nircam(filt: str | None, pupil: str | None) -> _Resolved:
    elements = {k: v for k, v in (("FILTER", filt), ("PUPIL", pupil)) if v}
    if pupil in NIRCAM_PUPIL_FILTER_PAIRS:
        expected = NIRCAM_PUPIL_FILTER_PAIRS[pupil]
        notes = [f"pupil-wheel filter {pupil} used with {filt}"]
        if filt != expected:
            notes.append(f"unexpected pairing: {pupil} is normally used with {expected}")
        return pupil, "imaging", elements, tuple(notes)
    if pupil in _NIRCAM_NONFILTER_PUPILS:
        mode = _NIRCAM_NONFILTER_PUPILS[pupil]
        return filt, mode, elements, (f"PUPIL={pupil}: {mode}, bandpass from FILTER",)
    if pupil in _NIRCAM_CLEAR_PUPILS or pupil is None:
        return filt, "imaging" if filt else "unknown", elements, ("bandpass from FILTER",)
    return filt, "unknown", elements, (f"unrecognised PUPIL={pupil}; bandpass from FILTER",)


def _niriss(filt: str | None, pupil: str | None) -> _Resolved:
    elements = {k: v for k, v in (("FILTER", filt), ("PUPIL", pupil)) if v}
    if filt in _NIRISS_SPECIAL:  # GR150R/C: the pupil holds the blocking filter
        mode = _NIRISS_SPECIAL[filt]
        return pupil, mode, elements, (f"FILTER={filt}: {mode}, bandpass from PUPIL",)
    if pupil in _NIRISS_SPECIAL:  # GR700XD (SOSS), NRM (AMI): the filter wheel holds the band
        mode = _NIRISS_SPECIAL[pupil]
        return filt, mode, elements, (f"PUPIL={pupil}: {mode}, bandpass from FILTER",)
    if filt == "CLEAR":
        return pupil, "imaging", elements, ("FILTER=CLEAR: bandpass from PUPIL",)
    if pupil in (None, "CLEARP"):
        return filt, "imaging" if filt else "unknown", elements, ("bandpass from FILTER",)
    return None, "unknown", elements, (f"cannot resolve NIRISS FILTER={filt}, PUPIL={pupil}",)


def _acs(filter1: str | None, filter2: str | None) -> _Resolved:
    elements = {k: v for k, v in (("FILTER1", filter1), ("FILTER2", filter2)) if v}
    real = [f for f in (filter1, filter2) if f and not f.startswith("CLEAR")]
    if len(real) == 1:
        return real[0], "imaging", elements, ("non-CLEAR element of FILTER1/FILTER2",)
    if not real:
        return None, "unknown", elements, ("both ACS filter wheels CLEAR",)
    return "+".join(real), "imaging", elements, ("two ACS elements combined (e.g. polariser)",)


def _single(key: str, value: str | None, *, generic: bool = False) -> _Resolved:
    if not value:
        return None, "unknown", {}, (f"no {key} keyword",)
    notes = ("bandpass from FILTER (instrument not specifically supported)",) if generic else ()
    return value, "imaging", {key: value}, notes


def _nominal_wavelength(
    name: str | None, telescope: str | None, instrument: str | None, detector: str | None
) -> u.Quantity | None:
    match = _FILTER_NAME.match(name or "")
    if not match:
        return None
    digits = int(match.group(1))
    if telescope == "JWST":
        return digits / 100 * u.um
    if telescope == "HST":
        infrared = instrument == "NICMOS" or (instrument == "WFC3" and detector == "IR")
        return digits / 100 * u.um if infrared else (digits * u.nm).to(u.um)
    return None
