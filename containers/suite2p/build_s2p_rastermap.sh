#!/bin/bash

docker build -t wanglabneuro/suite2p_rastermap:latest -t wanglabneuro/suite2p_rastermap:0.0.3 -f Dockerfile_s2p_rastermap .

# Versions:
# v0.0.3: Activate Suite2p conda environment in Dockerfile
# v0.0.2: Add python scripts called by Matlab pipeline
# v0.0.1: Working container with Suite2p and rastermap installed

# Test with docker run --rm -it wanglabneuro/suite2p_rastermap /bin/bash, or singularity run docker://wanglabneuro/suite2p_rastermap:latest /bin/bash