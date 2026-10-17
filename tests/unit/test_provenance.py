"""Tests for astroledger.provenance (roadmap §27 task 8)."""

import hashlib
import json

import numpy as np
import pytest
from astropy import units as u
from astropy.table import Table

import fits_factory as ff
from astroledger.io import open_image
from astroledger.provenance import (
    ProvenanceStore,
    environment,
    last_activity,
    sha256_file,
    step,
    use_store,
    write_sidecar,
)


@step("test.scale", version="2")
def scale(image, factor, radius=3 * u.pix):
    return np.asarray(image.data) * factor


@step("test.fail")
def fail(x):
    raise ValueError("bad input")


def test_step_records_inputs_params_outputs_and_environment(tmp_path):
    path = ff.jwst_cal(tmp_path / "jw_test_cal.fits")
    img = open_image(path)
    store = ProvenanceStore(tmp_path / "prov.sqlite")
    with use_store(store):
        out = scale(img, 2.0)

    act = last_activity()
    assert act.status == "ok" and act.name == "test.scale" and act.version == "2"
    assert act.inputs["image"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert act.inputs["image"]["file"] == "jw_test_cal.fits"
    assert act.inputs["image"]["bandpass"] == "JWST/NIRCAM/F200W"
    assert act.params == {"factor": 2.0, "radius": "3.0 pix"}
    assert act.outputs[0]["kind"] == "array" and act.outputs[0]["shape"] == list(out.shape)
    assert "astropy" in act.environment["packages"]
    assert len(act.environment["git"]["commit"]) == 40

    stored = store.get(act.id)
    assert stored["inputs"]["image"]["sha256"] == act.inputs["image"]["sha256"]
    assert store.generated(act.outputs[0]["sha256"])[0]["id"] == act.id


def test_failed_step_is_recorded_and_reraised(tmp_path):
    store = ProvenanceStore(tmp_path / "prov.sqlite")
    with use_store(store), pytest.raises(ValueError, match="bad input"):
        fail(1)
    (record,) = store.activities("test.fail")
    assert record["status"] == "error" and "bad input" in record["error"]


def test_no_store_still_tracks_last_activity(tmp_path):
    scale(open_image(ff.jwst_cal(tmp_path / "x_cal.fits")), 1.0)
    assert last_activity().name == "test.scale"


def test_sidecar_holds_output_checksum(tmp_path):
    scale(open_image(ff.jwst_cal(tmp_path / "x_cal.fits")), 1.0)
    output = tmp_path / "result.txt"
    output.write_text("42")
    sidecar = write_sidecar(output, last_activity())
    record = json.loads(sidecar.read_text())
    assert sidecar.name == "result.txt.prov.json"
    assert record["output_file"]["sha256"] == sha256_file(output)
    assert record["name"] == "test.scale"


def test_tables_and_files_are_entities(tmp_path):
    @step("test.tables")
    def passthrough(table, path):
        return table

    path = tmp_path / "f.txt"
    path.write_text("x")
    passthrough(Table({"a": [1, 2, 3]}), path)
    act = last_activity()
    assert act.inputs["table"]["kind"] == "table" and act.inputs["table"]["rows"] == 3
    assert act.inputs["path"]["sha256"] == sha256_file(path)


def test_package_versions_are_read_once():
    from astroledger.provenance import core

    assert core._software() is core._software()
    assert environment()["packages"] == core._software()["packages"]


def test_image_entity_records_archive_ids_and_all_planes(tmp_path):
    from astroledger.provenance import describe

    path = ff.jwst_cal(tmp_path / "jw02733002001_02101_00001_nrca1_cal.fits")
    from astropy.io import fits

    fits.setval(path, "CAL_VER", value="1.16.0")
    fits.setval(path, "CRDS_CTX", value="jwst_1293.pmap")
    fits.setval(path, "OBS_ID", value="V02733002001P0000000002101")
    image = open_image(path)
    entity = describe(image)
    assert entity["archive"] == {
        "OBS_ID": "V02733002001P0000000002101",
        "CAL_VER": "1.16.0",
        "CRDS_CTX": "jwst_1293.pmap",
    }
    assert entity["unit"] == str(image.unit)
    image.mask[0, 0] = not image.mask[0, 0]
    image.uncertainty.array[1, 1] += 1.0
    changed = describe(image)
    assert changed["data_sha256"] == entity["data_sha256"]
    assert changed["mask_sha256"] != entity["mask_sha256"]
    assert changed["uncertainty_sha256"] != entity["uncertainty_sha256"]


def test_lists_of_files_keep_each_checksum(tmp_path):
    files = []
    for name in ("a.dat", "b.dat"):
        (tmp_path / name).write_bytes(name.encode())
        files.append(tmp_path / name)

    @step("test.download")
    def download(names):
        return list(files)

    store = ProvenanceStore(tmp_path / "prov.sqlite")
    with use_store(store):
        download(["a", "b"])
    act = last_activity()
    assert act.params["names"] == ["a", "b"]  # a list of plain values stays a parameter
    items = act.outputs[0]["items"]
    assert [i["sha256"] for i in items] == [sha256_file(f) for f in files]
    assert store.generated(sha256_file(files[1]))[0]["id"] == act.id


def test_quantity_arrays_keep_their_unit():
    from astroledger.provenance import describe

    entity = describe(np.arange(20.0) * u.MJy / u.sr)
    assert entity["kind"] == "array" and entity["unit"] == "MJy / sr"


def test_git_state_is_current(monkeypatch):
    from astroledger.provenance import core

    states = iter([{"commit": "a", "dirty": False}, {"commit": "a", "dirty": True}])
    monkeypatch.setattr(core, "_git_state", lambda repo: next(states))
    if "git" not in environment():  # not a git checkout (e.g. installed wheel)
        pytest.skip("no git checkout")
    assert environment()["git"]["dirty"] is True
