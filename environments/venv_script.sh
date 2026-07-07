#!/bin/bash
# Create the reproducible optimouse dev/benchmark environment with uv.
# usage: bash environments/venv_script.sh
#
# Project dependencies are pinned in ../uv.lock (uv sync). CaImAn is installed
# separately from its GitHub tag because it ships no wheels and is deliberately
# excluded from the lock (see the note in pyproject.toml).

set -e

# Set CUDA / TF environment variables to prevent conflicts
export TF_CPP_MIN_LOG_LEVEL=2  # Suppress TensorFlow warnings
export CUDA_VISIBLE_DEVICES=0  # Specify GPU if available

# Install uv if missing
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Put the environment in .proc2P (rather than the uv default .venv)
export UV_PROJECT_ENVIRONMENT=.proc2P

uv venv .proc2P --python 3.10

# Install the locked project dependencies + all extras (editable install of
# optimouse). --inexact so a later re-sync won't remove CaImAn.
uv sync --extra all --inexact --prerelease=allow

# CaImAn: pinned separately (no wheels; built from the GitHub tag).
# On the cluster you may first need:
#   module load gcc/12.2.0
#   export LD_LIBRARY_PATH=$(dirname $(dirname $(which gcc)))/lib64:$LD_LIBRARY_PATH
uv pip install --python .proc2P/bin/python \
    "git+https://github.com/flatironinstitute/CaImAn.git@v1.12.2"
.proc2P/bin/caimanmanager install

echo "Environment ready: .proc2P (activate with 'source .proc2P/bin/activate')"
