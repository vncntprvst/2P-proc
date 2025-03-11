#!/bin/bash

# Define the environment directory name and archive file
CONDA_ENV_NAME="analysis2p_ui"
ENV_DIR=$(conda info --envs | grep "$CONDA_ENV_NAME" | awk '{print $NF}')

# If the environment folder doesn't exist, extract it
if [ ! -d "$ENV_DIR" ]; then
    TARGET_DIR="./portable_env"
    # Create target directory if it doesn't exist
    if [ ! -d "$TARGET_DIR" ]; then
        mkdir -p "$TARGET_DIR"
    fi

    # Download the portable environment
    echo "Environment directory not found: $ENV_DIR. Downloading and extracting the portable environment..."
    ARCHIVE_FILE="analysis2p_ui.tar.gz"
    GITHUB_RELEASE_URL="https://github.com/pseudomanu/Analysis_2P/releases/download/0.3.5/$ARCHIVE_FILE"
    curl -L -o "$ARCHIVE_FILE" "$GITHUB_RELEASE_URL"
    
    echo "Extracting the portable environment..."
    tar -xzf "$ARCHIVE_FILE" -C "$TARGET_DIR"
    # After extraction, the environment folder will be inside TARGET_DIR
    ENV_DIR="$TARGET_DIR/$CONDA_ENV_NAME"
    # Fix paths inside the extracted environment
    "$ENV_DIR/bin/conda-unpack"

    # Activate the environment
    source "$ENV_DIR/bin/activate"  
else
    echo "Found environment directory: $ENV_DIR"
    # Get the base environment directory
    BASE_ENV_DIR=$(conda info --base)
    echo "Base environment directory: $BASE_ENV_DIR"

    # Source the conda initialization script
    source "$BASE_ENV_DIR/etc/profile.d/conda.sh"

    # Activate the environment
    conda activate analysis2p_ui
fi

echo "Running the app..."
# python ui_app.py
streamlit run ui_app.py

# Optionally deactivate at the end
# deactivate