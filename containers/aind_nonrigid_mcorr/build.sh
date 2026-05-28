#!/bin/bash
# Build the aind_nonrigid_mcorr Docker image, push to Docker Hub, and
# convert to a Singularity/Apptainer SIF for cluster use.
#
# Usage:
#   bash build.sh                         # build + push + convert to SIF
#   bash build.sh --no-push               # build only, skip Docker Hub push
#   bash build.sh --no-sif                # build + push, skip SIF conversion
#   SIF_OUTPUT_DIR=/custom/path bash build.sh
#
# Requirements:
#   - Docker (for building and pushing)
#   - apptainer or singularity (for SIF conversion)
#   - Docker Hub write access to wanglabneuro/aind_nonrigid_mcorr

set -euo pipefail

DOCKER_IMAGE="wanglabneuro/aind_nonrigid_mcorr"
DOCKER_TAG="latest"
SIF_OUTPUT_DIR="${SIF_OUTPUT_DIR:-$HOME/.apptainer/images}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DO_PUSH=1
DO_SIF=1
for arg in "$@"; do
    case "$arg" in
        --no-push) DO_PUSH=0 ;;
        --no-sif)  DO_SIF=0  ;;
    esac
done

echo "=== Building Docker image ==="
docker build \
    -t "$DOCKER_IMAGE:$DOCKER_TAG" \
    -f "$SCRIPT_DIR/Dockerfile" \
    "$SCRIPT_DIR"

echo "Build complete: $DOCKER_IMAGE:$DOCKER_TAG"

if [ "$DO_PUSH" -eq 1 ]; then
    echo ""
    echo "=== Pushing to Docker Hub ==="
    docker push "$DOCKER_IMAGE:$DOCKER_TAG"
    echo "Push complete."
fi

if [ "$DO_SIF" -eq 1 ]; then
    echo ""
    echo "=== Converting to Singularity/Apptainer SIF ==="
    mkdir -p "$SIF_OUTPUT_DIR"

    SIF_PATH="$SIF_OUTPUT_DIR/aind_nonrigid_mcorr_latest.sif"
    HASH_PATH="$SIF_PATH.hash"
    CURRENT_HASH=$(docker inspect "$DOCKER_IMAGE:$DOCKER_TAG" --format='{{.Id}}')

    if [ -f "$HASH_PATH" ] && [ "$(cat "$HASH_PATH")" = "$CURRENT_HASH" ]; then
        echo "Docker image unchanged — existing SIF is up to date: $SIF_PATH"
    else
        if command -v apptainer &>/dev/null; then
            CONTAINER_CMD=apptainer
        elif command -v singularity &>/dev/null; then
            CONTAINER_CMD=singularity
        else
            echo "ERROR: neither apptainer nor singularity found; skipping SIF build."
            exit 1
        fi

        echo "Building SIF with $CONTAINER_CMD..."
        $CONTAINER_CMD build -F "$SIF_PATH" "docker-daemon://$DOCKER_IMAGE:$DOCKER_TAG"
        echo "$CURRENT_HASH" > "$HASH_PATH"
        echo "SIF written to: $SIF_PATH"
    fi
fi

echo ""
echo "Done."
echo "  Docker image : $DOCKER_IMAGE:$DOCKER_TAG"
[ "$DO_SIF" -eq 1 ] && echo "  SIF          : $SIF_OUTPUT_DIR/aind_nonrigid_mcorr_latest.sif"
