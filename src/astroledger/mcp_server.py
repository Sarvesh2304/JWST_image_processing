"""Read-only MCP server: astroledger's tools for Claude (roadmap §27 task 19).

Tools:

- ``list_files``: FITS files under the data root.
- ``inspect``: the L1 fact sheet of an image (metadata and pixel statistics).
- ``explain``: graded L1/L2/L3 statements about an image and its sources.
- ``search``: MAST observations (needs network access to ``mast.stsci.edu``).

Every tool is read-only: nothing is written, downloaded or modified, and every path is resolved
inside the data root given at start-up, so a client cannot read files outside it.

Run it with ``astroledger mcp --root DATA_DIR`` (stdio, for Claude Code), or with ``--http``
(Streamable HTTP, default 127.0.0.1:8000/mcp). The server has no authentication of its own;
a Claude app remote connector reaches it from Anthropic's cloud, with OAuth or without
authentication. Until OAuth is added, expose it only for public data, behind an unguessable
``--http-path``. See docs/mcp.md.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["DataRootError", "build_server", "main"]

INSTRUCTIONS = (
    "astroledger reads astronomical FITS images under a configured data folder. Statements from "
    "'explain' carry evidence levels: L1 = measured, L2 = inferred from a measurement plus a "
    "stated rule or catalogue record, L3 = hypothesis with the test that would decide it. When "
    "you relay them, keep each statement's level and never present an L3 as fact. Identities "
    "come only from catalogue records quoted in the statements; do not add object names. The "
    "observer's target designation is a label for the pointing, not an identification."
)
FITS_SUFFIXES = (".fits", ".fit", ".fts", ".fits.gz")


class DataRootError(ValueError):
    """A path outside the data root, or one that does not exist."""


def _resolve(root: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``root``; refuse anything that escapes it."""
    path = (root / relative).resolve()  # follows links: a link out of the root is refused too
    if path != root and root not in path.parents:
        raise DataRootError(f"{relative!r} is outside the data root")
    if not path.is_file():
        raise DataRootError(f"{relative!r} is not a file under the data root")
    return path


def _redact(message: str, root: Path) -> str:
    """Replace the data root's host path (as a whole path component) with ``<data root>``."""
    if root == Path(root.anchor):  # a filesystem root: every absolute path would match
        return message
    pattern = re.compile(re.escape(str(root)) + r"(?=$|[/\\'\"\s:,)])")
    return pattern.sub("<data root>", message)


