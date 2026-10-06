"""Tests for the astroledger command line and fact sheet (roadmap §27 task 10)."""

import json
from pathlib import Path

import pytest

import fits_factory as ff
from astroledger.cli import main
from astroledger.inspect import product_level


def test_inspect_text(tmp_path, capsys):
    path = ff.jwst_cal(tmp_path / "jw02733002001_02101_00001_nrca1_cal.fits")
    assert main(["inspect", str(path)]) == 0
    out = capsys.readouterr().out
    assert "JWST/NIRCAM/F200W" in out
    assert "Stage 2: calibrated exposure" in out
    assert "Measured from pixels (L1)" in out
    assert "jwst_1581.pmap" in out


def test_inspect_json_facts(tmp_path, capsys):
    path = ff.jwst_cal(tmp_path / "x_cal.fits")
    assert main(["inspect", "--json", str(path)]) == 0
    sheet = json.loads(capsys.readouterr().out)
    assert sheet["image"]["unit"] == "MJy / sr"
    assert sheet["image"]["masked_fraction"] == pytest.approx(5 / (64 * 80), abs=1e-4)
    assert sheet["image"]["pixel_scale_arcsec"] == pytest.approx([0.031, 0.031], rel=1e-3)
    assert sheet["image"]["centre_icrs_deg"][0] == pytest.approx(202.47, abs=1e-3)
    assert sheet["measured"]["sigma_clipped_median"] == pytest.approx(1.0, abs=0.01)
    assert sheet["measured"]["sigma_clipped_std"] == pytest.approx(0.1, rel=0.1)
    assert sheet["file"]["sha256"] and sheet["observation"]["bandpass"] == "JWST/NIRCAM/F200W"


def test_inspect_two_chip_reports_both(tmp_path, capsys):
    path = ff.hst_flt_two_chip(tmp_path / "j8xi01abq_flt.fits")
    assert main(["inspect", "--json", str(path)]) == 0
    sheets = json.loads(capsys.readouterr().out)
    assert [s["file"]["extension"] for s in sheets] == ["SCI,1", "SCI,2"]
    assert sheets[0]["file"]["product_level"].startswith("calibrated exposure")


def test_inspect_refuses_unsupported(tmp_path, capsys):
    path = ff.jwst_uncal(tmp_path / "x_uncal.fits")
    assert main(["inspect", str(path)]) == 2
    assert "4-D" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "telescope", "expected"),
    [
        ("jw02733-o001_t001_nircam_clear-f090w_i2d.fits", "JWST", "Stage 3"),
        ("jw02733001001_02101_00001_nrcb1_i2d.fits", "JWST", "Stage 2: resampled"),
        ("jw02733001001_02101_00001_nrcb1_rate.fits", "JWST", "Stage 1"),
        ("j8xi01abq_drc.fits", "HST", "drizzled combined image, CTE"),
        ("light_0001.fits", None, "unknown"),
    ],
)
def test_product_level(name, telescope, expected):
    assert product_level(name, telescope).startswith(expected)


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("astroledger ")


def test_entry_point_declared():
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    assert 'astroledger = "astroledger.cli:main"' in text
