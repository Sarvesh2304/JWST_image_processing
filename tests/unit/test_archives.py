"""Tests for astroledger.archives (roadmap §27 task 9). Network tests are marked ``remote``."""

import hashlib
import re

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

import fits_factory as ff
from astroledger.archives import cloud, mast

# --- bucket keys, ETags, ledger ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "key"),
    [
        (
            "jw02733002001_02101_00001_mirimage_cal.fits",
            "jwst/public/jw02733/jw02733002001/jw02733002001_02101_00001_mirimage_cal.fits",
        ),
        (
            "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits",
            "jwst/public/jw02733/L3/t/o001/jw02733-o001_t001_nircam_f405n-f444w_i2d.fits",
        ),
    ],
)
def test_jwst_key(name, key):
    assert cloud.jwst_key(name) == key


def test_jwst_key_rejects_unverified_patterns():
    with pytest.raises(ValueError, match="not known"):
        cloud.jwst_key("jw01345-c1018_t021_nircam_clear-f200w_i2d.fits")


def test_verify_etag_single_and_multipart(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(np.random.default_rng(0).bytes(11 * 1024 * 1024))
    data = path.read_bytes()
    assert cloud.verify_etag(path, hashlib.md5(data).hexdigest()) == "verified"
    part = 5 * 1024 * 1024
    md5s = b"".join(hashlib.md5(data[i : i + part]).digest() for i in range(0, len(data), part))
    assert cloud.verify_etag(path, f'"{hashlib.md5(md5s).hexdigest()}-3"') == "verified"
    assert cloud.verify_etag(path, "0" * 32) == "mismatch"
    assert cloud.verify_etag(path, "0" * 32 + "-7") == "unverifiable"


def test_ledger_budget(tmp_path):
    ledger = cloud.DownloadLedger(budget_bytes=100, log_path=tmp_path / "ledger.tsv")
    ledger.reserve(60, "a")
    ledger.record(60, "url", "0-59", "test")
    with pytest.raises(cloud.BudgetExceededError, match="exceed the budget"):
        ledger.reserve(41, "b")
    assert "60\turl\t0-59\ttest" in (tmp_path / "ledger.tsv").read_text()


# --- range-request cutouts against a fake S3 ---------------------------------------------------


class _Response:
    def __init__(self, content=b"", status=200, headers=None):
        self.content, self.status_code, self.headers = content, status, headers or {}

    def raise_for_status(self):
        pass


class FakeS3:
    """Serves one local file with HEAD and Range GET, counting requests."""

    def __init__(self, path):
        self.data = path.read_bytes()
        self.requests = 0

    def head(self, url, timeout=None):
        return _Response(headers={"Content-Length": str(len(self.data)), "ETag": '"abc"'})

    def get(self, url, headers=None, timeout=None, **kw):
        self.requests += 1
        start, stop = map(int, re.match(r"bytes=(\d+)-(\d+)", headers["Range"]).groups())
        return _Response(self.data[start : stop + 1], status=206)


@pytest.fixture
def fake_s3(tmp_path, monkeypatch):
    source = ff.jwst_cal(tmp_path / "jw02733002001_02101_00001_nrca1_cal.fits")
    server = FakeS3(source)
    monkeypatch.setattr(cloud.requests, "Session", lambda: server)
    return source, server


def test_remote_hdus_map_extensions(fake_s3):
    source, _ = fake_s3
    hdus = cloud.remote_hdus("any/key.fits")
    with fits.open(source) as local:
        assert [h.name for h in hdus] == [h.name for h in local]
        sci = next(h for h in hdus if h.name == "SCI")
        assert sci.header["BUNIT"] == "MJy/sr"
        assert sci.data_size == local["SCI"].data.nbytes


def test_fetch_rows_matches_source_pixels_and_wcs(fake_s3, tmp_path):
    source, _server = fake_s3
    ledger = cloud.DownloadLedger()
    out = cloud.fetch_rows(
        "jwst/public/jw02733/jw02733002001/jw02733002001_02101_00001_nrca1_cal.fits",
        (10, 40),
        tmp_path / "out",
        extensions=("SCI", "ERR", "DQ"),
        cols=(5, 70),
        ledger=ledger,
    )
    assert out.name == "jw02733002001_02101_00001_nrca1_cal_rows10-40_cols5-70.fits"
    with fits.open(source) as src, fits.open(out) as cut:
        for name in ("SCI", "ERR", "DQ"):
            np.testing.assert_array_equal(cut[name].data, src[name].data[10:40, 5:70])
        assert cut["DQ"].data.dtype == np.uint32
        assert cut[0].header["CUTSRC"] == "jw02733002001_02101_00001_nrca1_cal.fits"
        a = WCS(src["SCI"].header).pixel_to_world(30, 25)
        b = WCS(cut["SCI"].header).pixel_to_world(30 - 5, 25 - 10)
        assert a.separation(b).arcsec < 1e-6
    # Pixel transfers are exactly the requested rows (full width, 4-byte pixels, 3 extensions).
    row_bytes = sum(n for n, _, _, purpose in ledger.entries if "rows" in purpose)
    assert row_bytes == 3 * 30 * ff.SHAPE[1] * 4


@pytest.mark.parametrize("dtype", ["uint16", "uint32", "int8", "uint64", "int16"])
def test_fetch_rows_integer_conventions(tmp_path, monkeypatch, dtype):
    """Unsigned (BZERO-offset) and signed-byte integer images come back exactly."""
    info = np.iinfo(dtype)
    rng = np.random.default_rng(0)
    pixels = rng.integers(info.min, info.max, size=(20, 16), dtype=dtype, endpoint=True)
    pixels[0, :2] = (info.min, info.max)
    source = tmp_path / "src.fits"
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(pixels, name="SCI")]).writeto(source)
    monkeypatch.setattr(cloud.requests, "Session", lambda: FakeS3(source))
    out = cloud.fetch_rows("k/src.fits", (0, 5), tmp_path / "out", extensions=("SCI",))
    with fits.open(out) as cut:
        got = cut["SCI"].data.dtype
        assert (got.kind, got.itemsize) == (np.dtype(dtype).kind, np.dtype(dtype).itemsize)
        np.testing.assert_array_equal(cut["SCI"].data, pixels[0:5])


