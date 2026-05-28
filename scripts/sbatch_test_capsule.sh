#!/bin/bash
#SBATCH -t 00:30:00
#SBATCH -N 1
#SBATCH -n 8
#SBATCH --mem=32GB
#SBATCH --partition=ou_bcs_normal
#SBATCH --export=HDF5_USE_FILE_LOCKING=FALSE
#SBATCH --mail-type=ALL
#SBATCH --job-name=test_nonrigid_mcorr
#SBATCH -o ./slurm_logs/test_nonrigid_mcorr-%j.ans

# Test run for the aind_nonrigid_mcorr capsule on a small dataset.
#
# Usage:
#   sbatch sbatch_test_capsule.sh DATA_DIR RESULTS_DIR
#
#   DATA_DIR     Directory containing a single *.h5 file with a 'data' dataset
#                (T x H x W, float32). Use prepare_aind_test_data.py to create
#                one from existing TIFFs if needed.
#   RESULTS_DIR  Directory where capsule outputs will be written.
#
# After the job completes, run:
#   python validate_capsule_output.py RESULTS_DIR [DATA_DIR/movie.h5]

set -euo pipefail
mkdir -p ./slurm_logs

echo "Starting test capsule job $SLURM_JOB_ID on $(hostname) at $(date)"
echo "CPUs: $(nproc --all)  Memory: $(free -h | grep Mem | awk '{print $2}')"

# Get script directory
if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    SCRIPT_DIR="$SLURM_SUBMIT_DIR"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# Load .env
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a; source "$SCRIPT_DIR/.env"; set +a
    echo "Loaded $SCRIPT_DIR/.env"
fi

IMAGE_REPO="${IMAGE_REPO:-$HOME/.apptainer/images}"

# Positional arguments
DATA_DIR="${1:-}"
RESULTS_DIR="${2:-}"
if [ -z "$DATA_DIR" ] || [ -z "$RESULTS_DIR" ]; then
    echo "ERROR: DATA_DIR and RESULTS_DIR are required."
    echo "Usage: sbatch sbatch_test_capsule.sh DATA_DIR RESULTS_DIR"
    exit 1
fi
DATA_DIR=$(realpath "$DATA_DIR")
mkdir -p "$RESULTS_DIR"
RESULTS_DIR=$(realpath "$RESULTS_DIR")

echo "Data dir   : $DATA_DIR"
echo "Results dir: $RESULTS_DIR"

# Detect apptainer vs singularity
if command -v apptainer &>/dev/null; then
    CONTAINER_CMD=apptainer
elif command -v singularity &>/dev/null; then
    CONTAINER_CMD=singularity
else
    echo "ERROR: neither apptainer nor singularity found."
    exit 1
fi

# Check for the SIF
SIF="$IMAGE_REPO/aind_nonrigid_mcorr_latest.sif"
if [ ! -f "$SIF" ]; then
    echo "ERROR: SIF not found at $SIF"
    echo "Build it first: bash containers/aind_nonrigid_mcorr/build.sh"
    exit 1
fi
echo "Using SIF: $SIF"

# Matplotlib and CaImAn temp dirs
MPLCONFIGDIR=$(mktemp -d -p "${SLURM_TMPDIR:-$RESULTS_DIR}" mpl_cache.XXXXXX)
CAIMAN_TEMP=$(mktemp -d -p "$RESULTS_DIR" caiman_tmp.XXXXXX)
export MPLBACKEND=Agg

echo ""
echo "======================================="
echo "Running capsule (test mode)"
echo "======================================="

$CONTAINER_CMD run \
    -B "$DATA_DIR:/data" \
    -B "$RESULTS_DIR:/results" \
    -B "$CAIMAN_TEMP:$CAIMAN_TEMP" \
    -B "$MPLCONFIGDIR:$MPLCONFIGDIR" \
    --env CAIMAN_TEMP="$CAIMAN_TEMP",MPLBACKEND=Agg,MPLCONFIGDIR="$MPLCONFIGDIR" \
    "$SIF" \
    --pw-rigid \
    --max-shifts 6 \
    --strides 48 \
    --overlaps 24
EXIT_STATUS=$?

rm -rf "$CAIMAN_TEMP" "$MPLCONFIGDIR"

if [ $EXIT_STATUS -ne 0 ]; then
    echo "Capsule exited with status $EXIT_STATUS"
    exit 1
fi

echo ""
echo "Capsule finished. Validating outputs..."
python "$SCRIPT_DIR/validate_capsule_output.py" "$RESULTS_DIR"
VALIDATE_STATUS=$?

echo ""
echo "Results written to: $RESULTS_DIR"
ls -lh "$RESULTS_DIR"

exit $VALIDATE_STATUS
