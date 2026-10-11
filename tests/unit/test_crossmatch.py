"""Tests for astroledger.crossmatch.crossmatch (roadmap §27 task 17).

Synthetic catalogues of known surface density: catalogue B is uniform with density RHO; a
known fraction Q of catalogue A are B sources displaced by Gaussian errors, the rest are
unrelated. The engine must recover the density, Q, the Rayleigh completeness and the Poisson
chance-coincidence rate, and its reliabilities must be calibrated.
"""

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import QTable

from astroledger.crossmatch import centroid_error, crossmatch

RHO = 0.02  # per arcsec^2
SIG_A, SIG_B = 0.15, 0.10  # arcsec, 1-D
CENTRE = SkyCoord(150 * u.deg, 2 * u.deg)


def _table(x, y):
    c = SkyCoord(x * u.arcsec, y * u.arcsec, frame=CENTRE.skyoffset_frame()).icrs
    return QTable({"ra": c.ra.to(u.deg), "dec": c.dec.to(u.deg)})


@pytest.fixture(scope="module")
def field():
    rng = np.random.default_rng(1)
    half, margin, n_a, q = 300.0, 60.0, 1500, 0.7
    n_b = rng.poisson(RHO * (2 * half) ** 2)
    xb, yb = rng.uniform(-half, half, (2, n_b))
    has = rng.uniform(size=n_a) < q
    inner = np.flatnonzero((np.abs(xb) < half - margin) & (np.abs(yb) < half - margin))
    pick = rng.choice(inner, has.sum(), replace=False)
    sigma = np.hypot(SIG_A, SIG_B)
    xa, ya = rng.uniform(-half + margin, half - margin, (2, n_a))
    xa[has] = xb[pick] + rng.normal(0, sigma, has.sum())
    ya[has] = yb[pick] + rng.normal(0, sigma, has.sum())
    truth = np.full(n_a, -1)
    truth[has] = pick
    b = _table(xb, yb)
    b["name"] = [f"B{i}" for i in range(n_b)]
    b["mag"] = rng.uniform(15, 20, n_b) * u.mag
    return _table(xa, ya), b, truth, has


@pytest.fixture(scope="module")
def result(field):
    a, b, _, _ = field
    return crossmatch(
        a,
        b,
        sigma_a=SIG_A * u.arcsec,
        sigma_b=SIG_B * u.arcsec,
        k=3.0,
        copy_columns=("name", "mag"),
    )


def test_density_and_prior_are_recovered(field, result):
    _, _, _, has = field
    assert np.median(result.best["density"].to_value(u.arcsec**-2)) == pytest.approx(RHO, rel=0.05)
    assert result.meta["prior_q"] == pytest.approx(has.mean(), abs=0.03)


def test_true_pairs_recovered_at_rayleigh_rate(field, result):
    _, _, truth, has = field
    correct = np.asarray(result.best["b_index"]) == truth
    expected = 1 - np.exp(-(3.0**2) / 2)  # 0.989
    n = has.sum()
    assert correct[has].mean() == pytest.approx(
        expected, abs=3 * np.sqrt(expected * (1 - expected) / n) + 0.003
    )


def test_chance_rate_matches_poisson(field, result):
    _, _, _, has = field
    radius = 3.0 * np.hypot(SIG_A, SIG_B)
    expected = 1 - np.exp(-np.pi * radius**2 * RHO)  # about 1.8%
    unrelated = ~has
    observed = np.mean(np.asarray(result.best["b_index"])[unrelated] >= 0)
    sd = np.sqrt(expected * (1 - expected) / unrelated.sum())
    assert abs(observed - expected) < 3 * sd


def test_reliability_is_calibrated(field, result):
    _, _, truth, _ = field
    best = result.best
    matched = np.asarray(best["b_index"]) >= 0
    rel = np.asarray(best["reliability"])[matched]
    correct = (np.asarray(best["b_index"]) == truth)[matched]
    assert correct.mean() == pytest.approx(rel.mean(), abs=0.01)
    low = rel < 0.9
    assert correct[~low].mean() > 0.98
    if low.sum() >= 5:
        assert correct[low].mean() < correct[~low].mean()


def test_output_columns_and_evidence(result, field):
    best = result.best
    _, b, _, _ = field
    matched = np.asarray(best["b_index"]) >= 0
    assert set(best["evidence_level"][matched]) == {"L1 positional coincidence"}
    assert np.all(best["sep_sigma"][matched] <= 3.0)
    radius = best["radius"][matched].to_value(u.arcsec)
    assert radius == pytest.approx(np.full(matched.sum(), 3.0 * np.hypot(SIG_A, SIG_B)))
    # copied verbatim from B, masked where unmatched
    j = np.flatnonzero(matched)[0]
    assert best["b_name"][j] == b["name"][best["b_index"][j]]
    assert best["b_mag"][j] == b["mag"][best["b_index"][j]]
    assert np.all(best["b_name"].mask[~matched])
    assert all("no counterpart within 3 sigma" in f for f in best["flags"][~matched])
    assert result.meta["expected_completeness"] == pytest.approx(0.98889, abs=1e-4)


