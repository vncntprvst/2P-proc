#!/bin/bash

# Copy the Mesmerize folder one level above, to the context folder
rsync -avzP ../../Mesmerize context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p:latest -t wanglabneuro/analysis-2p:0.2.3 -f Dockerfile context

# Delete the Mesmerize folder from the context folder
rm -rf context/Mesmerize

# Push to Docker registry
docker push --all-tags wanglabneuro/analysis-2p

# Convert Docker image to Singularity image
# Requires Singularity installed on your system.
if ! command -v apptainer &> /dev/null
then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit
else
    # If a hash file exists, check the hash matches the current Docker image. If not, build a new Singularity image.
    if [ -f "analysis-2p_latest.sif.hash" ]; then
        if [ "$(docker inspect wanglabneuro/analysis-2p:latest --format='{{.Id}}')" == "$(cat analysis-2p_latest.sif.hash)" ]; then
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
        apptainer build -F analysis-2p_latest.sif docker://wanglabneuro/analysis-2p:latest 
        # docker logout
        # store a hash of the Docker image in a file
        docker inspect wanglabneuro/analysis-2p:latest --format='{{.Id}}' > analysis-2p_latest.sif.hash
    fi    
            
fi

# check if the server_dirs script exists, if so source it
if [ -f "../../secrets/server_dirs.sh" ]; then
    echo "Sourcing server_dirs.sh"
    source ../../secrets/server_dirs.sh
fi

# check if hppc_image_repo variable exists
if [ -n "${SSH_HPCC_IMAGE_REPO+x}" ]; then
    echo "Copying Singularity image to HPCC."
    rsync -aP analysis-2p_latest.sif "$SSH_HPCC_IMAGE_REPO/" # -z compression flag tends to screw up the transfer when using the script. May not be necessary anyway.
else
    echo "HPPC_IMAGE_REPO variable not set. Not copying to HPPC."
fi