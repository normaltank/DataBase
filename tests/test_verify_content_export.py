"""Exercise the standalone CLI using independently authored ZIPs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_content_export.py'
ABC = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


class VerifyExportTests(unittest.TestCase):
    def run_zip(self, entries, manifest, expected=0, digest=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'sample.zip'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(path, 'w') as archive:
                    for name, data in entries:
                        archive.writestr(name, data)
                    archive.writestr('manifest.json', json.dumps(manifest))
            args = [sys.executable, '-I', str(SCRIPT), str(path)]
            if digest:
                args += ['--sha256', hashlib.sha256(path.read_bytes()).hexdigest() if digest == 'correct' else digest]
            result = subprocess.run(args, cwd=temp, capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return result

    def manifest(self):
        return {'format': 'research-content-manifest-v1', 'files': [{'path': 'a.txt', 'bytes': 3, 'sha256': ABC}]}

    def test_independently_built_zip_passes_from_unrelated_directory(self):
        self.run_zip([('a.txt', b'abc')], self.manifest(), digest='correct')

    def test_missing_replaced_extra_and_duplicate_files_fail(self):
        for entries in [[], [('a.txt', b'abd')], [('a.txt', b'abc'), ('extra.txt', b'x')], [('a.txt', b'abc'), ('a.txt', b'abc')]]:
            with self.subTest(entries=entries):
                self.run_zip(entries, self.manifest(), 1)

    def test_unsafe_paths_and_schema_fail(self):
        for name in ['../a.txt', '/a.txt', 'C:/a.txt', 'a\\b.txt', 'a//b.txt', './a.txt', 'a/../b.txt', 'a.txt:stream', 'a./b.txt', 'CON.txt']:
            manifest = self.manifest()
            manifest['files'][0]['path'] = name
            with self.subTest(name=name):
                self.run_zip([(name, b'abc')], manifest, 1)
        for manifest in [{}, [], {'format': 'future', 'files': []}, {'format': 'research-content-manifest-v1', 'files': [None]}]:
            self.run_zip([('a.txt', b'abc')], manifest, 1)
        for key, value in [('bytes', True), ('bytes', -1), ('bytes', 4), ('sha256', 'broken'), ('sha256', '0' * 64)]:
            manifest = self.manifest()
            manifest['files'][0][key] = value
            self.run_zip([('a.txt', b'abc')], manifest, 1)
        manifest = self.manifest()
        manifest['files'] *= 2
        self.run_zip([('a.txt', b'abc')], manifest, 1)

    def test_trusted_whole_zip_digest_mismatch_fails(self):
        self.run_zip([('a.txt', b'abc')], self.manifest(), 1, '0' * 64)

    def test_non_zip_and_malformed_json_are_clean_failures(self):
        for data in [b'not a zip', b'PK\x03\x04broken']:
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'bad.zip'
                path.write_bytes(data)
                result = subprocess.run([sys.executable, '-I', str(SCRIPT), str(path)], cwd=temp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)
        for text in ['not json', '{"format":"research-content-manifest-v1","format":"research-content-manifest-v1","files":[]}']:
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'bad.zip'
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('manifest.json', text)
                result = subprocess.run([sys.executable, '-I', str(SCRIPT), str(path)], cwd=temp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)
