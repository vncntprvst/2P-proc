#!/bin/bash

# Build Docker image
docker build -t wanglabneuro/mesmerize-base:latest -t wanglabneuro/mesmerize-base:0.1.0 -f Dockerfile_update .

# Push to Docker registry
docker push --all-tags wanglabneuro/mesmerize-base

# Convert Docker image to Singularity image
# Requires Singularity installed on your system.
if ! command -v apptainer &> /dev/null
then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit
else
    singularity build mesmerize-base_latest.sif docker://wanglabneuro/mesmerize-base:latest
    # singularity build mesmerize-base_0.0.2.sif docker://wanglabneuro/mesmerize-base:0.0.3
fi

# check if hppc_image_repo variable exists
if [ -n "${HPPC_IMAGE_REPO+x}" ]; then
    rsync -aroguv mesmerize-base_latest.sif $HPPC_IMAGE_REPO/mesmerize-base_latest.sif
else
    echo "HPPC_IMAGE_REPO variable not set. Not copying to HPPC."
fi