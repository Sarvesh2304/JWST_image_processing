"""Exceptions raised when a data product cannot be used as requested."""


class ProductError(Exception):
    """Base class for problems with a data product."""


class UnsupportedProductError(ProductError):
    """The file is valid but not a product this reader handles (e.g. 4-D ramps, spectra).

    Raised instead of guessing, so unsupported data are never processed as if they were images.
    """


class AmbiguousProductError(ProductError):
    """The file holds several candidate images (e.g. HST two-chip ``SCI,1``/``SCI,2``).

    The caller must choose one explicitly; the reader never picks silently.
    """
