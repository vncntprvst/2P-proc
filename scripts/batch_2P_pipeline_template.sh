#!/bin/bash                      
#SBATCH -t 02:00:00                                 # walltime = 2 hour. Minimum to be safe: 30 mn
#SBATCH -N 1                                        # 1 node
#SBATCH -n 40                                       # e.g., 60 CPU (hyperthreaded) cores
#SBATCH --mem=300GB                                 # Request up to 700 GB of memory
#SBATCH --partition=ou_bcs_normal
#SBATCH --export=HDF5_USE_FILE_LOCKING=FALSE 
#SBATCH --mail-type=ALL                             # email on start, end, and fail       
#SBATCH -o ./slurm_logs/batch_2P_pipeline-%j.ans     # stdout

# If not running on Engaging, remove #SBATCH --partition=ou_bcs_normal from the directives in scripts/batch_2P_pipeline.sh

# Dynamically set mail-user (skip if not on SLURM)
if command -v scontrol >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    scontrol update job $SLURM_JOB_ID MailUser=$USER@mit.edu
fi

# Example usage:

# sbatch --mail-user=$EMAIL batch_2P_pipeline.sh CONFIG_FILE [options]

# Options:
#   --mcorr-only      Run only the motion correction step, skip the extraction step
#   --extractor
#       cnmf           Use CNMF for motion correction and extraction
#       suite2p        Use Suite2P for motion correction and extraction
#       aind           Use aind-ophys-extraction after motion correction
#   --mcorr-movie     Specify the path to the motion corrected movie file, if not the export directory.

# The script will read the configuration file specified in CONFIG_FILE.
# The following options can be set there:

    # In "params_mcorr", set "method" to "caiman" to run motion correction or "none" to skip it.
    # Set "save_mcorr_movie" to "h5" or "bin" to save the motion corrected movie as HDF5 or binary file, respectively.
    # If "save_mcorr_movie" is set to false, the motion corrected movie will temporarily be saved in the batch directory as a memory-mapped file (.mmap), and discarded later if cleanup is set to true.

    # In "params_extraction", set the "method" field to "cnmf", "suite2p", or "aind" to specify the extraction method, or
    # leave it empty to skip the extraction step (equivalent to running the pipeline with the --mcorr-only option).

# If the extraction's method field is set to "suite2p" or "aind", then the pipeline will run only 
# the motion correction step. The extraction step will then be run separately on the motion corrected movie.

# Input arguments:
# $1: Path to the configuration file
# [$2 - optional: Root data directory, the common directory to all datasets to be processed]
# [$3 - optional: Root export directory, the common directory to all export directories]
# [$4 - optional: Log directory, the directory where the log files are stored]

USE_STABLE=1  # Set to 1 to use stable (main branch) version of the pipeline, 0 to use latest (dev branch)
if [ $USE_STABLE -eq 1 ]; then
    echo "RUNNING STABLE (MAIN BRANCH) VERSION OF THE PIPELINE"
else
    echo "RUNNING LATEST (DEV BRANCH) VERSION OF THE PIPELINE"
fi

# Initialize pipeline success flag
PIPELINE_SUCCESS=1

# Parse optional arguments after the path file
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mcorr-only)
            MCORR_ONLY=1
            shift
            ;;
        --extractor)
            EXTRACTOR="$2"
            shift 2
            ;;
        --mcorr-movie)
            MCORR_OUTPUT="$2"
            shift 2
            ;;
        --*)
            echo "Unknown option $1"; exit 1;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done
set -- "${POSITIONAL[@]}"

# Check resource availability and usage
echo "Starting job $SLURM_JOB_ID on $(hostname) at $(date)"
echo "Available CPUs: $(nproc --all)"
echo "Available memory: $(free -h | grep Mem | awk '{print $2}')"
if [ -n "${SLURM_CPUS_ON_NODE:-}" ]; then echo "Requested CPUs: $SLURM_CPUS_ON_NODE"; fi
if [ -n "${SLURM_MEM_PER_NODE:-}" ]; then echo "Requested memory: $SLURM_MEM_PER_NODE"; fi
if command -v squeue >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    echo "Requested walltime: $(squeue -j $SLURM_JOB_ID -h --Format TimeLimit)"
fi

