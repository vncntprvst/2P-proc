#!/bin/bash
set -e

echo "Setting up CaImAn environment with mamba/conda..."

# Check if mamba is available, install if needed
if ! command -v mamba &> /dev/null; then
    echo "Installing micromamba..."
    "${SHELL}" <(curl -L micro.mamba.pm/install.sh)
    # Initialize micromamba in the current shell
    eval "$(~/micromamba/bin/micromamba shell hook -s posix)"
    # Set up alias for mamba to use micromamba
    alias mamba='micromamba'
fi

# Create the CaImAn environment with caiman and mesmerize-core
echo "Creating CaImAn environment with caiman and mesmerize-core..."
mamba create -n CaImAn -c conda-forge python=3.11 caiman mesmerize-core -y

# Activate the environment
echo "Activating CaImAn environment..."
eval "$(conda shell.bash hook)"
conda activate CaImAn

# Install uv if not available
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

# Install caiman manager
echo "Running caimanmanager install..."
caimanmanager install

# Install additional packages with uv
echo "Installing fastplotlib with notebook support..."
uv pip install "fastplotlib[notebook]"

echo "Installing pylibtiff..."
uv pip install pylibtiff

echo "Installing mesmerize-viz from GitHub..."
uv pip install git+https://github.com/kushalkolar/mesmerize-viz.git

echo "Installing PyQt6..."
uv pip install PyQt6

# Install suite2p and MKL packages
echo "Installing mkl packages with mamba and suite2p with uv..."
mamba install -y -c conda-forge mkl mkl_fft
uv pip install suite2p

# Install additional packages
echo "Installing additional packages..."
uv pip install pyarrow
uv pip install plotly

echo "Setup complete!"
echo ""
echo "To activate the environment in the future, run:"
echo "conda activate CaImAn"
echo ""
echo "Environment location: $(conda info --envs | grep CaImAn | awk '{print $2}')"
