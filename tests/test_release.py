import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.package_release import build


def test_release_is_reproducible_and_contains_only_manifest_files(tmp_path):
    archive=build(tmp_path)
    first=archive.read_bytes()
    assert build(tmp_path).read_bytes()==first
    with zipfile.ZipFile(archive) as bundle:
        manifest=json.loads(bundle.read('Jarvis/release-manifest.json'))
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(bundle.read('Jarvis/'+name)).hexdigest()==digest
        assert all('/.venv/' not in name and 'memory.db' not in name and 'secrets.bin' not in name for name in bundle.namelist())
    assert hashlib.sha256(first).hexdigest() in (tmp_path/'SHA256SUMS.txt').read_text()


@pytest.mark.skipif(os.name!='nt',reason='Windows source updater integration')
def test_windows_updater_and_restore(tmp_path):
    import shutil
    home=tmp_path/'installed'
    home.mkdir()
    updater=Path(__file__).parents[1]/'upgrade.ps1'
    shutil.copy(updater,home/'upgrade.ps1')
    (home/'jarvis').mkdir()
    original=home/'jarvis'/'__main__.py'
    original.write_text('# previous version\n')
    archive=build(tmp_path/'packages')
    env={**os.environ,'APPDATA':str(tmp_path/'appdata')}
    result=subprocess.run(['pwsh','-NoProfile','-File',str(home/'upgrade.ps1'),'-Package',str(archive),'-Checksum',hashlib.sha256(archive.read_bytes()).hexdigest()],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    assert original.read_text()!='# previous version\n'
    backup=next((tmp_path/'appdata'/'Jarvis'/'Program Backups').iterdir())
    result=subprocess.run(['pwsh','-NoProfile','-File',str(home/'upgrade.ps1'),'-Restore',str(backup)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    assert original.read_text()=='# previous version\n'