# Determine location of utility scripts
UTILS_DIR=${UTILS_DIR:-./utils}
UTILS_DIR=$(realpath "$UTILS_DIR")
if [ ! -d "$UTILS_DIR" ]; then
    echo "Utilities directory '$UTILS_DIR' not found. Attempting to download..."
    TMP_UTILS_DIR=$(mktemp -d)
    if command -v git >/dev/null 2>&1; then
        if git clone --depth 1 https://github.com/pseudomanu/Analysis_2P.git "$TMP_UTILS_DIR/repo"; then
            mkdir -p "$UTILS_DIR"
            cp -r "$TMP_UTILS_DIR/repo/scripts/utils/." "$UTILS_DIR"
            FETCH_SUCCESS=1
        fi
    elif command -v curl >/dev/null 2>&1; then
        if curl -L https://github.com/pseudomanu/Analysis_2P/archive/refs/heads/main.tar.gz | tar -xz -C "$TMP_UTILS_DIR"; then
            mkdir -p "$UTILS_DIR"
            cp -r "$TMP_UTILS_DIR/Analysis_2P-main/scripts/utils/." "$UTILS_DIR"
            FETCH_SUCCESS=1
        fi
    fi
    rm -rf "$TMP_UTILS_DIR"
    if [ "${FETCH_SUCCESS:-0}" -ne 1 ]; then
        echo "Failed to obtain utilities directory."
        exit 1
    fi
    echo "Utilities directory created at '$UTILS_DIR'."
    echo "Now add an .env file in '$UTILS_DIR', then run the script again."
    exit 1
fi

# Load global settings
source "$UTILS_DIR/set_globals.sh" "$USER"

if [ "$OS_VERSION" = "centos7" ]; then
    echo "Loading modules for CentOS 7."
    module load openmind/singularity/3.9.5 openmind/anaconda
    USE_SINGULARITY=1
elif [ "$OS_VERSION" = "rocky8" ]; then
    if [[ -d "$HOME/orcd" ]]; then
        echo "Loading modules for Rocky 8 on Engaging."
        module load apptainer/1.4.2 miniforge/23.11.0-0
    else
        echo "Loading modules for Rocky 8 on OpenMind."
        module load openmind8/apptainer openmind8/anaconda
    fi
    USE_SINGULARITY=1
else

    # Prefer Singularity if available locally and images are present
    if command -v singularity >/dev/null 2>&1 || command -v apptainer >/dev/null 2>&1; then
        if [ -f "$IMAGE_REPO/analysis-2p_latest.sif" ] && [ -f "$IMAGE_REPO/suite2p_latest.sif" ]; then
            echo "Singularity detected and images present; forcing Singularity path."
            USE_SINGULARITY=1
        else
            echo "OS version $OS_VERSION not recognized. Using Docker instead."
            USE_SINGULARITY=0
            source ../tests/a2P/bin/activate
            export PYTHONPATH="$PWD/../tests/a2P:$PYTHONPATH"
        fi
    else
        echo "OS version $OS_VERSION not recognized. Using Docker instead."
        USE_SINGULARITY=0
        source ../tests/a2P/bin/activate
        export PYTHONPATH="$PWD/../tests/a2P:$PYTHONPATH"   
    fi
fi

# Set global variables
CONFIG_FILE=$1
echo "Config file provided: $CONFIG_FILE"

if [ $# -eq 1 ]; then
    export USE_SINGULARITY
    # If only config file is provided, then get arguments from the file.
    source "$UTILS_DIR/update_paths_file.sh" "$CONFIG_FILE"
    source "$UTILS_DIR/read_path_file.sh" "$CONFIG_FILE"
else
    # Otherwise, use the provided arguments
    COMMON_ROOT_DATA_DIR=$2
    COMMON_ROOT_EXPORT_DIR=$3
    LOG_DIR=$4
fi

# Get directory of config file
CONFIG_FILE_DIR=$(realpath $(dirname "$CONFIG_FILE"))

# Get the motion correction and extraction methods from the configuration file
echo "Retrieving motion correction and extraction methods from the configuration file..."
if [ $USE_SINGULARITY -eq 1 ]; then
    MCORR_METHOD=$(singularity run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
        $IMAGE_REPO/analysis-2p_latest.sif \
        python /code/paths_params_io.py "$CONFIG_FILE" --get-mcorr-method)
    EXTRACTOR_METHOD=$(singularity run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
        $IMAGE_REPO/analysis-2p_latest.sif \
        python /code/paths_params_io.py "$CONFIG_FILE" --get-extraction-method)
else
    MCORR_METHOD=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
        wanglabneuro/analysis-2p:latest \
        python /code/paths_params_io.py "$CONFIG_FILE" --get-mcorr-method)
    EXTRACTOR_METHOD=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
        wanglabneuro/analysis-2p:latest \
        python /code/paths_params_io.py "$CONFIG_FILE" --get-extraction-method)
