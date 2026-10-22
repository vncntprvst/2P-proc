#!/bin/bash
#SBATCH -t 03:00:00
#SBATCH -N 1
#SBATCH -n 32
#SBATCH --mem=128GB
#SBATCH --partition=ou_bcs_normal
#SBATCH --job-name=zpos_suite2p
#SBATCH -o ./slurm_logs/zpos_suite2p-%j.ans

# Suite2p-style z-position (validation/zpos_suite2p.py) on a pipeline export, with this
# checkout's code in the 2p_proc image. Output: <export>/zpos_suite2p/z_correlation_suite2p.npz
# Usage: sbatch validation/cluster/zpos_suite2p.sh <export_dir> <zstack_shifted.tif>

EXPORT=$(realpath "$1")
ZSTACK=$(realpath "$2")
REPO=$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)
[ -n "${SLURM_SUBMIT_DIR:-}" ] && [ -f "$SLURM_SUBMIT_DIR/validation/zpos_suite2p.py" ] && REPO=$SLURM_SUBMIT_DIR
source "$REPO/scripts/.env" 2>/dev/null
IMAGE=${IMAGE_REPO:-$HOME/singularity_images}/2p_proc_latest.sif
MMAP=$(ls "$EXPORT"/*/*.mmap | head -1)
echo "export $EXPORT; movie $MMAP; z-stack $ZSTACK; image $IMAGE; code $REPO"
module load apptainer/1.4.2 2>/dev/null || true
apptainer run --cleanenv -B /orcd,/home "$IMAGE" bash -c \
    "cd $REPO && MPLBACKEND=Agg python validation/zpos_suite2p.py $MMAP $ZSTACK $EXPORT/zpos_suite2p"
