#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for the motion_correction module only.

This simplified test just verifies module import and basic functionality.
"""

import os
import sys
import traceback
from pathlib import Path

# Set up proper import paths
repo_root = Path(__file__).parent.parent
modules_dir = repo_root / "modules"

# Add directories to Python path
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
if str(modules_dir) not in sys.path:
    sys.path.insert(0, str(modules_dir))

def test_imports():
    """Test that we can import the motion correction module."""
    try:
        from modules.motion_correction import run_motion_correction_workflow
        from modules.motion_correction import get_default_mcorr_parameters
        print("+ Successfully imported motion_correction module")
        return True
    except ImportError as e:
        print(f"- Failed to import motion_correction module: {e}")
        traceback.print_exc()
        return False

def test_default_parameters():
    """Test that we can get default parameters from the module."""
    try:
        from modules.motion_correction import get_default_mcorr_parameters
        params = get_default_mcorr_parameters()
        print("+ Successfully got default parameters")
        print(f"  Default strides: {params['main']['strides']}")
        print(f"  Default overlaps: {params['main']['overlaps']}")
        return True
    except Exception as e:
        print(f"- Failed to get default parameters: {e}")
        traceback.print_exc()
        return False

def run_tests():
    """Run all tests."""
    print("=" * 60)
    print("MOTION CORRECTION MODULE TEST")
    print("=" * 60)
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    print("-" * 60)
    
    tests = [
        test_imports,
        test_default_parameters
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print("-" * 60)
    print(f"Test results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\nAll tests passed! Motion correction module is working.")
        return 0
    else:
        print("\nSome tests failed. Check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
