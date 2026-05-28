#!/bin/bash
#SBATCH -t 01:00:00
#SBATCH -N 1
#SBATCH -n 8
#SBATCH --mem=60GB
#SBATCH --partition=ou_bcs_normal
#SBATCH --export=HDF5_USE_FILE_LOCKING=FALSE
#SBATCH --mail-type=ALL
#SBATCH --job-name=aind_extraction
#SBATCH -o ./slurm_logs/aind_extraction-%j.ans

# Create log directory if it doesn't exist
mkdir -p ./slurm_logs

# Dynamically set mail-user (skip if not on SLURM)
if command -v scontrol >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    scontrol update job $SLURM_JOB_ID MailUser=$USER@mit.edu
fi

# Usage: sbatch [--mail-user=EMAIL] sbatch_aind_extraction.sh path/to/config.json
#
# Runs the AIND ophys Suite2p extraction capsule
# (aind-ophys-extraction-suite2p-docker-local_latest.sif) on every export path
# listed in the config file.  Falls back to the GHCR Docker image when the
# .sif is absent.

# Check resource availability and usage
echo "Starting job $SLURM_JOB_ID on $(hostname) at $(date)"
echo "Available CPUs: $(nproc --all)"
echo "Available memory: $(free -h | grep Mem | awk '{print $2}')"
if [ -n "${SLURM_CPUS_ON_NODE:-}" ]; then echo "Requested CPUs: $SLURM_CPUS_ON_NODE"; fi
if [ -n "${SLURM_MEM_PER_NODE:-}" ]; then echo "Requested memory: $SLURM_MEM_PER_NODE"; fi
if command -v squeue >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    echo "Requested walltime: $(squeue -j $SLURM_JOB_ID -h --Format TimeLimit)"
fi

# Get script directory (use SLURM_SUBMIT_DIR if running under SLURM, otherwise use BASH_SOURCE)
if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    SCRIPT_DIR="$SLURM_SUBMIT_DIR"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
echo "Script directory: $SCRIPT_DIR"
# Define CURRENT_DIR early so .env variable expansions can safely reference it.
CURRENT_DIR="$SCRIPT_DIR"

# Load environment variables from .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a  # auto-export all variables
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
    echo "Loaded environment from $SCRIPT_DIR/.env"
else
    echo "Warning: No .env file found at $SCRIPT_DIR/.env"
    echo "Copy template.env to .env and configure it for your environment."
fi

# Detect OS version for cluster-specific settings
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "centos" ]] && [[ "$VERSION_ID" == "7" ]]; then
            echo "centos7"
        elif [[ "$ID" == "rocky" ]] && [[ "$VERSION_ID" =~ ^8 ]]; then
            echo "rocky8"
        else
            echo "unknown"
        fi
    else
        echo "unknown"
    fi
}

OS_VERSION=$(detect_os)
echo "Detected OS: $OS_VERSION"

# Set default values if not in .env
IMAGE_REPO=${IMAGE_REPO:-$HOME/singularity_images}
LAB_SPACE=${LAB_SPACE:-}
USERNAME=${USER}

if [ "$OS_VERSION" = "rocky8" ]; then
    if [[ -d "$HOME/orcd" ]]; then
        echo "Loading modules"
        module load apptainer/1.4.2 miniforge/23.11.0-0
    else
        echo "Unknown OS version; not loading modules"
        exit 1
    fi
    USE_SINGULARITY=1
else
    # Prefer Singularity/Apptainer if available and the AIND extraction image is present
    if command -v singularity >/dev/null 2>&1 || command -v apptainer >/dev/null 2>&1; then
        if [ -f "$IMAGE_REPO/aind-ophys-extraction-suite2p-docker-local_latest.sif" ]; then
            echo "Singularity/Apptainer detected and aind-ophys-extraction image found."
            USE_SINGULARITY=1
        else
            echo "Singularity/Apptainer available but aind-ophys-extraction-suite2p-docker-local_latest.sif not found in $IMAGE_REPO"
            echo "Falling back to Docker."
            USE_SINGULARITY=0
        fi
    else
        echo "Singularity/Apptainer not found. Using Docker instead."
        USE_SINGULARITY=0
    fi
fi

