"""
run_tests.py - Test Runner Script for Onelab Payment Reconciliation

Executes the full test suite in tests/test_reconciliation.py.
Usage:
    python run_tests.py
"""

import sys
import pytest

if __name__ == "__main__":
    print("=" * 70)
    print("Running Onelab Payment Reconciliation Test Suite (17 Tests)...")
    print("=" * 70)
    exit_code = pytest.main(["-v", "tests/test_reconciliation.py"])
    if exit_code == 0:
        print("\n🎉 ALL 17 TESTS PASSED SUCCESSFULLY!")
    else:
        print(f"\n❌ Test run failed with exit code: {exit_code}")
    sys.exit(exit_code)

