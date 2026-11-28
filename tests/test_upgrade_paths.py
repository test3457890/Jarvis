"""Upgrade from shipped versions using the updater that those versions installed."""
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from jarvis import __version__
from scripts.package_release import build

ROOT = Path(__file__).parents[1]
OLD = ("v1.1.1", "v1.2.1", "v1.4.1")


def _tag_available(tag):
    return subprocess.run(["git", "rev-parse", "-q", "--verify", tag + "^{commit}"], cwd=ROOT,
                          capture_output=True).returncode == 0


def _extract(tag, target):
    archive = target.parent / (tag + ".zip")
    subprocess.run(["git", "archive", "--format=zip", "-o", str(archive), tag], cwd=ROOT, check=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)


def test_package_meets_old_updater_limits(tmp_path):
    # The 1.1.1 and 1.2.x updaters require these, so a new package must keep them.
    archive = build(tmp_path)
    with zipfile.ZipFile(archive) as bundle:
        total = 0
        for entry in bundle.infolist():
            assert entry.filename.startswith("Jarvis/") and ".." not in entry.filename
            assert entry.file_size <= 10_000_000
            total += entry.file_size
        manifest = json.loads(bundle.read("Jarvis/release-manifest.json"))
    assert total <= 50_000_000
    assert "jarvis/__main__.py" in manifest["files"] and manifest["version"] == __version__


@pytest.mark.skipif(os.name != "nt", reason="runs the PowerShell updater from older releases")
@pytest.mark.parametrize("tag", OLD)
def test_upgrade_with_the_old_updater_then_roll_back(tmp_path, tag):
    if not _tag_available(tag):
        pytest.skip(f"{tag} is not in this checkout (needs fetch-depth 0)")
    home = tmp_path / "Jarvis"
    _extract(tag, home)
    old_main = (home / "jarvis" / "__main__.py").read_bytes()
    appdata = tmp_path / "appdata"
    (appdata / "Jarvis").mkdir(parents=True)
    settings = {"honorific": "Alex", "theme": "light", "file_folders": []}
    (appdata / "Jarvis" / "config.json").write_text(json.dumps(settings))
    (appdata / "Jarvis" / "memory.db").write_bytes(b"user data stays")
    archive = build(tmp_path / "package")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    env = {**os.environ, "APPDATA": str(appdata)}
    ps = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    run = lambda *args: subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(home / "upgrade.ps1"), *args],
                                       env=env, capture_output=True, text=True)
    result = run("-Package", str(archive), "-Checksum", digest)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / "jarvis" / "__main__.py").read_bytes() == (ROOT / "jarvis" / "__main__.py").read_bytes()
    assert f'__version__ = "{__version__}"' in (home / "jarvis" / "__init__.py").read_text()
    assert json.loads((appdata / "Jarvis" / "config.json").read_text()) == settings
    assert (appdata / "Jarvis" / "memory.db").read_bytes() == b"user data stays"
    if tag == "v1.1.1":
        assert (home / "Jarvis.bat").exists(), "the old launcher is left in place"
    check = subprocess.run(["python", "-c", "import jarvis.__main__, jarvis.setupwizard"], cwd=home,
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    backup = max((appdata / "Jarvis" / "Program Backups").iterdir(), key=lambda p: p.stat().st_mtime)
    result = run("-Restore", str(backup))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / "jarvis" / "__main__.py").read_bytes() == old_main
    assert not (home / "jarvis" / "setupwizard.py").exists() or tag != "v1.1.1"
    assert json.loads((appdata / "Jarvis" / "config.json").read_text()) == settings