def test_fetch_rows_scaled_integers(tmp_path, monkeypatch):
    hdu = fits.ImageHDU(np.arange(80, dtype="int16").reshape(8, 10), name="SCI")
    hdu.header["BSCALE"], hdu.header["BZERO"] = 0.5, 100.0
    source = tmp_path / "scaled.fits"
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(source)
    with fits.open(source) as src:
        expected = src["SCI"].data[2:4].copy()
    monkeypatch.setattr(cloud.requests, "Session", lambda: FakeS3(source))
    out = cloud.fetch_rows("k/scaled.fits", (2, 4), tmp_path / "out", extensions=("SCI",))
    with fits.open(out) as cut:
        np.testing.assert_allclose(cut["SCI"].data, expected)


@pytest.mark.parametrize("cols", [(-5, 10), (20, 10), (30, 200)])
def test_fetch_rows_refuses_columns_outside_the_image(fake_s3, tmp_path, cols):
    with pytest.raises(ValueError, match="columns"):
        cloud.fetch_rows("k/x.fits", (0, 5), tmp_path, cols=cols)


class _Stream(_Response):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i : i + size]


class FakeObject:
    """Whole-object GET with a given advertised size and ETag; ``body`` is what arrives."""

    def __init__(self, body, size, etag):
        self.body, self.size, self.etag = body, size, etag

    def head(self, url, timeout=None):
        return _Response(headers={"Content-Length": str(self.size), "ETag": f'"{self.etag}"'})

    def get(self, url, stream=False, timeout=None, **kw):
        return _Stream(self.body)


def test_fetch_records_the_etag_check(tmp_path, monkeypatch):
    from astroledger.provenance import last_activity

    body = b"x" * 1000
    server = FakeObject(body, len(body), hashlib.md5(body).hexdigest())
    monkeypatch.setattr(cloud.requests, "Session", lambda: server)
    path = cloud.fetch("hst/public/abcd/x_flt.fits", tmp_path)
    assert path.name == "x_flt.fits" and path.read_bytes() == body
    extra = last_activity().extra
    assert extra["etag_check"] == "verified" and extra["size_bytes"] == 1000