# Resolve container command (singularity vs apptainer)
if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
    if command -v apptainer >/dev/null 2>&1; then
        CONTAINER_CMD="apptainer"
    else
        CONTAINER_CMD="singularity"
    fi
fi

# Config file is the first positional argument
CONFIG_FILE=$1
if [ -z "$CONFIG_FILE" ]; then
    echo "Error: No config file specified."
    echo "Usage: sbatch sbatch_aind_extraction.sh path/to/config.json"
    exit 1
fi
echo "Config file provided: $CONFIG_FILE"

# Get directory of config file
CONFIG_FILE_DIR=$(realpath "$(dirname "$CONFIG_FILE")")

# Parse config file to extract paths using Python inside the 2p_proc container
echo "Reading paths from configuration file..."

# Update remote paths (if needed)
if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
    CONFIG_FILE=$($CONTAINER_CMD run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        "$IMAGE_REPO/2p_proc_latest.sif" \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import update_remote_paths
path_file = sys.argv[1]
old_paths = sys.argv[2].split(',')
new_paths = sys.argv[3].split(',')
print(update_remote_paths(path_file, old_paths, new_paths))
" "$CONFIG_FILE" "/om/scratch/tmp,/om/user,/om2/scratch/tmp,/om2/user" \
"$OM_SCRATCH_TMP,$OM_USER_DIR_ALIAS,$OM2_SCRATCH_TMP,$OM2_USER_DIR_ALIAS")
else
    CONFIG_FILE=$(docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        wanglabneuro/2p_proc:latest \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import update_remote_paths
path_file = sys.argv[1]
old_paths = sys.argv[2].split(',')
new_paths = sys.argv[3].split(',')
print(update_remote_paths(path_file, old_paths, new_paths))
" "$CONFIG_FILE" "/om/scratch/tmp,/om/user,/om2/scratch/tmp,/om2/user" \
"$OM_SCRATCH_TMP,$OM_USER_DIR_ALIAS,$OM2_SCRATCH_TMP,$OM2_USER_DIR_ALIAS")
fi

# Read common roots
if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
    COMMON_ROOT_DATA_DIR=$($CONTAINER_CMD run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        "$IMAGE_REPO/2p_proc_latest.sif" \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "data_paths")
    COMMON_ROOT_EXPORT_DIR=$($CONTAINER_CMD run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        "$IMAGE_REPO/2p_proc_latest.sif" \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "export_paths")
    COMMON_ROOT_ZSTACK_DIR=$($CONTAINER_CMD run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        "$IMAGE_REPO/2p_proc_latest.sif" \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "zstack_paths")
    LOG_DIR=$($CONTAINER_CMD run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        "$IMAGE_REPO/2p_proc_latest.sif" \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "logging")
    IFS=' ' read -ra EXPORT_DATA_PATHS <<< "$($CONTAINER_CMD run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        "$IMAGE_REPO/2p_proc_latest.sif" \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import read_data_paths
print(read_data_paths(sys.argv[1], sys.argv[2], sys.argv[3]))
" "$CONFIG_FILE" "export_paths" "bash")"
else
    COMMON_ROOT_DATA_DIR=$(docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        wanglabneuro/2p_proc:latest \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "data_paths")
    COMMON_ROOT_EXPORT_DIR=$(docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        wanglabneuro/2p_proc:latest \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "export_paths")
    COMMON_ROOT_ZSTACK_DIR=$(docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        wanglabneuro/2p_proc:latest \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "zstack_paths")
    LOG_DIR=$(docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        wanglabneuro/2p_proc:latest \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "logging")
    IFS=' ' read -ra EXPORT_DATA_PATHS <<< "$(docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        wanglabneuro/2p_proc:latest \
        python -c "
import sys
sys.path.append('/code')
from paths_params_io import read_data_paths
print(read_data_paths(sys.argv[1], sys.argv[2], sys.argv[3]))
" "$CONFIG_FILE" "export_paths" "bash")"
fi

# Ensure export paths exist
for path in "${EXPORT_DATA_PATHS[@]}"; do
    if [ ! -d "$path" ]; then
        echo "Creating export path: $path"
        mkdir -p "$path"
    fi
done

# Check LOG_DIR
if [ ! -d "$LOG_DIR" ]; then
    echo "LOG_DIR does not exist. Creating it."
    mkdir -p "$LOG_DIR"
fi
if [ ! -w "$LOG_DIR" ]; then
    echo "LOG_DIR is not writable. Setting LOG_DIR to COMMON_ROOT_EXPORT_DIR."
    LOG_DIR=$COMMON_ROOT_EXPORT_DIR
fi

echo "Data directory:    $COMMON_ROOT_DATA_DIR"
echo "Export directory:  $COMMON_ROOT_EXPORT_DIR"
echo "Z-stack directory: $COMMON_ROOT_ZSTACK_DIR"
echo "Log directory:     $LOG_DIR"

# Set CURRENT_DIR for runtime helpers
CURRENT_DIR=$PWD

# Matplotlib cache handling
KEEP_MPL_CACHE=${KEEP_MPL_CACHE:-1}
MPL_CACHE_DIR=${MPL_CACHE_DIR:-$CURRENT_DIR/.matplotlib_cache}

setup_mpl_cache() {
    export MPLBACKEND="Agg"
    if [ "$KEEP_MPL_CACHE" = "1" ]; then
        export MPLCONFIGDIR="$MPL_CACHE_DIR"
        if ! mkdir -p "$MPLCONFIGDIR" 2>/dev/null; then
            if [ -n "${SLURM_TMPDIR:-}" ] && [ -d "${SLURM_TMPDIR:-}" ]; then
                export MPLCONFIGDIR="$(mktemp -d -p "$SLURM_TMPDIR" mpl_cache.XXXXXX)"
            else
                export MPLCONFIGDIR="$(mktemp -d -p "$CURRENT_DIR" mpl_cache.XXXXXX)"
            fi
        fi
    else
        if [ -n "${SLURM_TMPDIR:-}" ] && [ -d "${SLURM_TMPDIR:-}" ]; then
            export MPLCONFIGDIR="$(mktemp -d -p "$SLURM_TMPDIR" mpl_cache.XXXXXX)"
        else
            export MPLCONFIGDIR="$(mktemp -d -p "$CURRENT_DIR" mpl_cache.XXXXXX)"
        fi
    fi
}

cleanup_mpl_cache() {
    if [ "$KEEP_MPL_CACHE" != "1" ] && [ -n "${MPLCONFIGDIR:-}" ] && [ -d "${MPLCONFIGDIR:-}" ]; then
        rm -rf "$MPLCONFIGDIR"
    fi
}

#### AIND OPHYS EXTRACTION STEP

echo ""
echo "======================================="
echo "Running AIND ophys extraction step."
echo "======================================="

STEP_SUCCESS=1

for EXPORT_PATH in "${EXPORT_DATA_PATHS[@]}"; do
    echo "Running aind-ophys-extraction on $EXPORT_PATH"
    setup_mpl_cache

    if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
        singularity run -B "$EXPORT_PATH:$EXPORT_PATH" \
            --env MPLBACKEND="$MPLBACKEND",MPLCONFIGDIR="$MPLCONFIGDIR" \
            "$IMAGE_REPO/aind-ophys-extraction-suite2p-docker-local_latest.sif" \
            run --input-dir "$EXPORT_PATH"
        EXIT_STATUS=$?
    else
        docker run --rm \
            -v "$EXPORT_PATH:$EXPORT_PATH" \
            -e MPLBACKEND=Agg \
            -e MPLCONFIGDIR="$MPLCONFIGDIR" \
            ghcr.io/allenneuraldynamics/aind-ophys-extraction-suite2p-docker-local:latest \
            run --input-dir "$EXPORT_PATH"
        EXIT_STATUS=$?
    fi

    cleanup_mpl_cache

    if [ $EXIT_STATUS -ne 0 ]; then
        STEP_SUCCESS=0
        echo "AIND extraction failed for $EXPORT_PATH with exit status $EXIT_STATUS"
    fi
done

if [ "$STEP_SUCCESS" -ne 1 ]; then
    echo ""
    echo "One or more AIND extraction steps failed. Check logs above."
    exit 1
fi

echo ""
echo "AIND ophys extraction completed successfully."
exit 0
