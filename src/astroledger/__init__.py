"""astroledger: a personal astrophysics laboratory.

Archive data, personal observations and evidence-graded interpretation, with every
measurement carrying its units, uncertainty and provenance.

The package is at Phase 0 (skeleton). The plan is in ``docs/lab-roadmap/``.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("astroledger")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
