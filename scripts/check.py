"""Run syntax checks and every synthetic unittest, without external research data."""
import os
import py_compile
import sys
import unittest
from pathlib import Path


class SyntheticTestResult(unittest.TextTestResult):
    """Count started test cases unless unittest skips the entire case."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.non_skipped_tests = 0
        self._current_test = None
        self._current_test_skipped = False

    def startTest(self, test):
        self._current_test = test
        self._current_test_skipped = False
        super().startTest(test)

    def addSkip(self, test, reason):
        # Setup placeholders never start a case; subtests do not skip their parent.
        if test is self._current_test:
            self._current_test_skipped = True
        super().addSkip(test, reason)

    def stopTest(self, test):
        if not self._current_test_skipped:
            self.non_skipped_tests += 1
        self._current_test = None
        super().stopTest(test)


def main():
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
    if result.non_skipped_tests == 0:
        print("No synthetic tests ran; refusing a successful check.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
