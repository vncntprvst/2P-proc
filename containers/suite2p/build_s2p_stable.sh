#!/bin/bash

docker build -t wanglabneuro/suite2p:latest -t wanglabneuro/suite2p:v0.14.0 -f Dockerfile_s2p_stable .

# Check Suite2p version:
echo "Checking Suite2p version..."
docker run --rm -it wanglabneuro/suite2p:latest suite2p --version
