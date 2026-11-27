"""Build a reproducible source release with per-file hashes and an archive checksum."""
import hashlib
import json
from pathlib import Path
import zipfile

from jarvis import __version__

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = ('README.md', 'LICENSE', 'requirements.txt', 'install.ps1', 'upgrade.ps1', 'CHANGELOG.md', 'AGENTS.md')
    paths = [ROOT / name for name in names]
    paths += sorted((ROOT / 'jarvis').glob('*.py'))
    paths += [ROOT / 'jarvis' / 'ui.html', ROOT / 'scripts' / 'benchmark.py', ROOT / 'scripts' / 'check_defender.ps1']
    paths += sorted((ROOT / 'docs').glob('*.md'))
    paths += sorted(p for p in (ROOT / 'docs' / 'examples').rglob('*') if p.is_file())
    paths += [ROOT / 'scripts' / 'measure_document_search.py']
    paths += sorted((ROOT / 'docs' / 'screenshots').glob('*.png'))
    paths += sorted(p for p in (ROOT / 'docs' / 'design-concepts').glob('*')
                    if p.is_file() and p.suffix in ('.md', '.webp'))
    files = {str(path.relative_to(ROOT)).replace('\\','/'): path.read_bytes() for path in paths}
    manifest = {'version':__version__, 'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}
    files['release-manifest.json'] = json.dumps(manifest, indent=2).encode()
    archive = output / f'Jarvis{__version__}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo('Jarvis/' + name, date_time=(2026,1,1,0,0,0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, data)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(checksum + '  ' + archive.name + '\n', encoding='utf-8')
    return archive


if __name__ == '__main__':
    print(build(ROOT / 'dist'))
