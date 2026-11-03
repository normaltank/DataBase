"""Build an allowlisted source release plus both hash-locked native wheel sets."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile

from build_portable import download, digest

ROOT = Path(__file__).resolve().parents[1]
DIRS = {'platform_app', 'static', 'templates', 'server', 'tests', 'portable'}
FILES = {'app.py', 'requirements.txt', 'requirements-test.txt', 'PRODUCT.md', 'GLOSSARY.md', 'README.md',
         'docs/server-deployment.md', 'docs/portable-preview.md', 'docs/project-showcase.html',
         'portable/__init__.py', 'portable/demo_seed.py', 'portable/public_batch.py',
         'portable/samples/cee17-preview.json', 'portable/samples/fictional-article.pdf'}


def source_names():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    names = sorted(n for n in tracked if n and (n in FILES or PurePosixPath(n).parts[0] in DIRS
                   or (n.startswith('scripts/') and n.endswith('.py'))))
    if FILES - set(names):
        raise ValueError('Required versioned sources missing: ' + str(FILES - set(names)))
    for name in names:
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or ROOT not in path.resolve().parents:
            raise ValueError('Source is not a regular in-tree file: ' + name)
        if any(part.startswith('.') for part in PurePosixPath(name).parts):
            raise ValueError('Hidden development file is not distributable: ' + name)
    return names


def build(output, cache, allow_dirty=False):
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT))
    if dirty and not allow_dirty:
        raise ValueError('Commit reviewed source first. Dirty builds are pre-acceptance only.')
    version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    archive = output / ('Zhihui-server-' + version[:12] + '.zip')
    if archive.exists():
        raise ValueError('Output already exists; use a fresh directory.')
    with tempfile.TemporaryDirectory(prefix='server-build-', dir=output) as tmp:
        stage = Path(tmp)
        sources = source_names()
        for name in sources:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        lock = json.loads((ROOT / 'server/dependency-lock.json').read_text(encoding='utf-8'))
        for platform, artifacts in lock['platforms'].items():
            folder = stage / 'wheels' / platform
            folder.mkdir(parents=True)
            for artifact in artifacts:
                locked = dict(artifact, url=artifact['download_url'])
                prepared = cache / artifact['path']
                if prepared.is_file() and digest(prepared.read_bytes()) == artifact['sha256']:
                    source = prepared
                else:
                    source = download(locked, cache)
                shutil.copyfile(source, folder / artifact['filename'])
        manifest = {'format': 'research-server-v1', 'source_commit': version,
                    'source_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT).decode().strip(),
                    'source_dirty': dirty, 'source_files': sources, 'python': lock['python'],
                    'files': {p.relative_to(stage).as_posix(): {'bytes': p.stat().st_size, 'sha256': digest(p.read_bytes())}
                              for p in sorted(stage.rglob('*')) if p.is_file()}}
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in sorted([*manifest['files'], 'manifest.json']):
                z.write(stage / name, name)
    from verify_server import verify_zip
    result = verify_zip(archive)
    result.update(zip=str(archive.resolve()), sha256=digest(archive.read_bytes()))
    archive.with_suffix('.zip.sha256').write_text(result['sha256'] + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='Unreleased pre-acceptance only.')
    args = parser.parse_args()
    try:
        build(args.output.resolve(), args.cache.resolve(), args.allow_dirty)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
