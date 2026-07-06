#!/bin/bash

# Download the z-motion test fixture for the 2P processing pipeline.
# The fixture is a minimal, real-anatomy subset of C57_O1M2/10022023 (a short
# downsampled TSeries + its ZSeries reference stack) built by
# scripts/make_test_fixture.py and published as a GitHub release asset.
#
# Usage: ./download_test_data.sh
# Override the source with TEST_DATA_URL=... ./download_test_data.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MESMERIZE_DIR="$REPO_ROOT/Mesmerize"

TEST_DATA_URL="${TEST_DATA_URL:-https://github.com/vncntprvst/2P-proc/releases/download/test-data-v2/test_data.tar.gz}"

echo "2P-proc - z-motion test fixture download"
echo "========================================"

mkdir -p "$MESMERIZE_DIR"
cd "$MESMERIZE_DIR"

if [ -d "test_data" ]; then
    echo "Test data directory already exists."
    read -p "Re-download and overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping download."
        exit 0
    fi
    rm -rf test_data
fi

echo "Downloading fixture from: $TEST_DATA_URL"
if command -v wget >/dev/null 2>&1; then
    wget -O test_data.tar.gz "$TEST_DATA_URL"
elif command -v curl >/dev/null 2>&1; then
    curl -L -o test_data.tar.gz "$TEST_DATA_URL"
else
    echo "Error: neither wget nor curl found. Download manually:"
    echo "  $TEST_DATA_URL"
    exit 1
fi

echo "Extracting ..."
tar -xzf test_data.tar.gz
rm test_data.tar.gz

echo ""
echo "Fixture ready at: $MESMERIZE_DIR/test_data"
echo "Contents: one short TSeries + a ZSeries reference stack (real C57_O1M2 anatomy)."
echo ""
echo "Run the z-motion benchmark against it:"
echo "  python tests/benchmarks/benchmark_zcorr.py \\"
echo "      --real-zstack Mesmerize/test_data/ZSeries-10022023-1300-004 \\"
echo "      --real-movie Mesmerize/test_data/TSeries-10022023-1300-001 \\"
echo "      --save-results results/"
echo ""
echo "Size: $(du -sh test_data 2>/dev/null | cut -f1 || echo 'Unknown')"
