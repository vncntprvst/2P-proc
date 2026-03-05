#!/bin/bash

# Build Docker image
docker build -t wanglabneuro/2p_proc:latest -t wanglabneuro/2p_proc:0.10.0 -f Dockerfile context
#  --no-cache

# Push to Docker registry
docker push --all-tags wanglabneuro/2p_proc

# Convert Docker image to Singularity image
# Requires Singularity installed on your system.

# Set output directory for SIF files (default to .apptainer in home directory)
SIF_OUTPUT_DIR=${SIF_OUTPUT_DIR:-$HOME/.apptainer/images}
mkdir -p "$SIF_OUTPUT_DIR"

if ! command -v apptainer &> /dev/null
then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit
else
    # If a hash file exists, check the hash matches the current Docker image. If not, build a new Singularity image.
    if [ -f "$SIF_OUTPUT_DIR/2p_proc_latest.sif.hash" ]; then
        if [ "$(docker inspect wanglabneuro/2p_proc:latest --format='{{.Id}}')" == "$(cat $SIF_OUTPUT_DIR/2p_proc_latest.sif.hash)" ]; then
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
        echo "Building Singularity image in $SIF_OUTPUT_DIR"
        # docker login
        apptainer build -F "$SIF_OUTPUT_DIR/2p_proc_latest.sif" docker://wanglabneuro/2p_proc:latest
        # docker logout
        # store a hash of the Docker image in a file
        docker inspect wanglabneuro/2p_proc:latest --format='{{.Id}}' > "$SIF_OUTPUT_DIR/2p_proc_latest.sif.hash"
        echo "Singularity image built: $SIF_OUTPUT_DIR/2p_proc_latest.sif"
    fi

fi

# Load and export variables from .env
# Check current directory first, then parent containers/, then scripts/utils/
if [ -f ".env" ]; then
  set -a                           # auto-export all variables
  # shellcheck disable=SC1091
  . ".env"                         # source the .env (trusted file)
  set +a
elif [ -f "../.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "../.env"
  set +a
elif [ -f "../../scripts/utils/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "../../scripts/utils/.env"
  set +a
fi

# Build SSH_HPCC_IMAGE_REPO if both pieces exist
if [ -n "${SSH_TRANSFER_NODE:-}" ] && [ -n "${HPCC_IMAGE_REPO:-}" ]; then
export SSH_HPCC_IMAGE_REPO="${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}"
else
echo "Warning: SSH_TRANSFER_NODE or HPCC_IMAGE_REPO not set from .env; not setting SSH_HPCC_IMAGE_REPO"
fi

# Copy SIF to HPCC if SSH_HPCC_IMAGE_REPO is set (format: host:path)
if [ -n "${SSH_HPCC_IMAGE_REPO:-}" ]; then
  IFS=: read -r host path <<<"$SSH_HPCC_IMAGE_REPO"
  echo "Copying Singularity image to HPCC:"
  echo "  host: ${host:-<empty>}"
  echo "  path: ${path:-<empty>}"
    if [ -z "$host" ] || [ -z "$path" ] || [[ "$host" == *"/"* ]]; then
        echo "Invalid SSH_HPCC_IMAGE_REPO='$SSH_HPCC_IMAGE_REPO'; skipping rsync."
    else
            rsync -aP "$SIF_OUTPUT_DIR/2p_proc_latest.sif" "$SSH_HPCC_IMAGE_REPO/" # -z compression flag tends to screw up the transfer when using the script. May not be necessary anyway.
    fi
else
    echo "HPCC_IMAGE_REPO variable not set. Not copying to HPCC."
fi