def test_fetch_removes_a_truncated_multipart_download(tmp_path, monkeypatch):
    full = 20 * 1024 * 1024
    server = FakeObject(b"\0" * (15 * 1024 * 1024), full, "0" * 32 + "-3")
    monkeypatch.setattr(cloud.requests, "Session", lambda: server)
    with pytest.raises(OSError, match="received"):
        cloud.fetch("k/big.fits", tmp_path, ledger=cloud.DownloadLedger(budget_bytes=10**9))
    assert not (tmp_path / "big.fits").exists()


def test_fetch_rows_respects_budget(fake_s3, tmp_path):
    with pytest.raises(cloud.BudgetExceededError):
        cloud.fetch_rows(
            "k/x.fits", (0, 60), tmp_path, ledger=cloud.DownloadLedger(budget_bytes=5000)
        )


# --- MAST search (astroquery mocked) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("instrument", "filters", "expected"),
    [
        ("NIRCAM/IMAGE", "F444W;F405N", "F405N"),
        ("NIRCAM/IMAGE", "F405N;F444W", "F405N"),
        ("NIRCAM/IMAGE", "F356W", "F356W"),
        ("NIRCAM/IMAGE", "CLEAR;F090W", "F090W"),
        ("NIRISS/IMAGE", "CLEAR;F150W", "F150W"),
        ("MIRI/IMAGE", "F770W", "F770W"),
        ("NIRCAM/IMAGE", "F150W2;F444W", None),
        ("ACS/WFC", "F814W;CLEAR2L", "F814W"),
        ("ACS/WFC", "CLEAR1L;F606W", "F606W"),
    ],
)
def test_bandpass_from_mast(instrument, filters, expected):
    assert mast.bandpass_from_mast(instrument, filters) == expected


def test_search_keeps_masked_filters_unknown(monkeypatch):
    from astropy.table import MaskedColumn

    class FakeObservations:
        @staticmethod
        def query_criteria(**criteria):
            return Table(
                {
                    "obs_id": ["a", "b"],
                    "instrument_name": ["NIRCAM/IMAGE", "NIRCAM/IMAGE"],
                    "filters": MaskedColumn(["F444W;F405N", "x"], mask=[False, True]),
                }
            )

    monkeypatch.setattr(mast, "_observations", lambda: FakeObservations)
    assert list(mast.search("t")["bandpass"]) == ["F405N", ""]


def test_search_builds_criteria_and_resolves_bandpass(monkeypatch):
    calls = {}

    class FakeObservations:
        @staticmethod
        def query_criteria(**criteria):
            calls.update(criteria)
            return Table(
                {
                    "obs_id": ["jw02733-o001_t001_nircam_f405n-f444w"],
                    "target_name": ["NGC-3132"],
                    "instrument_name": ["NIRCAM/IMAGE"],
                    "filters": ["F444W;F405N"],
                    "calib_level": [3],
                    "extra_column": [1],
                }
            )

    monkeypatch.setattr(mast, "_observations", lambda: FakeObservations)
    table = mast.search("NGC 3132", instrument="NIRCAM/IMAGE", proposal_id=2733)
    assert calls["objectname"] == "NGC 3132" and calls["proposal_id"] == "2733"
    assert calls["obs_collection"] == "JWST" and calls["calib_level"] == 3
    assert list(table["bandpass"]) == ["F405N"]
    assert "extra_column" not in table.colnames


# --- live (run with: pytest -m remote) --------------------------------------------------------


@pytest.mark.remote
def test_live_list_program_2733_level3():
    items = cloud.list_keys("jwst/public/jw02733/L3/t/o001/")
    names = {i["key"].rsplit("/", 1)[-1] for i in items}
    assert "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits" in names


@pytest.mark.remote
def test_live_mast_search_ngc3132():
    table = mast.search("NGC 3132", instrument="NIRCAM/IMAGE", proposal_id="2733")
    assert "F405N" in set(table["bandpass"])


def test_ignored_range_is_still_counted(tmp_path, monkeypatch):
    class IgnoresRange(FakeS3):
        def get(self, url, headers=None, timeout=None, **kw):
            return _Response(self.data, status=200)

    source = tmp_path / "x.fits"
    source.write_bytes(b"\0" * 5000)
    monkeypatch.setattr(cloud.requests, "Session", lambda: IgnoresRange(source))
    ledger = cloud.DownloadLedger()
    with pytest.raises(OSError, match="returned 200"):
        cloud._get_range("k/x.fits", 0, 100, cloud.requests.Session(), ledger, "test")
    assert ledger.used_bytes == 5000
