#!/bin/bash                      
#SBATCH -t 01:30:00                  # walltime = 1 hours and 30 minutes
#SBATCH -N 1                         #  one node
#SBATCH -n 5                         #  two CPU (hyperthreaded) cores
#SBATCH --gres=gpu:1                 #  one GPU
#SBATCH --constraint=high-capacity   #  high-capacity GPU

source /etc/profile.d/modules.sh

unset XDG_RUNTIME_DIR
module load openmind/singularity

portNum=$1
portNum="${portNum:=9000}"

userID=$2
userID="${userID:=$USER}"
cd /om2/user/$userID

singularity exec --nv \
    -B /nese/mit/group/fan_wang/all_staff,/om2/user/$USER \
    /om2/group/wanglab/images/jlab_caiman.simg \
    jupyter notebook \
    --no-browser --port=$portNum \
    --NotebookApp.token='' --NotebookApp.password=''