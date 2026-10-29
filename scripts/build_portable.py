"""Build a Windows application-local preview from explicit source and artifact allowlists.

Builder requires Python/Git and internet only for uncached locked artifacts. Recipients do not.
"""
import argparse
import base64
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'portable/runtime-lock.json'
SOURCE_DIRS = {'platform_app', 'static', 'templates'}
SOURCE_FILES = {
    'app.py', 'requirements.txt', 'PRODUCT.md', 'GLOSSARY.md',
    'docs/portable-preview.md', 'portable/__init__.py', 'portable/launch.py',
    'portable/demo_seed.py', 'portable/runtime-lock.json', 'portable/quick-start.html',
    'portable/samples/fictional-article.pdf',
    'scripts/build_portable.py', 'scripts/verify_portable.py', 'scripts/check_portable_preview.py',
    'scripts/verify_work_materials.py', 'portable/start.bat', 'portable/stop.bat',
}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def safe_entries(archive):
    seen = set()
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        key = item.filename.rstrip('/').casefold()
        if (item.orig_filename != item.filename or not item.filename or '\\' in item.filename or ':' in item.filename
                or path.is_absolute() or any(p in ('', '.', '..') for p in item.filename.rstrip('/').split('/'))
                or key in seen or stat.S_ISLNK(item.external_attr >> 16)):
            raise ValueError('Unsafe or duplicate archive entry: ' + item.filename)
        seen.add(key)
        yield item


def download(artifact, cache):
    name = artifact['filename']
    if Path(name).name != name:
        raise ValueError('Invalid locked filename')
    url = urllib.parse.urlsplit(artifact['url'])
    if url.scheme != 'https' or url.hostname not in {'www.python.org', 'files.pythonhosted.org'}:
        raise ValueError('Artifact must use the locked official HTTPS host')
    path = cache / name
    if not path.is_file():
        temporary = path.with_suffix('.download')
        with urllib.request.urlopen(artifact['url'], timeout=60) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output)
        temporary.replace(path)
    if digest(path.read_bytes()) != artifact['sha256']:
        raise ValueError('Locked artifact digest mismatch: ' + name)
    return path


def source_paths():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    selected = sorted(p for p in tracked if p and (p in SOURCE_FILES or PurePosixPath(p).parts[0] in SOURCE_DIRS))
    missing = SOURCE_FILES - set(selected)
    if missing:
        raise ValueError('Required versioned source missing: ' + ', '.join(sorted(missing)))
    for name in selected:
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or ROOT not in path.resolve().parents:
            raise ValueError('Source must be a regular file inside checkout: ' + name)
        if PurePosixPath(name).parts[0] in SOURCE_DIRS and path.suffix not in {'.py', '.js', '.css', '.html', '.svg', '.png', '.ico', '.woff2'}:
            raise ValueError('Unexpected application source suffix: ' + name)
        yield name, path


