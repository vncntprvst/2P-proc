#!/bin/bash
#SBATCH -t 02:00:00
#SBATCH -N 1
#SBATCH -n 16
#SBATCH --mem=64GB
#SBATCH --partition=ou_bcs_normal
#SBATCH --job-name=benchmark_zcorr
#SBATCH -o ./slurm_logs/benchmark_zcorr-%j.ans

# Run the full z-correction benchmark sweep.
#
# Usage:
#   sbatch sbatch_benchmark_zcorr.sh [--results-dir DIR] [--n-frames N]
#
# Results are written to RESULTS_DIR (default: ./benchmark_results/).
# Requires the 2p_proc singularity image (or an activated conda env with
# optimouse + caiman installed).

set -euo pipefail
mkdir -p ./slurm_logs

echo "Starting benchmark job $SLURM_JOB_ID on $(hostname) at $(date)"

if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    SCRIPT_DIR="$SLURM_SUBMIT_DIR"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a; source "$SCRIPT_DIR/.env"; set +a
fi
IMAGE_REPO="${IMAGE_REPO:-$HOME/.apptainer/images}"

# Parse optional arguments
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/benchmark_results}"
N_FRAMES=300
HEIGHT=256
WIDTH=256
N_Z=25

while [[ $# -gt 0 ]]; do
    case "$1" in
        --results-dir) RESULTS_DIR="$2"; shift 2 ;;
        --n-frames)    N_FRAMES="$2";    shift 2 ;;
        --height)      HEIGHT="$2";      shift 2 ;;
        --width)       WIDTH="$2";       shift 2 ;;
        --n-z)         N_Z="$2";         shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

mkdir -p "$RESULTS_DIR"
echo "Results dir: $RESULTS_DIR"

# Matplotlib + CaImAn temp setup
MPLCONFIGDIR=$(mktemp -d -p "${SLURM_TMPDIR:-$RESULTS_DIR}" mpl_cache.XXXXXX)
CAIMAN_TEMP=$(mktemp -d -p "$RESULTS_DIR" caiman_tmp.XXXXXX)
export MPLBACKEND=Agg

RUN_CMD="python $REPO_ROOT/tests/benchmarks/benchmark_zcorr.py \
    --save-results $RESULTS_DIR \
    --n-frames $N_FRAMES \
    --height $HEIGHT \
    --width $WIDTH \
    --n-z $N_Z"

SIF="$IMAGE_REPO/2p_proc_latest.sif"
if [ -f "$SIF" ]; then
    if command -v apptainer &>/dev/null; then CONTAINER_CMD=apptainer
    else CONTAINER_CMD=singularity; fi
    echo "Running inside container: $SIF"
    $CONTAINER_CMD run \
        -B "$REPO_ROOT:$REPO_ROOT" \
        -B "$RESULTS_DIR:$RESULTS_DIR" \
        -B "$CAIMAN_TEMP:$CAIMAN_TEMP" \
        -B "$MPLCONFIGDIR:$MPLCONFIGDIR" \
        --env CAIMAN_TEMP="$CAIMAN_TEMP",MPLBACKEND=Agg,MPLCONFIGDIR="$MPLCONFIGDIR" \
        "$SIF" \
        $RUN_CMD
else
    echo "SIF not found at $SIF — running in current environment"
    export CAIMAN_TEMP MPLCONFIGDIR
    $RUN_CMD
fi

rm -rf "$CAIMAN_TEMP" "$MPLCONFIGDIR"
echo "Benchmark complete. Results in $RESULTS_DIR"
