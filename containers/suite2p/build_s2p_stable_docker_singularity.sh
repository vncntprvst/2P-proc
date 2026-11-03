#!/bin/bash
# Build the Suite2p extraction image, push it to Docker Hub, build the Singularity image
# suite2p_<VERSION>.sif and copy it to the cluster image folder (SSH_TRANSFER_NODE and
# HPCC_IMAGE_REPO in .env). Each version keeps its own file; suite2p_latest.sif is a link to the
# newest one.

IMAGE=wanglabneuro/suite2p
VERSION=0.14.0  # Suite2p version; bump together with S2P_VERSION in scripts/2P_proc_template.sh
TAG=v$VERSION
SIF_NAME=suite2p_${VERSION}.sif
LINK_NAME=suite2p_latest.sif

# Build Docker image
docker build -t $IMAGE:latest -t $IMAGE:$TAG -f Dockerfile_s2p_stable context || exit 1

# Push to Docker registry
docker push $IMAGE:$TAG && docker push $IMAGE:latest

# Convert Docker image to Singularity image
SIF_OUTPUT_DIR=${SIF_OUTPUT_DIR:-$HOME/.apptainer/images}
mkdir -p "$SIF_OUTPUT_DIR"
SIF="$SIF_OUTPUT_DIR/$SIF_NAME"
if ! command -v apptainer &> /dev/null; then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit 1
fi
if [ -f "$SIF" ] && [ -f "$SIF.hash" ] && [ "$(docker inspect $IMAGE:$TAG --format='{{.Id}}')" == "$(cat "$SIF.hash")" ]; then
    echo "Docker image has not changed. Not building $SIF."
else
    echo "Building Singularity image $SIF"
    apptainer build -F "$SIF" docker://$IMAGE:$TAG || exit 1
    docker inspect $IMAGE:$TAG --format='{{.Id}}' > "$SIF.hash"
    echo "Singularity image built: $SIF"
fi
if [ -L "$SIF_OUTPUT_DIR/$LINK_NAME" ] || [ ! -e "$SIF_OUTPUT_DIR/$LINK_NAME" ]; then
    ln -sfn "$SIF_NAME" "$SIF_OUTPUT_DIR/$LINK_NAME"
else
    echo "$SIF_OUTPUT_DIR/$LINK_NAME is a file, not a link; left unchanged."
fi

# Load and export variables from .env
# Check current directory first, then parent containers/, then scripts/utils/
for f in .env ../.env ../2p_proc/.env ../../scripts/utils/.env; do
    if [ -f "$f" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$f"
        set +a
        break
    fi
done

# Copy the SIF to the cluster; an existing file of the same version is not replaced
if [ -n "${SSH_TRANSFER_NODE:-}" ] && [ -n "${HPCC_IMAGE_REPO:-}" ]; then
    echo "Copying $SIF_NAME to ${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/"
    rsync -aP --ignore-existing "$SIF" "${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/"
    ssh "$SSH_TRANSFER_NODE" "cd '$HPCC_IMAGE_REPO' && ls -l '$SIF_NAME' && \
        if [ -L '$LINK_NAME' ] || [ ! -e '$LINK_NAME' ]; then ln -sfn '$SIF_NAME' '$LINK_NAME'; \
        else echo '$LINK_NAME is a file, not a link; left unchanged.'; fi"
else
    echo "SSH_TRANSFER_NODE or HPCC_IMAGE_REPO not set in .env; not copying to the cluster."
fi

# Test the Singularity image
# apptainer exec "$SIF" suite2p --version
