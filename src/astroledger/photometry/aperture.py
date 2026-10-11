"""Aperture photometry with local background and propagated uncertainties.

Method
------
1. Pixel values are converted to flux density per pixel (Jy):

   - surface brightness (e.g. JWST ``MJy/sr``): multiply by the pixel solid angle ``PIXAR_SR``;
   - count rates with ``PHOTFNU`` (Jy s / count or electron): multiply by ``PHOTFNU``;
   - count rates with ``PHOTFLAM`` and ``PHOTPLAM`` (HST): f_lambda -> f_nu at the pivot.

   Without a calibration keyword, photometry stays in native units and no magnitude is given.
2. Circular apertures are summed exactly (``method="exact"``) with masked pixels excluded.
3. The local background is the 3-sigma-clipped median (5 iterations, the photutils default also
   used by the JWST pipeline source catalogue) in a circular annulus, subtracted per unmasked
   aperture pixel. Its uncertainty is the standard error of the median,
   sqrt(pi/2) * std / sqrt(n). ``bkg_unstable`` flags annuli whose clipped median has not
   converged after those iterations (it moves by more than its uncertainty if clipping
   continues), which happens on structured emission such as a nebula.
4. ``flux_err`` = sqrt(sum ERR^2 + (area * sigma_bkg)^2); ``flux_err_aperture`` = sqrt(sum ERR^2)
   alone, the convention of the JWST pipeline source catalogue.

Fluxes are *not* aperture-corrected unless a correction factor is supplied (e.g. from the JWST
APCORR reference data, which the pipeline source catalogue records). For resampled products
(``i2d``, ``drz``) neighbouring pixels are correlated, so ERR-based uncertainties are lower
limits; this is stated in the output metadata.
"""

from __future__ import annotations

import numpy as np
from astropy import constants as const
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.stats import SigmaClip
from astropy.table import QTable
from astropy.wcs.utils import proj_plane_pixel_scales
from photutils.aperture import ApertureStats, CircularAnnulus, CircularAperture, aperture_photometry

from astroledger.core.mode import require_imaging
from astroledger.core.product import ImageProduct
from astroledger.provenance import step

__all__ = ["AB_ZERO_POINT", "aperture_photometry_table", "flux_conversion"]

AB_ZERO_POINT = 3631.0 * u.Jy


def flux_conversion(image: ImageProduct) -> tuple[float | None, str]:
    """Factor converting pixel values to Jy per pixel, and where it came from.

    Returns ``(None, reason)`` when no calibration is available.
    """
    unit = image.unit
    if unit is not None and unit.is_equivalent(u.MJy / u.sr):
        pixar = image.keyword("PIXAR_SR")
        if not pixar:
            return None, "surface-brightness unit but no PIXAR_SR keyword"
        factor = (1 * unit * float(pixar) * u.sr).to_value(u.Jy)
        return factor, f"{unit} x PIXAR_SR={float(pixar):.6e} sr"
    if unit is not None and (
        unit.is_equivalent(u.electron / u.s) or unit.is_equivalent(u.count / u.s)
    ):
        photfnu = image.keyword("PHOTFNU")
        if photfnu:
            return float(photfnu), f"{unit} x PHOTFNU={float(photfnu):.6e} Jy s"
        photflam, photplam = image.keyword("PHOTFLAM"), image.keyword("PHOTPLAM")
        if photflam and photplam:
            flam = float(photflam) * u.erg / u.s / u.cm**2 / u.AA
            fnu = (flam * (float(photplam) * u.AA) ** 2 / const.c).to_value(u.Jy)
            return fnu, f"{unit} x PHOTFLAM={float(photflam):.6e}, PHOTPLAM={float(photplam):.2f} A"
        return None, "count-rate unit but no PHOTFNU or PHOTFLAM/PHOTPLAM keywords"
    return None, f"no flux calibration for unit {unit}"


def _pixel_radius(radius: float | u.Quantity, image: ImageProduct) -> float:
    if isinstance(radius, u.Quantity):
        if radius.unit.is_equivalent(u.pix):
            return float(radius.to_value(u.pix))
        if image.wcs is None:
            raise ValueError("angular radius needs a WCS")
        scale = np.mean(proj_plane_pixel_scales(image.wcs.celestial)) * u.deg
        return float((radius / scale).decompose())
    return float(radius)