fi
echo "Motion correction method: $MCORR_METHOD"
echo "Extraction method: $EXTRACTOR_METHOD"

# Set script directory and current directory
# SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
CURRENT_DIR=$PWD

#### MOTION CORRECTION STEP

if [ "$MCORR_METHOD" != "none" ]; then
    echo ""
    echo "==============================="
    echo "Running motion correction step."
    echo "==============================="

    # Build python command with optional arguments
    PYTHON_MC_CMD="python -u /code/pipeline/pipeline_mcorr.py $CONFIG_FILE"
    # if [ $save_mcorr_movie -eq 1 ]; then
    #     PYTHON_MC_CMD+=" --save-binary $MCORR_SAVE_OPTS"
    # fi

    echo "Motion correction command: $PYTHON_MC_CMD"

    if [ $USE_SINGULARITY -eq 1 ]; then
        echo "Using Singularity."

        # Create list of mount points to pass to Singularity. Only use unique mount points.
        echo "OM_USERS_DIR: $OM_USER_DIR_ALIAS"
        echo "OM2_USERS_DIR: $OM2_USER_DIR_ALIAS"
        echo "CURRENT_DIR: $CURRENT_DIR"
        
        # Create an array of directories
        SESSION_ROOT_DIR="$(dirname "$COMMON_ROOT_DATA_DIR")"
        DIRS=("$CONFIG_FILE_DIR" "$LOG_DIR" \
                "$SESSION_ROOT_DIR" "$COMMON_ROOT_DATA_DIR" "$COMMON_ROOT_EXPORT_DIR" \
                "$CURRENT_DIR" "$SLURM_SUBMIT_DIR")
        echo "DIRS: ${DIRS[@]}"

       # Build Singularity bind list with exact (not substring) de-duplication
        UNIQ_DIRS=()

        for dir in "${DIRS[@]}"; do
            [ -z "$dir" ] && continue

            already=0
            for u in "${UNIQ_DIRS[@]}"; do
                if [ "$u" = "$dir" ]; then
                    already=1
                    break
                fi
            done

            if [ $already -eq 0 ]; then
                UNIQ_DIRS+=("$dir")
            fi
        done

        MOUNT_POINTS=$(IFS=, ; echo "${UNIQ_DIRS[*]}")
        echo "MOUNT_POINTS: $MOUNT_POINTS"

        # Use non-GUI backend to speed up Matplotlib imports
        export MPLBACKEND="Agg"
        # Fix Matplotlib cache warning by setting MPLCONFIGDIR to a writable location
        export MPLCONFIGDIR="$CURRENT_DIR/.matplotlib_cache"
        mkdir -p "$MPLCONFIGDIR"

        # Create a temporary directory in COMMON_ROOT_EXPORT_DIR for CaImAn and assign it to CAIMAN_TEMP
        CAIMAN_TEMP=$(mktemp -d -p $COMMON_ROOT_EXPORT_DIR)

        echo "Starting Batch mcorr cnmf analysis on analysis-2p singularity image."

        if [ $USE_STABLE -eq 1 ]; then
            # To run the pipeline with the stable version of the code repository 
            singularity run \
                -B $MOUNT_POINTS \
                --env CAIMAN_TEMP=$CAIMAN_TEMP,MPLBACKEND=$MPLBACKEND,MPLCONFIGDIR=$MPLCONFIGDIR \
                $IMAGE_REPO/analysis-2p_latest.sif \
                $PYTHON_MC_CMD
            SINGULARITY_EXIT_STATUS=$?
        else
            # To run the pipeline with an up-to-date (development) code repository 
            CODE_DIR=$PIPELINE_CODE_DIR
            echo "Using code directory: $CODE_DIR"
            singularity run \
                -B $MOUNT_POINTS \
                -B $CODE_DIR:/code \
                --env CAIMAN_TEMP=$CAIMAN_TEMP,MPLBACKEND=$MPLBACKEND,MPLCONFIGDIR=$MPLCONFIGDIR \
                $IMAGE_REPO/analysis-2p_latest.sif \
                $PYTHON_MC_CMD
            SINGULARITY_EXIT_STATUS=$?
        fi
        
        # Check if Singularity command failed
        if [ $SINGULARITY_EXIT_STATUS -ne 0 ]; then
            PIPELINE_SUCCESS=0
            echo "Singularity command failed with exit status $SINGULARITY_EXIT_STATUS"
            exit $SINGULARITY_EXIT_STATUS
        fi

        # Remove the temporary directories
        rm -rf $CAIMAN_TEMP 
        rm -rf "$MPLCONFIGDIR"
        :
    else
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        REPO_DIR="$(dirname "$SCRIPT_DIR")"
        CODE_DIR=$REPO_DIR
        echo "Using code directory: $CODE_DIR"
        echo "Starting Batch mcorr cnmf analysis on analysis-2p docker image."
        export MPLBACKEND="Agg"
        export MPLCONFIGDIR="$CURRENT_DIR/.matplotlib_cache"
        mkdir -p "$MPLCONFIGDIR"
        docker run \
            --rm \
            --user $HOST_USER_ID:$HOST_GROUP_ID \
            -v $COMMON_ROOT_DATA_DIR:$COMMON_ROOT_DATA_DIR \
            -v $COMMON_ROOT_EXPORT_DIR:$COMMON_ROOT_EXPORT_DIR \
            -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            -v $LOG_DIR:$LOG_DIR \
            -v $CODE_DIR:/code \
            -e MPLBACKEND=Agg \
            -e MPLCONFIGDIR=$MPLCONFIGDIR \
            wanglabneuro/analysis-2p:latest \
            $PYTHON_MC_CMD
        
        # Capture the exit status of the docker command
        DOCKER_EXIT_STATUS=$?
        if [ $DOCKER_EXIT_STATUS -ne 0 ]; then
            PIPELINE_SUCCESS=0
            echo "Docker command failed with exit status $DOCKER_EXIT_STATUS"
            exit $DOCKER_EXIT_STATUS
        fi

        # Remove the temporary directories
        rm -rf "$MPLCONFIGDIR"
        :
    fi

