"""Malformed distribution archives are rejected at the public verifier CLI."""
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile


class PortableArchiveTests(unittest.TestCase):
    def test_public_verifier_rejects_traversal_absolute_backslash_duplicate_and_symlink(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='portable-invalid-') as temporary:
            for i, (names, expected) in enumerate([
                (['../outside'], 'Unsafe file name'), (['/absolute'], 'Unsafe file name'),
                (['C:/drive'], 'Unsafe file name'), (['a\\secret'], 'Unsafe file name'),
                (['safeXtail'], 'Unsafe file name'),
                (['same', 'SAME'], 'Duplicate case-insensitive'), (['link'], 'symbolic link'),
            ]):
                with self.subTest(names=names):
                    path = Path(temporary) / f'bad-{i}.zip'
                    with warnings.catch_warnings(), zipfile.ZipFile(path, 'w') as z:
                        warnings.simplefilter('ignore', UserWarning)
                        for name in names:
                            item = zipfile.ZipInfo(name)
                            if name == 'link':
                                item.create_system = 3
                                item.external_attr = (stat.S_IFLNK | 0o777) << 16
                            z.writestr(item, b'synthetic only')
                    if names == ['a\\secret']:
                        # ZipInfo normalizes Windows separators on write; mutate the raw stored entry.
                        path.write_bytes(path.read_bytes().replace(b'a/secret', b'a\\secret'))
                    if names == ['safeXtail']:
                        # Python retains the original NUL-bearing ZIP name separately from filename.
                        path.write_bytes(path.read_bytes().replace(b'safeXtail', b'safe\0tail'))
                    result = subprocess.run([sys.executable, str(root / 'scripts/verify_portable.py'), str(path)],
                        capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)
            self.assertFalse((Path(temporary).parent / 'outside').exists())

    def test_public_verifier_rejects_windows_path_aliases_before_manifest_checks(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='portable-windows-alias-') as temporary:
            for alias in ['probe./collision.py', 'probe /collision.py', 'probe/collision.py.', 'probe/collision.py ']:
                with self.subTest(alias=alias):
                    path = Path(temporary) / 'alias.zip'
                    with zipfile.ZipFile(path, 'w') as archive:
                        archive.writestr('static/probe/collision.py', b'first synthetic probe')
                        archive.writestr(f'static/{alias}', b'second synthetic probe')
                    result = subprocess.run([sys.executable, str(root / 'scripts/verify_portable.py'), str(path)],
                        capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Unsafe file name', result.stderr)

    def test_public_verifier_rejects_windows_devices_and_sanitized_names(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='portable-windows-name-') as temporary:
            for name in [
                'NUL.py', 'con/collision.py', 'PRN.py', 'aux.py', 'CoM1.py', 'LPT9/collision.py',
                'COM\u00b9.py', 'LPT\u00b2.py', 'CONIN$.py', 'CONOUT$.py', 'CON .py',
                'probe.py:stream', 'probe<name.py', 'probe>name.py', 'probe"name.py',
                'probe|name.py', 'probe?name.py', 'probe*name.py', 'probe\x1fname.py',
            ]:
                with self.subTest(name=name):
                    path = Path(temporary) / 'name.zip'
                    with zipfile.ZipFile(path, 'w') as archive:
                        archive.writestr('static/' + name, b'synthetic only')
                    result = subprocess.run([sys.executable, str(root / 'scripts/verify_portable.py'), str(path)],
                        capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Unsafe file name', result.stderr)

    def test_builder_requires_actual_intro_before_downloading_or_packaging(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='portable-no-intro-') as temporary:
            result = subprocess.run([sys.executable, str(root / 'scripts/build_portable.py'),
                '--output', temporary, '--cache', str(Path(temporary) / 'cache'), '--allow-dirty'],
                capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--intro-pdf', result.stderr)
            self.assertEqual(list(Path(temporary).rglob('*.zip')), [])


if __name__ == '__main__':
    unittest.main()
