"""Read MAST's public copy of JWST/HST data on AWS (``s3://stpubdata``) over HTTPS.

Three things are possible without downloading whole products:

- **List** files of a program (S3 ``ListObjectsV2``).
- **Fetch** a whole file, verified against its S3 ETag.
- **Cut out** a band of rows from a large FITS image with HTTP range requests. The cutout is
  written as a new FITS file whose headers are copied verbatim from the archive product, with
  ``CRPIXn`` shifted so the WCS stays correct, and keywords recording the source and offsets.

Every byte transferred is counted by a :class:`DownloadLedger`, which can enforce a budget.

Bucket layout (verified by listing ``jwst/public/jw02733/``):

- per-exposure products: ``jwst/public/jw{PPPPP}/jw{PPPPPOOOVVV}/<file>``
- Stage-3 target associations: ``jwst/public/jw{PPPPP}/L3/t/o{OOO}/<file>``
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits

from astroledger.provenance import step

__all__ = [
    "BUCKET_URL",
    "BudgetExceededError",
    "DownloadLedger",
    "RemoteFile",
    "RemoteHDU",
    "fetch",
    "fetch_rows",
    "jwst_key",
    "list_keys",
    "remote_hdus",
    "verify_etag",
]

BUCKET_URL = "https://stpubdata.s3.amazonaws.com"
_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_BLOCK = 2880
_DTYPES = {8: ">u1", 16: ">i2", 32: ">i4", 64: ">i8", -32: ">f4", -64: ">f8"}
_EXPOSURE = re.compile(r"^jw(\d{5})(\d{3})(\d{3})_")
_LEVEL3_TARGET = re.compile(r"^jw(\d{5})-o(\d{3})_t\d{3}_")


class BudgetExceededError(RuntimeError):
    """A transfer would exceed the download budget."""


@dataclass
class DownloadLedger:
    """Counts bytes transferred and optionally enforces a budget.

    Parameters
    ----------
    budget_bytes : int, optional
        Maximum total bytes. Requests that would exceed it raise :class:`BudgetExceededError`
        *before* any data is transferred.
    log_path : path, optional
        Tab-separated log of every transfer (bytes, url, range, purpose).
    """

    budget_bytes: int | None = None
    log_path: Path | None = None
    used_bytes: int = 0
    entries: list[tuple[int, str, str, str]] = field(default_factory=list)

    def reserve(self, n_bytes: int, what: str) -> None:
        if self.budget_bytes is not None and self.used_bytes + n_bytes > self.budget_bytes:
            raise BudgetExceededError(
                f"{what}: {n_bytes / 1e6:.1f} MB would exceed the budget "
                f"({self.used_bytes / 1e6:.1f} of {self.budget_bytes / 1e6:.1f} MB used)"
            )

    def record(self, n_bytes: int, url: str, byte_range: str, purpose: str) -> None:
        self.used_bytes += n_bytes
        self.entries.append((n_bytes, url, byte_range, purpose))
        if self.log_path is not None:
            new = not Path(self.log_path).exists()
            with Path(self.log_path).open("a", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t")
                if new:
                    writer.writerow(["bytes", "url", "range", "purpose"])
                writer.writerow([n_bytes, url, byte_range, purpose])


def _url(key: str) -> str:
    return f"{BUCKET_URL}/{key.lstrip('/')}"


def jwst_key(filename: str) -> str:
    """S3 key of a JWST product in ``stpubdata`` from its archive filename.

    Supports per-exposure products (``jw02733002001_02101_00001_mirimage_cal.fits``) and
    Stage-3 target associations (``jw02733-o001_t001_nircam_clear-f090w_i2d.fits``).

    Raises
    ------
    ValueError
        For name patterns whose bucket location has not been verified (e.g. candidate ``-c``
        associations).
    """
    name = Path(filename).name
    if match := _EXPOSURE.match(name):
        program = match.group(1)
        return f"jwst/public/jw{program}/{name[:13]}/{name}"
    if match := _LEVEL3_TARGET.match(name):
        program, obs = match.groups()
        return f"jwst/public/jw{program}/L3/t/o{obs}/{name}"
    raise ValueError(f"{name}: bucket location not known for this product name pattern")


def list_keys(prefix: str, *, session: requests.Session | None = None) -> list[dict]:
    """List objects under ``prefix`` (all pages). Each item: ``key``, ``size``, ``etag``."""
    http = session or requests.Session()
    items, token = [], None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        response = http.get(BUCKET_URL + "/", params=params, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for item in root.findall("s3:Contents", _S3_NS):
            items.append(
                {
                    "key": item.findtext("s3:Key", namespaces=_S3_NS),
                    "size": int(item.findtext("s3:Size", namespaces=_S3_NS)),
                    "etag": item.findtext("s3:ETag", namespaces=_S3_NS).strip('"'),
                }
            )
        if root.findtext("s3:IsTruncated", namespaces=_S3_NS) != "true":
            return items
        token = root.findtext("s3:NextContinuationToken", namespaces=_S3_NS)


def verify_etag(path: str | Path, etag: str) -> str:
    """Check a downloaded file against its S3 ETag.

    Returns ``"verified"``, ``"mismatch"`` or ``"unverifiable"`` (multipart upload whose part
    size cannot be inferred). Single-part ETags are the file's MD5; multipart ETags are the MD5 of
    the concatenated part MD5s, suffixed with ``-<parts>``.
    """
    path, etag = Path(path), etag.strip('"')
    if "-" not in etag:
        return "verified" if _md5(path) == etag else "mismatch"
    digest, parts = etag.split("-")
    size = path.stat().st_size
    for part_mib in (8, 16, 5, 10, 15, 32, 50, 64, 100, 128, 256, 512):
        part = part_mib * 1024 * 1024
        if math.ceil(size / part) != int(parts):
            continue
        md5s = b""
        with path.open("rb") as stream:
            while chunk := stream.read(part):
                md5s += hashlib.md5(chunk).digest()
        if hashlib.md5(md5s).hexdigest() == digest:
            return "verified"
    if int(parts) == 1:  # part size irrelevant: MD5 of the single part's MD5
        return (
            "verified"
            if hashlib.md5(bytes.fromhex(_md5(path))).hexdigest() == digest
            else "mismatch"
        )
    return "unverifiable"


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _head(key: str, http: requests.Session) -> tuple[int, str]:
    response = http.head(_url(key), timeout=60)
    response.raise_for_status()
    return int(response.headers["Content-Length"]), response.headers.get("ETag", "").strip('"')


def _get_range(
    key: str, start: int, stop: int, http: requests.Session, ledger: DownloadLedger, purpose: str
) -> bytes:
    """Bytes ``[start, stop)`` of an object."""
    n = stop - start
    ledger.reserve(n, f"{key} [{start}:{stop}]")
    response = http.get(_url(key), headers={"Range": f"bytes={start}-{stop - 1}"}, timeout=300)
    response.raise_for_status()
    if response.status_code != 206 or len(response.content) != n:
        raise OSError(
            f"{key}: range request returned {response.status_code}, {len(response.content)} bytes"
        )
    ledger.record(n, _url(key), f"{start}-{stop - 1}", purpose)
    return response.content


class RemoteFile(io.RawIOBase):
    """Read-only, seekable file over HTTP range requests, for libraries such as pyarrow.

    Every byte read is recorded in ``ledger``; reads that would exceed its budget raise
    :class:`BudgetExceededError` before any transfer.
    """

    def __init__(
        self,
        key: str,
        *,
        ledger: DownloadLedger | None = None,
        session: requests.Session | None = None,
        purpose: str = "range read",
    ) -> None:
        self.key, self.purpose = key, purpose
        self._http = session or requests.Session()
        self._ledger = ledger or DownloadLedger()
        self.size, self.etag = _head(key, self._http)
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def read(self, size: int = -1) -> bytes:
        stop = self.size if size is None or size < 0 else min(self.size, self._pos + size)
        if stop <= self._pos:
            return b""
        data = _get_range(self.key, self._pos, stop, self._http, self._ledger, self.purpose)
        self._pos = stop
        return data

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


@step("archives.cloud.fetch", version="1")
def fetch(key: str, dest_dir: str | Path, *, ledger: DownloadLedger | None = None) -> Path:
    """Download a whole object, keeping its archive filename, and verify its ETag.

    Raises
    ------
    OSError
        If the downloaded file does not match the ETag.
    """
    http, ledger = requests.Session(), ledger or DownloadLedger()
    size, etag = _head(key, http)
    ledger.reserve(size, key)
    dest = Path(dest_dir) / Path(key).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with http.get(_url(key), stream=True, timeout=300) as response:
        response.raise_for_status()
        with dest.open("wb") as stream:
            for chunk in response.iter_content(1 << 20):
                stream.write(chunk)
    ledger.record(dest.stat().st_size, _url(key), "full", "fetch")
    status = verify_etag(dest, etag)
    if status == "mismatch":
        dest.unlink()
        raise OSError(f"{key}: download does not match its ETag {etag}")
    return dest


@dataclass(frozen=True)
class RemoteHDU:
    """Location of one HDU inside a remote FITS file."""

    index: int
    name: str
    ver: int
    header: fits.Header
    data_start: int
    data_size: int


def _data_size(header: fits.Header) -> int:
    naxis = header.get("NAXIS", 0)
    if naxis == 0:
        return 0
    n = abs(header["BITPIX"]) // 8
    for axis in range(1, naxis + 1):
        n *= header[f"NAXIS{axis}"]
    return header.get("GCOUNT", 1) * (n + header.get("PCOUNT", 0))


def remote_hdus(
    key: str,
    *,
    stop_after: set[str] | None = None,
    ledger: DownloadLedger | None = None,
    session: requests.Session | None = None,
) -> list[RemoteHDU]:
    """Read the headers of a remote FITS file without downloading its data.

    Parameters
    ----------
    stop_after : set of str, optional
        Stop once all these ``EXTNAME`` values have been seen (saves requests).
    """
    http, ledger = session or requests.Session(), ledger or DownloadLedger()
    total, _ = _head(key, http)
    hdus, offset, index = [], 0, 0
    wanted = set(stop_after or ())
    while offset < total:
        raw = b""
        while b"END" + b" " * 77 not in _cards(raw):
            chunk_stop = min(offset + len(raw) + 10 * _BLOCK, total)
            raw += _get_range(key, offset + len(raw), chunk_stop, http, ledger, "header")
        end = _cards(raw).index(b"END" + b" " * 77)
        header_len = (end // _BLOCK + 1) * _BLOCK
        header = fits.Header.fromstring(raw[:header_len].decode("ascii"))
        name = header.get("EXTNAME", "PRIMARY").strip().upper()
        size = _data_size(header)
        hdus.append(
            RemoteHDU(index, name, header.get("EXTVER", 1), header, offset + header_len, size)
        )
        offset += header_len + math.ceil(size / _BLOCK) * _BLOCK
        index += 1
        wanted.discard(name)
        if stop_after and not wanted:
            break
    return hdus


def _cards(raw: bytes) -> bytes:
    """Header bytes truncated to whole 80-character cards (END must start a card)."""
    usable = len(raw) - len(raw) % 80
    cards = raw[:usable]
    for i in range(0, usable, 80):
        if cards[i : i + 80] == b"END" + b" " * 77:
            return cards[: i + 80]
    return b""


@step("archives.cloud.fetch_rows", version="1")
def fetch_rows(
    key: str,
    rows: tuple[int, int],
    dest_dir: str | Path,
    *,
    extensions: tuple[str, ...] = ("SCI", "ERR"),
    cols: tuple[int, int] | None = None,
    ledger: DownloadLedger | None = None,
) -> Path:
    """Write a cutout of rows ``[y0, y1)`` (and optionally columns) of a remote FITS image.

    Only the requested rows of the requested extensions are transferred. Headers are copied
    verbatim, with ``CRPIXn`` shifted by the cutout offsets and these keywords added:
    ``CUTSRC`` (archive filename), ``CUTX0``/``CUTY0`` (0-based offsets of the cutout in the
    original), ``CUTETAG`` (S3 ETag of the source). Pixel values are not modified.

    Returns
    -------
    pathlib.Path
        ``<archive stem>_rows<y0>-<y1>[_cols<x0>-<x1>].fits`` in ``dest_dir``: a derived file,
        named so it cannot be mistaken for the archive product.
    """
    http, ledger = requests.Session(), ledger or DownloadLedger()
    y0, y1 = rows
    _, etag = _head(key, http)
    hdus = remote_hdus(key, stop_after=set(extensions), ledger=ledger, session=http)
    primary = hdus[0].header.copy()
    primary["CUTSRC"] = (Path(key).name, "source archive file")
    primary["CUTETAG"] = (etag, "S3 ETag of source")
    out = [fits.PrimaryHDU(header=primary)]
    for name in extensions:
        hdu = next((h for h in hdus if h.name == name), None)
        if hdu is None:
            raise ValueError(f"{key}: no {name} extension")
        header = hdu.header
        nx, ny = header["NAXIS1"], header["NAXIS2"]
        if header["NAXIS"] != 2 or not 0 <= y0 < y1 <= ny:
            raise ValueError(f"{name}: rows {rows} outside 2-D image of {ny} rows")
        x0, x1 = cols if cols is not None else (0, nx)
        dtype = np.dtype(_DTYPES[header["BITPIX"]])
        row_bytes = nx * dtype.itemsize
        start = hdu.data_start + y0 * row_bytes
        raw = _get_range(
            key, start, start + (y1 - y0) * row_bytes, http, ledger, f"{name} rows {y0}-{y1}"
        )
        data = np.frombuffer(raw, dtype=dtype).reshape(y1 - y0, nx)[:, x0:x1]
        bscale, bzero = header.get("BSCALE", 1), header.get("BZERO", 0)
        if (bscale, bzero) == (1, 2**31) and header["BITPIX"] == 32:
            data = (data.astype(np.int64) + 2**31).astype(np.uint32)
        elif (bscale, bzero) != (1, 0):
            data = data * bscale + bzero
        else:
            data = data.astype(dtype.newbyteorder("="))
        new = header.copy()
        for card in ("BSCALE", "BZERO"):
            new.remove(card, ignore_missing=True)
        for keyword in list(new.keys()):
            if re.fullmatch(r"CRPIX1[A-Z]?", keyword):
                new[keyword] -= x0
            elif re.fullmatch(r"CRPIX2[A-Z]?", keyword):
                new[keyword] -= y0
        new["CUTX0"] = (x0, "0-based column offset of cutout in source image")
        new["CUTY0"] = (y0, "0-based row offset of cutout in source image")
        out.append(fits.ImageHDU(data=data, header=new, name=name))
    stem = Path(key).name.removesuffix(".fits")
    suffix = f"_rows{y0}-{y1}" + (f"_cols{cols[0]}-{cols[1]}" if cols else "")
    dest = Path(dest_dir) / f"{stem}{suffix}.fits"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fits.HDUList(out).writeto(dest, overwrite=True)
    return dest
