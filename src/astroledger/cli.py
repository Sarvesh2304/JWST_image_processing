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

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
