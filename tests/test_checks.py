"""Exercise test discovery and the check command without any external dataset."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import Counter
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

    def run_check(self, root, *args):
        env = {**os.environ, EXTERNAL_OPT_IN: "1", "PYTHONIOENCODING": "utf-8"}
        script = FILESYSTEM_GUARD + '''
import runpy
import sys
sys.argv = ["scripts/check.py", *sys.argv[1:]]
runpy.run_path("scripts/check.py", run_name="__main__")
'''
        return subprocess.run([sys.executable, "-c", script, *args], cwd=root, env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def test_shard_command_runs_only_selected_whole_module(self):
        root = self.checkout('''
import unittest
class FirstFixture(unittest.TestCase):
    def test_one(self): print("FIRST_MODULE_EXECUTED")
    def test_two(self): pass
''')
        (root / "tests/test_zulu.py").write_text('''
import unittest
class LastFixture(unittest.TestCase):
    def test_only(self): print("LAST_MODULE_EXECUTED")
''', encoding="utf-8")
        result = self.run_check(root, "--shard-index", "2", "--shard-count", "2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("LAST_MODULE_EXECUTED", result.stdout)
        self.assertNotIn("FIRST_MODULE_EXECUTED", result.stdout)
        self.assertIn("Ran 1 test", result.stderr)

    def test_windows_gate_requires_both_successes_and_identical_nonempty_plans(self):
        workflow = (ROOT / ".github/workflows/check.yml").read_text(encoding="utf-8")
        gate = workflow.split("  windows_gate:\n", 1)[1]
        self.assertIn("name: Python 3.12 / windows-latest\n", gate)
        self.assertIn("needs: [windows_one, windows_two]", gate)
        self.assertIn("if: ${{ always() }}", gate)
        self.assertIn("shell: python", gate)
        code = textwrap.dedent(gate.split("        run: |\n", 1)[1])
        head = {"SHA_ONE": "expected", "SHA_TWO": "expected", "EXPECTED_SHA": "expected"}
        for first, second, plan_a, plan_b, succeeds in [
            ("success", "success", "same", "same", True),
            ("success", "success", "first", "second", False),
            ("success", "success", "", "", False),
            ("success", "success", "same", "", False),
        ] + [(status, "success", "same", "same", False) for status in ("failure", "cancelled", "skipped")] + [
            ("success", status, "same", "same", False) for status in ("failure", "cancelled", "skipped")
        ]:
            with self.subTest(first=first, second=second, plans=(plan_a, plan_b)):
                env = {**os.environ, "SHARD_ONE_RESULT": first, "SHARD_TWO_RESULT": second,
                       "PLAN_ONE": plan_a, "PLAN_TWO": plan_b, **head}
                result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, succeeds, result.stdout + result.stderr)
        for invalid in [{"SHA_ONE": "different"}, {"SHA_TWO": "different"},
                        {"SHA_ONE": ""}, {"SHA_TWO": ""}, {"EXPECTED_SHA": ""}]:
            with self.subTest(invalid_head=invalid):
                env = {**os.environ, **head, **invalid, "SHARD_ONE_RESULT": "success",
                       "SHARD_TWO_RESULT": "success", "PLAN_ONE": "same", "PLAN_TWO": "same"}
                result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shards_match_full_multiset_and_preserve_module_class_fixture_order(self):
        root = self.checkout('''
import unittest
def setUpModule(): print("EVENT module setup")
def tearDownModule(): print("EVENT module teardown")
class First(unittest.TestCase):
    @classmethod
    def setUpClass(cls): print("EVENT first setup")
    @classmethod
    def tearDownClass(cls): print("EVENT first teardown")
    def test_one(self): print("EVENT first test")
class Second(unittest.TestCase):
    @classmethod
    def setUpClass(cls): print("EVENT second setup")
    @classmethod
    def tearDownClass(cls): print("EVENT second teardown")
    def test_two(self): print("EVENT second test")
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([First("test_one"), First("test_one"), Second("test_two")])
''')
        (root / "tests/test_zulu.py").write_text('''
import unittest
def setUpModule(): print("EVENT zulu setup")
def tearDownModule(): print("EVENT zulu teardown")
class Last(unittest.TestCase):
    def test_last(self): print("EVENT last test")
''', encoding="utf-8")
        full = self.run_check(root)
        self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
        plan_result = self.run_check(root, "--plan", "--shard-count", "2")
        self.assertEqual(plan_result.returncode, 0, plan_result.stdout + plan_result.stderr)
        plan = json.loads(plan_result.stdout)
        self.assertTrue(plan["coverage_verified"])
        self.assertEqual(plan["full"]["tests"], 4)
        self.assertEqual(plan["full"]["modules"], 2)
        self.assertEqual([shard["tests"] for shard in plan["shards"]], [3, 1])
        self.assertEqual(plan_result.stdout, self.run_check(root, "--plan", "--shard-count", "2").stdout)
        self.assertIn("Plan only; no tests executed", plan_result.stderr)
        self.assertNotIn("EVENT", plan_result.stdout + plan_result.stderr)
        parts = [self.run_check(root, "--shard-index", str(index), "--shard-count", "2",
                                "--expected-plan-digest", plan["plan_digest"]) for index in (1, 2)]
        for part in parts:
            self.assertEqual(part.returncode, 0, part.stdout + part.stderr)
        self.assertIn("Synthetic execution: started=3, non-skipped=3, skipped=0", parts[0].stderr)
        self.assertIn("Synthetic execution: started=1, non-skipped=1, skipped=0", parts[1].stderr)
        def ids(result):
            return re.findall(r"^test_\w+ \(([^)]+)\) \.\.\.", result.stderr, re.MULTILINE)
        expected = ["test_fixture.First.test_one", "test_fixture.First.test_one",
                    "test_fixture.Second.test_two", "test_zulu.Last.test_last"]
        self.assertEqual(ids(full), expected)
        self.assertEqual([ids(part) for part in parts], [expected[:3], expected[3:]])
        self.assertEqual(Counter(ids(parts[0]) + ids(parts[1])), Counter(ids(full)))
        self.assertFalse(set(ids(parts[0])) & set(ids(parts[1])))
        events = lambda result: [line for line in result.stdout.splitlines() if line.startswith("EVENT")]
        self.assertEqual(events(full), ["EVENT module setup", "EVENT first setup", "EVENT first test",
                                      "EVENT first test", "EVENT first teardown", "EVENT second setup",
                                      "EVENT second test", "EVENT second teardown", "EVENT module teardown",
                                      "EVENT zulu setup", "EVENT last test", "EVENT zulu teardown"])
        self.assertEqual(events(parts[0]) + events(parts[1]), events(full))
        mismatch = self.run_check(root, "--shard-index", "1", "--shard-count", "2",
                                  "--expected-plan-digest", "wrong-plan")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("Actual discovery differs", mismatch.stderr)
        self.assertNotIn("EVENT", mismatch.stdout)

    def test_shard_arguments_and_empty_shards_cannot_succeed(self):
        root = self.checkout("import unittest\nclass Sample(unittest.TestCase):\n def test_ok(self): pass\n")
        for args in [("--shard-index", "1"), ("--shard-count", "2"),
                     ("--shard-index", "0", "--shard-count", "2"),
                     ("--shard-index", "3", "--shard-count", "2"),
                     ("--shard-index", "1", "--shard-count", "0"),
                     ("--plan", "--shard-count", "-1"),
                     ("--shard-index", "2", "--shard-count", "2"),
                     ("--plan", "--shard-count", "2"),
                     ("--plan", "--shard-index", "1"),
                     ("--expected-plan-digest", "a"), ("--unexpected",)]:
            with self.subTest(args=args):
                result = self.run_check(root, *args)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("Ran 1 test", result.stderr)
                self.assertRegex(result.stderr, r"Total check time: [0-9.]+s")

    def test_shard_checks_keep_failure_skip_syntax_and_external_guards(self):
        sources = {
            "empty": "",
            "skip": 'import unittest\n@unittest.skip("all skipped")\nclass Sample(unittest.TestCase):\n def test_one(self): pass\n',
            "module_skip": 'import unittest\ndef setUpModule(): raise unittest.SkipTest("module skipped")\nclass Sample(unittest.TestCase):\n def test_one(self): pass\n',
            "class_skip": 'import unittest\nclass Sample(unittest.TestCase):\n @classmethod\n def setUpClass(cls): raise unittest.SkipTest("class skipped")\n def test_one(self): pass\n',
            "failure": 'import unittest\nclass Sample(unittest.TestCase):\n def test_one(self): self.fail("deliberate shard failure")\n',
            "import_error": 'raise RuntimeError("discovery error fixture")\n',
        }
        for name, source in sources.items():
            with self.subTest(case=name):
                result = self.run_check(self.checkout(source), "--shard-index", "1", "--shard-count", "1")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                if name in {"skip", "module_skip", "class_skip"}:
                    self.assertIn("No synthetic tests ran", result.stderr)
                if name == "failure":
                    self.assertIn("deliberate shard failure", result.stderr)
                if name == "import_error":
                    self.assertIn("Cannot partition test discovery errors", result.stderr)
        empty_plan = self.run_check(self.checkout(""), "--plan", "--shard-count", "2")
        self.assertNotEqual(empty_plan.returncode, 0)
        root = self.checkout('''
import os
import unittest
from pathlib import Path
if os.environ.get("RUN_THINKTANK_IMPORT_TEST") == "1":
    Path("D:/Agent Workspace/ThinkTank").is_dir()
class Sample(unittest.TestCase):
    def test_one(self):
        self.assertEqual(os.environ["RUN_THINKTANK_IMPORT_TEST"], "0")
''')
        result = self.run_check(root, "--shard-index", "1", "--shard-count", "1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Syntax validation still includes application sources outside test discovery.
        (root / "platform_app/unimported.py").write_text("def invalid syntax\n", encoding="utf-8")
        invalid = self.run_check(root, "--shard-index", "1", "--shard-count", "1")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("SyntaxError", invalid.stderr)

    def test_shard_plan_rejects_overlapping_ids_from_distinct_modules(self):
        source = '''
import unittest
class Ambiguous(unittest.TestCase):
    def id(self): return "shared.custom.id"
    def test_one(self): pass
'''
        root = self.checkout(source)
        (root / "tests/test_zulu.py").write_text(source, encoding="utf-8")
        result = self.run_check(root, "--plan", "--shard-count", "2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Test IDs overlap across shards", result.stderr)

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

    def test_check_command_reports_total_and_bounded_slowest_case_lifecycles(self):
        root = self.checkout('''
import time
import unittest
class SlowFixture(unittest.TestCase):
    def setUp(self):
        time.sleep(0.12)
        self.addCleanup(time.sleep, 0.05)
    def tearDown(self):
        time.sleep(0.08)
    def test_lifecycle(self):
        pass
class FastFixture(unittest.TestCase):
    pass
for number in range(11):
    setattr(FastFixture, f"test_fast_{number:02}", lambda self: None)
''')
        result = self.run_check(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ran 12 tests", result.stderr)
        total = re.search(r"Total check time: ([0-9.]+)s", result.stderr)
        self.assertIsNotNone(total, result.stderr)
        timings = re.findall(r"^  ([0-9.]+)s (test_fixture\S+)$", result.stderr, re.MULTILINE)
        self.assertEqual(len(timings), 10, result.stderr)
        durations = [float(seconds) for seconds, _ in timings]
        self.assertEqual(durations, sorted(durations, reverse=True))
        self.assertEqual(timings[0][1], "test_fixture.SlowFixture.test_lifecycle")
        # Empty body: the measured cost must include setup, teardown and cleanup.
        self.assertGreaterEqual(durations[0], 0.22)
        self.assertGreaterEqual(float(total.group(1)), durations[0])

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
        self.assertRegex(result.stderr, r"Total check time: [0-9.]+s")
        self.assertRegex(result.stderr, r"  [0-9.]+s test_fixture.SyntheticFixture.test_sample")
        invalid = self.checkout("", app_source="def invalid syntax\n")
        result = self.run_check(invalid)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SyntaxError", result.stderr)
        self.assertRegex(result.stderr, r"Total check time: [0-9.]+s")

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

    def test_check_command_rejects_suites_skipped_during_setup(self):
        fixtures = {
            "module": '''
import unittest
def setUpModule():
    raise unittest.SkipTest("module setup skipped")
class SyntheticFixture(unittest.TestCase):
    def test_sample(self):
        self.fail("setup skip must prevent execution")
''',
            "class": '''
import unittest
class SyntheticFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise unittest.SkipTest("class setup skipped")
    def test_sample(self):
        self.fail("setup skip must prevent execution")
''',
            "test": '''
import unittest
class SyntheticFixture(unittest.TestCase):
    def setUp(self):
        self.skipTest("test setup skipped")
    def test_sample(self):
        self.fail("setup skip must prevent execution")
''',
        }
        for name, source in fixtures.items():
            with self.subTest(setup=name):
                result = self.run_check(self.checkout(source))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("No synthetic tests ran", result.stderr)
                self.assertIn(f"{name} setup skipped", result.stderr)

    def test_check_command_accepts_executed_test_alongside_class_setup_skip(self):
        root = self.checkout('''
import unittest
class SkippedFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise unittest.SkipTest("class setup skipped")
    def test_sample(self):
        self.fail("setup skip must prevent execution")
class SyntheticFixture(unittest.TestCase):
    def test_sample(self):
        print("SYNTHETIC_SAMPLE_EXECUTED")
        self.assertEqual(2 + 2, 4)
''')
        result = self.run_check(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SYNTHETIC_SAMPLE_EXECUTED", result.stdout)
        self.assertIn("class setup skipped", result.stderr)

    def test_check_command_accepts_executed_test_with_skipped_subtest(self):
        root = self.checkout('''
import unittest
class SyntheticFixture(unittest.TestCase):
    def test_sample(self):
        with self.subTest(part="optional"):
            self.skipTest("optional subtest skipped")
        self.assertEqual(2 + 2, 4)
        print("SYNTHETIC_SAMPLE_EXECUTED")
''')
        result = self.run_check(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SYNTHETIC_SAMPLE_EXECUTED", result.stdout)
        self.assertIn("optional subtest skipped", result.stderr)
