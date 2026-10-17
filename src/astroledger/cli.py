"""Command-line interface: ``astroledger <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from astroledger import __version__

__all__ = ["main"]


def _inspect(args: argparse.Namespace) -> int:
    from astroledger.core.errors import ProductError
    from astroledger.inspect import fact_sheet, format_fact_sheet
    from astroledger.io import open_image, open_images

    try:
        images = (
            [open_image(args.file, extver=args.extver)]
            if args.extver is not None
            else open_images(args.file)
        )
    except (ProductError, OSError) as exc:
        print(f"astroledger inspect: {exc}", file=sys.stderr)
        return 2
    sheets = [fact_sheet(img) for img in images]
    if args.json:
        print(json.dumps(sheets if len(sheets) > 1 else sheets[0], indent=2, default=str))
    else:
        print("\n\n".join(format_fact_sheet(s) for s in sheets))
    return 0


def _explain(args: argparse.Namespace) -> int:
    from astropy.table import QTable

    from astroledger.core.errors import ProductError
    from astroledger.interpret import explain, format_explanation
    from astroledger.io import open_image

    try:
        image = open_image(args.file, extver=args.extver)
        gaia = QTable.read(args.gaia) if args.gaia else None
        catalogue = QTable.read(args.catalogue) if args.catalogue else None
        result = explain(image, gaia=gaia, catalogue=catalogue)
    except (ProductError, OSError) as exc:
        print(f"astroledger explain: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(format_explanation(result, limit=args.limit))
    return 0


def _mcp(args: argparse.Namespace) -> int:
    try:
        from astroledger.mcp_server import main as serve
    except ImportError:  # pragma: no cover - depends on the optional extra
        print('astroledger mcp: install the "mcp" extra: pip install -e ".[mcp]"', file=sys.stderr)
        return 2
    serve(args.root, http=args.http, host=args.host, port=args.port, path=args.http_path)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``astroledger`` command."""
    parser = argparse.ArgumentParser(prog="astroledger", description=__doc__)
    parser.add_argument("--version", action="version", version=f"astroledger {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser(
        "inspect", help="print a fact sheet (metadata + pixel measurements) for a FITS image"
    )
    inspect.add_argument("file", help="FITS file")
    inspect.add_argument(
        "--extver", type=int, help="EXTVER of the SCI extension (multi-chip files)"
    )
    inspect.add_argument("--json", action="store_true", help="machine-readable output")
    inspect.set_defaults(handler=_inspect)

    explain = commands.add_parser(
        "explain", help="graded statements (L1/L2/L3) about an image and its sources"
    )
    explain.add_argument("file", help="FITS image (direct imaging only)")
    explain.add_argument("--extver", type=int, help="EXTVER of the SCI extension")
    explain.add_argument("--gaia", help="Gaia DR3 table (ECSV) covering the field")
    explain.add_argument(
        "--catalogue", help="SIMBAD records (ECSV from archives.cds.simbad_cone) for the field"
    )
    explain.add_argument("--limit", type=int, default=20, help="sources shown in text output")
    explain.add_argument("--json", action="store_true", help="machine-readable output")
    explain.set_defaults(handler=_explain)

    mcp = commands.add_parser(
        "mcp", help="run the read-only MCP server (stdio by default) over a data folder"
    )
    mcp.add_argument("--root", default="data", help="folder the tools may read (default: data)")
    mcp.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    mcp.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1)")
    mcp.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")
    mcp.add_argument("--http-path", default="/mcp", help="HTTP endpoint path (default /mcp)")
    mcp.set_defaults(handler=_mcp)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
