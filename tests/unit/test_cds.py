"""Tests for the CDS adapters, astroledger.archives.cds (roadmap §27 task 16).

The services are replaced by stubs returning small SYNTHETIC tables (the CDS hosts are not
reachable from CI). The tests check the adapters' guarantees, not CDS content:

- the query sent is the documented ADQL / parameters;
- results are copied unchanged, with only provenance added (no identity field is generated);
- results are cached: a repeated query does not touch the service;
- each call is recorded as a provenance step.

Live queries are marked ``remote`` and excluded from the default run.
"""

import json
from typing import ClassVar

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from astroledger.archives import cds
from astroledger.provenance import ProvenanceStore, use_store

pytest.importorskip("astroquery")

CENTRE = SkyCoord(151.757 * u.deg, -40.4365 * u.deg)


def _synthetic_simbad():
    t = Table(
        {
            "oid": np.array([11, 22], dtype=np.int64),
            "main_id": np.array(["SYNTH OBJ 1", "SYNTH OBJ 2"], dtype=object),
            "otype": np.array(["PN", "*"], dtype=object),
            "ra": [151.757, 151.760],
            "dec": [-40.4365, -40.4370],
            "coo_err_maj": [1.0, 2.0],
            "coo_err_min": [1.0, 2.0],
            "coo_bibcode": np.array(["0000SYNTH...1....1X", ""], dtype=object),
        }
    )
    t["ra"].unit = t["dec"].unit = "deg"
    t["coo_err_maj"].unit = t["coo_err_min"].unit = "mas"
    return t


class FakeSimbad:
    server = "simbad.cds.unistra.fr"
    calls: ClassVar[list] = []

    def query_tap(self, query, maxrec=10000):
        FakeSimbad.calls.append(query)
        if "FROM ident" in query:
            return Table({"id": np.array(["SYNTH OBJ 1", "SYNTH ALT 1"], dtype=object)})
        if "FROM has_ref" in query:
            return Table({"bibcode": np.array(["0000SYNTH...1....1X"], dtype=object)})
        return _synthetic_simbad()


@pytest.fixture
def simbad(monkeypatch):
    FakeSimbad.calls = []
    monkeypatch.setattr(cds, "_simbad", lambda: FakeSimbad())
    return FakeSimbad


def test_simbad_cone_query_and_copy(simbad, tmp_path):
    table = cds.simbad_cone(CENTRE, 30 * u.arcsec, cache_dir=tmp_path)
    query = simbad.calls[0]
    assert "FROM basic" in query and "CONTAINS(POINT('ICRS', basic.ra, basic.dec)" in query
    assert "CIRCLE('ICRS', 151.75700000, -40.43650000, 0.00833333)" in query
    # exactly the service's columns and values; provenance only in meta
    assert table.colnames == _synthetic_simbad().colnames
    assert list(table["main_id"]) == ["SYNTH OBJ 1", "SYNTH OBJ 2"]
    prov = table.meta["provenance"]
    assert prov["service"] == "SIMBAD" and prov["query"] == query
    assert table.meta["from_cache"] is False


def test_results_are_cached(simbad, tmp_path):
    first = cds.simbad_cone(CENTRE, 30 * u.arcsec, cache_dir=tmp_path)
    second = cds.simbad_cone(CENTRE, 30 * u.arcsec, cache_dir=tmp_path)
    assert len(simbad.calls) == 1  # the second call never reached the service
    assert second.meta["from_cache"] is True
    assert list(second["main_id"]) == list(first["main_id"])
    assert second["ra"].unit == u.deg
    cds.simbad_cone(CENTRE, 31 * u.arcsec, cache_dir=tmp_path)
    assert len(simbad.calls) == 2  # a different query is not served from the cache


def test_cache_round_trip_keeps_empty_strings_and_masks(monkeypatch, tmp_path):
    from astropy.table import MaskedColumn
    from astropy.utils.masked import Masked

    def table():
        return Table(
            {
                "main_id": np.array(["A", ""]),  # a genuine empty string
                "otype": MaskedColumn(["G", "PN"], mask=[False, True]),
                "coo_err_maj": Masked([1.0, 2.0] * u.mas, mask=[True, False]),
                "ra": [1.0, 2.0],
            }
        )

    class Odd(FakeSimbad):
        def query_tap(self, query, maxrec=10000):
            return table()

    monkeypatch.setattr(cds, "_simbad", lambda: Odd())
    first = cds.simbad_cone(CENTRE, 5 * u.arcsec, cache_dir=tmp_path)
    cached = cds.simbad_cone(CENTRE, 5 * u.arcsec, cache_dir=tmp_path)
    assert cached.meta["from_cache"] is True
    for name in first.colnames:
        assert list(np.ma.getmaskarray(cached[name])) == list(np.ma.getmaskarray(first[name]))
    assert list(cached["main_id"]) == ["A", ""] and not np.ma.is_masked(cached["main_id"][1])
    assert cached["otype"][0] == "G" and np.ma.is_masked(cached["otype"][1])


