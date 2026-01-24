#!/bin/bash

DEFAULT_CAPSULE_NAME="aind-ophys-extraction-suite2p"
CAPSULE_NAME="${1:-$DEFAULT_CAPSULE_NAME}"
SIF_NAME="${CAPSULE_NAME}-latest.sif"

echo "Building container using capsule name: $CAPSULE_NAME"

echo "Building Docker image..."
if ! docker build \
    --build-arg CAPSULE_NAME=$CAPSULE_NAME \
    -f Dockerfile \
    -t wanglabneuro/$CAPSULE_NAME-docker-local:latest \
    . \
    --no-cache; then
    echo "ERROR: Docker build failed."
    exit 1
fi

# Push to Docker registry
if ! docker push --all-tags wanglabneuro/$CAPSULE_NAME-docker-local; then
    echo "WARNING: Failed to push to Docker registry. Continuing with local image."
    echo "If you want to push to Docker Hub, please check your credentials and permissions."
    # Don't exit, continue with local image for singularity conversion
else
    echo "Successfully pushed Docker image to registry."
fi


# Convert Docker image to Singularity image
# Requires Singularity installed on your system.
if ! command -v apptainer &> /dev/null
then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit
else
    # If a hash file exists, check the hash matches the current Docker image. If not, build a new Singularity image.
    if [ -f "$CAPSULE_NAME.sif.hash" ]; then
        if [ "$(docker inspect wanglabneuro/$CAPSULE_NAME-docker-local:latest --format='{{.Id}}')" == "$(cat $CAPSULE_NAME.sif.hash)" ]; then
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
        echo "Building Singularity image as: $SIF_NAME"
        
        # Verify that Docker image exists locally
        if ! docker image inspect wanglabneuro/$CAPSULE_NAME-docker-local:latest >/dev/null 2>&1; then
            echo "ERROR: Local Docker image not found. Cannot build Singularity image."
            exit 1
        fi
        
        # Build from local Docker image
        apptainer build -F "$SIF_NAME" docker-daemon://wanglabneuro/$CAPSULE_NAME-docker-local:latest
        local_build_status=$?
                
        # Check if build succeeded
        if [ -f "$SIF_NAME" ]; then
            echo "Singularity image built successfully as $SIF_NAME"
            # Store a hash of the Docker image in a file
            docker inspect wanglabneuro/$CAPSULE_NAME-docker-local:latest --format='{{.Id}}' > "$CAPSULE_NAME.sif.hash"
        else
            echo "ERROR: Failed to build Singularity image"
            exit 1
        fi
    fi

fi

# If the .env script exists, get the HPCC_IMAGE_REPO variable
ENV_FILE="../../scripts/utils/.env"
if [ -f "$ENV_FILE" ]; then
    echo "Getting server information from .env file: $ENV_FILE"
    
    # Check if file is readable
    if [ ! -r "$ENV_FILE" ]; then
        echo "WARNING: .env file exists but is not readable. Skipping HPCC transfer."
    else
        # Source the environment variables
        while IFS='=' read -r key value; do
            if [[ $key != \#* && -n $key ]]; then
                export "$key=$value"
            fi
        done < "$ENV_FILE"
        
        # Check required variables
        if [ -z "${SSH_TRANSFER_NODE}" ]; then
            echo "WARNING: SSH_TRANSFER_NODE not set in .env file. Skipping HPCC transfer."
        elif [ -z "${HPCC_IMAGE_REPO}" ]; then
            echo "WARNING: HPCC_IMAGE_REPO not set in .env file. Skipping HPCC transfer."
        else
            export SSH_HPCC_IMAGE_REPO="${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}"
        fi
    fi
else
    echo "INFO: .env file not found at $ENV_FILE. Skipping HPCC transfer."
fi

# Check if HPCC transfer is possible
if [ -n "${SSH_HPCC_IMAGE_REPO+x}" ]; then
    if [ -f "$SIF_NAME" ]; then
        echo "Copying Singularity image to HPCC..."
        
        # Test SSH connection first
        echo "Testing SSH connection to $SSH_TRANSFER_NODE..."
        if ! ssh -q "$SSH_TRANSFER_NODE" exit; then
            echo "ERROR: SSH connection to $SSH_TRANSFER_NODE failed. Check your SSH configuration."
            echo "HPCC transfer skipped."
        else
            # Verify destination directory exists
            echo "Verifying destination directory exists on HPCC..."
            if ! ssh "$SSH_TRANSFER_NODE" "mkdir -p $(dirname ${HPCC_IMAGE_REPO})"; then
                echo "ERROR: Failed to verify/create directory on HPCC."
                echo "HPCC transfer skipped."
            else
                # Perform the transfer
                echo "Starting file transfer to HPCC..."
                rsync -aP "$SIF_NAME" "$SSH_HPCC_IMAGE_REPO/"
                if [ $? -eq 0 ]; then
                    echo "SUCCESS: Copied $SIF_NAME to HPCC at $SSH_HPCC_IMAGE_REPO"
                else
                    echo "ERROR: Failed to copy $SIF_NAME to HPCC using rsync."
                    echo "Check your SSH configuration and permissions."
                fi
            fi
        fi
    else
        echo "ERROR: Singularity image $SIF_NAME not found. Cannot copy to HPCC."
    fi
else
    echo "INFO: HPCC transfer configuration not complete. Skipping HPCC transfer."
fi