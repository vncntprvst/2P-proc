# create a new env in your directory
#!/bin/bash

curl -LsSf https://astral.sh/uv/install.sh | sh

source $HOME/.local/bin/env 

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