@step("photometry.aperture", version="1")
def aperture_photometry_table(
    image: ImageProduct,
    positions: SkyCoord | np.ndarray,
    radius: float | u.Quantity,
    *,
    annulus: tuple[float, float] = (8.0, 13.0),
    aperture_correction: float | None = None,
    sigma: float = 3.0,
    maxiters: int = 5,
) -> QTable:
    """Measure background-subtracted aperture fluxes with uncertainties.

    Parameters
    ----------
    image : ImageProduct
        Image with unit (and ideally ``uncertainty``).
    positions : SkyCoord or array of shape (N, 2)
        Sky positions, or 0-based pixel positions ``(x, y)``.
    radius : float or Quantity
        Aperture radius in pixels, or as an angle (converted with the WCS pixel scale).
    annulus : (float, float)
        Inner and outer background-annulus radii in pixels.
    aperture_correction : float, optional
        Multiplicative correction to total flux, from a stated source. Not applied by default.
    sigma : float
        Sigma-clipping threshold for the background.
    maxiters : int
        Sigma-clipping iterations (5 matches photutils and the JWST pipeline).

    Returns
    -------
    astropy.table.QTable
        One row per position: ``id, x, y, ra, dec, flux, flux_err, flux_err_aperture,
        bkg_per_pixel, bkg_per_pixel_err, n_bkg, bkg_unstable, masked_fraction, snr, abmag,
        abmag_err``. ``meta`` records the method, unit conversion and caveats.

    Raises
    ------
    UnsupportedProductError
        If the product is not direct imaging (spectroscopy, coronagraphy, time series, ...).
    """
    require_imaging(image, "aperture photometry")
    if isinstance(positions, SkyCoord):
        if image.wcs is None:
            raise ValueError("sky positions need a WCS")
        xy = np.column_stack(image.wcs.world_to_pixel(positions))
    else:
        xy = np.atleast_2d(np.asarray(positions, dtype=float))
    r = _pixel_radius(radius, image)
    mask = image.mask if image.mask is not None else ~np.isfinite(image.data)
    data = np.where(mask, 0.0, np.asarray(image.data, dtype=float))
    error = None
    if image.uncertainty is not None:
        error = np.where(mask, 0.0, np.asarray(image.uncertainty.array, dtype=float))

    factor, conversion = flux_conversion(image)
    scale = factor if factor is not None else 1.0
    out_unit = u.Jy if factor is not None else (image.unit or u.dimensionless_unscaled)

    apertures = CircularAperture(xy, r=r)
    sums = aperture_photometry(
        data * scale,
        apertures,
        error=None if error is None else error * scale,
        mask=mask,
        method="exact",
    )
    area = apertures.area_overlap(data, mask=mask, method="exact")
    full_area = apertures.area
    annuli = CircularAnnulus(xy, r_in=annulus[0], r_out=annulus[1])

    def clipped(iterations: int | None) -> ApertureStats:
        clip = SigmaClip(sigma=sigma, maxiters=iterations)
        return ApertureStats(data * scale, annuli, mask=mask, sigma_clip=clip)

    stats = clipped(maxiters)
    bkg = np.atleast_1d(np.asarray(stats.median, dtype=float))
    n_bkg = np.atleast_1d(np.asarray(stats.sum_aper_area.value, dtype=float))
    bkg_err = np.sqrt(np.pi / 2) * np.atleast_1d(np.asarray(stats.std, dtype=float))
    bkg_err = bkg_err / np.sqrt(np.maximum(n_bkg, 1))
    converged = np.atleast_1d(np.asarray(clipped(None).median, dtype=float))
    bkg_unstable = np.abs(converged - bkg) > bkg_err

    flux = np.asarray(sums["aperture_sum"], dtype=float) - bkg * area
    if error is not None:
        flux_err_aperture = np.asarray(sums["aperture_sum_err"], dtype=float)
        flux_err = np.hypot(flux_err_aperture, area * bkg_err)
    else:
        flux_err = flux_err_aperture = np.full_like(flux, np.nan)
    if aperture_correction is not None:
        flux = flux * aperture_correction
        flux_err = flux_err * aperture_correction
        flux_err_aperture = flux_err_aperture * aperture_correction

    table = QTable()
    table["id"] = np.arange(1, len(xy) + 1)
    table["x"], table["y"] = xy[:, 0], xy[:, 1]
    if image.wcs is not None:
        sky = image.wcs.pixel_to_world(xy[:, 0], xy[:, 1])
        table["ra"], table["dec"] = sky.icrs.ra, sky.icrs.dec
    table["flux"] = flux * out_unit
    table["flux_err"] = flux_err * out_unit
    table["flux_err_aperture"] = flux_err_aperture * out_unit
    table["bkg_per_pixel"] = bkg * out_unit
    table["bkg_per_pixel_err"] = bkg_err * out_unit
    table["n_bkg"] = n_bkg
    table["bkg_unstable"] = bkg_unstable
    table["masked_fraction"] = 1.0 - area / full_area
    with np.errstate(divide="ignore", invalid="ignore"):
        table["snr"] = flux / flux_err
        if factor is not None:
            ratio = flux / AB_ZERO_POINT.to_value(u.Jy)
            table["abmag"] = np.where(ratio > 0, -2.5 * np.log10(ratio), np.nan)
            table["abmag_err"] = np.where(ratio > 0, 2.5 / np.log(10) * flux_err / flux, np.nan)
    resampled = image.source.filename.removesuffix(".fits").rsplit("_", 1)[-1] in {
        "i2d",
        "drz",
        "drc",
    }
    resampled = resampled or "_i2d_" in image.source.filename
    table.meta.update(
        {
            "aperture_radius_pix": r,
            "annulus_pix": list(annulus),
            "unit_conversion": conversion,
            "aperture_correction": aperture_correction,
            "aperture_corrected": aperture_correction is not None,
            "background": (
                f"{sigma}-sigma clipped median ({maxiters} iterations) in annulus; "
                "error sqrt(pi/2)*std/sqrt(n)"
            ),
            "caveats": (
                ["resampled product: correlated noise, ERR-based uncertainties are lower limits"]
                if resampled
                else []
            )
            + ([] if factor is not None else ["no flux calibration: native units, no magnitudes"]),
            "bandpass": image.bandpass.key,
            "source_file": image.source.filename,
        }
    )
    return table
