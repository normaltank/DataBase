"""Exercise test discovery and the check command without any external dataset."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_OPT_IN = "RUN_THINKTANK_IMPORT_TEST"
FILESYSTEM_GUARD = r'''
import builtins
import io
import os
from contextlib import ExitStack
from unittest.mock import patch

def guarded(operation):
    def call(path, *args, **kwargs):
        if isinstance(path, (str, bytes, os.PathLike)):
            text = os.fsdecode(path).replace("\\", "/").casefold()
            if "thinktank" in text.split("/"):
                raise AssertionError("External ThinkTank filesystem access was attempted")
        return operation(path, *args, **kwargs)
    return call

guards = ExitStack()
for owner, name in [(os, "stat"), (os, "lstat"), (os, "scandir"), (os, "open"),
                    (builtins, "open"), (io, "open")]:
    guards.enter_context(patch.object(owner, name, guarded(getattr(owner, name))))
'''


class CheckCommandTests(unittest.TestCase):
    def checkout(self, test_source, app_source="value = 1\n"):
        directory = tempfile.TemporaryDirectory(prefix="synthetic-check-command-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for folder in ["scripts", "platform_app", "tests"]:
            (root / folder).mkdir()
        shutil.copyfile(ROOT / "scripts/check.py", root / "scripts/check.py")
        (root / "app.py").write_text(app_source, encoding="utf-8")
        (root / "platform_app/__init__.py").write_text("", encoding="utf-8")
        (root / "tests/test_fixture.py").write_text(test_source, encoding="utf-8")
        return root

    def run_check(self, root):
        env = {**os.environ, EXTERNAL_OPT_IN: "1", "PYTHONIOENCODING": "utf-8"}
        script = FILESYSTEM_GUARD + '''
import runpy
runpy.run_path("scripts/check.py", run_name="__main__")
'''
        return subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def test_default_discovery_never_probes_external_data(self):
        script = FILESYSTEM_GUARD + r'''
import unittest
loader = unittest.TestLoader()
loader.discover("tests")
assert not loader.errors, "\n".join(loader.errors)
suite = loader.loadTestsFromName("test_platform.PlatformTests.test_real_import_is_idempotent_and_read_only")
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and result.testsRun == 1 and len(result.skipped) == 1
guards.close()
'''
        env = os.environ.copy()
        env.pop(EXTERNAL_OPT_IN, None)
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_command_runs_synthetic_suite_despite_inherited_external_opt_in(self):
        root = self.checkout('''
import os
import unittest
from pathlib import Path
if os.environ.get("RUN_THINKTANK_IMPORT_TEST") == "1":
    Path("D:/Agent Workspace/ThinkTank").is_dir()
class SyntheticFixture(unittest.TestCase):
    def test_sample(self):
        print("SYNTHETIC_SAMPLE_EXECUTED")
        self.assertNotEqual(os.environ.get("RUN_THINKTANK_IMPORT_TEST"), "1")
''')
        result = self.run_check(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SYNTHETIC_SAMPLE_EXECUTED", result.stdout)
        self.assertIn("Ran 1 test", result.stderr)

    def test_check_command_propagates_test_failure_and_syntax_errors(self):
        failing = self.checkout('''
import unittest
class SyntheticFixture(unittest.TestCase):
    def test_sample(self):
        self.fail("deliberate synthetic failure")
''')
        result = self.run_check(failing)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("deliberate synthetic failure", result.stderr)
        invalid = self.checkout("", app_source="def invalid syntax\n")
        result = self.run_check(invalid)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SyntaxError", result.stderr)

    def test_check_command_rejects_empty_and_entirely_skipped_suites(self):
        for source in ["", '''
import unittest
class SyntheticFixture(unittest.TestCase):
    @unittest.skip("synthetic skipped test")
    def test_sample(self):
        pass
''']:
            with self.subTest(source=source):
                result = self.run_check(self.checkout(source))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("No synthetic tests ran", result.stderr)
