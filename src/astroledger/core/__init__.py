"""Core data types shared by every part of astroledger."""

from astroledger.core.errors import AmbiguousProductError, ProductError, UnsupportedProductError
from astroledger.core.product import ImageProduct, SourceInfo

__all__ = [
    "AmbiguousProductError",
    "ImageProduct",
    "ProductError",
    "SourceInfo",
    "UnsupportedProductError",
]
