"""Provenance records for processing steps.

Decorate a processing function with :func:`step` and every call is recorded as an
:class:`Activity` (W3C PROV terms): the input entities with checksums (files, images, arrays,
tables), the parameters, the outputs, the software environment (package versions, git commit)
and the outcome. Records go to the active :class:`ProvenanceStore` (SQLite), if one is set, and
can be written next to output files as JSON sidecars.

Example
-------
>>> @step("photometry.aperture", version="1")
... def measure(image, radius): ...
>>> with use_store(ProvenanceStore("lab.sqlite")):
...     result = measure(img, 3.0)
>>> last_activity().id
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import inspect
import json
import platform
import sqlite3
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
from astropy import units as u

__all__ = [
    "Activity",
    "ProvenanceStore",
    "describe",
    "environment",
    "last_activity",
    "sha256_file",
    "step",
    "use_store",
    "write_sidecar",
]

_PACKAGES = ("astroledger", "numpy", "astropy", "photutils", "reproject", "scipy", "astroquery")
_STORE: contextvars.ContextVar[ProvenanceStore | None] = contextvars.ContextVar(
    "store", default=None
)
_LAST: contextvars.ContextVar[Activity | None] = contextvars.ContextVar("last", default=None)


@dataclass
class Activity:
    """One execution of a processing step."""

    id: str
    name: str
    version: str
    function: str
    started: str
    ended: str
    status: str
    inputs: dict[str, Any]
    params: dict[str, Any]
    outputs: list[Any]
    environment: dict[str, Any]
    error: str | None = None
    duration_s: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True, default=str)


# --- hashing and description -----------------------------------------------------------------


def sha256_file(path: str | Path) -> str:
    """SHA-256 of a file, read in 1 MiB blocks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_array(array: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(f"{array.dtype.str}{array.shape}".encode())
    digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def describe(value: Any) -> dict[str, Any]:
    """Describe a value as a provenance entity (data) or a parameter.

    Returns a dict with ``"kind"``: ``image``, ``file``, ``array``, ``table`` (entities, with
    checksums) or ``param`` (with a JSON-safe ``value``).
    """
    from astroledger.core.product import ImageProduct

    if isinstance(value, ImageProduct):
        return {
            "kind": "image",
            "file": value.source.filename,
            "path": str(value.source.path),
            "sha256": value.source.sha256,
            "extension": list(value.source.extension),
            "bandpass": value.bandpass.key,
            "data_sha256": _sha256_array(np.asarray(value.data)),
        }
    if isinstance(value, Path) or (
        isinstance(value, str) and len(value) < 4096 and _is_file(value)
    ):
        path = Path(value)
        if path.is_file():
            return {
                "kind": "file",
                "path": str(path),
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        return {"kind": "param", "value": str(path)}
    if isinstance(value, np.ndarray) and value.ndim > 0 and value.size > 8:
        return {
            "kind": "array",
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "sha256": _sha256_array(value),
        }
    try:
        from astropy.table import Table

        if isinstance(value, Table):
            return {
                "kind": "table",
                "rows": len(value),
                "columns": list(value.colnames),
                "sha256": hashlib.sha256(_table_bytes(value)).hexdigest(),
            }
    except ImportError:  # pragma: no cover - astropy is a core dependency
        pass
    return {"kind": "param", "value": _jsonable(value)}


def _is_file(text: str) -> bool:
    try:
        return Path(text).is_file()
    except OSError:
        return False


def _table_bytes(table: Any) -> bytes:
    import io

    buffer = io.StringIO()
    table.write(buffer, format="ascii.ecsv")
    return buffer.getvalue().encode()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, u.Quantity):
        if value.isscalar:
            return str(value)
        return {"value": value.value.tolist(), "unit": str(value.unit)}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    text = str(value)
    return text if len(text) <= 500 else text[:500] + "..."


# --- environment -------------------------------------------------------------------------------


@functools.cache
def environment() -> dict[str, Any]:
    """Software environment of this process: Python, platform, package versions, git state."""
    packages = {}
    for name in _PACKAGES:
        with contextlib.suppress(metadata.PackageNotFoundError):
            packages[name] = metadata.version(name)
    env: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
    }
    source = Path(__file__).resolve().parents[3]
    if (source / ".git").exists():
        env["git"] = _git_state(source)
    return env


def _git_state(repo: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"error": f"git state unavailable: {exc}"}


# --- store -------------------------------------------------------------------------------------


