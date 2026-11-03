"""Malformed distribution archives are rejected at the public verifier CLI."""
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
import os
import shutil
import time


class PortableArchiveTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Portable process ownership uses Windows byte locks')
    def test_portable_stop_waits_for_held_server_lock_and_delayed_release(self):
        root = Path(__file__).resolve().parents[1]
        helper = '''
import importlib.util, sys, time
from pathlib import Path
path, action = Path(sys.argv[1]), sys.argv[2]
spec = importlib.util.spec_from_file_location('synthetic_portable', path)
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
with launch.lock('server.lock', timeout=0):
    if action == 'hold':
        (launch.STATE / 'held').touch()
        while not (launch.STATE / 'release').exists():
            time.sleep(.02)
'''
        with tempfile.TemporaryDirectory(prefix='portable-owned-lock-') as tmp:
            copy = Path(tmp)
            (copy / 'portable').mkdir()
            state = copy / '.portable'
            state.mkdir()
            launch = copy / 'portable/launch.py'
            shutil.copyfile(root / 'portable/launch.py', launch)
            holder = subprocess.Popen([sys.executable, '-c', helper, str(launch), 'hold'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stop = None
            try:
                deadline = time.monotonic() + 15
                while not (state / 'held').exists():
                    self.assertIsNone(holder.poll(), 'lock holder exited before becoming ready')
                    self.assertLess(time.monotonic(), deadline, 'lock holder did not become ready')
                    time.sleep(.05)
                with self.subTest(action='busy-probe'):
                    busy = subprocess.run([sys.executable, '-c', helper, str(launch), 'probe'],
                        capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(busy.returncode, 0)
                    self.assertIn('This copy is busy', busy.stderr)
                    self.assertEqual(busy.stderr.strip().splitlines()[-1],
                                     'RuntimeError: This copy is busy. Wait and try again.')
                stop = subprocess.Popen([sys.executable, '-I', '-B', str(launch), 'stop'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                time.sleep(.8)
                with self.subTest(action='wait-until-released'):
                    self.assertIsNone(stop.poll(), 'stop must wait while this copy still owns its server lock')
                (state / 'release').touch()
                stdout, stderr = stop.communicate(timeout=15)
                with self.subTest(action='stop-after-release'):
                    self.assertEqual(stop.returncode, 0, stderr)
                    self.assertIn('This portable copy is stopped', stdout)
                holder.communicate(timeout=10)
                self.assertEqual(holder.returncode, 0)
            finally:
                for child in (stop, holder):
                    if child is not None:
                        if child.poll() is None:
                            child.kill()  # Only these synthetic children, never a recorded PID.
                        child.communicate(timeout=10)

    def test_builder_checks_actual_html_introduction_before_runtime_download(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='portable-intro-html-') as temporary:
            intro = Path(temporary) / 'intro.html'
            intro.write_text('This is not an HTML document.', encoding='utf-8')
            result = subprocess.run([sys.executable, str(root / 'scripts/build_portable.py'),
                '--output', temporary, '--cache', str(Path(temporary) / 'cache'), '--allow-dirty',
                '--intro-html', str(intro)], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Introduction must be a regular UTF-8 HTML document', result.stderr)
            self.assertEqual(list(Path(temporary).rglob('*.download')), [])

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
