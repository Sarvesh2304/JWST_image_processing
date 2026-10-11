"""Tests for astroledger.archives.gaia and cloud.RemoteFile against a fake S3 (task 14).

The Parquet file served here is synthetic, built in the test with the layout of MAST's HATS copy
of Gaia DR3: rows sorted by source_id, with source_id >> 35 = HEALPix level-12 nested pixel.
"""

import io
import re

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy_healpix import HEALPix

from astroledger.archives import cloud, gaia

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

CENTRE = SkyCoord(151.757 * u.deg, -40.4365 * u.deg)


class _Response:
    def __init__(self, content=b"", status=200, headers=None):
        self.content, self.status_code, self.headers = content, status, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(self.status_code)


class FakeBucket:
    """Serves several objects by key with HEAD and Range GET, counting bytes served."""

    def __init__(self, objects):
        self.objects = objects
        self.served = 0

    def _key(self, url):
        return url.split(".amazonaws.com/", 1)[1]

    def head(self, url, timeout=None):
        data = self.objects.get(self._key(url))
        if data is None:
            return _Response(status=404)
        return _Response(headers={"Content-Length": str(len(data)), "ETag": '"x"'})

    def get(self, url, headers=None, timeout=None, **kw):
        data = self.objects[self._key(url)]
        start, stop = map(int, re.match(r"bytes=(\d+)-(\d+)", headers["Range"]).groups())
        self.served += stop + 1 - start
        return _Response(data[start : stop + 1], status=206)


def _synthetic_partition():
    """Parquet bytes for one order-4 partition: a cluster near CENTRE and a far group."""
    hp12 = HEALPix(nside=2**12, order="nested")
    rng = np.random.default_rng(0)
    near = CENTRE.directional_offset_by(
        rng.uniform(0, 360, 30) * u.deg, 60 * np.sqrt(rng.uniform(0, 1, 30)) * u.arcsec
    )
    centre_parent = int(hp12.lonlat_to_healpix(CENTRE.ra, CENTRE.dec)) >> 16
    trial = CENTRE.directional_offset_by(
        rng.uniform(0, 360, 6000) * u.deg, rng.uniform(300, 3600, 6000) * u.arcsec
    )
    same = (hp12.lonlat_to_healpix(trial.ra, trial.dec).astype(np.int64) >> 16) == centre_parent
    far = trial[same][:2000]
    ra = np.concatenate([near.ra.deg, far.ra.deg])
    dec = np.concatenate([near.dec.deg, far.dec.deg])
    pix = hp12.lonlat_to_healpix(ra * u.deg, dec * u.deg).astype(np.int64)
    order4 = set((pix >> 16).tolist())
    assert len(order4) == 1, "test layout must stay in one partition"
    source_id = (pix << 35) + np.arange(len(pix))
    order = np.argsort(source_id)
    n = len(pix)
    table = pa.table(
        {
            "source_id": source_id[order],
            "ra": ra[order],
            "dec": dec[order],
            "ra_error": np.full(n, 0.1),
            "dec_error": np.full(n, 0.1),
            "pmra": np.full(n, 5.0),
            "pmra_error": np.full(n, 0.1),
            "pmdec": np.full(n, -3.0),
            "pmdec_error": np.full(n, 0.1),
            "ref_epoch": np.full(n, 2016.0),
            "phot_g_mean_mag": np.full(n, 18.0),
            "astrometric_params_solved": np.full(n, 31, dtype=np.int16),
        }
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer, row_group_size=200)
    return buffer.getvalue(), order4.pop(), ra, dec


@pytest.fixture
def bucket(monkeypatch):
    data, npix, ra, dec = _synthetic_partition()
    objects = {
        f"{gaia.HATS_ROOT}/partition_info.csv": f"Norder,Npix\n3,1\n4,{npix}\n".encode(),
        gaia._partition_key(4, npix): data,
    }
    server = FakeBucket(objects)
    monkeypatch.setattr(cloud.requests, "Session", lambda: server)
    return server, data, ra, dec


def test_hats_partitions_maps_pixels_to_parents():
    partitions = {(3, 5), (4, 100)}
    pixels = np.array([(100 << 16) + 7, (5 << 18) + 1])
    assert gaia.hats_partitions(pixels, partitions) == {
        (4, 100): [(100 << 16) + 7],
        (3, 5): [(5 << 18) + 1],
    }
    with pytest.raises(ValueError, match="no partition"):
        gaia.hats_partitions(np.array([1]), partitions)


def test_partition_key_layout():
    assert gaia._partition_key(4, 2407) == (
        "gaia/gaia_dr3/public/hats/gaia/dataset/Norder=4/Dir=0/Npix=2407.parquet"
    )
    assert gaia._partition_key(6, 12345).endswith("Norder=6/Dir=10000/Npix=12345.parquet")


def test_remote_file_reads_exact_ranges(bucket):
    server, data, *_ = bucket
    ledger = cloud.DownloadLedger()
    key = next(k for k in server.objects if k.endswith(".parquet"))
    remote = cloud.RemoteFile(key, ledger=ledger)
    assert remote.size == len(data)
    remote.seek(-8, io.SEEK_END)
    assert remote.read() == data[-8:]
    remote.seek(100)
    assert remote.read(50) == data[100:150] and remote.tell() == 150
    assert ledger.used_bytes == 58


def test_remote_file_respects_budget(bucket):
    server, *_ = bucket
    key = next(k for k in server.objects if k.endswith(".parquet"))
    remote = cloud.RemoteFile(key, ledger=cloud.DownloadLedger(budget_bytes=10))
    with pytest.raises(cloud.BudgetExceededError):
        remote.read(100)


def test_gaia_cone_reads_only_needed_row_groups(bucket):
    _, data, ra, dec = bucket
    ledger = cloud.DownloadLedger()
    result = gaia.gaia_cone(CENTRE, 70 * u.arcsec, ledger=ledger)
    expected = CENTRE.separation(SkyCoord(ra * u.deg, dec * u.deg)) < 70 * u.arcsec
    assert len(result) == expected.sum() == 30
    assert result["ra"].unit == u.deg and result["pmra"].unit == u.mas / u.yr
    assert np.all(np.diff(result["source_id"]) > 0)
    groups = next(iter(result.meta["row_groups_read"].values()))
    assert 1 <= len(groups) < pq.ParquetFile(io.BytesIO(data)).num_row_groups
    assert result.meta["bytes_read"] == ledger.used_bytes < len(data)


@pytest.mark.remote
def test_live_gaia_cone_small():
    """Live read from MAST's AWS copy (about 14 MB: one row group's astrometry columns)."""
    ledger = cloud.DownloadLedger(budget_bytes=30_000_000)
    result = gaia.gaia_cone(CENTRE, 10 * u.arcsec, ledger=ledger)
    assert len(result) >= 1
    assert np.all(result["ref_epoch"].to_value(u.yr) == 2016.0)
