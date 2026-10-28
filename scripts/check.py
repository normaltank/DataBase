"""Run syntax checks and every synthetic unittest, without external research data."""
import os
import py_compile
import sys
import time
import unittest
from pathlib import Path


class SyntheticTestResult(unittest.TextTestResult):
    """Count started test cases unless unittest skips the entire case."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.non_skipped_tests = 0
        self._current_test = None
        self._current_test_skipped = False
        self.slowest_tests = []

    def startTest(self, test):
        self._test_started_at = time.perf_counter()
        self._current_test = test
        self._current_test_skipped = False
        super().startTest(test)

    def addSkip(self, test, reason):
        # Setup placeholders never start a case; subtests do not skip their parent.
        if test is self._current_test:
            self._current_test_skipped = True
        super().addSkip(test, reason)

    def stopTest(self, test):
        # startTest precedes setUp; stopTest follows tearDown and test cleanups.
        elapsed = time.perf_counter() - self._test_started_at
        self.slowest_tests.append((elapsed, test.id()))
        self.slowest_tests.sort(reverse=True)
        del self.slowest_tests[10:]
        if not self._current_test_skipped:
            self.non_skipped_tests += 1
        self._current_test = None
        super().stopTest(test)


def check():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    # This command always means synthetic checks, even in a shell used for an opt-in run.
    os.environ["RUN_THINKTANK_IMPORT_TEST"] = "0"
    print("Checking Python syntax and the complete synthetic test suite.", flush=True)
    sources = [root / "app.py"]
    for folder in ["platform_app", "scripts", "tests"]:
        sources.extend(sorted((root / folder).rglob("*.py")))
    for source in sources:
        py_compile.compile(str(source), doraise=True)
    suite = unittest.TestLoader().discover(str(root / "tests"))
    result = unittest.TextTestRunner(verbosity=2, resultclass=SyntheticTestResult).run(suite)
    print("Slowest test cases (up to 10; includes setUp, tearDown and cleanups; "
          "shared module/class fixtures are included only in total time):", file=sys.stderr)
    for elapsed, test_id in result.slowest_tests:
        print(f"  {elapsed:.3f}s {test_id}", file=sys.stderr)
    if result.non_skipped_tests == 0:
        print("No synthetic tests ran; refusing a successful check.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def main():
    started_at = time.perf_counter()
    try:
        return check()
    finally:
        print(f"Total check time: {time.perf_counter() - started_at:.3f}s", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
