#!/bin/bash

LOGFILE="a2p_ui_log.txt"
CONDA_ENV_NAME="analysis2p_ui"

# Function to find a free port starting at 8502
find_free_port() {
    local PORT=8502
    while netstat -tuln | grep -q ":$PORT "; do
        ((PORT++))
    done
    echo "$PORT"
}

# Check if the conda environment exists
ENV_DIR=$(conda info --envs | grep "$CONDA_ENV_NAME" | awk '{print $NF}')

if [ -d "$ENV_DIR" ]; then
    echo "Environment $CONDA_ENV_NAME found." | tee "$LOGFILE"
else
    echo "Environment $CONDA_ENV_NAME not found." | tee "$LOGFILE"
    echo "Please choose an option:"
    echo "1. Install conda environment"
    echo "2. Download and extract the portable environment"
    echo "3. Exit"
    read -p "Enter your choice (1, 2, or 3): " choice
    echo "User selected option: $choice" | tee -a "$LOGFILE"

    if [ "$choice" == "1" ]; then
        echo "Installing conda environment..." | tee -a "$LOGFILE"
        conda create -n "$CONDA_ENV_NAME" python=3.9 -y >> "$LOGFILE" 2>&1
        source "$(conda info --base)/etc/profile.d/conda.sh"
        conda activate "$CONDA_ENV_NAME" >> "$LOGFILE" 2>&1
        pip install streamlit python-dotenv >> "$LOGFILE" 2>&1
        echo "Installation complete. Restarting script..." | tee -a "$LOGFILE"
        exec "$0"
        exit 0
    elif [ "$choice" == "2" ]; then
        echo "Downloading and extracting the portable environment..." | tee -a "$LOGFILE"
        
        TARGET_DIR="./portable_env"
        ARCHIVE_FILE="analysis2p_ui.tar.gz"
        GITHUB_RELEASE_URL="https://github.com/pseudomanu/Analysis_2P/releases/download/0.3.6/$ARCHIVE_FILE"
        
        # Create target directory if it doesn't exist
        mkdir -p "$TARGET_DIR"
        
        curl -L -o "$ARCHIVE_FILE" "$GITHUB_RELEASE_URL" >> "$LOGFILE" 2>&1
        echo "Extracting the portable environment..." | tee -a "$LOGFILE"
        tar -xzf "$ARCHIVE_FILE" -C "$TARGET_DIR" >> "$LOGFILE" 2>&1
        
        ENV_DIR="$TARGET_DIR/$CONDA_ENV_NAME"
        echo "Fixing paths inside the extracted environment..." | tee -a "$LOGFILE"
        "$ENV_DIR/bin/conda-unpack" >> "$LOGFILE" 2>&1
    else
        echo "Exiting..." | tee -a "$LOGFILE"
        exit 0
    fi
fi

echo "Activating environment..." | tee -a "$LOGFILE"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV_NAME" >> "$LOGFILE" 2>&1

# Find a free port
PORT=$(find_free_port)
echo "Running the app on port $PORT..." | tee -a "$LOGFILE"

# Start the Streamlit app
streamlit run ui_app.py --server.port "$PORT"

echo "Press any key to exit."
read -n 1 -s
exit 0
