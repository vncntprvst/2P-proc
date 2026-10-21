#!/bin/bash
#SBATCH -t 06:00:00
#SBATCH -N 1
#SBATCH -n 16
#SBATCH --mem=64GB
#SBATCH --partition=ou_bcs_normal
#SBATCH -o ./slurm_logs/cellreg_benchmark-%j.out

# CellReg (zivlab/CellReg v1.6.0) on the 2P-proc registration benchmark cases.
# Submit from this folder (validation/registration/cellreg):
#   sbatch cellreg_benchmark.sh <data_dir> [microns_per_pixel]
# data_dir holds inputs/ (from export_cellreg_inputs.py) and CellReg/ (upstream clone);
# outputs go to data_dir/outputs.

mkdir -p ./slurm_logs
echo "Job $SLURM_JOB_ID on $(hostname) at $(date), CPUs $SLURM_CPUS_ON_NODE, mem $SLURM_MEM_PER_NODE"
module load matlab/matlab-2024a

SCRIPT_DIR=${SLURM_SUBMIT_DIR:-$PWD}
DATA=$(realpath "$1")
UM=${2:-1.4542}
export XDG_RUNTIME_DIR=$DATA/runtime-$USER
mkdir -p "$XDG_RUNTIME_DIR"

matlab -nodesktop -nodisplay -r "addpath('$SCRIPT_DIR'); \
try, \
    run_all_cases('$DATA/inputs', '$DATA/outputs', '$DATA/CellReg', $UM); \
    exit(0); \
catch ME, \
    disp(getReport(ME,'extended')); \
    exit(1); \
end"
STATUS=$?
rm -rf "$XDG_RUNTIME_DIR"
echo "Finished with status $STATUS at $(date)"
exit $STATUS
