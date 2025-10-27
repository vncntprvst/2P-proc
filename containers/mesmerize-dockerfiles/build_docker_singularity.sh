#!/bin/bash

# Build Docker image
docker build -t wanglabneuro/mesmerize-base:latest -t wanglabneuro/mesmerize-base:0.2.1 -f Dockerfile context

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
     apptainer build -F mesmerize-base_latest.sif docker://wanglabneuro/mesmerize-base:latest
fi