#!/bin/bash
# Build the cell-registration image, push it to Docker Hub, convert it to a Singularity image
# and copy it to the cluster image folder (SSH_TRANSFER_NODE / HPCC_IMAGE_REPO in .env, as for 2p_proc).

# Version history:
# v0.1.1: optimouse 0.1.8.
# v0.1.0: optimouse 0.1.7 + ROICaT 1.7.12 (CPU torch 2.14.1), Python 3.11.

IMAGE=wanglabneuro/2p_registration
TAG=0.1.1

docker build -t $IMAGE:latest -t $IMAGE:$TAG -f Dockerfile . || exit 1
docker push --all-tags $IMAGE

SIF_OUTPUT_DIR=${SIF_OUTPUT_DIR:-$HOME/.apptainer/images}
mkdir -p "$SIF_OUTPUT_DIR"
SIF="$SIF_OUTPUT_DIR/2p_registration_latest.sif"
if ! command -v apptainer &> /dev/null; then
    echo "apptainer could not be found; not building the Singularity image."
    exit 1
fi
if [ -f "$SIF.hash" ] && [ "$(docker inspect $IMAGE:latest --format='{{.Id}}')" == "$(cat "$SIF.hash")" ]; then
    echo "Docker image has not changed. Not building Singularity image."
else
    apptainer build -F "$SIF" docker://$IMAGE:latest || exit 1
    docker inspect $IMAGE:latest --format='{{.Id}}' > "$SIF.hash"
    echo "Singularity image built: $SIF"
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
if [ -n "${SSH_TRANSFER_NODE:-}" ] && [ -n "${HPCC_IMAGE_REPO:-}" ]; then
    echo "Copying $SIF to ${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/"
    rsync -aP "$SIF" "${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}/"
else
    echo "SSH_TRANSFER_NODE or HPCC_IMAGE_REPO not set in .env; not copying to the cluster."
fi
