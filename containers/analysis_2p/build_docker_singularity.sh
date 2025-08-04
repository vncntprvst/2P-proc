#!/bin/bash

# Copy the Mesmerize and modules folder one level above, to the context folder
rsync -avzP --include="utils/" --include="paths/" --include="parameters/" --include="*.py" --include="*.ipynb" --include="*.md" --exclude="*/" ../../Mesmerize/ context/Mesmerize/
rsync -avzP ../../modules context/
rsync -avzP ../../pipeline context/
# rsync -avzP ../../Matlab context/
rsync -avzP ../../readme.md context/
rsync -avzP ../../LICENSE.md context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p:latest -t wanglabneuro/analysis-2p:0.5.1 -f Dockerfile context --no-cache

# Delete the Mesmerize and modules folder from the context folder
rm -rf context/Mesmerize
rm -rf context/modules
rm -rf context/pipeline
# rm -rf context/Matlab
rm -f context/readme.md
rm -f context/LICENSE.md

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
    rsync -aP analysis-2p_latest.sif "$SSH_HPCC_IMAGE_REPO/" # -z compression flag tends to screw up the transfer when using the script. May not be necessary anyway.
else
    echo "HPCC_IMAGE_REPO variable not set. Not copying to HPCC."
fi