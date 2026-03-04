#!/bin/bash
# create a new Suite2P env in your directory
# usage: bash s2p_venv_script.sh

set -e

# Check if uv is installed, if not install it
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    # if on Windows, use the Windows installer
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    else
        # if on Linux or macOS, use the shell script installer
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
fi

uv venv .suite2p --python 3.10
source .suite2p/bin/activate

# Get latest core build tooling
uv pip install --upgrade pip setuptools wheel

# Match the container's suite2p environment
uv pip install ipykernel
uv pip install "git+https://github.com/MouseLand/suite2p.git@v0.14.0#egg=suite2p[all]"

# Register a local Jupyter kernel like the container setup
python -m ipykernel install --user --name suite2p --display-name "Suite2p"

echo "Suite2P environment ready: .suite2p"
