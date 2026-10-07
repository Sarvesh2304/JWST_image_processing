"""Gaia DR3 sources from MAST's HATS copy of the catalogue on AWS, read selectively.

MAST hosts Gaia DR3 as a HATS catalogue: Parquet files partitioned by HEALPix tile
(``s3://stpubdata/gaia/gaia_dr3/public/hats/gaia/``). Rows in each file are sorted by
``source_id``, and a Gaia ``source_id`` encodes the source's HEALPix level-12 (nested) pixel:
``source_id // 2**35``. A cone search therefore needs only:

1. the partition file(s) containing the cone (from ``partition_info.csv``);
2. the Parquet footer;
3. the requested columns of the row groups whose ``source_id`` range overlaps the cone's
   level-12 pixels.

All reads are HTTP range requests counted by a :class:`~astroledger.archives.cloud.DownloadLedger`.
Gaia DR3 positions refer to epoch J2016.0 (``ref_epoch``), so propagate them before comparing
with images taken at other epochs (see :func:`astroledger.astrometry.propagate`).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import QTable, vstack
from astropy_healpix import HEALPix

from astroledger.archives.cloud import DownloadLedger, RemoteFile, _get_range, _head
from astroledger.provenance import step

__all__ = ["ASTROMETRY_COLUMNS", "HATS_ROOT", "gaia_cone", "hats_partitions", "save"]

HATS_ROOT = "gaia/gaia_dr3/public/hats/gaia"

#: Columns for astrometric work: positions, proper motions, their errors, epoch, brightness.
ASTROMETRY_COLUMNS = (
    "source_id",
    "ra",
    "dec",
    "ra_error",
    "dec_error",
    "pmra",
    "pmra_error",
    "pmdec",
    "pmdec_error",
    "ref_epoch",
    "phot_g_mean_mag",
    "astrometric_params_solved",
)
_UNITS = {
    "ra": u.deg,
    "dec": u.deg,
    "ra_error": u.mas,
    "dec_error": u.mas,
    "pmra": u.mas / u.yr,
    "pmra_error": u.mas / u.yr,
    "pmdec": u.mas / u.yr,
    "pmdec_error": u.mas / u.yr,
    "parallax": u.mas,
    "parallax_error": u.mas,
    "ref_epoch": u.yr,
    "phot_g_mean_mag": u.mag,
}
_SOURCE_ID_SHIFT = 35  # source_id // 2**35 = HEALPix level-12 nested pixel


def _partition_index(ledger: DownloadLedger) -> set[tuple[int, int]]:
    key = f"{HATS_ROOT}/partition_info.csv"
    session = requests.Session()
    size, _ = _head(key, session)
    text = _get_range(key, 0, size, session, ledger, "gaia partition index").decode()
    return {(int(r["Norder"]), int(r["Npix"])) for r in csv.DictReader(io.StringIO(text))}


def hats_partitions(level12_pixels: np.ndarray, partitions: set[tuple[int, int]]) -> dict:
    """Map level-12 pixels to the HATS partitions containing them: ``{(order, npix): [pixels]}``."""
    orders = sorted({order for order, _ in partitions})
    result: dict[tuple[int, int], list[int]] = {}
    for pixel in np.atleast_1d(level12_pixels):
        for order in orders:
            parent = (order, int(pixel) >> (2 * (12 - order)))
            if parent in partitions:
                result.setdefault(parent, []).append(int(pixel))
                break
        else:
            raise ValueError(f"level-12 pixel {pixel} is in no partition")
    return result


def _partition_key(order: int, npix: int) -> str:
    return f"{HATS_ROOT}/dataset/Norder={order}/Dir={npix // 10000 * 10000}/Npix={npix}.parquet"


@step("archives.gaia.cone", version="1")
def gaia_cone(
    center: SkyCoord,
    radius: u.Quantity,
    *,
    columns: tuple[str, ...] = ASTROMETRY_COLUMNS,
    ledger: DownloadLedger | None = None,
) -> QTable:
    """Gaia DR3 sources within ``radius`` of ``center``, reading only what is needed.

    Returns
    -------
    astropy.table.QTable
        Requested columns with units; ``meta`` records partitions, row groups and bytes read.
    """
    import pyarrow.parquet as pq

    ledger = ledger or DownloadLedger()
    start = ledger.used_bytes
    hp12 = HEALPix(nside=2**12, order="nested")
    margin = hp12.pixel_resolution  # ensure pixels touching the cone edge are included
    pixels = np.unique(hp12.cone_search_lonlat(center.ra, center.dec, radius=radius + margin))
    columns = tuple(dict.fromkeys(("source_id", "ra", "dec", *columns)))
    tables, read_groups = [], {}
    for (order, npix), members in hats_partitions(pixels, _partition_index(ledger)).items():
        key = _partition_key(order, npix)
        parquet = pq.ParquetFile(RemoteFile(key, ledger=ledger, purpose=f"gaia {order}/{npix}"))
        meta = parquet.metadata
        names = [meta.schema.column(i).name for i in range(meta.num_columns)]
        id_column = names.index("source_id")
        lows = np.array(members, dtype=np.int64) << _SOURCE_ID_SHIFT
        highs = (np.array(members, dtype=np.int64) + 1) << _SOURCE_ID_SHIFT
        groups = []
        for g in range(meta.num_row_groups):
            stats = meta.row_group(g).column(id_column).statistics
            if np.any((stats.max >= lows) & (stats.min < highs)):
                groups.append(g)
        read_groups[key] = groups
        if groups:
            arrow = parquet.read_row_groups(groups, columns=list(columns))
            data = {name: arrow[name].to_numpy(zero_copy_only=False) for name in columns}
            keep = np.isin(data["source_id"] >> _SOURCE_ID_SHIFT, members)
            tables.append(QTable({name: values[keep] for name, values in data.items()}))
    rows = vstack(tables) if tables else QTable()
    if len(rows):
        sky = SkyCoord(rows["ra"] * u.deg, rows["dec"] * u.deg)
        rows = rows[sky.separation(center) < radius]
        for name in rows.colnames:
            if name in _UNITS:
                rows[name] = np.asarray(rows[name], dtype=float) * _UNITS[name]
    rows.meta.update(
        {
            "catalogue": "Gaia DR3 (MAST HATS copy)",
            "center_deg": [float(center.icrs.ra.deg), float(center.icrs.dec.deg)],
            "radius_arcsec": float(radius.to_value(u.arcsec)),
            "row_groups_read": {k: v for k, v in read_groups.items()},
            "bytes_read": ledger.used_bytes - start,
        }
    )
    return rows


def save(table: QTable, path: str | Path) -> Path:
    """Write a Gaia cone result as ECSV (units and metadata kept)."""
    path = Path(path)
    table.write(path, format="ascii.ecsv", overwrite=True)
    return path
