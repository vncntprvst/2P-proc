#!/bin/bash

# Download and extract test dataset for Analysis 2P pipeline
# Usage: ./download_test_data.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MESMERIZE_DIR="$REPO_ROOT/Mesmerize"

echo "Analysis 2P - Test Dataset Download"
echo "==================================="

# Check if we're in the right directory
if [ ! -d "$MESMERIZE_DIR" ]; then
    echo "Error: Mesmerize directory not found at $MESMERIZE_DIR"
    echo "Please run this script from the repository root or scripts directory"
    exit 1
fi

cd "$MESMERIZE_DIR"

# Check if test data already exists
if [ -d "test_data" ]; then
    echo "Test data directory already exists."
    read -p "Do you want to re-download and overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping download."
        exit 0
    fi
    echo "Removing existing test data..."
    rm -rf test_data
fi

echo "Downloading test dataset from GitHub releases..."
echo "This may take a few minutes (downloading ~1.2GB)..."

# Download the latest test dataset
if command -v wget >/dev/null 2>&1; then
    wget -O test_data_small.tar.gz "https://github.com/pseudomanu/Analysis_2P/releases/download/test-data-v1.1/test_data_small.tar.gz"
elif command -v curl >/dev/null 2>&1; then
    curl -L -o test_data_small.tar.gz "https://github.com/pseudomanu/Analysis_2P/releases/download/test-data-v1.1/test_data_small.tar.gz"
else
    echo "Error: Neither wget nor curl found. Please install one of them or download manually:"
    echo "https://github.com/pseudomanu/Analysis_2P/releases/download/test-data-v1.1/test_data_small.tar.gz"
    exit 1
fi

echo "Extracting test dataset..."
tar -xzf test_data_small.tar.gz

echo "Cleaning up archive..."
rm test_data_small.tar.gz

echo ""
echo "Test dataset successfully downloaded and extracted!"
echo ""
echo "Dataset contents:"
echo "  - 2 test sessions with 1000 frames each"
echo "  - Z-stacks for z-motion correction"
echo "  - Parameter files for both CaImAn and z-correction"
echo ""
echo "You can now run the pipeline with:"
echo "  Quick test:  python pipeline/pipeline_mcorr.py Mesmerize/paths/paths_test_smaller.json"
echo "               python pipeline/pipeline_cnmf.py Mesmerize/paths/paths_test_smaller.json"
echo "  Full test:   python pipeline/pipeline_mcorr.py Mesmerize/paths/paths_test_small.json"
echo "               python pipeline/pipeline_cnmf.py Mesmerize/paths/paths_test_small.json"
echo ""
echo "Dataset location: $MESMERIZE_DIR/test_data"
echo "Dataset size: $(du -sh test_data 2>/dev/null | cut -f1 || echo 'Unknown')"
