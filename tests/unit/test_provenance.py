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


def test_environment_is_cached():
    assert environment() is environment()
