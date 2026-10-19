#!/usr/bin/env python3
"""
Game-Room Unified - Master Test Runner.
Executes all test suites across the project:
1. Backend Server Tests (FastAPI / SQLite / Auth / Sync)
2. Android Sync Engine Client Tests (Node.js)
3. End-to-End Real Integration Tests (Android Engine <-> Live FastAPI Server)
"""
import sys
import os
import subprocess
import time

def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def run_suite(name, cmd, cwd):
    print_header(f"RUNNING: {name}")
    start = time.time()
    res = subprocess.run(cmd, cwd=cwd)
    duration = time.time() - start
    if res.returncode == 0:
        print(f"\n[PASS] {name} ({duration:.2f}s)")
        return True
    else:
        print(f"\n[FAIL] {name} (exit code: {res.returncode}, {duration:.2f}s)")
        return False

def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tests_dir = os.path.join(repo_root, "tests")

    suites = [
        (
            "Backend Server Unit Tests (48 tests)",
            [sys.executable, "-m", "unittest", "discover", "-s", os.path.join(tests_dir, "server")],
            repo_root
        ),
        (
            "Android Client Sync Engine Unit Tests (24 suites)",
            ["node", os.path.join(tests_dir, "android", "test_sync_engine.js")],
            repo_root
        ),
        (
            "E2E Integration Test Matrix (16 real scenarios)",
            [sys.executable, os.path.join(tests_dir, "e2e", "run_e2e_integration_tests.py")],
            repo_root
        )
    ]

    all_passed = True
    results = []

    for name, cmd, cwd in suites:
        passed = run_suite(name, cmd, cwd)
        results.append((name, passed))
        if not passed:
            all_passed = False

    print_header("SUMMARY TEST REPORT")
    for name, passed in results:
        status = "PASSED [OK]" if passed else "FAILED [X]"
        print(f"  - {name}: {status}")

    print("=" * 70)
    if all_passed:
        print(" ALL TEST SUITES COMPLETED SUCCESSFULLY! ")
        print("=" * 70 + "\n")
        sys.exit(0)
    else:
        print(" SOME TEST SUITES FAILED! ")
        print("=" * 70 + "\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
