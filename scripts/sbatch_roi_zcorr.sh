#!/bin/bash
#SBATCH -t 00:30:00
#SBATCH -N 1
#SBATCH -n 8
#SBATCH --mem=32GB
#SBATCH --partition=ou_bcs_normal
#SBATCH --export=HDF5_USE_FILE_LOCKING=FALSE
#SBATCH --mail-type=ALL
#SBATCH --job-name=roi_zcorr
#SBATCH -o ./slurm_logs/roi_zcorr-%j.ans

# Create log directory if it doesn't exist
mkdir -p ./slurm_logs

# Dynamically set mail-user (skip if not on SLURM)
if command -v scontrol >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    scontrol update job $SLURM_JOB_ID MailUser=$USER@mit.edu
fi

# Usage: sbatch [--mail-user=EMAIL] sbatch_roi_zcorr.sh path/to/config.json
#
# Runs the ROI z-motion correction step via pipeline.roi_zcorr inside the
# 2p_proc_latest.sif container.  Falls back to Docker when the .sif is absent.
#
# This step requires:
#   - params_mcorr.z_motion_correction set in the config
#   - paths.zstack_paths containing at least one non-empty entry

USE_STABLE=1  # Set to 1 to use stable (main branch) version of the pipeline, 0 to use latest (dev branch)
if [ $USE_STABLE -eq 1 ]; then
    echo "RUNNING STABLE (MAIN BRANCH) VERSION OF THE PIPELINE"
else
    echo "RUNNING LATEST (DEV BRANCH) VERSION OF THE PIPELINE"
fi

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
    # Prefer Singularity/Apptainer if available and the main 2p_proc image is present
    if command -v singularity >/dev/null 2>&1 || command -v apptainer >/dev/null 2>&1; then
        if [ -f "$IMAGE_REPO/2p_proc_latest.sif" ]; then
            echo "Singularity/Apptainer detected and 2p_proc image found."
            USE_SINGULARITY=1
        else
            echo "Singularity/Apptainer available but 2p_proc_latest.sif not found in $IMAGE_REPO"
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
    echo "Usage: sbatch sbatch_roi_zcorr.sh path/to/config.json"
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
fi

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

#### ROI Z-MOTION CORRECTION STEP

echo ""
echo "================================"
echo "Running ROI z-motion correction."
echo "================================"

# Build mount points (same logic as 2P_proc_template.sh)
if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
    DIRS=()
    [ -n "$CONFIG_FILE_DIR" ] && [[ "$CONFIG_FILE_DIR" = /* ]] && DIRS+=("$CONFIG_FILE_DIR")
    [ -n "$LOG_DIR" ] && [[ "$LOG_DIR" = /* ]] && DIRS+=("$LOG_DIR")
    if [ -n "$COMMON_ROOT_DATA_DIR" ] && [[ "$COMMON_ROOT_DATA_DIR" = /* ]]; then
        SESSION_ROOT_DIR="$(dirname "$COMMON_ROOT_DATA_DIR")"
        DIRS+=("$SESSION_ROOT_DIR" "$COMMON_ROOT_DATA_DIR")
    fi
    [ -n "$COMMON_ROOT_EXPORT_DIR" ] && [[ "$COMMON_ROOT_EXPORT_DIR" = /* ]] && DIRS+=("$COMMON_ROOT_EXPORT_DIR")
    [ -n "$COMMON_ROOT_ZSTACK_DIR" ] && [[ "$COMMON_ROOT_ZSTACK_DIR" = /* ]] && DIRS+=("$COMMON_ROOT_ZSTACK_DIR")
    [ -n "$CURRENT_DIR" ] && [[ "$CURRENT_DIR" = /* ]] && DIRS+=("$CURRENT_DIR")
    [ -n "$SLURM_SUBMIT_DIR" ] && [[ "$SLURM_SUBMIT_DIR" = /* ]] && DIRS+=("$SLURM_SUBMIT_DIR")

    # Exact (non-substring) de-duplication of mount points
    UNIQ_DIRS=()
    for dir in "${DIRS[@]}"; do
        [ -z "$dir" ] && continue
        already=0
        for u in "${UNIQ_DIRS[@]}"; do
            if [ "$u" = "$dir" ]; then
                already=1
                break
            fi
        done
        if [ $already -eq 0 ]; then
            UNIQ_DIRS+=("$dir")
        fi
    done

    MOUNT_POINTS=$(IFS=, ; echo "${UNIQ_DIRS[*]}")
    echo "MOUNT_POINTS: $MOUNT_POINTS"
fi

setup_mpl_cache

if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
    if [ $USE_STABLE -eq 1 ]; then
        singularity run -B "$MOUNT_POINTS" \
            --env MPLBACKEND="$MPLBACKEND",MPLCONFIGDIR="$MPLCONFIGDIR" \
            "$IMAGE_REPO/2p_proc_latest.sif" \
            python -u -m pipeline.roi_zcorr "$CONFIG_FILE"
    else
        echo "Using code directory: $PIPELINE_CODE_DIR for ROI z-correction."
        singularity run -B "$MOUNT_POINTS" \
            -B "$PIPELINE_CODE_DIR:/code" \
            --env MPLBACKEND="$MPLBACKEND",MPLCONFIGDIR="$MPLCONFIGDIR" \
            "$IMAGE_REPO/2p_proc_latest.sif" \
            python -u -m pipeline.roi_zcorr "$CONFIG_FILE"
    fi
    EXIT_STATUS=$?
else
    SCRIPT_DIR_LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_DIR="$(dirname "$SCRIPT_DIR_LOCAL")"
    CODE_DIR=$REPO_DIR
    echo "Using code directory: $CODE_DIR"
    docker run --rm \
        --user "$HOST_USER_ID:$HOST_GROUP_ID" \
        -v "$COMMON_ROOT_DATA_DIR:$COMMON_ROOT_DATA_DIR" \
        -v "$COMMON_ROOT_EXPORT_DIR:$COMMON_ROOT_EXPORT_DIR" \
        -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" \
        -v "$LOG_DIR:$LOG_DIR" \
        -v "$CODE_DIR:/code" \
        -e MPLBACKEND=Agg \
        -e MPLCONFIGDIR="$MPLCONFIGDIR" \
        wanglabneuro/2p_proc:latest \
        python -u -m pipeline.roi_zcorr "$CONFIG_FILE"
    EXIT_STATUS=$?
fi

cleanup_mpl_cache

if [ $EXIT_STATUS -ne 0 ]; then
    echo "ROI z-motion correction failed with exit status $EXIT_STATUS"
    exit 1
fi

echo ""
echo "ROI z-motion correction completed successfully."
exit 0