def build(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT))
    if dirty and not args.allow_dirty:
        raise ValueError('Commit reviewed source before release building; --allow-dirty is for pre-acceptance only.')
    if not args.prepare_only and (not args.intro_pdf or not args.intro_pdf.is_file()):
        raise ValueError('--intro-pdf must name the actual approved project introduction PDF.')
    intro = args.intro_pdf.resolve() if args.intro_pdf else None
    if intro and (intro.is_symlink() or not intro.read_bytes().startswith(b'%PDF-')):
        raise ValueError('Introduction must be a regular PDF file.')
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    runtime = dict(lock['python'])
    locked_digest = base64.b64decode(runtime['sigstore']['messageSignature']['messageDigest']['digest']).hex()
    if runtime['sha256'] != locked_digest:
        raise ValueError('Runtime lock differs from official digest evidence.')
    staging = Path(tempfile.mkdtemp(prefix='preview-staging-', dir=output))
    for name, source in source_paths():
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for action in ('start', 'stop'):
        # BAT files use only ASCII and CRLF, so Windows code pages cannot corrupt commands.
        (staging / f'{action}.bat').write_bytes((ROOT / f'portable/{action}.bat').read_text(encoding='utf-8').replace('\r\n', '\n').replace('\n', '\r\n').encode('ascii'))
    shutil.copyfile(ROOT / 'portable/quick-start.html', staging / '使用说明.html')
    if intro:
        shutil.copyfile(intro, staging / '项目介绍.pdf')
    runtime_dir = staging / 'runtime'
    runtime_dir.mkdir()
    with zipfile.ZipFile(download(runtime, cache)) as z:
        for entry in safe_entries(z):
            if not entry.is_dir():
                target = runtime_dir / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(entry))
    # Explicit paths remain isolated from environment, registry and user site; workers use same executable.
    (runtime_dir / 'python312._pth').write_bytes(b'python312.zip\n.\nLib/site-packages\n..\n')
    site = runtime_dir / 'Lib/site-packages'
    site.mkdir(parents=True)
    licenses = []
    for wheel in lock['wheels']:
        with zipfile.ZipFile(download(wheel, cache)) as z:
            found_license = False
            for entry in safe_entries(z):
                if entry.is_dir():
                    continue
                # Chosen wheels have no scripts or .data relocation requirements.
                if '.data' in PurePosixPath(entry.filename).parts[0]:
                    raise ValueError('Unsupported wheel relocation: ' + wheel['filename'])
                target = site / entry.filename
                if target.exists():
                    raise ValueError('Wheel collision: ' + entry.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = z.read(entry)
                target.write_bytes(raw)
                if any(part.lower().startswith(('license', 'copying')) for part in PurePosixPath(entry.filename).parts):
                    found_license = True
                    licenses.append(f"{wheel['name']} {wheel['version']}: runtime/Lib/site-packages/{entry.filename}")
                if entry.filename.endswith('.dist-info/METADATA'):
                    metadata = BytesParser().parsebytes(raw)
                    if metadata['Version'] != wheel['version'] or metadata['Name'].lower() != wheel['name'].lower():
                        raise ValueError('Wheel metadata differs from lock')
            if not found_license:
                raise ValueError('Wheel license not retained: ' + wheel['filename'])
    notices = [
        'Third-party components in this Windows x64 local preview',
        f"CPython {runtime['version']} (Python Software Foundation): runtime/LICENSE.txt",
        'Official source: ' + runtime['url'],
        'Each bundled wheel is retained in full, including DLLs, metadata and license notices.',
        'Versions, official download URLs and SHA256: portable/runtime-lock.json',
        'Application source: https://github.com/normaltank/DataBase',
        'The application has no general public license declaration; inclusion is for the authorized project demonstration.',
        '', *licenses,
    ]
    (staging / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices) + '\n', encoding='utf-8')
    version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT).decode().strip()
    manifest = {'format': 1, 'purpose': 'synthetic local preview', 'source_commit': version,
        'source_tree': tree, 'source_dirty': dirty, 'introduction_present': bool(intro),
        'python': runtime['version'], 'platform': 'Windows 10/11 x64',
        'files': {p.relative_to(staging).as_posix(): {'bytes': p.stat().st_size, 'sha256': digest(p.read_bytes())}
                  for p in sorted(staging.rglob('*')) if p.is_file()}}
    (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    from verify_portable import verify_directory, verify_zip
    verify_directory(staging, require_intro=not args.prepare_only)
    result = {'staging': str(staging), 'source_commit': version, 'source_dirty': dirty, 'complete': False}
    if not args.prepare_only:
        archive = output / ('Zhihui-preview-' + version[:12] + '.zip')
        if archive.exists():
            raise ValueError('Output already exists; choose a fresh output directory.')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name in sorted([*manifest['files'], 'manifest.json']):
                z.write(staging / name, name)
        verify_zip(archive)
        result.update(zip=str(archive), bytes=archive.stat().st_size, sha256=digest(archive.read_bytes()), complete=True)
        (archive.with_suffix('.zip.sha256')).write_text(result['sha256'] + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--cache', type=Path, default=Path(tempfile.gettempdir()) / 'database-portable78-artifacts')
    parser.add_argument('--intro-pdf', type=Path)
    parser.add_argument('--prepare-only', action='store_true', help='Prepare runtime/source only; no shareable ZIP.')
    parser.add_argument('--allow-dirty', action='store_true', help='Record unreleased source for pre-acceptance only.')
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
