#!/bin/bash
#SBATCH -t 00:30:00
#SBATCH -N 1
#SBATCH -n 8
#SBATCH --mem=32GB
#SBATCH --partition=ou_bcs_normal
#SBATCH --export=HDF5_USE_FILE_LOCKING=FALSE
#SBATCH --mail-type=ALL
#SBATCH --job-name=zmotion_correction
#SBATCH -o ./slurm_logs/zmotion_correction-%j.ans

# Usage: sbatch [--mail-user=EMAIL] sbatch_zmotion_correction.sh path/to/config.json
#
# Runs the AIND z-motion correction capsule (aind_zmotion_correction_latest.sif).
# Falls back to Docker (wanglabneuro/aind_zmotion_correction:latest) if the .sif is absent.
#
# Input (mounted as /data)   : the motion-correction results (motion_corrected.h5).
# Z-stack (mounted as /zstack): the anatomical reference stack, passed as --zstack.
# Output (mounted as /results): z_correlation.npz, z_drift.png, processing.json.

mkdir -p ./slurm_logs

if command -v scontrol >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    scontrol update job $SLURM_JOB_ID MailUser=$USER@mit.edu
fi

echo "Starting job ${SLURM_JOB_ID:-local} on $(hostname) at $(date)"

if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    SCRIPT_DIR="$SLURM_SUBMIT_DIR"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
CURRENT_DIR="$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
    echo "Loaded environment from $SCRIPT_DIR/.env"
else
    echo "Warning: No .env file found at $SCRIPT_DIR/.env"
fi

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "centos" ]] && [[ "$VERSION_ID" == "7" ]]; then echo "centos7";
        elif [[ "$ID" == "rocky" ]] && [[ "$VERSION_ID" =~ ^8 ]]; then echo "rocky8";
        else echo "unknown"; fi
    else echo "unknown"; fi
}
OS_VERSION=$(detect_os)
echo "Detected OS: $OS_VERSION"

IMAGE_REPO=${IMAGE_REPO:-$HOME/singularity_images}

if [ "$OS_VERSION" = "rocky8" ]; then
    if [[ -d "$HOME/orcd" ]]; then
        module load apptainer/1.4.2 miniforge/23.11.0-0
    else
        echo "Unknown OS version; not loading modules"; exit 1
    fi
    USE_SINGULARITY=1
else
    if command -v singularity >/dev/null 2>&1 || command -v apptainer >/dev/null 2>&1; then
        if [ -f "$IMAGE_REPO/aind_zmotion_correction_latest.sif" ]; then
            USE_SINGULARITY=1
        else
            echo "aind_zmotion_correction_latest.sif not found in $IMAGE_REPO; using Docker."
            USE_SINGULARITY=0
        fi
    else
        USE_SINGULARITY=0
    fi
fi

if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
    if command -v apptainer >/dev/null 2>&1; then CONTAINER_CMD="apptainer"; else CONTAINER_CMD="singularity"; fi
fi

CONFIG_FILE=$1
if [ -z "$CONFIG_FILE" ]; then
    echo "Error: No config file specified."
    echo "Usage: sbatch sbatch_zmotion_correction.sh path/to/config.json"
    exit 1
fi
CONFIG_FILE_DIR=$(realpath "$(dirname "$CONFIG_FILE")")

# Parse config with paths_params_io inside the 2p_proc container to locate the
# export root (holds motion_correction/ results) and the z-stack root.
read_common() {  # $1 = section key
    if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
        $CONTAINER_CMD run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" "$IMAGE_REPO/2p_proc_latest.sif" \
            python -c "import sys; sys.path.append('/code'); from paths_params_io import get_common_dir; print(get_common_dir(sys.argv[1], sys.argv[2]))" \
            "$CONFIG_FILE" "$1"
    else
        docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" wanglabneuro/2p_proc:latest \
            python -c "import sys; sys.path.append('/code'); from paths_params_io import get_common_dir; print(get_common_dir(sys.argv[1], sys.argv[2]))" \
            "$CONFIG_FILE" "$1"
    fi
}

COMMON_ROOT_EXPORT_DIR=$(read_common "export_paths")
COMMON_ROOT_ZSTACK_DIR=$(read_common "zstack_paths")

MCORR_RESULTS_DIR="$COMMON_ROOT_EXPORT_DIR/motion_correction"
ZMOTION_RESULTS_DIR="$COMMON_ROOT_EXPORT_DIR/z_motion"
mkdir -p "$ZMOTION_RESULTS_DIR"

echo "Motion-correction dir (/data)   : $MCORR_RESULTS_DIR"
echo "Z-stack dir           (/zstack) : $COMMON_ROOT_ZSTACK_DIR"
echo "Results dir           (/results): $ZMOTION_RESULTS_DIR"

export MPLBACKEND="Agg"
MPLCONFIGDIR=${MPLCONFIGDIR:-$CURRENT_DIR/.matplotlib_cache}
mkdir -p "$MPLCONFIGDIR"

echo ""
echo "======================================="
echo "Running z-motion correction step."
echo "======================================="

if [ "${USE_SINGULARITY:-0}" -eq 1 ]; then
    $CONTAINER_CMD run \
        -B "$MCORR_RESULTS_DIR:/data" \
        -B "$COMMON_ROOT_ZSTACK_DIR:/zstack" \
        -B "$ZMOTION_RESULTS_DIR:/results" \
        -B "$MPLCONFIGDIR:$MPLCONFIGDIR" \
        --env MPLBACKEND="$MPLBACKEND",MPLCONFIGDIR="$MPLCONFIGDIR" \
        "$IMAGE_REPO/aind_zmotion_correction_latest.sif" \
        --zstack /zstack
    EXIT_STATUS=$?
else
    docker run --rm \
        -v "$MCORR_RESULTS_DIR:/data" \
        -v "$COMMON_ROOT_ZSTACK_DIR:/zstack" \
        -v "$ZMOTION_RESULTS_DIR:/results" \
        -e MPLBACKEND=Agg \
        -e MPLCONFIGDIR="$MPLCONFIGDIR" \
        wanglabneuro/aind_zmotion_correction:latest \
        --zstack /zstack
    EXIT_STATUS=$?
fi

if [ $EXIT_STATUS -ne 0 ]; then
    echo "Z-motion correction failed with exit status $EXIT_STATUS"
    exit 1
fi

echo ""
echo "Z-motion correction completed successfully. Outputs in $ZMOTION_RESULTS_DIR"
exit 0
