#!/bin/bash

set -e  # Exit on any error

echo "Setting up CaImAn environment with mamba/conda..."

# Install micromamba non-interactively
if ! command -v micromamba &> /dev/null; then
    echo "Installing micromamba..."
    # Use the direct binary installation method for containers
    mkdir -p ~/.local/bin
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba -O > ~/.local/bin/micromamba
    chmod +x ~/.local/bin/micromamba
    export PATH="$HOME/.local/bin:$PATH"
    
    # Initialize micromamba
    ~/.local/bin/micromamba shell init --shell bash --root-prefix=~/micromamba
    source ~/.bashrc || true
    export MAMBA_ROOT_PREFIX=~/micromamba
fi

# Create alias for convenience
alias mamba='micromamba'

# Install uv if not available
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

echo "Creating CaImAn environment with micromamba..."
micromamba create -n CaImAn -c conda-forge python=3.11 mesmerize-core caiman numpy -y

echo "Activating CaImAn environment..."
eval "$(micromamba shell hook --shell bash)"
micromamba activate CaImAn

echo "Running caimanmanager install..."
caimanmanager install

echo "Installing additional conda packages..."
micromamba install -n CaImAn -c conda-forge mkl mkl_fft -y || echo "Warning: MKL packages not available"
micromamba install -n CaImAn -c conda-forge ipykernel pip tslearn bottleneck graphviz bokeh jupyterlab jupyterlab-git nb_conda_kernels -y
micromamba install -n CaImAn -c defaults ffmpeg -y
micromamba install -n CaImAn -c conda-forge "tifffile>=2023.8.12" -y

echo "Installing pip packages with uv..."
uv pip install "fastplotlib[notebook]"
uv pip install pylibtiff
uv pip install git+https://github.com/kushalkolar/mesmerize-viz.git
uv pip install PyQt6
uv pip install suite2p
uv pip install pyarrow
uv pip install plotly

echo "Setup complete! To activate the environment, run:"
echo "micromamba activate CaImAn"