def test_conflicts_are_reported():
    # A0 sits between two equally distant B sources; A1 and A2 both point at B2.
    a = _table(np.array([0.0, 50.0, 50.3]), np.array([0.0, 0.0, 0.0]))
    b = _table(np.array([-0.2, 0.2, 50.15]), np.array([0.0, 0.0, 0.0]))
    m = crossmatch(
        a, b, sigma_a=0.1 * u.arcsec, sigma_b=0.1 * u.arcsec, density=0.01 / u.arcsec**2, prior=0.9
    )
    kinds = list(m.conflicts["kind"])
    assert "several candidates" in kinds and "shared counterpart" in kinds
    assert "ambiguous" in m.best["flags"][0]
    assert "shared" in m.best["flags"][1] and "shared" in m.best["flags"][2]
    assert m.best["n_within_radius"][0] == 2


def test_chance_coincidence_flag_in_dense_field():
    # one pair at 1 arcsec separation with a large error, in a dense catalogue
    a = _table(np.array([0.0]), np.array([0.0]))
    b = _table(np.array([1.0]), np.array([0.0]))
    m = crossmatch(a, b, sigma_a=0.5 * u.arcsec, sigma_b=0.1 * u.arcsec, density=0.05 / u.arcsec**2)
    assert m.best["p_chance"][0] == pytest.approx(1 - np.exp(-np.pi * 0.05))
    assert "chance coincidence not excluded" in m.best["flags"][0]


def test_systematic_term_widens_the_radius():
    a = _table(np.array([0.0]), np.array([0.0]))
    b = _table(np.array([0.5]), np.array([0.0]))
    tight = crossmatch(
        a, b, sigma_a=0.05 * u.arcsec, sigma_b=0.05 * u.arcsec, density=0.001 / u.arcsec**2
    )
    wide = crossmatch(
        a,
        b,
        sigma_a=0.05 * u.arcsec,
        sigma_b=0.05 * u.arcsec,
        sigma_sys=0.2 * u.arcsec,
        density=0.001 / u.arcsec**2,
    )
    assert tight.best["b_index"][0] == -1 and wide.best["b_index"][0] == 0


def test_density_is_edge_corrected():
    """Sources at corners and edges of B's footprint see a quarter or half of their annulus.

    The corrected density is unbiased at edges. At corners the convex hull of the points lies
    slightly inside the true footprint, so it reads about 13% high (measured over 20 seeds:
    1.13 +- 0.03); that errs conservative for P_chance. Without correction it would read 0.25x.
    """
    ratios = []
    for seed in range(8):
        rng = np.random.default_rng(seed)
        xb, yb = rng.uniform(0, 400, (2, int(RHO * 400**2)))
        a = _table(
            np.array([0.5, 399.5, 0.5, 399.5, 0.5, 200.0]),
            np.array([0.5, 0.5, 399.5, 399.5, 200.0, 0.5]),
        )
        m = crossmatch(
            a,
            _table(xb, yb),
            sigma_a=0.1 * u.arcsec,
            sigma_b=0.1 * u.arcsec,
            annulus=(5 * u.arcsec, 40 * u.arcsec),
        )
        ratios.append(m.best["density"].to_value(u.arcsec**-2) / RHO)
    ratios = np.array(ratios)
    assert 1.0 < ratios[:, :4].mean() < 1.3  # corners
    assert ratios[:, 4:].mean() == pytest.approx(1.0, abs=0.1)  # edge midpoints


def test_empty_catalogues():
    a = _table(np.array([0.0]), np.array([0.0]))
    m = crossmatch(a, a[:0], sigma_a=0.1 * u.arcsec, sigma_b=0.1 * u.arcsec)
    assert m.best["b_index"][0] == -1 and m.meta["n_matched"] == 0


def test_centroid_error():
    assert centroid_error(2.35 * u.pix, 10.0).to_value(u.pix) == pytest.approx(0.1)


def test_registration_removes_a_frame_offset(field):
    """A coherent 0.3 arcsec shift of A would break 3-sigma matching; registration recovers it."""
    a, b, truth, has = field
    shifted = _coords_table(a, dra=0.30, ddec=-0.20)
    plain = crossmatch(shifted, b, sigma_a=SIG_A * u.arcsec, sigma_b=SIG_B * u.arcsec, k=3.0)
    registered = crossmatch(
        shifted,
        b,
        sigma_a=SIG_A * u.arcsec,
        sigma_b=SIG_B * u.arcsec,
        k=3.0,
        register=True,
        register_radius=1.0 * u.arcsec,
    )
    reg = registered.meta["registration"]
    assert reg["applied"] and reg["n_pairs"] > 100
    assert reg["offset_dra_arcsec"] == pytest.approx(0.30, abs=3 * reg["offset_err_arcsec"])
    assert reg["offset_ddec_arcsec"] == pytest.approx(-0.20, abs=3 * reg["offset_err_arcsec"])
    # the residual scatter is explained by the given errors: little systematic term is added
    assert registered.meta["sigma_sys_arcsec"] < 0.1
    good_plain = np.mean(np.asarray(plain.best["b_index"])[has] == truth[has])
    good_reg = np.mean(np.asarray(registered.best["b_index"])[has] == truth[has])
    assert good_plain < 0.8 < 0.97 < good_reg


def test_registration_needs_enough_pairs():
    a = _table(np.array([0.0, 10.0]), np.array([0.0, 0.0]))
    m = crossmatch(a, a, sigma_a=0.1 * u.arcsec, sigma_b=0.1 * u.arcsec, register=True)
    assert m.meta["registration"]["applied"] is False


def _coords_table(table, *, dra, ddec):
    c = SkyCoord(table["ra"], table["dec"]).spherical_offsets_by(dra * u.arcsec, ddec * u.arcsec)
    return QTable({"ra": c.ra.to(u.deg), "dec": c.dec.to(u.deg)})
