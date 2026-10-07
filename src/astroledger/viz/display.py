"""Display images and colour composites without altering the data.

Everything here builds display copies. Science arrays are never clipped, filled or stretched in
place; stretches are :class:`astropy.visualization.ImageNormalize` objects applied at render time.

Colour composites follow two conventions:

- **Chromatic ordering.** Channels are sorted by wavelength: shortest -> blue, longest -> red.
- **Common grid.** Every channel is reprojected onto one reference WCS before stacking, so
  images with different pixel grids (e.g. NIRCam short- and long-wavelength) line up on the sky.

A composite is "representative colour": channel scalings are display choices and are recorded
in the returned :class:`RGBComposite` so the figure can state them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from astropy.visualization import (
    AsinhStretch,
    BaseStretch,
    ImageNormalize,
    LinearStretch,
    LogStretch,
    PercentileInterval,
    SqrtStretch,
)
from astropy.wcs import WCS

from astroledger.core.mode import require_imaging
from astroledger.core.product import ImageProduct

__all__ = ["RGBComposite", "display_norm", "make_rgb", "show", "show_rgb"]

_STRETCHES = {
    "asinh": lambda a: AsinhStretch(a),
    "sqrt": lambda a: SqrtStretch(),
    "log": lambda a: LogStretch(1.0 / a if a else 1000.0),
    "linear": lambda a: LinearStretch(),
}


def _display_values(image: ImageProduct | np.ndarray) -> np.ndarray:
    """Float copy with masked or non-finite pixels set to NaN (the input is not modified)."""
    data = image.data if isinstance(image, ImageProduct) else np.asarray(image)
    values = np.array(data, dtype=float, copy=True)
    mask = getattr(image, "mask", None)
    if mask is not None:
        values[mask] = np.nan
    values[~np.isfinite(values)] = np.nan
    return values


def _stretch(name: str, a: float) -> BaseStretch:
    try:
        return _STRETCHES[name](a)
    except KeyError:
        raise ValueError(f"unknown stretch {name!r}; choose from {sorted(_STRETCHES)}") from None


def display_norm(
    image: ImageProduct | np.ndarray,
    *,
    percentile: float = 99.5,
    stretch: str = "asinh",
    a: float = 0.1,
) -> ImageNormalize:
    """Display normalisation computed from the unmasked, finite pixels.

    Parameters
    ----------
    image : ImageProduct or numpy.ndarray
        Image to scale. Masked pixels are excluded from the interval.
    percentile : float, default 99.5
        Central percentage of pixel values mapped onto the colour range.
    stretch : {"asinh", "sqrt", "log", "linear"}
        Display stretch.
    a : float, default 0.1
        Softening parameter of the asinh (or log) stretch.
    """
    values = _display_values(image)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("no finite, unmasked pixels to scale")
    return ImageNormalize(
        finite, interval=PercentileInterval(percentile), stretch=_stretch(stretch, a)
    )


def _caption(image: ImageProduct, extra: str = "") -> str:
    name, ver = image.source.extension
    parts = [
        f"{image.source.filename} [{name},{ver}]",
        image.bandpass.key,
        f"CAL_VER {image.keyword('CAL_VER')}" if image.keyword("CAL_VER") else "",
        f"program {image.keyword('PROGRAM')}" if image.keyword("PROGRAM") else "",
    ]
    text = " · ".join(p for p in parts if p)
    return f"{text}\n{extra}" if extra else text


def show(
    image: ImageProduct,
    *,
    ax: plt.Axes | None = None,
    norm: ImageNormalize | None = None,
    cmap: str = "inferno",
    title: str | None = None,
    colorbar: bool = True,
    caption: bool = True,
) -> plt.Figure:
    """Plot an image with sky axes (when it has a WCS), masked pixels in grey, and a caption.

    The caption names the file, extension, bandpass and calibration version, and states that the
    stretch is a display choice.
    """
    norm = norm or display_norm(image)
    values = _display_values(image)
    if ax is None:
        fig = plt.figure(figsize=(7.5, 7))
        ax = fig.add_subplot(projection=image.wcs) if image.wcs is not None else fig.add_subplot()
    fig = ax.figure
    colours = plt.get_cmap(cmap).with_extremes(bad="#3a3f47")
    shown = ax.imshow(values, origin="lower", cmap=colours, norm=norm)
    if image.wcs is not None and hasattr(ax, "coords"):
        ax.coords[0].set_axislabel("RA")
        ax.coords[1].set_axislabel("Dec")
        ax.coords.grid(color="white", alpha=0.2, linestyle=":")
    else:
        ax.set_xlabel("x (pixel)")
        ax.set_ylabel("y (pixel)")
    ax.set_title(
        title
        or f"{image.keyword('TARGPROP') or image.keyword('TARGNAME') or ''} "
        f"{image.bandpass.name or ''}".strip(),
        fontsize=10,
    )
    if colorbar:
        bar = fig.colorbar(shown, ax=ax, fraction=0.046, pad=0.04)
        bar.set_label(str(image.unit) if image.unit is not None else "unit unknown")
    if caption:
        stretch = type(norm.stretch).__name__.replace("Stretch", "").lower()
        fig.text(
            0.01,
            0.005,
            _caption(
                image,
                f"display: {stretch} stretch (display only); "
                f"grey = masked ({image.n_masked / image.data.size:.1%})",
            ),
            fontsize=6.5,
            color="0.35",
            va="bottom",
        )
    return fig


@dataclass(frozen=True)
class RGBComposite:
    """A representative-colour composite and how it was made.

    Attributes
    ----------
    rgb : numpy.ndarray
        Float array of shape (ny, nx, 3) with values in [0, 1].
    wcs : astropy.wcs.WCS
        WCS of the common grid.
    channels : tuple of dict
        One entry per colour (``"red"``, ``"green"``, ``"blue"``) with the bandpass key, nominal
        wavelength, source file and the display scaling used.
    method : str
        Human-readable description of the reprojection and scaling.
    """

    rgb: np.ndarray
    wcs: WCS
    channels: tuple[dict, ...]
    method: str


def _wavelength_um(image: ImageProduct) -> float:
    band = image.bandpass
    value = band.pivot if band.pivot is not None else band.nominal_wavelength
    if value is None:
        raise ValueError(f"{image.source.filename}: bandpass wavelength unknown; cannot order")
    return float(value.to_value("um"))


def make_rgb(
    images: Sequence[ImageProduct],
    *,
    reference: ImageProduct | None = None,
    percentile: float = 99.5,
    stretch: str = "asinh",
    a: float = 0.1,
) -> RGBComposite:
    """Build a chromatically ordered colour composite on a common sky grid.

    Parameters
    ----------
    images : sequence of three ImageProduct
        Any order; they are sorted by wavelength (pivot if known, else nominal).
    reference : ImageProduct, optional
        Image whose WCS and shape define the output grid. Default: the longest-wavelength image.
    percentile, stretch, a
        Per-channel display scaling (see :func:`display_norm`), applied after reprojection.
    """
    from reproject import reproject_interp

    if len(images) != 3:
        raise ValueError(f"need exactly 3 images, got {len(images)}")
    for img in images:
        require_imaging(img, "colour composite")
    if any(img.wcs is None for img in images):
        raise ValueError("all images need a celestial WCS to be aligned")
    ordered = sorted(images, key=_wavelength_um)  # blue, green, red
    ref = reference or ordered[-1]
    shape = ref.data.shape

    channels = []
    planes = []
    for colour, img in zip(("blue", "green", "red"), ordered, strict=True):
        values = _display_values(img)
        if img is ref:
            plane = values
        else:
            plane, _ = reproject_interp((values, img.wcs), ref.wcs, shape_out=shape)
        norm = display_norm(plane, percentile=percentile, stretch=stretch, a=a)
        planes.append(np.nan_to_num(np.clip(norm(plane, clip=True).filled(np.nan), 0, 1), nan=0))
        channels.append(
            {
                "colour": colour,
                "bandpass": img.bandpass.key,
                "wavelength_um": _wavelength_um(img),
                "file": img.source.filename,
                "scale": f"{stretch} (a={a}), {percentile}% interval",
                "interval": (float(norm.vmin), float(norm.vmax)),
            }
        )
    rgb = np.dstack([planes[2], planes[1], planes[0]])
    method = (
        f"reprojected onto the grid of {ref.source.filename} with reproject_interp; "
        f"each channel scaled independently ({stretch}, {percentile}% interval) for display"
    )
    return RGBComposite(rgb=rgb, wcs=ref.wcs, channels=tuple(reversed(channels)), method=method)


def show_rgb(composite: RGBComposite, *, title: str = "", caption: str = "") -> plt.Figure:
    """Plot a colour composite with sky axes and a legend stating the channel mapping."""
    fig = plt.figure(figsize=(7.5, 7.3))
    ax = fig.add_subplot(projection=composite.wcs)
    ax.imshow(composite.rgb, origin="lower")
    ax.coords[0].set_axislabel("RA")
    ax.coords[1].set_axislabel("Dec")
    ax.coords.grid(color="white", alpha=0.15, linestyle=":")
    ax.set_title(title, fontsize=10)
    mapping = "   ".join(
        f"{c['colour'][0].upper()}: {c['bandpass'].split('/')[-1]} ({c['wavelength_um']:.2f} µm)"
        for c in composite.channels
    )
    footer = f"{mapping}\nrepresentative colour · {composite.method}"
    if caption:
        footer += f"\n{caption}"
    fig.text(0.01, 0.005, footer, fontsize=6.5, color="0.35", va="bottom")
    return fig
