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
    assert ' ' not in archive.name
    first=archive.read_bytes()
    assert build(tmp_path).read_bytes()==first
    with zipfile.ZipFile(archive) as bundle:
        manifest=json.loads(bundle.read('Jarvis/release-manifest.json'))
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(bundle.read('Jarvis/'+name)).hexdigest()==digest
        assert all('/.venv/' not in name and 'memory.db' not in name and 'secrets.bin' not in name for name in bundle.namelist())
    assert (tmp_path/'SHA256SUMS.txt').read_text().strip() == hashlib.sha256(first).hexdigest() + '  ' + archive.name


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


@pytest.mark.skipif(os.name!='nt',reason='Windows updater failure recovery')
def test_windows_updater_rolls_back_a_partial_copy(tmp_path):
    import shutil
    home=tmp_path/'installed'
    (home/'jarvis').mkdir(parents=True)
    updater=Path(__file__).parents[1]/'upgrade.ps1'
    shutil.copy(updater,home/'upgrade.ps1')
    (home/'jarvis'/'__main__.py').write_text('previous main')
    (home/'README.md').write_text('previous readme')
    content={'jarvis/__main__.py':b'new main','README.md':b'new readme'}
    manifest={'version':'test','files':{name:hashlib.sha256(data).hexdigest() for name,data in content.items()}}
    archive=tmp_path/'update.zip'
    with zipfile.ZipFile(archive,'w') as bundle:
        for name,data in content.items():
            bundle.writestr('Jarvis/'+name,data)
        bundle.writestr('Jarvis/release-manifest.json',json.dumps(manifest))
    wrapper=tmp_path/'inject failure.ps1'
    wrapper.write_text(r'''
param([string] $Updater, [string] $Package, [string] $Checksum)
function Copy-Item {
    param([string] $LiteralPath, [string] $Destination, [switch] $Force)
    if ($LiteralPath -like '*Jarvis Update*README.md') { throw 'Simulated failure during publication' }
    Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
}
& $Updater -Package $Package -Checksum $Checksum
''')
    env={**os.environ,'APPDATA':str(tmp_path/'appdata')}
    result=subprocess.run(['pwsh','-NoProfile','-File',str(wrapper),'-Updater',str(home/'upgrade.ps1'),'-Package',str(archive),'-Checksum',hashlib.sha256(archive.read_bytes()).hexdigest()],env=env,capture_output=True,text=True)
    assert result.returncode!=0
    assert (home/'jarvis'/'__main__.py').read_text()=='previous main'
    assert (home/'README.md').read_text()=='previous readme'


def test_release_has_no_batch_launcher_and_ships_diagnostics(tmp_path):
    archive = build(tmp_path)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert not any(name.lower().endswith(('.bat', '.cmd', '.exe', '.vbs')) for name in names)
    assert 'Jarvis/scripts/check_defender.ps1' in names and 'Jarvis/jarvis/setupwizard.py' in names
    assert 'Jarvis/CHANGELOG.md' in names and 'Jarvis/AGENTS.md' in names


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer integration')
def test_windows_installer_creates_direct_shortcut_and_keeps_settings(tmp_path):
    import shutil
    home = tmp_path / 'Jarvis'
    root = Path(__file__).parents[1]
    shutil.copytree(root / 'jarvis', home / 'jarvis')
    for name in ('install.ps1', 'requirements.txt'):
        shutil.copy(root / name, home / name)
    appdata = tmp_path / 'appdata'
    (appdata / 'Jarvis').mkdir(parents=True)
    (appdata / 'Jarvis' / 'config.json').write_text(json.dumps({'honorific': 'Brett', 'user_name': 'Brett T'}))
    env = {**os.environ, 'APPDATA': str(appdata)}
    command = ['pwsh', '-NoProfile', '-File', str(home / 'install.ps1'), '-SkipPackages', '-Profile', 'low-memory']
    result = subprocess.run(command, env=env, capture_output=True, text=True, cwd=home)
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads((appdata / 'Jarvis' / 'config.json').read_text())
    assert saved['honorific'] == 'Brett' and saved['user_name'] == 'Brett T'
    assert saved['performance_profile'] == 'low-memory' and saved['setup_complete'] is True
    link = appdata / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Jarvis.lnk'
    query = ("$l=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
             "Write-Output $l.TargetPath; Write-Output $l.Arguments" % link)
    output = subprocess.run(['pwsh', '-NoProfile', '-Command', query], capture_output=True, text=True).stdout
    assert output.splitlines()[0].lower().endswith('\\.venv\\scripts\\python.exe')
    assert output.splitlines()[1] == '-m jarvis'
    # A second run (an upgrade or repair) keeps everything and succeeds.
    result = subprocess.run(command[:-2], env=env, capture_output=True, text=True, cwd=home)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((appdata / 'Jarvis' / 'config.json').read_text())['honorific'] == 'Brett'
