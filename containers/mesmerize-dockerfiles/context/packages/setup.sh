#!/bin/bash
set -e

echo "Setting up mescore environment with uv..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "uv is not installed. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env
fi

# Create the mescore environment with Python 3.9
echo "Creating mescore environment with Python 3.9..."
uv venv mescore --python 3.9

# Activate the environment
echo "Activating mescore environment..."
source mescore/bin/activate

# Install core packages
echo "Installing mesmerize-core..."
uv pip install mesmerize-core

# Install caiman and run caiman manager
echo "Installing caiman..."
uv pip install caiman
echo "Running caimanmanager install..."
caimanmanager install

# Install fastplotlib with notebook support
echo "Installing fastplotlib with notebook support..."
uv pip install "fastplotlib[notebook]"

# Install pylibtiff
echo "Installing pylibtiff..."
uv pip install pylibtiff

# Install mesmerize-viz from GitHub
echo "Installing mesmerize-viz from GitHub..."
git clone https://github.com/kushalkolar/mesmerize-viz.git
cd mesmerize-viz
uv pip install -e .
uv pip install PyQt6
cd ..

# Install MKL and suite2p for z-correction
echo "Installing mkl, mkl_fft and suite2p..."
# Note: MKL packages might need conda, so we'll try with uv first
uv pip install mkl mkl_fft || echo "Warning: MKL packages may need conda installation"
uv pip install suite2p

# Install additional packages
echo "Installing additional packages..."
uv pip install pyarrow
uv pip install plotly

echo "Setup complete!"
echo ""
echo "To activate the environment in the future, run:"
echo "source mescore/bin/activate"
echo ""
echo "Environment location: $(pwd)/mescore"
