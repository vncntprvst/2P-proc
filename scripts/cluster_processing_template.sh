#!/bin/sh
#SBATCH -t 10:00:00
#SBATCH -N 1
#SBATCH -n 5
#SBATCH --mem=1500MB
#SBATCH -o ./slurm_logs/cluster_processing-%j.ans
#SBATCH --mail-type=ALL

# This script runs the Analysis 2P pipeline on the cluster.
# Step 1: Transfer data from storage to processing file system if necessary
# Step 2: Process 2P data with batch Mesmerize script
# Step 3: Run other processing scripts on cluster
# Step 4: Transfer data back to storage

# Example usage:  
# ./cluster_processing.sh /MyFiles/MyPathFile.json
# sbatch cluster_processing.sh /MyFiles/MyPathFile.json

#####################################################################################
# Dynamically set mail-user
scontrol update job $SLURM_JOB_ID MailUser=$USER@mit.edu

TERM=xterm-256color
echo -e '\n'
echo -e '\e[33m## STARTING Analysis 2P - cluster_processing.sh ##\e[0m'
echo -e '\n'
echo "Requested walltime: $(squeue -j $SLURM_JOB_ID -h --Format TimeLimit)"

transfer_data=True
process_data=True

####################################################
########### Initializations ###################

# Get path file from user
PATH_FILE=$1  # Argument passed in by user.
echo "PATH_FILE: $PATH_FILE"
if [ -z "$PATH_FILE" ]; then
    echo "No PATH_FILE specified, exiting."
    exit 1
fi

# Load global settings
source ./utils/set_globals.sh $USER

if [ "$OS_VERSION" = "centos7" ]; then
    echo "Loading modules for CentOS 7."
    module load openmind/anaconda
elif [ "$OS_VERSION" = "rocky8" ]; then
    echo "Loading modules for Rocky 8."
    module load openmind8/anaconda
fi

####################################################
########### Prepare data for processing ############
####################################################

if [ "$transfer_data" = True ]; then
    echo -e '\e[35m* Transferring data to processing file system \e[0m'
    SOURCE_PATH_FILE=$PATH_FILE
    echo -e "\e[35m Running transfer_data.sh with arguments: 1 and $SOURCE_PATH_FILE \e[0m"
    echo -n "" >&2  # Proper flush
    output=$(bash transfer_data.sh 1 $SOURCE_PATH_FILE)
    echo "$output"

    TARGET_PATH_FILE=$(echo "$output" | grep TARGET_PATH_FILE | awk '{print $2}')
    ROOT_DATA_DIR=$(echo "$output" | grep ROOT_DATA_DIR | awk '{print $2}')
    ROOT_EXPORT_DIR=$(echo "$output" | grep ROOT_EXPORT_DIR | awk '{print $2}')
    TOTAL_NUM_FILES=$(echo "$output" | grep TOTAL_NUM_FILES | awk '{print $2}')
    TOTAL_SIZE=$(echo "$output" | grep TOTAL_SIZE | awk '{print $2}')
else
    TARGET_PATH_FILE=$PATH_FILE
fi

####################################################
### Process 2P data with batch Mesmerize script ####
####################################################

if [ "$process_data" = True ]; then
    echo -e '\n\e[35m Running Analysis 2P pipeline (om_batch_mcorr_cnmf.sh) \e[0m'
    echo -n "" >&2  # Proper flush

    TARGET_PATH_FILE=$(echo "$TARGET_PATH_FILE" | head -n 1 | tr -d '\r' | xargs)

    START_TIME=$(date +"%Y-%m-%d %H:%M:%S")
    START_TIME_S=$(date -d"$START_TIME" +%s)

    echo "Sending job request om_batch_mcorr_cnmf.sh on $TOTAL_NUM_FILES files, $TOTAL_SIZE MB of data, at $START_TIME"
    BATCH_MCORR_CNMF_JOB_ID=$(sbatch --mail-user=$EMAIL om_batch_mcorr_cnmf.sh $TARGET_PATH_FILE | awk '{print $NF}')
    echo "Submitted job ID: $BATCH_MCORR_CNMF_JOB_ID"

    # Wait for the job to complete
    while squeue -j $BATCH_MCORR_CNMF_JOB_ID 2>/dev/null | grep -q $BATCH_MCORR_CNMF_JOB_ID; do
        sleep 1
        # Echo a dot every 5 minutes
        if [ $((SECONDS % 300)) -eq 0 ]; then
            echo -n '.'
        fi
        # Print time every 30 minutes
        if [ $((SECONDS % 1800)) -eq 0 ]; then
            echo -e "\n$(date)"
        fi
    done

    END_TIME=$(date +"%Y-%m-%d %H:%M:%S")
    END_TIME_S=$(date -d"$END_TIME" +%s)
    ELAPSED_TIME_S=$((END_TIME_S - START_TIME_S))
    ELAPSED_TIME=$(date -u -d @${ELAPSED_TIME_S} +"%T")

    echo "Finished om_batch_mcorr_cnmf.sh at $END_TIME"
    echo "Total elapsed time: $ELAPSED_TIME"

# # TBD:  Add a check to see if the om_batch_mcorr_cnmf.sh script ran successfully. Proceed only if it did.
fi

####################################################
### Run other processing scripts on cluster ########
####################################################

echo -e '\n'
# echo -e '\e[35m  \e[0m'

####################################################
########## Transfer data back to storage ###########
####################################################

if [ "$transfer_data" = True ]; then
    echo -e '\n\e[35m Transferring data back to storage \e[0m'
    KEEP_DATA_IN_PLACE=1
    bash transfer_data.sh 2 $TARGET_PATH_FILE $SOURCE_PATH_FILE $KEEP_DATA_IN_PLACE
else
    echo -e '\n'
fi

####################################################
echo -e "\e[33m## DONE with Analysis 2P cluster processing.sh ##\e[0m"
