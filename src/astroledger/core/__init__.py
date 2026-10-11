"""Core data types shared by every part of astroledger."""

from astroledger.core.bandpass import Bandpass
from astroledger.core.errors import AmbiguousProductError, ProductError, UnsupportedProductError
from astroledger.core.mode import ModeCategory, ObservingMode, observing_mode, require_imaging
from astroledger.core.product import ImageProduct, SourceInfo

__all__ = [
    "AmbiguousProductError",
    "Bandpass",
    "ImageProduct",
    "ModeCategory",
    "ObservingMode",
    "ProductError",
    "SourceInfo",
    "UnsupportedProductError",
    "observing_mode",
    "require_imaging",
]
