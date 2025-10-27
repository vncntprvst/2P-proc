#!/bin/bash

docker build -t wanglabneuro/suite2p_rastermap:latest -t wanglabneuro/suite2p_rastermap:0.0.4 -f Dockerfile_s2p_rastermap context

# Versions:
# v0.0.4: Update containers/suite2p/context/scripts/run_deconv_spikes.py. Keep Suite2p at v0.14.0.
# v0.0.3: Activate Suite2p conda environment in Dockerfile
# v0.0.2: Add python scripts called by Matlab pipeline
# v0.0.1: Working container with Suite2p and rastermap installed

# Test with docker run --rm -it wanglabneuro/suite2p_rastermap /bin/bash, or singularity run docker://wanglabneuro/suite2p_rastermap:latest /bin/bash