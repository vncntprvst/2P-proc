#!/bin/bash
# create a new env in your directory
# usage: bash venv_script.sh

# Set CUDA environment variables to prevent conflicts
export TF_CPP_MIN_LOG_LEVEL=2  # Suppress TensorFlow warnings
export CUDA_VISIBLE_DEVICES=0  # Specify GPU if available

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

uv venv .a2P --python 3.10
source .a2P/bin/activate

# get latest pip setuptools and wheel
uv pip install --upgrade setuptools wheel cython numpy

# Install CUDA-compatible versions
uv pip install "tensorflow>=2.12,<2.16" --no-deps
uv pip install "torch>=2.0" --index-url https://download.pytorch.org/whl/cu118

# install caiman
# on cluster: 
# module load gcc/12.2.0
# export LD_LIBRARY_PATH=$(dirname $(dirname $(which gcc)))/lib64:$LD_LIBRARY_PATH

uv pip install git+https://github.com/flatironinstitute/CaImAn.git
caimanmanager install

# install mesmerize-core
uv pip install mesmerize-core

# install mesmerize-viz
uv pip install mesmerize-viz --prerelease=allow

# install other dependencies
uv pip install simplejpeg pylibtiff PyQt6 pyarrow plotly imagecodecs