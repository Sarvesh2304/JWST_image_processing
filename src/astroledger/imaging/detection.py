"""Source detection with a controlled false-positive rate.

Method (photutils conventions):

1. **Background.** ``Background2D`` with 3-sigma clipped medians in ``box_size`` meshes, median
   filtered. Two passes: sources found in the first pass are masked (dilated) when the
   background is re-estimated, so bright sources do not bias it.
2. **Matched filter.** The background-subtracted image is convolved with a normalised Gaussian
   kernel of FWHM ``kernel_fwhm`` pixels (about the PSF FWHM).
3. **Threshold.** ``nsigma`` times the background RMS of the *unconvolved* image, per pixel.
   Smoothing lowers the noise of the convolved image, so this threshold is conservative. Using
   the convolved image's own RMS instead would inflate false detections (see
   ``tests/science/test_legacy_defects.py``).
4. **Segmentation.** At least ``n_pixels`` connected pixels above threshold. Deblending is
   optional and off by default (as in the JWST pipeline): on JWST data it splits bright stars'
   wings and diffraction spikes into many spurious sources.
5. **Bright-neighbour flag.** ``near_bright_source`` marks detections within
   ``bright_radius`` pixels of a source more than ``bright_ratio`` times brighter: candidate
   PSF wings or diffraction-spike fragments. It is a heuristic flag, not a removal, and it
   cannot catch spikes from bright stars that lie outside the image.
6. **False-positive estimate.** The same detection run on the negated background-subtracted
   image. Real sources are positive, so detections there estimate how many positive
   detections are noise.

Measurements come from the unconvolved data, with ERR (when present) as the per-pixel error.
Pixel values of the input product are never modified.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from astropy import units as u
from astropy.convolution import Gaussian2DKernel, convolve
from astropy.stats import SigmaClip, gaussian_fwhm_to_sigma
from astropy.table import QTable
from photutils.background import Background2D, MedianBackground
from photutils.segmentation import SegmentationImage, SourceCatalog, deblend_sources, detect_sources
from photutils.utils.exceptions import NoDetectionsWarning
from scipy import ndimage

from astroledger.core.product import ImageProduct
from astroledger.photometry.aperture import flux_conversion
from astroledger.provenance import step

__all__ = ["Detections", "detect"]


@dataclass
class Detections:
    """Result of :func:`detect`.

    Attributes
    ----------
    catalog : astropy.table.QTable
        One row per source: ``label, x, y, ra, dec, area, semimajor_axis, semiminor_axis,
        ellipticity, fwhm, flux, flux_err, snr, near_bright_source``. Flux in Jy when the image
        is flux-calibrated.
    segmentation : photutils.segmentation.SegmentationImage or None
        Segment labels (None when nothing was detected).
    background, background_rms : numpy.ndarray
        2-D background model and its RMS, in the image's units.
    n_false_estimate : int or None
        Detections in the negated image with the same settings (None if not run).
    negative_segmentation : photutils.segmentation.SegmentationImage or None
        Segments found in the negated image, to see where false positives arise.
    params : dict
        Settings used.
    notes : list of str
        What the user should know when interpreting the catalogue.
    """

    catalog: QTable
    segmentation: SegmentationImage | None
    background: np.ndarray
    background_rms: np.ndarray
    n_false_estimate: int | None
    negative_segmentation: SegmentationImage | None
    params: dict
    notes: list[str] = field(default_factory=list)

    def false_positive_positions(self) -> np.ndarray:
        """Pixel positions ``(x, y)`` of the negative-image detections, shape (N, 2).

        Map these to see *where* noise or background-model residuals mimic sources (e.g. over
        structured emission), rather than relying on the total count alone.
        """
        if self.negative_segmentation is None:
            return np.empty((0, 2))
        seg = self.negative_segmentation
        yx = ndimage.center_of_mass(np.ones(seg.data.shape), labels=seg.data, index=seg.labels)
        return np.array(yx, dtype=float).reshape(-1, 2)[:, ::-1]


def _segment(data, threshold, kernel, n_pixels, mask, deblend):
    convolved = convolve(np.where(mask, 0.0, data), kernel, normalize_kernel=True)
    with warnings.catch_warnings():
        # "No sources found" is reported through the result (None / notes), not as a warning.
        warnings.simplefilter("ignore", NoDetectionsWarning)
        segm = detect_sources(convolved, threshold, n_pixels=n_pixels, mask=mask)
    if segm is not None and deblend:
        segm = deblend_sources(
            convolved, segm, n_pixels=n_pixels, n_levels=32, contrast=0.001, progress_bar=False
        )
    return segm, convolved


def _background(data, mask, box_size, filter_size, exclude_percentile=10.0):
    return Background2D(
        data,
        box_size,
        filter_size=(filter_size, filter_size),
        mask=mask,
        sigma_clip=SigmaClip(sigma=3.0, maxiters=10),
        bkg_estimator=MedianBackground(),
        exclude_percentile=exclude_percentile,
    )


def _near_bright(table: QTable, ratio: float, radius: float) -> np.ndarray:
    flux = np.asarray(table["flux"].value, dtype=float)
    x, y = np.asarray(table["x"], dtype=float), np.asarray(table["y"], dtype=float)
    flag = np.zeros(len(table), dtype=bool)
    for i in np.flatnonzero(np.isfinite(flux) & (flux > 0)):
        distance = np.hypot(x - x[i], y - y[i])
        flag |= (distance > 0) & (distance < radius) & (flux * ratio < flux[i])
    return flag


@step("imaging.detect", version="1")
def detect(
    image: ImageProduct,
    *,
    nsigma: float = 3.0,
    kernel_fwhm: float = 2.0,
    n_pixels: int = 5,
    box_size: int = 64,
    filter_size: int = 3,
    deblend: bool = False,
    estimate_false_positives: bool = True,
    bright_ratio: float = 50.0,
    bright_radius: float = 60.0,
) -> Detections:
    """Detect sources in an image (see module docstring for the method).

    Parameters
    ----------
    image : ImageProduct
        Image to search; its mask is respected.
    nsigma : float
        Threshold in units of the unconvolved background RMS.
    kernel_fwhm : float
        FWHM of the Gaussian matched filter, in pixels (choose about the PSF FWHM).
    n_pixels : int
        Minimum connected pixels per source.
    box_size, filter_size : int
        Background mesh size and median-filter size, in pixels / meshes.
    deblend : bool
        Split blended sources (off by default; see module notes).
    estimate_false_positives : bool
        Also run the detection on the negated image.
    bright_ratio, bright_radius : float
        Settings of the ``near_bright_source`` flag (flux ratio, radius in pixels).
    """
    mask = np.asarray(image.mask) if image.mask is not None else ~np.isfinite(image.data)
    data = np.where(mask, 0.0, np.asarray(image.data, dtype=float))
    kernel = Gaussian2DKernel(kernel_fwhm * gaussian_fwhm_to_sigma)
    kernel.normalize()

    bkg = _background(data, mask, box_size, filter_size)
    threshold = nsigma * bkg.background_rms
    segm, _ = _segment(data - bkg.background, threshold, kernel, n_pixels, mask, deblend=False)
    if segm is not None:  # second pass: mask sources (dilated) when estimating the background
        source_mask = ndimage.binary_dilation(segm.data > 0, iterations=3)
        # Masked sources may cover much of a mesh; accept meshes that keep >= 30% of pixels.
        bkg = _background(data, mask | source_mask, box_size, filter_size, exclude_percentile=70)
        threshold = nsigma * bkg.background_rms
    subtracted = data - bkg.background
    segm, convolved = _segment(subtracted, threshold, kernel, n_pixels, mask, deblend)

    n_false, negative = None, None
    if estimate_false_positives:
        negative, _ = _segment(-subtracted, threshold, kernel, n_pixels, mask, deblend=False)
        n_false = 0 if negative is None else int(negative.n_labels)

    factor, conversion = flux_conversion(image)
    scale = factor if factor is not None else 1.0
    unit = u.Jy if factor is not None else (image.unit or u.dimensionless_unscaled)
    error = None
    if image.uncertainty is not None:
        error = np.where(mask, 0.0, np.asarray(image.uncertainty.array, dtype=float)) * scale
    params = {
        "nsigma": nsigma,
        "kernel_fwhm_pix": kernel_fwhm,
        "n_pixels": n_pixels,
        "box_size": box_size,
        "filter_size": filter_size,
        "deblend": deblend,
        "bright_ratio": bright_ratio,
        "bright_radius_pix": bright_radius,
        "threshold": "nsigma x unconvolved background RMS",
        "unit_conversion": conversion,
    }
    notes = [
        f"background mesh {box_size} px: structure larger than the mesh is treated as background",
        "detections are significant positive features, not necessarily point sources: on "
        "structured emission (nebulae, galaxies) many are knots of that emission; compare with "
        "false_positive_positions() to see where background residuals mimic sources",
    ]
    if image.uncertainty is None:
        notes.append("no ERR: flux_err not available")
    if segm is None:
        notes.append("no sources detected above the threshold")

    table = QTable()
    if segm is not None:
        cat = SourceCatalog(
            subtracted * scale,
            segm,
            convolved_data=convolved * scale,
            error=error,
            mask=mask,
            wcs=image.wcs,
        )
        table["label"] = cat.labels
        table["x"] = cat.x_centroid
        table["y"] = cat.y_centroid
        if image.wcs is not None:
            sky = image.wcs.pixel_to_world(cat.x_centroid, cat.y_centroid)
            table["ra"], table["dec"] = sky.icrs.ra, sky.icrs.dec
        table["area"] = cat.area
        table["semimajor_axis"] = cat.semimajor_axis
        table["semiminor_axis"] = cat.semiminor_axis
        table["ellipticity"] = cat.ellipticity
        table["fwhm"] = cat.fwhm
        table["flux"] = np.asarray(cat.segment_flux, dtype=float) * unit
        if error is not None:
            table["flux_err"] = np.asarray(cat.segment_flux_err, dtype=float) * unit
            with np.errstate(divide="ignore", invalid="ignore"):
                table["snr"] = table["flux"] / table["flux_err"]
        table["near_bright_source"] = _near_bright(table, bright_ratio, bright_radius)
    table.meta.update(
        {
            "params": params,
            "n_false_estimate": n_false,
            "source_file": image.source.filename,
            "bandpass": image.bandpass.key,
        }
    )
    return Detections(
        catalog=table,
        segmentation=segm,
        background=bkg.background,
        background_rms=bkg.background_rms,
        n_false_estimate=n_false,
        negative_segmentation=negative,
        params=params,
        notes=notes,
    )