class ProvenanceStore:
    """SQLite store of activities and the entities they used and generated."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS activities (
                    id TEXT PRIMARY KEY, name TEXT, version TEXT, function TEXT,
                    started TEXT, ended TEXT, status TEXT, record TEXT);
                CREATE TABLE IF NOT EXISTS entities (
                    activity_id TEXT REFERENCES activities(id), role TEXT, name TEXT,
                    kind TEXT, sha256 TEXT, path TEXT);
                CREATE INDEX IF NOT EXISTS entities_sha ON entities(sha256);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def add(self, activity: Activity) -> None:
        rows = [("input", k, v) for k, v in activity.inputs.items()]
        rows += [("output", str(i), v) for i, v in enumerate(activity.outputs)]
        with self._connect() as db:
            db.execute(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    activity.id,
                    activity.name,
                    activity.version,
                    activity.function,
                    activity.started,
                    activity.ended,
                    activity.status,
                    activity.to_json(),
                ),
            )
            db.executemany(
                "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (activity.id, role, name, e.get("kind"), e.get("sha256"), e.get("path"))
                    for role, name, e in rows
                    if e.get("kind") != "param"
                ],
            )

    def get(self, activity_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM activities WHERE id = ?", (activity_id,)
            ).fetchone()
        if row is None:
            raise KeyError(activity_id)
        return json.loads(row[0])

    def activities(self, name: str | None = None) -> list[dict[str, Any]]:
        query, args = "SELECT record FROM activities", ()
        if name:
            query, args = query + " WHERE name = ?", (name,)
        with self._connect() as db:
            return [json.loads(r[0]) for r in db.execute(query + " ORDER BY started", args)]

    def generated(self, sha256: str) -> list[dict[str, Any]]:
        """Activities that produced an entity with this checksum (its lineage, one step back)."""
        with self._connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT activity_id FROM entities WHERE role = 'output' AND sha256 = ?",
                    (sha256,),
                )
            ]
        return [self.get(i) for i in ids]


@contextlib.contextmanager
def use_store(store: ProvenanceStore | None) -> Iterator[ProvenanceStore | None]:
    """Record activities into ``store`` within the ``with`` block."""
    token = _STORE.set(store)
    try:
        yield store
    finally:
        _STORE.reset(token)


def last_activity() -> Activity | None:
    """The most recent activity recorded in this context (also when no store is active)."""
    return _LAST.get()


# --- decorator -----------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def step(name: str, version: str = "1") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Record each call of the decorated function as a provenance :class:`Activity`.

    Parameters
    ----------
    name : str
        Stable step name, e.g. ``"photometry.aperture"``.
    version : str
        Version of the step's algorithm; bump it when results can change.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            inputs, params = {}, {}
            for key, value in bound.arguments.items():
                described = describe(value)
                if described["kind"] == "param":
                    params[key] = described["value"]
                else:
                    inputs[key] = described
            activity = Activity(
                id=f"{time.time_ns():x}-{uuid.uuid4().hex[:8]}",
                name=name,
                version=version,
                function=f"{fn.__module__}.{fn.__qualname__}",
                started=_now(),
                ended="",
                status="running",
                inputs=inputs,
                params=params,
                outputs=[],
                environment=environment(),
            )
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                activity.status = "error"
                activity.error = "".join(traceback.format_exception_only(exc)).strip()
                _finish(activity, t0)
                raise
            results = result if isinstance(result, tuple) else (result,)
            activity.outputs = [describe(r) for r in results]
            activity.status = "ok"
            _finish(activity, t0)
            with contextlib.suppress(AttributeError, TypeError):
                result.provenance_id = activity.id
            return result

        wrapper.provenance_step = (name, version)  # type: ignore[attr-defined]
        return wrapper

    return decorate


def _finish(activity: Activity, t0: float) -> None:
    activity.ended = _now()
    activity.duration_s = round(time.perf_counter() - t0, 6)
    _LAST.set(activity)
    store = _STORE.get()
    if store is not None:
        store.add(activity)


def write_sidecar(output: str | Path, activity: Activity) -> Path:
    """Write ``<output>.prov.json`` describing how ``output`` was made.

    The output file's own checksum is added, so the sidecar can be matched to the file.
    """
    output = Path(output)
    record = json.loads(activity.to_json())
    record["output_file"] = {"path": output.name, "sha256": sha256_file(output)}
    sidecar = output.with_name(output.name + ".prov.json")
    sidecar.write_text(json.dumps(record, indent=2, sort_keys=True))
    return sidecar