def _jsonable(value: Any) -> Any:
    """Plain JSON types for tool results (numpy scalars, paths, quantities)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float | int | str | bool) or value is None:
        return value
    return str(value)


def build_server(root: str | Path, *, explain_source_limit: int = 50):
    """Create the MCP server bound to a data root.

    Parameters
    ----------
    root : path
        Folder whose FITS files (and Gaia tables) the tools may read.
    explain_source_limit : int
        Maximum number of sources returned by ``explain`` in one call (the rest are summarised).
    """
    import functools

    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    from astroledger import __version__
    from astroledger.core.errors import ProductError

    root = Path(root).resolve()
    if not root.is_dir():
        raise DataRootError(f"data root {root} is not a directory")
    server = MCPServer(name="astroledger", version=__version__, instructions=INSTRUCTIONS)

    def anticipated(*kinds):
        """Report foreseeable failures to the model with their reason (as ToolError)."""

        def wrap(fn):
            @functools.wraps(fn)
            def inner(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except kinds as exc:
                    # the client sees paths relative to the root, never the host's layout
                    message = _redact(str(exc), root)
                    raise ToolError(f"{type(exc).__name__}: {message}") from exc

            return inner

        return wrap

    from astropy.io.registry import IORegistryError

    local_errors = (DataRootError, ProductError, OSError, ValueError, KeyError, IORegistryError)
    local = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    remote = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

    @server.tool(title="List FITS files", annotations=local, structured_output=True)
    @anticipated(*local_errors)
    def list_files(subfolder: str = "") -> dict[str, Any]:
        """List FITS images under the data root (paths relative to it, with sizes in MB)."""
        base = (root / subfolder).resolve()
        if base != root and root not in base.parents:
            raise DataRootError(f"{subfolder!r} is outside the data root")
        if not base.is_dir():
            raise DataRootError(f"{subfolder!r} is not a folder under the data root")
        files = sorted(
            p
            for p in base.rglob("*")
            if p.is_file()
            and p.name.lower().endswith(FITS_SUFFIXES)
            and root in p.resolve().parents  # links pointing outside the root are not offered
        )
        return {
            "root": root.name,  # the folder's name only: the host path is not disclosed
            "files": [
                {"path": str(p.relative_to(root)), "size_mb": round(p.stat().st_size / 1e6, 2)}
                for p in files
            ],
        }

    @server.tool(title="Inspect a FITS image", annotations=local, structured_output=True)
    @anticipated(*local_errors)
    def inspect(path: str, extver: int | None = None) -> dict[str, Any]:
        """Fact sheet (L1) of a FITS image: telescope, instrument, bandpass, observing mode,
        target designation, units, WCS footprint and pixel statistics.

        ``path`` is relative to the data root; ``extver`` picks one SCI extension of a
        multi-chip file (e.g. HST WFC3/UVIS, ACS/WFC).
        """
        from astroledger.inspect import fact_sheet
        from astroledger.io import open_image, open_images

        file = _resolve(root, path)
        images = [open_image(file, extver=extver)] if extver is not None else open_images(file)
        sheets = [fact_sheet(image) for image in images]
        return _jsonable(sheets[0] if len(sheets) == 1 else {"extensions": sheets})

    @server.tool(
        title="Explain an image with evidence levels", annotations=local, structured_output=True
    )
    @anticipated(*local_errors)
    def explain(
        path: str,
        gaia_table: str | None = None,
        simbad_table: str | None = None,
        extver: int | None = None,
        max_sources: int = 20,
    ) -> dict[str, Any]:
        """Graded statements about an image and its detected sources.

        Each statement has a level (L1 measured, L2 inferred with a cited rule or catalogue
        record, L3 hypothesis with a test) and its evidence. ``gaia_table`` is an ECSV of Gaia
        DR3 sources for the field, relative to the data root; without it no star is established
        (L2). ``simbad_table`` is an ECSV of SIMBAD records for the field (from
        ``archives.cds.simbad_cone``); without it no galaxy or nebula is established (L2).
        Sources with an L2 inference come first; at most ``max_sources`` are returned.
        """
        from astropy.table import QTable

        from astroledger.interpret import explain as run_explain
        from astroledger.io import open_image

        image = open_image(_resolve(root, path), extver=extver)
        gaia = QTable.read(_resolve(root, gaia_table)) if gaia_table else None
        records = QTable.read(_resolve(root, simbad_table)) if simbad_table else None
        result = run_explain(image, gaia=gaia, catalogue=records)
        limit = max(0, min(int(max_sources), explain_source_limit))
        ranked = result.ranked_sources()
        return _jsonable(
            {
                "summary": result.summary,
                "image": [s.to_dict() for s in result.image],
                "sources": [
                    {"label": k, "statements": [s.to_dict() for s in v]} for k, v in ranked[:limit]
                ],
                "sources_not_shown": max(0, len(ranked) - limit),
                "notes": result.notes,
            }
        )

    @server.tool(title="Search MAST observations", annotations=remote, structured_output=True)
    @anticipated(Exception)  # network and archive failures are expected here
    def search(
        target: str,
        radius_arcmin: float = 3.0,
        collection: str = "JWST",
        instrument: str | None = None,
        proposal_id: str | None = None,
        max_rows: int = 50,
    ) -> dict[str, Any]:
        """Search MAST for observations around a target name or 'RA DEC' in degrees.

        Returns one row per observation with the true bandpass resolved from the optical
        elements. Needs network access to mast.stsci.edu.
        """
        from astropy import units as u
        from astropy.coordinates import SkyCoord

        from astroledger.archives.mast import search as mast_search

        parts = target.split()
        where: str | SkyCoord = target
        if len(parts) == 2:
            try:
                where = SkyCoord(float(parts[0]) * u.deg, float(parts[1]) * u.deg)
            except ValueError:
                where = target
        table = mast_search(
            where,
            radius=radius_arcmin * u.arcmin,
            collection=collection,
            instrument=instrument,
            proposal_id=proposal_id,
        )
        rows = [
            {name: _jsonable(row[name]) for name in table.colnames}
            for row in table[: max(0, int(max_rows))]
        ]
        return {"n_total": len(table), "rows": rows}

    return server


def main(
    root: str | os.PathLike,
    *,
    http: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
):
    """Run the server over stdio (default) or Streamable HTTP at ``http://host:port{path}``."""
    server = build_server(root)
    if http:
        server.run("streamable-http", host=host, port=port, streamable_http_path=path)
    else:
        server.run("stdio")
