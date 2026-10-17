"""CDS adapters: Sesame name resolution, SIMBAD (TAP) and VizieR, cached and provenance-recorded.

Every result is a copy of what the service returned, never a reconstruction:

- columns are exactly the service's columns, with values unchanged;
- ``meta`` adds only provenance: the service, the query text, the retrieval time, the
  astroquery/astropy version, the cache key, and whether this call was served from the cache.

No function here produces an identity, object type, or bibliography on its own. An empty
result stays empty; there is no fallback to a "likely" answer.

Caching: each query is stored once as ECSV (or JSON for name resolution) under ``cache_dir``,
keyed by the SHA-256 of the service and the exact query. Repeating a query reads the stored
copy, so results are reproducible offline. Delete a file to force a fresh retrieval.

Network: needs ``cds.unistra.fr`` (Sesame), ``simbad.cds.unistra.fr`` (SIMBAD TAP) and
``vizier.cds.unistra.fr`` / ``tapvizier.cds.unistra.fr`` (VizieR).

SIMBAD TAP tables and columns used, as also used by astroquery's SIMBAD module:
``basic`` (oid, main_id, otype, ra, dec, coo_err_maj, coo_err_min, coo_bibcode),
``ident`` (oidref, id), ``has_ref`` (oidref, oidbibref) and ``ref`` (oidbib, bibcode).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import QTable, Table

from astroledger.provenance import step

__all__ = [
    "default_cache_dir",
    "resolve_name",
    "simbad_bibliography",
    "simbad_cone",
    "simbad_identifiers",
    "vizier_cone",
]

SIMBAD_CONE_COLUMNS = (
    "basic.oid",
    "basic.main_id",
    "basic.otype",
    "basic.ra",
    "basic.dec",
    "basic.coo_err_maj",
    "basic.coo_err_min",
    "basic.coo_bibcode",
)


def default_cache_dir() -> Path:
    """``$ASTROLEDGER_CACHE/cds`` if set, else ``./data/cds_cache``."""
    base = os.environ.get("ASTROLEDGER_CACHE")
    return Path(base) / "cds" if base else Path("data") / "cds_cache"


#: Cache format; part of the key so files written by an older format are never misread.
_CACHE_FORMAT = "ecsv-data-mask-1"


def _key(service: str, query: str) -> str:
    return hashlib.sha256(f"{_CACHE_FORMAT}\n{service}\n{query}".encode()).hexdigest()[:24]


def _versions() -> dict:
    import astropy

    try:
        import astroquery

        aq = astroquery.__version__
    except ImportError:  # pragma: no cover - astroquery is in the archives extra
        aq = None
    return {"astropy": astropy.__version__, "astroquery": aq}


def _provenance(service: str, endpoint: str, query: str, key: str) -> dict:
    return {
        "service": service,
        "endpoint": endpoint,
        "query": query,
        "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "software": _versions(),
        "cache_key": key,
    }


def _cached_table(service: str, endpoint: str, query: str, fetch, cache_dir) -> QTable:
    """Return the cached copy of a query result, or fetch, store and return it."""
    cache = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    key = _key(service, query)
    path = cache / f"{service.lower()}_{key}.ecsv"
    if path.exists():
        # masks are stored as explicit columns, so an empty string stays an empty string
        table = QTable.read(path, format="ascii.ecsv", fill_values=None)
        table.meta["from_cache"] = True
        table.meta["cache_file"] = str(path)
        return table
    result = fetch()
    table = QTable(result) if result is not None else QTable()
    table.meta = {"provenance": _provenance(service, endpoint, query, key)}
    cache.mkdir(parents=True, exist_ok=True)
    table.write(path, format="ascii.ecsv", overwrite=True, serialize_method="data_mask")
    table.meta["from_cache"] = False
    table.meta["cache_file"] = str(path)
    return table


def _deg(angle) -> float:
    return float(u.Quantity(angle).to_value(u.deg))


@step("archives.cds.resolve_name", version="1")
def resolve_name(name: str, *, cache_dir: str | Path | None = None) -> dict:
    """Resolve an object name to ICRS coordinates with CDS Sesame (via astropy).

    Returns
    -------
    dict
        ``name`` (as asked), ``ra_deg``, ``dec_deg`` and ``provenance``. Raises
        :class:`astropy.coordinates.name_resolve.NameResolveError` when Sesame has no answer;
        nothing is guessed.
    """
    from astropy.coordinates import name_resolve

    cache = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    key = _key("sesame", name)
    path = cache / f"sesame_{key}.json"
    if path.exists():
        record = json.loads(path.read_text())
        record["from_cache"] = True
        return record
    coord = name_resolve.get_icrs_coordinates(name, cache=False)
    record = {
        "name": name,
        "ra_deg": float(coord.ra.deg),
        "dec_deg": float(coord.dec.deg),
        "provenance": _provenance(
            "Sesame", "CDS Sesame via astropy.coordinates.name_resolve", name, key
        ),
    }
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    record["from_cache"] = False
    return record


def _simbad():
    from astroquery.simbad import Simbad

    return Simbad()


@step("archives.cds.simbad_cone", version="1")
def simbad_cone(
    center: SkyCoord,
    radius: u.Quantity,
    *,
    max_rows: int = 2000,
    cache_dir: str | Path | None = None,
) -> QTable:
    """SIMBAD objects within ``radius`` of ``center`` (SIMBAD TAP, table ``basic``).

    Columns, exactly as SIMBAD returns them: ``oid``, ``main_id``, ``otype``, ``ra``, ``dec``,
    ``coo_err_maj``, ``coo_err_min``, ``coo_bibcode``.
    """
    c = center.icrs
    query = (
        f"SELECT TOP {int(max_rows)} {', '.join(SIMBAD_CONE_COLUMNS)} FROM basic "
        f"WHERE CONTAINS(POINT('ICRS', basic.ra, basic.dec), "
        f"CIRCLE('ICRS', {c.ra.deg:.8f}, {c.dec.deg:.8f}, {_deg(radius):.8f})) = 1"
    )
    simbad = _simbad()
    return _cached_table(
        "SIMBAD",
        str(getattr(simbad, "server", "simbad.cds.unistra.fr")),
        query,
        lambda: simbad.query_tap(query, maxrec=int(max_rows)),
        cache_dir,
    )


@step("archives.cds.simbad_identifiers", version="1")
def simbad_identifiers(oid: int, *, cache_dir: str | Path | None = None) -> QTable:
    """All identifiers SIMBAD lists for the object with internal identifier ``oid``."""
    query = f"SELECT ident.id FROM ident WHERE ident.oidref = {int(oid)}"
    simbad = _simbad()
    return _cached_table(
        "SIMBAD",
        str(getattr(simbad, "server", "simbad.cds.unistra.fr")),
        query,
        lambda: simbad.query_tap(query),
        cache_dir,
    )


@step("archives.cds.simbad_bibliography", version="1")
def simbad_bibliography(oid: int, *, cache_dir: str | Path | None = None) -> QTable:
    """Bibcodes of the references SIMBAD links to the object with internal identifier ``oid``."""
    query = (
        "SELECT ref.bibcode FROM has_ref JOIN ref ON has_ref.oidbibref = ref.oidbib "
        f"WHERE has_ref.oidref = {int(oid)}"
    )
    simbad = _simbad()
    return _cached_table(
        "SIMBAD",
        str(getattr(simbad, "server", "simbad.cds.unistra.fr")),
        query,
        lambda: simbad.query_tap(query),
        cache_dir,
    )


@step("archives.cds.vizier_cone", version="1")
def vizier_cone(
    catalog: str,
    center: SkyCoord,
    radius: u.Quantity,
    *,
    columns: tuple[str, ...] = ("**",),
    max_rows: int = 2000,
    cache_dir: str | Path | None = None,
) -> QTable:
    """Rows of a VizieR catalogue (e.g. ``"I/355/gaiadr3"``) within ``radius`` of ``center``.

    ``columns=("**",)`` returns every column of the catalogue. ``catalog`` must name one
    table; a name matching several (e.g. a whole catalogue with sub-tables) is refused.
    """
    from astroquery.vizier import Vizier

    c = center.icrs
    query = json.dumps(
        {
            "catalog": catalog,
            "ra_deg": round(c.ra.deg, 8),
            "dec_deg": round(c.dec.deg, 8),
            "radius_deg": round(_deg(radius), 8),
            "columns": list(columns),
            "row_limit": int(max_rows),
        },
        sort_keys=True,
    )
    vizier = Vizier(columns=list(columns), row_limit=int(max_rows))

    def fetch():
        result = vizier.query_region(c, radius=u.Quantity(radius), catalog=catalog)
        if len(result) > 1:  # never pick one silently
            raise ValueError(
                f"VizieR returned {len(result)} tables for {catalog!r} "
                f"({', '.join(result.keys())}); ask for one of them"
            )
        return result[0] if len(result) else Table()

    return _cached_table(
        "VizieR",
        str(getattr(vizier, "VIZIER_SERVER", "vizier.cds.unistra.fr")),
        query,
        fetch,
        cache_dir,
    )