def test_identifiers_and_bibliography(simbad, tmp_path):
    ids = cds.simbad_identifiers(11, cache_dir=tmp_path)
    refs = cds.simbad_bibliography(11, cache_dir=tmp_path)
    assert "FROM ident WHERE ident.oidref = 11" in simbad.calls[0]
    assert "has_ref.oidbibref = ref.oidbib" in simbad.calls[1]
    assert list(ids["id"]) == ["SYNTH OBJ 1", "SYNTH ALT 1"]
    assert list(refs["bibcode"]) == ["0000SYNTH...1....1X"]


def test_empty_result_stays_empty(monkeypatch, tmp_path):
    class Empty(FakeSimbad):
        def query_tap(self, query, maxrec=10000):
            return Table(names=("oid", "main_id"), dtype=(np.int64, object))

    monkeypatch.setattr(cds, "_simbad", lambda: Empty())
    table = cds.simbad_cone(CENTRE, 5 * u.arcsec, cache_dir=tmp_path)
    assert len(table) == 0 and table.meta["provenance"]["service"] == "SIMBAD"


def test_resolve_name_is_cached_and_never_guesses(monkeypatch, tmp_path):
    from astropy.coordinates import name_resolve

    calls = []

    def fake(name, cache=False):
        calls.append(name)
        if name == "unknown thing":
            raise name_resolve.NameResolveError(
                "Unable to find coordinates for name 'unknown thing'"
            )
        return SkyCoord(10.0 * u.deg, 20.0 * u.deg)

    monkeypatch.setattr(name_resolve, "get_icrs_coordinates", fake)
    first = cds.resolve_name("synthetic name", cache_dir=tmp_path)
    second = cds.resolve_name("synthetic name", cache_dir=tmp_path)
    assert first["ra_deg"] == 10.0 and second["from_cache"] and len(calls) == 1
    assert (
        json.loads((next(tmp_path.glob("sesame_*.json"))).read_text())["provenance"]["service"]
        == "Sesame"
    )
    with pytest.raises(name_resolve.NameResolveError):
        cds.resolve_name("unknown thing", cache_dir=tmp_path)
    assert not any("unknown" in p.read_text() for p in tmp_path.glob("sesame_*.json"))


def test_vizier_cone_parameters(monkeypatch, tmp_path):
    from astroquery.vizier import VizierClass

    seen = {}

    def fake_query_region(self, coordinates, radius=None, catalog=None, **kwargs):
        seen.update(radius=radius, catalog=catalog, columns=self.columns, row_limit=self.ROW_LIMIT)
        t = Table({"Source": np.array([123], dtype=np.int64), "RA_ICRS": [151.757]})
        return [t]

    monkeypatch.setattr(VizierClass, "query_region", fake_query_region)
    table = cds.vizier_cone(
        "I/355/gaiadr3", CENTRE, 10 * u.arcsec, columns=("Source", "RA_ICRS"), cache_dir=tmp_path
    )
    assert seen["catalog"] == "I/355/gaiadr3" and seen["radius"] == 10 * u.arcsec
    assert list(seen["columns"]) == ["Source", "RA_ICRS"]
    assert table.colnames == ["Source", "RA_ICRS"]
    assert json.loads(table.meta["provenance"]["query"])["catalog"] == "I/355/gaiadr3"


def test_vizier_refuses_several_tables(monkeypatch, tmp_path):
    from astroquery.utils import TableList
    from astroquery.vizier import VizierClass

    def two_tables(self, coordinates, radius=None, catalog=None, **kwargs):
        return TableList({"I/x/a": Table({"v": [1]}), "I/x/b": Table({"v": [2]})})

    monkeypatch.setattr(VizierClass, "query_region", two_tables)
    with pytest.raises(ValueError, match="2 tables"):
        cds.vizier_cone("I/x", CENTRE, 10 * u.arcsec, cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.ecsv"))


def test_calls_are_provenance_steps(simbad, tmp_path):
    store = ProvenanceStore(tmp_path / "prov.sqlite")
    with use_store(store):
        cds.simbad_cone(CENTRE, 30 * u.arcsec, cache_dir=tmp_path / "cache")
    names = [a["name"] for a in store.activities()]
    assert "archives.cds.simbad_cone" in names


@pytest.mark.remote
def test_live_simbad_cone(tmp_path):
    table = cds.simbad_cone(CENTRE, 60 * u.arcsec, cache_dir=tmp_path)
    assert {"oid", "main_id", "otype", "ra", "dec"} <= set(table.colnames)


@pytest.mark.remote
def test_live_resolve(tmp_path):
    record = cds.resolve_name("NGC 3132", cache_dir=tmp_path)
    assert (
        SkyCoord(record["ra_deg"] * u.deg, record["dec_deg"] * u.deg).separation(CENTRE)
        < 1 * u.arcmin
    )
