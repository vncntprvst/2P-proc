#!/bin/bash

# Build Docker image
docker build -t wanglabneuro/suite2p:latest -t wanglabneuro/suite2p:v0.14.0 -f Dockerfile_s2p_stable .

# Push to Docker registry
docker push --all-tags wanglabneuro/suite2p

# Convert Docker image to Singularity image
# Requires Singularity installed on your system.
if ! command -v apptainer &> /dev/null
then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit
else
    # If a hash file exists, check the hash matches the current Docker image. If not, build a new Singularity image.
    if [ -f "suite2p_latest.sif.hash" ]; then
        if [ "$(docker inspect wanglabneuro/suite2p:latest --format='{{.Id}}')" == "$(cat suite2p_latest.sif.hash)" ]; then
            echo "Docker image has not changed. Not building Singularity image."
            build_singularity=0
        else
            echo "Docker image has changed. Building Singularity image."
            build_singularity=1
        fi
    else
        echo "Hash file not found. Building Singularity image."
        build_singularity=1
    fi
          
    if [ $build_singularity -eq 1 ]; then
        echo "Building Singularity image."
        # docker login
        apptainer build -F suite2p_latest.sif docker://wanglabneuro/suite2p:latest 
        # docker logout
        # store a hash of the Docker image in a file
        docker inspect wanglabneuro/suite2p:latest --format='{{.Id}}' > suite2p_latest.sif.hash
    fi    
            
fi

# If the .env script exists, get the HPCC_IMAGE_REPO variable
if [ -f "../../scripts/utils/.env" ]; then
    echo "Get server information from .env file."
    while IFS='=' read -r key value; do
        if [[ $key != \#* ]]; then
            export "$key=$value"
        fi
    done < "../../scripts/utils/.env"
    export SSH_HPCC_IMAGE_REPO="${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}"
fi

# check if hppc_image_repo variable exists
if [ -n "${SSH_HPCC_IMAGE_REPO+x}" ]; then
    echo "Copying Singularity image to HPCC."
    rsync -aP suite2p_latest.sif "$SSH_HPCC_IMAGE_REPO/"
else
    echo "HPPC_IMAGE_REPO variable not set. Not copying to HPPC."
fi