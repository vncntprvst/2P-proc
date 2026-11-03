#!/bin/bash
#SBATCH -t 01:00:00
#SBATCH -N 1
#SBATCH -n 4
#SBATCH --mem=32GB
#SBATCH --partition=ou_bcs_normal
#SBATCH --job-name=concat_timing
#SBATCH -o ./slurm_logs/concat_timing-%j.ans

# Time the parts of the concatenation step for raw folders on different storage.
# Usage: sbatch concat_timing.sh <out_dir> <raw_folder> [<raw_folder> ...]
# Set P2P_VERSION to pick the 2p_proc image (default 0.13.0).

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
[ -n "${SLURM_SUBMIT_DIR:-}" ] && REPO="$(cd "$SLURM_SUBMIT_DIR/../.." && pwd)"
[ -f "$REPO/scripts/.env" ] && source "$REPO/scripts/.env"
IMAGE="${IMAGE_REPO:-$HOME/singularity_images}/2p_proc_${P2P_VERSION:-0.13.0}.sif"
OUT="$1"; shift
SRC=(); BINDS="$REPO,$OUT"
for s in "$@"; do SRC+=(--src "$s"); BINDS="$BINDS,$s"; done
mkdir -p "$OUT"

echo "Node $(hostname), image $IMAGE"
for s in "$@" "$OUT"; do df -hT "$s" | tail -1; done
module load apptainer/1.4.2 2>/dev/null || module load apptainer 2>/dev/null || true
apptainer exec -B "$BINDS" "$IMAGE" python -u "$REPO/validation/cluster/concat_timing.py" \
    --out "$OUT" "${SRC[@]}"
rm -f "$OUT/timing_mpt.tiff"
rmdir "$OUT" 2>/dev/null
