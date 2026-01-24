#!/bin/bash
# Script to create Allen Neural Dynamics Docker images

# Default capsule name if not provided
DEFAULT_CAPSULE_NAME="aind-ophys-extraction-suite2p"
CAPSULE_NAME="${1:-$DEFAULT_CAPSULE_NAME}"

echo "Building container using capsule name: $CAPSULE_NAME"

docker build \
    --build-arg CAPSULE_NAME=$CAPSULE_NAME \
    -f Dockerfile \
    -t wanglabneuro/$CAPSULE_NAME-docker-local:latest \
    . \
    --no-cache

## Tests
echo "Build completed for image: wanglabneuro/$CAPSULE_NAME-docker-local:latest"

echo "Running test to verify container..."
docker run --rm -it wanglabneuro/$CAPSULE_NAME-docker-local:latest python3 -c "import sys; print('Python version:', sys.version)"

echo "To run the Analysis 2P pipeline with this container, use:"
echo "docker run --rm -it -v /path/to/data:/data wanglabneuro/$CAPSULE_NAME-docker-local:latest [arguments]"