"""Run syntax checks and every synthetic unittest, without external research data."""
import os
import py_compile
import sys
import unittest
from pathlib import Path


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
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun == len(result.skipped):
        print("No synthetic tests ran; refusing a successful check.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
