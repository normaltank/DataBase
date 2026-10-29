"""Malformed distribution archives are rejected at the public verifier CLI."""
import os
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
                    result = subprocess.run([sys.executable, str(root / 'scripts/verify_portable.py'), str(path)],
                        capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)
            self.assertFalse((Path(temporary).parent / 'outside').exists())

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
