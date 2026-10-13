"""Tests for the read-only MCP server, astroledger.mcp_server (roadmap §27 task 19).

The server is exercised through the MCP protocol itself: in-process with ``mcp.Client`` and,
once, as a real stdio subprocess (the way Claude Code launches it). Images are synthetic.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from test_interpret import _gaia, _write

import fits_factory as ff
from astroledger.io import open_image

mcp = pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters  # noqa: E402

from astroledger.mcp_server import build_server  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def root(tmp_path):
    data = tmp_path / "data"
    (data / "jwst").mkdir(parents=True)
    ff.jwst_cal(data / "jwst" / "jw02733002001_02101_00001_nrca1_cal.fits")
    image_path = _write(data / "synthetic_i2d.fits")
    _gaia(open_image(image_path)).write(data / "gaia.ecsv", format="ascii.ecsv")
    _write(data / "coron_i2d.fits", exp_type="NRC_CORON")
    outside = tmp_path / "secret.fits"
    outside.write_bytes(b"not for clients")
    (data / "link.fits").symlink_to(outside)
    return data


async def _call(root, name, arguments):
    async with Client(build_server(root)) as client:
        return await client.call_tool(name, arguments)


def test_tools_are_read_only_and_described(root):
    async def go():
        async with Client(build_server(root)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in _run(go())}
    assert set(tools) == {"list_files", "inspect", "explain", "search"}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.description
    assert tools["search"].annotations.open_world_hint is True
    assert tools["inspect"].annotations.open_world_hint is False


def test_list_files_stays_inside_the_root(root):
    result = _run(_call(root, "list_files", {}))
    paths = [f["path"] for f in result.structured_content["files"]]
    assert "jwst/jw02733002001_02101_00001_nrca1_cal.fits" in paths
    assert "link.fits" not in paths  # a link pointing outside the root is not offered
    escaped = _run(_call(root, "list_files", {"subfolder": ".."}))
    assert escaped.is_error and "outside the data root" in escaped.content[0].text


@pytest.mark.parametrize("path", ["../secret.fits", "/etc/passwd", "link.fits", "missing.fits"])
def test_paths_outside_the_root_are_refused(root, path):
    result = _run(_call(root, "inspect", {"path": path}))
    assert result.is_error
    assert "data root" in result.content[0].text


def test_inspect_returns_the_fact_sheet(root):
    result = _run(_call(root, "inspect", {"path": "jwst/jw02733002001_02101_00001_nrca1_cal.fits"}))
    assert not result.is_error
    sheet = result.structured_content
    assert sheet["observation"]["bandpass"] == "JWST/NIRCAM/F200W"
    assert sheet["observation"]["image_analysis"] == "supported"


def test_explain_with_gaia_returns_graded_statements(root):
    result = _run(
        _call(
            root,
            "explain",
            {"path": "synthetic_i2d.fits", "gaia_table": "gaia.ecsv", "max_sources": 2},
        )
    )
    assert not result.is_error
    payload = result.structured_content
    assert payload["summary"]["L2_star"] == 1
    assert (
        len(payload["sources"]) == 2
        and payload["sources_not_shown"] == payload["summary"]["n_sources"] - 2
    )
    first = payload["sources"][0]["statements"]
    assert any(s["level"] == "L2_INFERENCE" for s in first)  # L2 sources come first
    for source in payload["sources"]:
        for s in source["statements"]:
            assert s["level"] != "L3_HYPOTHESIS" or s["test"]


def test_explain_refuses_non_imaging(root):
    result = _run(_call(root, "explain", {"path": "coron_i2d.fits"}))
    assert result.is_error and "NRC_CORON" in result.content[0].text


def test_search_parses_coordinates_and_reports_failures(root, monkeypatch):
    from astropy.table import Table

    from astroledger.archives import mast

    seen = {}

    def fake_search(target, **kwargs):
        seen["target"], seen["kwargs"] = target, kwargs
        return Table({"obs_id": ["a", "b", "c"], "filters": ["F444W;F405N"] * 3})

    monkeypatch.setattr(mast, "search", fake_search)
    result = _run(_call(root, "search", {"target": "151.757 -40.4365", "max_rows": 2}))
    assert not result.is_error
    assert result.structured_content["n_total"] == 3 and len(result.structured_content["rows"]) == 2
    assert seen["target"].ra.deg == pytest.approx(151.757)

    def broken(target, **kwargs):
        raise ConnectionError("mast.stsci.edu unreachable")

    monkeypatch.setattr(mast, "search", broken)
    failed = _run(_call(root, "search", {"target": "NGC 3132"}))
    assert failed.is_error and "unreachable" in failed.content[0].text


def test_stdio_subprocess(root):
    """The server as Claude Code runs it: a subprocess speaking MCP over stdio."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "astroledger.cli", "mcp", "--root", str(root)],
        env={**os.environ, "PYTHONWARNINGS": "ignore"},
    )

    async def go():
        async with Client(params) as client:
            tools = await client.list_tools()
            listed = await client.call_tool("list_files", {})
            return tools, listed

    tools, listed = _run(go())
    assert {t.name for t in tools.tools} == {"list_files", "inspect", "explain", "search"}
    assert not listed.is_error


def test_root_must_exist(tmp_path):
    from astroledger.mcp_server import DataRootError

    with pytest.raises(DataRootError):
        build_server(tmp_path / "nope")
    assert Path(tmp_path).exists()


def test_streamable_http_on_a_custom_path(root, monkeypatch):
    """The transport a Claude app remote connector uses, on an unguessable path."""
    import socket
    import subprocess
    import time

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    path = "/mcp-test-7f3a9c"
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "astroledger.cli",
            "mcp",
            "--root",
            str(root),
            "--http",
            "--port",
            str(port),
            "--http-path",
            path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.3)

        async def go():
            async with Client(f"http://127.0.0.1:{port}{path}") as client:
                tools = await client.list_tools()
                listed = await client.call_tool("list_files", {})
                return tools, listed

        tools, listed = _run(go())
        assert {t.name for t in tools.tools} == {"list_files", "inspect", "explain", "search"}
        assert not listed.is_error
    finally:
        proc.terminate()
        proc.wait(timeout=30)