fi

#### OPS FILE CREATION FOR SUITE2P OR AIND EXTRACTION (AIND pipeline uses Suite2P)

if [ "$EXTRACTOR_METHOD" = "suite2p" ] || [ "$EXTRACTOR_METHOD" = "aind" ]; then
    echo ""
    echo "=================================================="
    echo "Creating ops files for Suite2P or AIND extraction."
    echo "=================================================="

    # Check that numpy and h5py are installed
    if ! python -c "import numpy, h5py" &> /dev/null; then
        echo "Installing numpy and h5py..."
        python -m pip install --user numpy h5py
    fi

    # Make sure an ops file exists for each export path
    for EXPORT_PATH in "${EXPORT_DATA_PATHS[@]}"; do
        if [ -f "$EXPORT_PATH/ops.npy" ]; then
            echo "Ops file already exists: $EXPORT_PATH/ops.npy"
            echo "Removing existing ops file..."
            rm "$EXPORT_PATH/ops.npy"
        fi
        echo "Getting ops parameters from configuration file..."
        if [ $USE_SINGULARITY -eq 1 ]; then
            OPS=$(singularity run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR -B $EXPORT_PATH:$EXPORT_PATH \
                $IMAGE_REPO/analysis-2p_latest.sif \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-suite2p-ops --export-path "$EXPORT_PATH")
        else
            OPS=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR -v $EXPORT_PATH:$EXPORT_PATH \
                wanglabneuro/analysis-2p:latest \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-suite2p-ops --export-path "$EXPORT_PATH")
        fi

        if command -v jq &> /dev/null; then
            OPS_NFRAMES=$(echo "$OPS" | jq -r '.nframes')
            OPS_LY=$(echo "$OPS" | jq -r '.Ly')
            OPS_LX=$(echo "$OPS" | jq -r '.Lx')
            OPS_FS=$(echo "$OPS" | jq -r '.fs')
            OPS_TAU=$(echo "$OPS" | jq -r '.tau')
            OPS_ZCORR_FILE=$(echo "$OPS" | jq -r '.zcorr_file')
        else
            echo "jq not found. Falling back to Python."
            OPS_NFRAMES=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('nframes',''))")
            OPS_LY=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('Ly',''))")
            OPS_LX=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('Lx',''))")
            OPS_FS=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('fs',''))")
            OPS_TAU=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tau',''))")
            OPS_ZCORR_FILE=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('zcorr_file',''))")
        fi

        # If OPS_NFRAMES is not set, use ImageMagik
        if [ -z "$OPS_NFRAMES" ] || [ "$OPS_NFRAMES" -le 0 ]; then
            if [ -f "$EXPORT_PATH/mcorr_movie.tiff" ]; then
                OPS_NFRAMES=$(identify -ping "$EXPORT_PATH/mcorr_movie.tiff" | wc -l)
            elif [ -f "$EXPORT_PATH/mcorr_u8.tiff" ]; then
                # Fallback only if mcorr_movie.tiff is missing
                OPS_NFRAMES=$(identify -ping "$EXPORT_PATH/mcorr_u8.tiff" | wc -l)
            fi
        fi
        if [ -z "$OPS_NFRAMES" ] || [ "$OPS_NFRAMES" -le 0 ]; then
            echo "Error: OPS_NFRAMES is not set or invalid. Please install ImageMagick."
            PIPELINE_SUCCESS=0
            continue
        fi

        # Create the ops dictionary
        if [ $USE_SINGULARITY -eq 1 ]; then
            output_format_STR=$(singularity run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
                $IMAGE_REPO/analysis-2p_latest.sif \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-output-format)
        else
            output_format_STR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
                wanglabneuro/analysis-2p:latest \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-output-format)
        fi

        if [ "$output_format_STR" = "h5" ]; then
            EXPORT_FILE="$EXPORT_PATH/mcorr_movie.h5"
        elif [ "$output_format_STR" = "bin" ]; then
            EXPORT_FILE="$EXPORT_PATH/mcorr_movie.bin"
        elif [ "$output_format_STR" = "tiff" ] || [ "$output_format_STR" = "tif" ]; then
            # Use the full-precision TIFF for Suite2p
            EXPORT_FILE="$EXPORT_PATH/mcorr_movie.tiff"
        fi

        echo "Ops parameters: "
        echo "  - movie: $EXPORT_FILE"
        echo "  - nframes: $OPS_NFRAMES"
        echo "  - Ly: $OPS_LY"
        echo "  - Lx: $OPS_LX"
        echo "  - fs: $OPS_FS"
        echo "  - tau: $OPS_TAU"
        # If zcorr_file is not None, include it in the ops parameters
        if [ -n "$OPS_ZCORR_FILE" ]; then
            echo "  - zcorr_file: $OPS_ZCORR_FILE"
        fi

        OPS_PYTHON_CMD="python /app/scripts/make_ops.py \
            --export_path \"$EXPORT_PATH\" \
            --movie \"$EXPORT_FILE\" \
            --h5py_key data \
            --nframes \"$OPS_NFRAMES\" \
            --Ly \"$OPS_LY\" \
            --Lx \"$OPS_LX\" \
            --fs \"$OPS_FS\" \
            --tau \"$OPS_TAU\" \
            --save_mat 1 \
            --do_registration 0 \
            --nonrigid 0"
        if [ -n "$OPS_ZCORR_FILE" ]; then
            OPS_PYTHON_CMD+=" \
            --zcorr_file \"$OPS_ZCORR_FILE\""
        fi

        if [ $USE_SINGULARITY -eq 1 ]; then
            singularity run -B $EXPORT_PATH:$EXPORT_PATH \
                $IMAGE_REPO/suite2p_latest.sif \
                $OPS_PYTHON_CMD
            OPS_EXIT_STATUS=$?
        else
            docker run --rm -v $EXPORT_PATH:$EXPORT_PATH \
                $IMAGE_REPO/suite2p_latest.sif \
                $OPS_PYTHON_CMD
            OPS_EXIT_STATUS=$?
        fi

        # Check if ops creation failed
        if [ $OPS_EXIT_STATUS -ne 0 ]; then
            PIPELINE_SUCCESS=0
            echo "Failed to create ops file for $EXPORT_PATH"
        fi

    done
