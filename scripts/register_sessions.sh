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
# Images (from IMAGE_REPO in .env next to this script): 2p_registration_<REG_VERSION>.sif for roicat,
# 2p_proc_<P2P_VERSION>.sif for caiman. Set REG_VERSION / P2P_VERSION in .env to use another version.
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
REG_VERSION=${REG_VERSION:-0.1.1}
P2P_VERSION=${P2P_VERSION:-0.12.0}

# Run archive: a copy of the log (and config) goes to $LAB_SPACE/A2P/runs/$USER, as for 2P_proc.sh
LAB_SPACE=${LAB_SPACE:-}
if [ -z "$LAB_SPACE" ] && [ -d /orcd/data/fan_wang/001/A2P/runs ]; then
    LAB_SPACE=/orcd/data/fan_wang/001
fi
archive_run() {
    local status=$? dest log
    [ -n "$LAB_SPACE" ] && [ -n "${SLURM_JOB_ID:-}" ] || return
    dest="$LAB_SPACE/A2P/runs/$USER"
    mkdir -p "$dest" 2>/dev/null || { echo "Cannot write to the run archive $dest"; return; }
    log=$(scontrol show job "$SLURM_JOB_ID" 2>/dev/null | sed -n 's/^ *StdOut=//p')
    [ -f "$log" ] || log="./slurm_logs/register_sessions-${SLURM_JOB_ID}.ans"
    echo "Archiving log in $dest (exit status $status)"
    [ -f "$log" ] && cp "$log" "$dest/register_sessions-${SLURM_JOB_ID}.log"
    [ -n "$CONFIG" ] && [ -f "$CONFIG" ] && cp "$CONFIG" "$dest/"
}
trap archive_run EXIT

usage() {
    echo "Usage: sbatch register_sessions.sh --exports <export1> <export2> ... [--out DIR] [--method roicat|caiman]"
    echo "   or: sbatch register_sessions.sh --config <config.json> [options]"
}

# Export folders given without --exports are taken as --exports
if [ $# -gt 0 ] && [[ "$1" != --* ]]; then
    set -- --exports "$@"
fi

# Parse arguments: pass them to the Python call with resolved paths, and collect paths to bind
ARGS=()
METHOD=roicat
CONFIG=""
PATHS=()
mode=""
for a in "$@"; do
    case "$a" in
        --exports|--out|--config|--method|--um-per-pixel|--python|--iscell-file)
            mode=${a#--}; ARGS+=("$a"); continue ;;
        --cpu) mode=""; ARGS+=("$a"); continue ;;
        --*) echo "Unknown option: $a"; usage; exit 1 ;;
    esac
    case "$mode" in
        exports) p="$(realpath "$a")"; PATHS+=("$p"); ARGS+=("$p") ;;
        out) p="$(realpath -m "$a")"; PATHS+=("$p"); ARGS+=("$p"); mode="" ;;
        config) CONFIG="$(realpath "$a")"; PATHS+=("$(dirname "$CONFIG")"); ARGS+=("$CONFIG"); mode="" ;;
        method) METHOD="$a"; ARGS+=("$a"); mode="" ;;
        um-per-pixel|python|iscell-file) ARGS+=("$a"); mode="" ;;
        *) echo "Unexpected argument: $a"; usage; exit 1 ;;
    esac
done
if [ ${#PATHS[@]} -eq 0 ]; then
    echo "No export folders or config given."
    usage
    exit 1
fi

case "$METHOD" in
    roicat) IMAGE="$IMAGE_REPO/2p_registration_${REG_VERSION}.sif"; EXTRA=(--cpu) ;;
    caiman) IMAGE="$IMAGE_REPO/2p_proc_${P2P_VERSION}.sif"; EXTRA=() ;;
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
