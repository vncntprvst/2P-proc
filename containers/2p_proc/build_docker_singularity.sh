#!/bin/bash
# Build the 2p_proc image, push it to Docker Hub, build the Singularity image 2p_proc_<TAG>.sif and
# copy it to the cluster image folder (SSH_TRANSFER_NODE and HPCC_IMAGE_REPO in .env).
# Each version keeps its own file, so older versions stay available; 2p_proc_latest.sif is a link
# to the newest one. Version history: build.sh.

IMAGE=wanglabneuro/2p_proc
# Bump together with the optimouse pin in Dockerfile, build.sh, and P2P_VERSION in
# scripts/2P_proc_template.sh and scripts/register_sessions.sh
TAG=0.13.0
SIF_NAME=2p_proc_${TAG}.sif
LINK_NAME=2p_proc_latest.sif

# Build Docker image
docker build -t $IMAGE:latest -t $IMAGE:$TAG -f Dockerfile context || exit 1
#  --no-cache

# Push to Docker registry
docker push $IMAGE:$TAG && docker push $IMAGE:latest

# Convert Docker image to Singularity image
# Set output directory for SIF files (default to .apptainer in home directory)
SIF_OUTPUT_DIR=${SIF_OUTPUT_DIR:-$HOME/.apptainer/images}
mkdir -p "$SIF_OUTPUT_DIR"
SIF="$SIF_OUTPUT_DIR/$SIF_NAME"

if ! command -v apptainer &> /dev/null; then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit 1
fi
# Rebuild only if the Docker image differs from the one the SIF was built from
if [ -f "$SIF" ] && [ -f "$SIF.hash" ] && [ "$(docker inspect $IMAGE:$TAG --format='{{.Id}}')" == "$(cat "$SIF.hash")" ]; then
    echo "Docker image has not changed. Not building $SIF."
else
    echo "Building Singularity image $SIF"
    apptainer build -F "$SIF" docker://$IMAGE:$TAG || exit 1
    docker inspect $IMAGE:$TAG --format='{{.Id}}' > "$SIF.hash"
    echo "Singularity image built: $SIF"
fi
# Point the "latest" link to this version (a regular file with that name is left alone)
if [ -L "$SIF_OUTPUT_DIR/$LINK_NAME" ] || [ ! -e "$SIF_OUTPUT_DIR/$LINK_NAME" ]; then
    ln -sfn "$SIF_NAME" "$SIF_OUTPUT_DIR/$LINK_NAME"
else
    echo "$SIF_OUTPUT_DIR/$LINK_NAME is a file, not a link; left unchanged."
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

# Copy the SIF to the cluster. An existing file of the same version is not replaced: bump TAG for a
# new image.
if [ -n "${SSH_TRANSFER_NODE:-}" ] && [ -n "${HPCC_IMAGE_REPO:-}" ]; then
    echo "Copying $SIF_NAME to ${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/"
    rsync -aP --ignore-existing "$SIF" "${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/" # no -z: compression tends to break the transfer
    ssh "$SSH_TRANSFER_NODE" "cd '$HPCC_IMAGE_REPO' && ls -l '$SIF_NAME' && \
        if [ -L '$LINK_NAME' ] || [ ! -e '$LINK_NAME' ]; then ln -sfn '$SIF_NAME' '$LINK_NAME'; \
        else echo '$LINK_NAME is a file, not a link; left unchanged.'; fi"
else
    echo "SSH_TRANSFER_NODE or HPCC_IMAGE_REPO not set in .env; not copying to the cluster."
fi
