import astroledger


def test_version_is_set():
    assert isinstance(astroledger.__version__, str)
    assert astroledger.__version__ != "0.0.0+unknown", "package is not installed (pip install -e .)"