fi

#### EXTRACTOR STEP
if [ "$EXTRACTOR_METHOD" = "cnmf" ] || [ "$EXTRACTOR_METHOD" = "suite2p" ] || [ "$EXTRACTOR_METHOD" = "aind" ]; then
    echo ""
    echo "========================"
    echo "Running extraction step."
    echo "========================"
fi

if [ -z "$MCORR_OUTPUT" ] && [ "$EXTRACTOR_METHOD" = "cnmf" ]; then
    EXPORT_PATH="${EXPORT_DATA_PATHS[0]}"
    if [ -d "$EXPORT_PATH" ]; then
        if ! ls "$EXPORT_PATH"/batch_*.pickle >/dev/null 2>&1; then
            for candidate in \
                "$EXPORT_PATH/mcorr_movie.tiff" \
                "$EXPORT_PATH/mcorr_movie.h5" \
                "$EXPORT_PATH/mcorr_movie.bin" \
                "$EXPORT_PATH/mcorr_movie.mmap"; do
                if [ -f "$candidate" ]; then
                    MCORR_OUTPUT="$candidate"
                    break
                fi
            done
            if [ -z "$MCORR_OUTPUT" ]; then
                MCORR_OUTPUT=$(ls -t "$EXPORT_PATH"/*.mmap 2>/dev/null | head -n 1)
            fi
            if [ -z "$MCORR_OUTPUT" ]; then
                latest_batch=$(find "$EXPORT_PATH" -maxdepth 1 -type d -name '*-*' | sort | tail -n 1)
                if [ -n "$latest_batch" ]; then
                    MCORR_OUTPUT=$(ls -t "$latest_batch"/*.mmap 2>/dev/null | head -n 1)
                fi
            fi
        fi
    fi
    if [ -n "$MCORR_OUTPUT" ]; then
        echo "Motion corrected movie detected: $MCORR_OUTPUT"
    fi
fi

if [ "$EXTRACTOR_METHOD" = "cnmf" ]; then
    echo "Running CNMF extraction."
    export MPLBACKEND="Agg"
    export MPLCONFIGDIR="$CURRENT_DIR/.matplotlib_cache"
    mkdir -p "$MPLCONFIGDIR"
    if [ $USE_SINGULARITY -eq 1 ]; then
        CAIMAN_TEMP=$(mktemp -d -p $COMMON_ROOT_EXPORT_DIR)
        CNMF_CMD="python -u /code/pipeline/pipeline_cnmf.py $CONFIG_FILE"
        if [ -n "$MCORR_OUTPUT" ]; then
            CNMF_CMD+=" --mcorr-movie $MCORR_OUTPUT"
        fi
        if [ $USE_STABLE -eq 1 ]; then
            singularity run -B $MOUNT_POINTS \
                            --env CAIMAN_TEMP=$CAIMAN_TEMP,MPLBACKEND=$MPLBACKEND,MPLCONFIGDIR=$MPLCONFIGDIR \
                            $IMAGE_REPO/analysis-2p_latest.sif $CNMF_CMD
        else
            echo "Using code directory: $PIPELINE_CODE_DIR for CNMF extraction."
            singularity run -B $MOUNT_POINTS \
                            -B $PIPELINE_CODE_DIR:/code \
                            --env CAIMAN_TEMP=$CAIMAN_TEMP,MPLBACKEND=$MPLBACKEND,MPLCONFIGDIR=$MPLCONFIGDIR \
                            $IMAGE_REPO/analysis-2p_latest.sif $CNMF_CMD
        fi
        CNMF_EXIT_STATUS=$?
        rm -rf $CAIMAN_TEMP
    else
        CNMF_CMD="python -u /code/pipeline/pipeline_cnmf.py $CONFIG_FILE"
        if [ -n "$MCORR_OUTPUT" ]; then
            CNMF_CMD+=" --mcorr-movie $MCORR_OUTPUT"
        fi
        docker run --rm --user $HOST_USER_ID:$HOST_GROUP_ID -v $COMMON_ROOT_DATA_DIR:$COMMON_ROOT_DATA_DIR -v $COMMON_ROOT_EXPORT_DIR:$COMMON_ROOT_EXPORT_DIR -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR -v $LOG_DIR:$LOG_DIR -v $CODE_DIR:/code -e MPLBACKEND=Agg wanglabneuro/analysis-2p:latest $CNMF_CMD
        CNMF_EXIT_STATUS=$?
    fi
    rm -rf "$MPLCONFIGDIR"
    :
    if [ $CNMF_EXIT_STATUS -ne 0 ]; then
        PIPELINE_SUCCESS=0
        echo "CNMF extraction failed with exit status $CNMF_EXIT_STATUS"
    fi
fi

# If using the aind extractor, run the extraction capsule on each export path
if [ "$EXTRACTOR_METHOD" = "suite2p" ]; then
    for EXPORT_PATH in "${EXPORT_DATA_PATHS[@]}"; do
        echo "Running suite2p extraction on $EXPORT_PATH (API runner)"
        export MPLBACKEND="Agg"
        export MPLCONFIGDIR="$CURRENT_DIR/.matplotlib_cache"
        mkdir -p "$MPLCONFIGDIR"
        if [ $USE_SINGULARITY -eq 1 ]; then
            singularity run -B $EXPORT_PATH:$EXPORT_PATH \
                --env MPLCONFIGDIR=$MPLCONFIGDIR \
                --env MPLBACKEND=$MPLBACKEND \
                $IMAGE_REPO/suite2p_latest.sif \
                python /app/scripts/run_suite2p_api.py --ops "$EXPORT_PATH/ops.npy"
            SUITE2P_EXIT_STATUS=$?
        else
            docker run --rm -v $EXPORT_PATH:$EXPORT_PATH \
                -e MPLCONFIGDIR=$MPLCONFIGDIR \
                -e MPLBACKEND=Agg \
                wanglabneuro/suite2p:latest \
                python /app/scripts/run_suite2p_api.py --ops "$EXPORT_PATH/ops.npy"
            SUITE2P_EXIT_STATUS=$?
        fi

        # Note that the extraction can also be called without a script (but with un-controlled preprocessing that will impact ROI detection): 
        # python -m suite2p \
        # --single_plane \
        # --ops $EXPORT_PATH/ops.npy 
        
        # Check if Suite2P extraction failed
        if [ $SUITE2P_EXIT_STATUS -ne 0 ]; then
            PIPELINE_SUCCESS=0
            echo "Suite2P extraction failed for $EXPORT_PATH with exit status $SUITE2P_EXIT_STATUS"
        fi
        
        rm -rf "$MPLCONFIGDIR"
        :
    done
fi

# If using the aind extractor, run the extraction capsule on each export path
if [ "$EXTRACTOR_METHOD" = "aind" ]; then
    for EXPORT_PATH in "${EXPORT_DATA_PATHS[@]}"; do
        echo "Running aind-ophys-extraction on $EXPORT_PATH"
        export MPLBACKEND="Agg"
        export MPLCONFIGDIR="$CURRENT_DIR/.matplotlib_cache"
        mkdir -p "$MPLCONFIGDIR"
        if [ $USE_SINGULARITY -eq 1 ]; then
            singularity run -B $EXPORT_PATH:$EXPORT_PATH \
                --env MPLBACKEND=$MPLBACKEND \
                --env MPLCONFIGDIR=$MPLCONFIGDIR \
                $IMAGE_REPO/aind-ophys-extraction-suite2p-docker-local_latest.sif \
                run --input-dir $EXPORT_PATH
            AIND_EXIT_STATUS=$?
        else
            docker run --rm -v $EXPORT_PATH:$EXPORT_PATH \
                -e MPLBACKEND=Agg \
                -e MPLCONFIGDIR=$MPLCONFIGDIR \
                ghcr.io/allenneuraldynamics/aind-ophys-extraction-suite2p-docker-local:latest \
                run --input-dir $EXPORT_PATH
            AIND_EXIT_STATUS=$?
        fi
        
        # Check if AIND extraction failed
        if [ $AIND_EXIT_STATUS -ne 0 ]; then
            PIPELINE_SUCCESS=0
            echo "AIND extraction failed for $EXPORT_PATH with exit status $AIND_EXIT_STATUS"
        fi

        rm -rf "$MPLCONFIGDIR"
        :
    done
fi

#### ROI Z-MOTION CORRECTION STEP
if [ "$EXTRACTOR_METHOD" = "suite2p" ]; then
    echo ""
    echo "================================"
    echo "Running ROI z-motion correction."
    echo "================================"

    export MPLBACKEND="Agg"
    export MPLCONFIGDIR="$CURRENT_DIR/.matplotlib_cache"
    mkdir -p "$MPLCONFIGDIR"
    if [ $USE_SINGULARITY -eq 1 ]; then
        singularity run -B $MOUNT_POINTS --env MPLBACKEND=$MPLBACKEND --env MPLCONFIGDIR=$MPLCONFIGDIR $IMAGE_REPO/analysis-2p_latest.sif \
            python -u /code/pipeline/roi_zcorr.py $CONFIG_FILE
        ROI_Z_EXIT_STATUS=$?
    else
        docker run --rm --user $HOST_USER_ID:$HOST_GROUP_ID \
            -v $COMMON_ROOT_DATA_DIR:$COMMON_ROOT_DATA_DIR \
            -v $COMMON_ROOT_EXPORT_DIR:$COMMON_ROOT_EXPORT_DIR \
            -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            -v $LOG_DIR:$LOG_DIR \
            -v $CODE_DIR:/code \
            -e MPLBACKEND=Agg \
            -e MPLCONFIGDIR=$MPLCONFIGDIR \
            wanglabneuro/analysis-2p:latest \
            python -u /code/pipeline/roi_zcorr.py $CONFIG_FILE
        ROI_Z_EXIT_STATUS=$?
    fi
    rm -rf "$MPLCONFIGDIR"
    :
    if [ $ROI_Z_EXIT_STATUS -ne 0 ]; then
        PIPELINE_SUCCESS=0
        echo "ROI z-motion correction failed with exit status $ROI_Z_EXIT_STATUS"
    fi
fi


# Return script exit status based on pipeline success
echo ""
echo "================================"
echo "Wrapping up"
echo "================================"
if [ "${PIPELINE_SUCCESS:-0}" -eq 1 ]; then
    echo "Pipeline completed successfully."
    if [ -n "$LAB_SPACE" ]; then
        mkdir -p "$LAB_SPACE/A2P/runs/$USERNAME"

        cfg_base="$(basename "$CONFIG_FILE")"
        # remove case-insensitive .json (if present) and set .log
        base_no_json="${cfg_base%.[jJ][sS][oO][nN]}"
        log_name="${base_no_json}.log"

        if [ -z "$SLURM_LOG_FILE" ] && [ -n "$SLURM_JOB_ID" ]; then
            SLURM_LOG_FILE="./slurm_logs/batch_2P_pipeline-${SLURM_JOB_ID}.ans"
        fi

        if [ -n "$SLURM_LOG_FILE" ] && [ -f "$SLURM_LOG_FILE" ]; then
            cp "$SLURM_LOG_FILE" "$LAB_SPACE/A2P/runs/$USERNAME/$log_name"
        else
            echo "Warning: SLURM log file not found: ${SLURM_LOG_FILE:-<unset>}"
        fi
        cp "$CONFIG_FILE" "$LAB_SPACE/A2P/runs/$USERNAME/$cfg_base"
    fi
    if [ "${RUN_NWB_CONVERSION:-0}" -eq 1 ]; then
        bash "$(dirname "$0")/nwb_conversion.sh" "$CONFIG_FILE"
    fi
    # Consolidated post-extraction cleanup of mcorr_movie.{ext}
    CLEANUP_AFTER="false"
    if command -v jq &> /dev/null; then
        CLEANUP_AFTER=$(jq -r '.params_extra.cleanup // false' "$CONFIG_FILE" 2>/dev/null)
    fi
    if [ "$CLEANUP_AFTER" = "true" ]; then
        if [ $USE_SINGULARITY -eq 1 ]; then
            output_format_STR=$(singularity run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
                $IMAGE_REPO/analysis-2p_latest.sif \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-output-format)
        else
            output_format_STR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
                wanglabneuro/analysis-2p:latest \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-output-format)
        fi
        for EXPORT_PATH in "${EXPORT_DATA_PATHS[@]}"; do
            if [ "$output_format_STR" = "h5" ]; then
                EXPORT_FILE="$EXPORT_PATH/mcorr_movie.h5"
            elif [ "$output_format_STR" = "bin" ]; then
                EXPORT_FILE="$EXPORT_PATH/mcorr_movie.bin"
            else
                EXPORT_FILE="$EXPORT_PATH/mcorr_movie.tiff"
            fi
            if [ -f "$EXPORT_FILE" ]; then
                echo "Cleaning up motion-corrected movie: $EXPORT_FILE"
                rm -f "$EXPORT_FILE"
                [ -f "${EXPORT_FILE}.json" ] && rm -f "${EXPORT_FILE}.json"
            fi
        done
    fi
    exit 0
else
    echo "Pipeline failed. Check logs for details."
    exit 1
fi
