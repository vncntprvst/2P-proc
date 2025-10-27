# create a new env in your directory
#!/bin/bash

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Source the appropriate shell configuration file
if [ -f "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
elif [ -f "$HOME/.zshrc" ]; then
    source "$HOME/.zshrc"
elif [ -f "$HOME/.profile" ]; then
    source "$HOME/.profile"
else
    echo "Warning: No shell configuration file found to source."
fi

# Check if uv is installed
uv --version 

# Create a new virtual environment named mescore with Python 3.10
uv venv mescore --python 3.10
source mescore/bin/activate

# get latest pip setuptools and wheel
uv pip install --upgrade pip setuptools wheel cython numpy

# Install other scientific dependencies
uv pip install scipy scikit-image h5py matplotlib opencv-python-headless

# Install versions of TensorFlow compatible 
uv pip install "tensorflow>=2.12,<2.16" --no-deps
uv pip install --upgrade keras

# install caiman
uv pip install git+https://github.com/flatironinstitute/CaImAn.git
caimanmanager install

# install mesmerize-core
uv pip install mesmerize-core

# install mesmerize-viz
uv pip install mesmerize-viz --prerelease=allow

# install other dependencies
uv pip install simplejpeg PyQt6