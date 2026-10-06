"""The legacy prototype in ``legacy/`` is frozen: its files must match ``legacy/MANIFEST.sha256``.

If this test fails, a legacy file was edited. Do not update the manifest to make it pass;
new work belongs in the new package. See ``legacy/README.md``.
"""

import hashlib
from pathlib import Path

LEGACY = Path(__file__).resolve().parents[1] / "legacy"


def _manifest() -> dict[str, str]:
    entries = {}
    for line in (LEGACY / "MANIFEST.sha256").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        entries[name] = digest
    return entries


def test_manifest_lists_every_legacy_file():
    on_disk = {p.name for p in LEGACY.iterdir() if p.is_file()} - {"README.md", "MANIFEST.sha256"}
    assert on_disk == set(_manifest())


def test_legacy_files_unchanged():
    for name, digest in _manifest().items():
        actual = hashlib.sha256((LEGACY / name).read_bytes()).hexdigest()
        assert actual == digest, f"legacy/{name} was modified; the legacy prototype is frozen"
