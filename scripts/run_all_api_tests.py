#!/usr/bin/env python3
"""
Centralized API Test Runner for Workflow Engine

This script dynamically discovers and runs all API tests in the project,
providing comprehensive test reporting and deployment gate functionality.
"""

import os
import sys
import unittest
from datetime import datetime


def print_separator(char="=", length=80):
    """Print a consistent separator line."""
    print(char * length)


def print_header(title):
    """Print a formatted header."""
    print_separator("=")
    print(f"🧪 {title}")
    print_separator("=")


def print_test_summary(results, start_time, end_time):
    """Print a comprehensive test summary."""
    run_time = end_time - start_time

    print_separator("-")
    print("📊 TEST SUMMARY")
    print_separator("-")

    # Basic counts
    tests_run = results.testsRun
    errors = len(results.errors)
    failures = len(results.failures)
    skipped = len(results.skipped)
    success_rate = ((tests_run - errors - failures - skipped) / tests_run * 100) if tests_run > 0 else 0

    print(f"Total Tests:      {tests_run}")
    print(f"Passed:          {tests_run - errors - failures - skipped}")
    print(f"Failed:          {failures}")
    print(f"Errors:          {errors}")
    print(f"Skipped:         {skipped}")
    print(f"Success Rate:    {success_rate:.1f}%")
    print(f"Duration:        {run_time.total_seconds():.2f} seconds")

    # Deployment gate logic
    print_separator("-")
    print("🚦 DEPLOYMENT GATE CHECK")
    print_separator("-")

    if tests_run == 0:
        print("❌ NO TESTS EXECUTED")
        print("🔒 DEPLOYMENT BLOCKED - No tests found to validate API")
        return False

    if errors > 0 or failures > 0:
        print(f"❌ TESTS FAILED ({failures} failures, {errors} errors)")
        print("🔒 DEPLOYMENT BLOCKED - All tests must pass")

        # Print detailed failure info
        if failures:
            print("\n💥 TEST FAILURES:")
            for test, traceback in results.failures:
                print(f"  ❌ {test}")

        if errors:
            print("\n🚨 TEST ERRORS:")
            for test, traceback in results.errors:
                print(f"  ⚠️ {test}")

        return False

    if skipped > 0:
        print(f"⚠️  Some tests were skipped ({skipped} tests)")
        print("✅ DEPLOYMENT APPROVED - All executed tests passed")

        # Print skips
        print("\n⏭️  SKIPPED TESTS:")
        for test, reason in results.skipped:
            print(f"  ⏭️  {test}: {reason}")
    else:
        print("✅ ALL TESTS PASSED")
        print("🚀 DEPLOYMENT APPROVED - All tests green!")

    return True


def discover_api_tests():
    """Dynamically discover all API test modules."""
    test_files = []

    # Define test directories to search
    test_dirs = [
        "features/crm/backend",
        "features",  # Future features
        "tests",  # General test directory
    ]

    # Common test file patterns
    test_patterns = ["*api*test*.py", "*api*tests*.py", "test*api*.py"]

    print_header("Discovering API Tests")

    for test_dir in test_dirs:
        if not os.path.exists(test_dir):
            continue

        print(f"🔍 Scanning {test_dir}/")

        # Walk through directory looking for test files
        for root, dirs, files in os.walk(test_dir):
            for pattern in test_patterns:
                # Find matching files
                import fnmatch

                matches = fnmatch.filter(files, pattern)

                for match in matches:
                    test_file = os.path.join(root, match)

                    # Only include files that actually exist, are Python files, and not already added
                    if os.path.isfile(test_file) and test_file.endswith(".py") and test_file not in test_files:
                        test_files.append(test_file)
                        print(f"  ✅ Found API test: {test_file}")

    # Add specific known API test files
    known_api_tests = [
        "features/crm/backend/api_integration_tests.py",
    ]

    # Verify specific files exist
    for known_test in known_api_tests:
        if os.path.exists(known_test) and known_test not in test_files:
            test_files.append(known_test)
            print(f"  ✅ Found known API test: {known_test}")

    return test_files


def run_api_tests():
    """Run all discovered API tests."""

    # Add current directory to Python path for imports
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)  # Go up one level from scripts/ to project root
    sys.path.insert(0, project_root)

    start_time = datetime.now()

    print_header("Workflow Engine API Test Suite")
    print(f"Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version}")

    # Discover test files
    test_files = discover_api_tests()

    if not test_files:
        print("❌ No API test modules found!")
        print("💡 Make sure your test files follow naming conventions:")
        print("   - *api*test*.py")
        print("   - *api*tests*.py")
        print("   - Located in features/*/backend/ directories")
        return False

    print(f"\n📋 Found {len(test_files)} test file(s)")

    # Set up test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    print_header("Loading Test Modules")

    for test_file in test_files:
        try:
            print(f"📦 Loading: {test_file}")

            # Use direct file loading approach
            # Strip file extension and convert to module name
            module_name = test_file.replace("/", ".").replace("\\", ".").replace(".py", "")

            # Load tests from the module using file path
            import importlib.util

            spec = importlib.util.spec_from_file_location(module_name, test_file)
            if spec is None:
                print(f"  ⚠️  Warning: Could not create spec for {test_file}")
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find test classes in the module
            test_cases = []
            for name in dir(module):
                obj = getattr(module, name)
                if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and obj != unittest.TestCase:
                    test_cases.append(obj)

            # Load tests from discovered test classes
            for test_case in test_cases:
                tests = loader.loadTestsFromTestCase(test_case)
                suite.addTests(tests)

            test_count = sum(
                tests.countTestCases() for tests in [loader.loadTestsFromTestCase(tc) for tc in test_cases]
            )
            print(f"  ✅ Loaded {test_count} test(s) from {len(test_cases)} test class(es)")

        except Exception as e:
            print(f"  ⚠️  Warning: Could not load {test_file}: {e}")
            continue

    if suite.countTestCases() == 0:
        print("❌ No test cases found in discovered modules!")
        return False

    print(f"\n🚀 Running {suite.countTestCases()} test case(s)")
    print_separator("-")

    # Run tests with detailed output
    runner = unittest.TextTestRunner(
        verbosity=2,  # Detailed output
        stream=sys.stdout,
        descriptions=True,
    )

    try:
        results = runner.run(suite)
        end_time = datetime.now()

        print_separator()

        # Print comprehensive summary
        deployment_approved = print_test_summary(results, start_time, end_time)

        print_separator()

        return deployment_approved

    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return False


def main():
    """Main entry point."""
    try:
        success = run_api_tests()

        # Exit with appropriate code
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n⏹️  Test execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
