#!/bin/bash
# Run motion correction test with the small test dataset
# This script provides an easy way to run the motion correction test
# 
# IMPORTANT: To run this script correctly:
# 1. Navigate to the scripts directory:
#    cd /path/to/Analysis_2P/scripts
#
# 2. Activate the relevant conda environment (e.g., mescore or CaImAn):
#    conda activate mescore
#
# 3. Run this script:
#    ./run_motion_correction_test.sh
#
# Running from other directories or without the proper conda
# environment activated will likely cause import errors.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_SCRIPT="$REPO_ROOT/tests/test_motion_correction.py"

echo "Analysis 2P - Motion Correction Test"
echo "==================================="

# Check if we're in a conda environment
if [ -z "$CONDA_PREFIX" ]; then
    echo "Warning: No conda environment detected. The test may fail if dependencies are not available."
    echo "It's recommended to run this in the 'mescore' conda environment."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Exiting."
        exit 0
    fi
fi

# Check if test script exists
if [ ! -f "$TEST_SCRIPT" ]; then
    echo "Error: Test script not found at $TEST_SCRIPT"
    exit 1
fi

echo "Running motion correction test..."
echo "(This will download test data if not already present)"
echo

# Run the test from the repository root to ensure correct import paths
cd "$REPO_ROOT"
PYTHONPATH="$REPO_ROOT:$REPO_ROOT/Mesmerize:$PYTHONPATH" python "$TEST_SCRIPT"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo
    echo "✅ Motion correction test passed!"
else
    echo
    echo "❌ Motion correction test failed."
fi

exit $exit_code
