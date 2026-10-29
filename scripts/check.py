"""Run syntax checks and every synthetic unittest, without external research data."""
import argparse
import hashlib
import json
import os
import py_compile
import sys
import time
import unittest
from collections import Counter
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


def test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def shard_plan(suite, count):
    """Assign complete modules, preserving discovery order within each shard."""
    cases = list(test_cases(suite))
    if not cases:
        raise ValueError("No synthetic tests discovered; refusing an empty shard plan.")
    modules = {}
    for case in cases:
        modules.setdefault(type(case).__module__, []).append(case)
    if count > len(modules):
        raise ValueError("Shard count exceeds discovered modules and would leave empty shards.")
    assignments, sizes = {}, [0] * count
    for module, members in modules.items():
        index = min(range(count), key=lambda index: (sizes[index], index))
        assignments[module] = index
        sizes[index] += len(members)
    shards = [[] for _ in range(count)]
    for case in cases:
        shards[assignments[type(case).__module__]].append(case)
    full_ids = Counter(case.id() for case in cases)
    combined, seen = Counter(), set()
    descriptions = []
    for index, members in enumerate(shards):
        if not members:
            raise ValueError(f"Shard {index + 1}/{count} is empty; reduce shard count.")
        ids = Counter(case.id() for case in members)
        if seen.intersection(ids):
            raise ValueError("Test IDs overlap across shards; refusing ambiguous coverage.")
        seen.update(ids)
        combined.update(ids)
        descriptions.append({"index": index + 1, "tests": len(members),
                             "modules": len({type(case).__module__ for case in members}),
                             "digest": digest(sorted(ids.elements()))})
    if combined != full_ids:
        raise ValueError("Shard test-ID multiset differs from full discovery.")
    plan = {"algorithm": "whole-module-greedy-count-v1", "shard_count": count,
            "full": {"tests": len(cases), "modules": len(modules),
                     "digest": digest(sorted(full_ids.elements()))},
            "shards": descriptions, "coverage_verified": True}
    plan["plan_digest"] = digest(plan)
    return shards, plan


def check(shard_index=None, shard_count=None, plan_only=False, expected_plan_digest=None):
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    # This command always means synthetic checks, even in a shell used for an opt-in run.
    os.environ["RUN_THINKTANK_IMPORT_TEST"] = "0"
    message = ("Checking Python syntax and the complete synthetic test suite." if shard_count is None
               else "Checking Python syntax and complete synthetic test discovery before sharding.")
    print(message,
          file=sys.stderr if plan_only else sys.stdout, flush=True)
    sources = [root / "app.py"]
    for folder in ["platform_app", "scripts", "tests"]:
        sources.extend(sorted((root / folder).rglob("*.py")))
    for source in sources:
        py_compile.compile(str(source), doraise=True)
    loader = unittest.TestLoader()
    suite = loader.discover(str(root / "tests"))
    if shard_count is not None:
        if loader.errors:
            raise ValueError("Cannot partition test discovery errors:\n" + "\n".join(loader.errors))
        shards, plan = shard_plan(suite, shard_count)
        if expected_plan_digest is not None and expected_plan_digest != plan["plan_digest"]:
            raise ValueError("Actual discovery differs from the expected shard plan; no tests executed.")
        if plan_only:
            print(json.dumps(plan, sort_keys=True), flush=True)
            print("Plan only; no tests executed.", file=sys.stderr)
            return 0
        suite = unittest.TestSuite(shards[shard_index - 1])
        print(f"Synthetic shard {shard_index}/{shard_count}: {suite.countTestCases()} tests; "
              f"full discovery {plan['full']['tests']} tests; plan {plan['plan_digest']}", flush=True)
    result = unittest.TextTestRunner(verbosity=2, resultclass=SyntheticTestResult).run(suite)
    print(f"Synthetic execution: started={result.testsRun}, non-skipped={result.non_skipped_tests}, "
          f"skipped={len(result.skipped)}", file=sys.stderr)
    print("Slowest test cases (up to 10; includes setUp, tearDown and cleanups; "
          "shared module/class fixtures are included only in total time):", file=sys.stderr)
    for elapsed, test_id in result.slowest_tests:
        print(f"  {elapsed:.3f}s {test_id}", file=sys.stderr)
    if result.non_skipped_tests == 0:
        print("No synthetic tests ran; refusing a successful check.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    started_at = time.perf_counter()
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--shard-index", type=int, help="1-based shard to execute")
        parser.add_argument("--shard-count", type=int, help="number of whole-module shards")
        parser.add_argument("--plan", action="store_true", help="check syntax and emit JSON coverage plan without running tests")
        parser.add_argument("--expected-plan-digest", help="require this plan SHA-256 before executing a shard")
        args = parser.parse_args(argv)
        if args.plan:
            if args.shard_index is not None:
                parser.error("--plan does not accept --shard-index")
            if args.shard_count is None:
                args.shard_count = 1
        elif (args.shard_index is None) != (args.shard_count is None):
            parser.error("--shard-index and --shard-count must be supplied together")
        if args.shard_count is not None and args.shard_count < 1:
            parser.error("--shard-count must be positive")
        if args.shard_index is not None and not 1 <= args.shard_index <= args.shard_count:
            parser.error("--shard-index must be between 1 and --shard-count")
        if args.expected_plan_digest is not None and (args.plan or args.shard_index is None):
            parser.error("--expected-plan-digest requires shard execution")
        return check(args.shard_index, args.shard_count, args.plan, args.expected_plan_digest)
    finally:
        print(f"Total check time: {time.perf_counter() - started_at:.3f}s", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
