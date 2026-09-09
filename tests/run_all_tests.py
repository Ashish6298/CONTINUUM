"""
Project Continuum - Test Suite Runner & Verification Engine
===========================================================
Executes all unit tests, verifies state isolation, validates schemas,
and outputs formatted test execution summaries.
"""

import sys
import unittest
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_test_suite() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(PROJECT_ROOT / "tests"), pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    start_time = time.time()
    result = runner.run(suite)
    duration = time.time() - start_time

    print("\n" + "=" * 80)
    print(f"CONTINUUM TEST EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Passed:         {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures:       {len(result.failures)}")
    print(f"Errors:         {len(result.errors)}")
    print(f"Duration:       {duration:.3f}s")
    print(f"Overall Status: {'SUCCESS (100% Passed)' if result.wasSuccessful() else 'FAILED'}")
    print("=" * 80)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_test_suite())
