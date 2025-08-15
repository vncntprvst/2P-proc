#!/bin/bash

# Copy necessary repository files to context directory
rsync -avzP ../../pipeline context/
rsync -avzP ../../scripts context/
rsync -avzP ../../modules context/
rsync -avzP ../../readme.md context/
rsync -avzP ../../LICENSE.md context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p-nwb:latest -f Dockerfile context

# Clean up context directory
rm -rf context/pipeline context/scripts context/modules
rm -f context/readme.md context/LICENSE.md
