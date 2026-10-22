#!/bin/bash
#SBATCH -t 04:00:00                                 # walltime; ROICaT on CPU takes ~10-30 min for 3 sessions
#SBATCH -N 1                                        # 1 node
#SBATCH -n 16                                       # CPU cores
#SBATCH --mem=64GB                                  # memory
#SBATCH --partition=ou_bcs_normal                   # Default partition for BCS
#SBATCH --mail-type=ALL                             # email on start, end, and fail
#SBATCH --job-name=register_sessions                # job name
#SBATCH -o ./slurm_logs/register_sessions-%j.ans    # log files (%j expands to jobID)

# Match the same cells across separately processed sessions of one field of view
# (pipeline.register_sessions). Validated in validation/registration (see
# validation/report/registration/registration_report.html).
#
# Usage:
#   sbatch --mail-user=$EMAIL register_sessions.sh --exports <export1> <export2> ... [options]
#   sbatch --mail-user=$EMAIL register_sessions.sh --config <config.json> [options]
#
# Options (passed to pipeline.register_sessions):
#   --exports DIR ...    pipeline export folders (Suite2p suite2p/plane0, or CNMF results_caiman.mat)
#   --config FILE        config with paths.export_paths and optional params_registration
#   --out DIR            output folder (default: <common parent>/cell_registration_<method>)
#   --method M           roicat (default) or caiman
#   --um-per-pixel X     default: imaging.microns_per_pixel from the config, else 1.45
#   --iscell-file F      Suite2p iscell file (default iscell.npy, e.g. a curated copy)
#
# Images (from IMAGE_REPO in .env next to this script): 2p_registration_latest.sif for roicat,
# 2p_proc_latest.sif for caiman.
# Outputs: cell_registration.npz / .mat (cells x sessions ROI indices, extraction order; 1-based
# in the .mat, 0 = absent), cell_registration_qc.json (matches, affine residual and FOV
# similarity per session pair) and cell_registration.png.

mkdir -p ./slurm_logs

if command -v scontrol >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    scontrol update job "$SLURM_JOB_ID" MailUser="$USER@mit.edu"
fi
echo "Starting job ${SLURM_JOB_ID:-local} on $(hostname) at $(date)"

if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    SCRIPT_DIR="$SLURM_SUBMIT_DIR"
else
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
fi
CURRENT_DIR="$SCRIPT_DIR"
if [ -f "$SCRIPT_DIR/.env" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    echo "Loaded environment from $SCRIPT_DIR/.env"
fi
IMAGE_REPO=${IMAGE_REPO:-$HOME/singularity_images}

# Parse arguments: keep them for the Python call, and collect paths to bind
ARGS=("$@")
METHOD=roicat
CONFIG=""
PATHS=()
mode=""
for a in "$@"; do
    case "$a" in
        --exports) mode=exports; continue ;;
        --out) mode=out; continue ;;
        --config) mode=config; continue ;;
        --method) mode=method; continue ;;
        --*) mode=""; continue ;;
    esac
    case "$mode" in
        exports) PATHS+=("$(realpath "$a")") ;;
        out) PATHS+=("$(realpath -m "$a")"); mode="" ;;
        config) CONFIG="$(realpath "$a")"; PATHS+=("$(dirname "$CONFIG")"); mode="" ;;
        method) METHOD="$a"; mode="" ;;
    esac
done
if [ ${#ARGS[@]} -eq 0 ]; then
    echo "Usage: sbatch register_sessions.sh --exports <export1> <export2> ... [--out DIR] [--method roicat|caiman]"
    exit 1
fi

case "$METHOD" in
    roicat) IMAGE="$IMAGE_REPO/2p_registration_latest.sif"; EXTRA=(--cpu) ;;
    caiman) IMAGE="$IMAGE_REPO/2p_proc_latest.sif"; EXTRA=() ;;
    *) echo "Unsupported method in a container: $METHOD (use roicat or caiman)"; exit 1 ;;
esac
if [ ! -f "$IMAGE" ]; then
    echo "Image not found: $IMAGE"
    exit 1
fi

# Bind the top-level folders of all inputs/outputs (e.g. /orcd), plus the config's export paths
if [ -n "$CONFIG" ]; then
    while IFS= read -r p; do
        [ -n "$p" ] && PATHS+=("$p")
    done < <(python3 -c "import json,sys; [print(p) for p in json.load(open(sys.argv[1])).get('paths',{}).get('export_paths',[])]" "$CONFIG" 2>/dev/null)
fi
BINDS=$(for p in "${PATHS[@]}"; do echo "/$(echo "$p" | cut -d/ -f2)"; done | sort -u | paste -sd, -)
echo "Method: $METHOD; image: $IMAGE; binds: $BINDS"

module load apptainer/1.4.2 2>/dev/null || module load apptainer 2>/dev/null || true
CONTAINER_CMD=$(command -v apptainer || command -v singularity)
export MPLBACKEND=Agg
"$CONTAINER_CMD" run --cleanenv -B "$BINDS" "$IMAGE" \
    python -u -m pipeline.register_sessions "${ARGS[@]}" "${EXTRA[@]}"
STATUS=$?
echo "Finished with status $STATUS at $(date)"
exit $STATUS
