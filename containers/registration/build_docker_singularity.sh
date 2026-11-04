#!/bin/bash
# Build the cell-registration image, push it to Docker Hub, build the Singularity image
# 2p_registration_<TAG>.sif and copy it to the cluster image folder (SSH_TRANSFER_NODE /
# HPCC_IMAGE_REPO in .env, as for 2p_proc). Each version keeps its own file;
# 2p_registration_latest.sif is a link to the newest one.

# Version history:
# v0.1.2: optimouse 0.1.11 (a session can also be a ROI file, e.g. written by the Matlab function call_roicat.m).
# v0.1.1: optimouse 0.1.8.
# v0.1.0: optimouse 0.1.7 + ROICaT 1.7.12 (CPU torch 2.14.1), Python 3.11.

IMAGE=wanglabneuro/2p_registration
TAG=0.1.2  # bump together with REG_VERSION in scripts/register_sessions.sh
SIF_NAME=2p_registration_${TAG}.sif
LINK_NAME=2p_registration_latest.sif

docker build -t $IMAGE:latest -t $IMAGE:$TAG -f Dockerfile . || exit 1
docker push $IMAGE:$TAG && docker push $IMAGE:latest

SIF_OUTPUT_DIR=${SIF_OUTPUT_DIR:-$HOME/.apptainer/images}
mkdir -p "$SIF_OUTPUT_DIR"
SIF="$SIF_OUTPUT_DIR/$SIF_NAME"
if ! command -v apptainer &> /dev/null; then
    echo "apptainer could not be found; not building the Singularity image."
    exit 1
fi
if [ -f "$SIF" ] && [ -f "$SIF.hash" ] && [ "$(docker inspect $IMAGE:$TAG --format='{{.Id}}')" == "$(cat "$SIF.hash")" ]; then
    echo "Docker image has not changed. Not building $SIF."
else
    apptainer build -F "$SIF" docker://$IMAGE:$TAG || exit 1
    docker inspect $IMAGE:$TAG --format='{{.Id}}' > "$SIF.hash"
    echo "Singularity image built: $SIF"
fi
if [ -L "$SIF_OUTPUT_DIR/$LINK_NAME" ] || [ ! -e "$SIF_OUTPUT_DIR/$LINK_NAME" ]; then
    ln -sfn "$SIF_NAME" "$SIF_OUTPUT_DIR/$LINK_NAME"
else
    echo "$SIF_OUTPUT_DIR/$LINK_NAME is a file, not a link; left unchanged."
fi

# Load SSH_TRANSFER_NODE and HPCC_IMAGE_REPO from .env (this folder, containers/, or scripts/utils/)
for f in .env ../.env ../2p_proc/.env ../../scripts/utils/.env; do
    if [ -f "$f" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$f"
        set +a
        break
    fi
done
# Copy to the cluster; an existing file of the same version is not replaced (bump TAG instead)
if [ -n "${SSH_TRANSFER_NODE:-}" ] && [ -n "${HPCC_IMAGE_REPO:-}" ]; then
    echo "Copying $SIF_NAME to ${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/"
    rsync -aP --ignore-existing "$SIF" "${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/"
    ssh "$SSH_TRANSFER_NODE" "cd '$HPCC_IMAGE_REPO' && ls -l '$SIF_NAME' && \
        if [ -L '$LINK_NAME' ] || [ ! -e '$LINK_NAME' ]; then ln -sfn '$SIF_NAME' '$LINK_NAME'; \
        else echo '$LINK_NAME is a file, not a link; left unchanged.'; fi"
else
    echo "SSH_TRANSFER_NODE or HPCC_IMAGE_REPO not set in .env; not copying to the cluster."
fi
