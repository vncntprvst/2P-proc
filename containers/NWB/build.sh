#!/bin/bash

# Copy conversion script to context directory
cp nwb_conversion.py context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p-nwb:latest -f Dockerfile context

# Clean up context directory
rm -f context/nwb_conversion.py
