#!/bin/bash                      
#SBATCH -t 02:00:00                                 # walltime = 2 hour. Minimum to be safe: 30 mn
#SBATCH -N 1                                        # 1 node
#SBATCH -n 40                                       # e.g., 60 CPU (hyperthreaded) cores
#SBATCH --mem=300GB                                 # Request up to 700 GB of memory
#SBATCH --partition=ou_bcs_normal
#SBATCH --export=HDF5_USE_FILE_LOCKING=FALSE 
#SBATCH --mail-type=ALL                             # email on start, end, and fail
#SBATCH --job-name=2P_proc_pipeline                 # job name       
#SBATCH -o ./slurm_logs/2P_proc-%j.ans              # stdout

# Create log directory if it doesn't exist
mkdir -p ./slurm_logs

# Dynamically set mail-user (skip if not on SLURM)
if command -v scontrol >/dev/null 2>&1 && [ -n "${SLURM_JOB_ID:-}" ]; then
    scontrol update job $SLURM_JOB_ID MailUser=$USER@mit.edu
fi

# Example usage:

# sbatch --mail-user=$EMAIL 2P_proc.sh CONFIG_FILE [options]

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
    # Set "save_mcorr_movie" to "tiff", "memap", "h5" or "bin" to save the motion corrected movie as HDF5 or binary file, respectively.
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

# Get script directory (use SLURM_SUBMIT_DIR if running under SLURM, otherwise use BASH_SOURCE)
if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    SCRIPT_DIR="$SLURM_SUBMIT_DIR"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
echo "Script directory: $SCRIPT_DIR"
# Define CURRENT_DIR early so .env variable expansions can safely reference it.
CURRENT_DIR="$SCRIPT_DIR"

# Load environment variables from .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a  # auto-export all variables
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
    echo "Loaded environment from $SCRIPT_DIR/.env"
else
    echo "Warning: No .env file found at $SCRIPT_DIR/.env"
    echo "Copy template.env to .env and configure it for your environment."
fi

# Detect OS version for cluster-specific settings
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "centos" ]] && [[ "$VERSION_ID" == "7" ]]; then
            echo "centos7"
        elif [[ "$ID" == "rocky" ]] && [[ "$VERSION_ID" =~ ^8 ]]; then
            echo "rocky8"
        else
            echo "unknown"
        fi
    else
        echo "unknown"
    fi
}

OS_VERSION=$(detect_os)
echo "Detected OS: $OS_VERSION"

# Set default values if not in .env
IMAGE_REPO=${IMAGE_REPO:-$HOME/singularity_images}
LAB_SPACE=${LAB_SPACE:-}
USERNAME=${USER}

if [ "$OS_VERSION" = "rocky8" ]; then
    if [[ -d "$HOME/orcd" ]]; then
        echo "Loading modules"
        module load apptainer/1.4.2 miniforge/23.11.0-0
    else
        echo "Unknown OS version; not loading modules"
        exit 1
    fi
    USE_SINGULARITY=1
else

    # Prefer Singularity if available locally and images are present
    if command -v singularity >/dev/null 2>&1 || command -v apptainer >/dev/null 2>&1; then
        # Check if main processing image exists (suite2p image is optional)
        if [ -f "$IMAGE_REPO/2p_proc_latest.sif" ]; then
            echo "Singularity/Apptainer detected and 2p_proc image found."
            USE_SINGULARITY=1
            # Warn if suite2p image is missing but don't fail
            if [ ! -f "$IMAGE_REPO/suite2p_latest.sif" ]; then
                echo "Warning: suite2p_latest.sif not found. Suite2P extraction will use Docker if needed."
            fi
        else
            echo "Singularity/Apptainer available but 2p_proc image not found in $IMAGE_REPO"
            echo "Please build or download the image, or use Docker instead."
            USE_SINGULARITY=0
        fi
    else
        echo "Singularity/Apptainer not found. Using Docker instead."
        USE_SINGULARITY=0
    fi
fi

# Set global variables
CONFIG_FILE=$1
echo "Config file provided: $CONFIG_FILE"

# Get directory of config file
CONFIG_FILE_DIR=$(realpath $(dirname "$CONFIG_FILE"))

# Parse config file to extract paths using Python in container
if [ $# -eq 1 ]; then
    export USE_SINGULARITY
    echo "Reading paths from configuration file..."

    if [ $USE_SINGULARITY -eq 1 ]; then
        if command -v apptainer >/dev/null 2>&1; then
            CONTAINER_CMD="apptainer"
        else
            CONTAINER_CMD="singularity"
        fi
    fi

    # Update remote paths (if needed)
    if [ $USE_SINGULARITY -eq 1 ]; then
        CONFIG_FILE=$($CONTAINER_CMD run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            $IMAGE_REPO/2p_proc_latest.sif \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import update_remote_paths
path_file = sys.argv[1]
old_paths = sys.argv[2].split(',')
new_paths = sys.argv[3].split(',')
print(update_remote_paths(path_file, old_paths, new_paths))
" "$CONFIG_FILE" "/om/scratch/tmp,/om/user,/om2/scratch/tmp,/om2/user" \
"$OM_SCRATCH_TMP,$OM_USER_DIR_ALIAS,$OM2_SCRATCH_TMP,$OM2_USER_DIR_ALIAS")
    else
        CONFIG_FILE=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            wanglabneuro/2p_proc:latest \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import update_remote_paths
path_file = sys.argv[1]
old_paths = sys.argv[2].split(',')
new_paths = sys.argv[3].split(',')
print(update_remote_paths(path_file, old_paths, new_paths))
" "$CONFIG_FILE" "/om/scratch/tmp,/om/user,/om2/scratch/tmp,/om2/user" \
"$OM_SCRATCH_TMP,$OM_USER_DIR_ALIAS,$OM2_SCRATCH_TMP,$OM2_USER_DIR_ALIAS")
    fi

    # Read common roots
    if [ $USE_SINGULARITY -eq 1 ]; then
        COMMON_ROOT_DATA_DIR=$($CONTAINER_CMD run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            $IMAGE_REPO/2p_proc_latest.sif \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "data_paths")
        COMMON_ROOT_EXPORT_DIR=$($CONTAINER_CMD run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            $IMAGE_REPO/2p_proc_latest.sif \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "export_paths")
        LOG_DIR=$($CONTAINER_CMD run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            $IMAGE_REPO/2p_proc_latest.sif \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "logging")
        EXTRACTOR=$($CONTAINER_CMD run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            $IMAGE_REPO/2p_proc_latest.sif \
            python /code/paths_params_io.py "$CONFIG_FILE" --get-extraction-method)
        IFS=' ' read -ra SOURCE_DATA_PATHS <<< "$($CONTAINER_CMD run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            $IMAGE_REPO/2p_proc_latest.sif \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import read_data_paths
print(read_data_paths(sys.argv[1], sys.argv[2], sys.argv[3]))
" "$CONFIG_FILE" "data_paths" "bash")"
        IFS=' ' read -ra EXPORT_DATA_PATHS <<< "$($CONTAINER_CMD run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            $IMAGE_REPO/2p_proc_latest.sif \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import read_data_paths
print(read_data_paths(sys.argv[1], sys.argv[2], sys.argv[3]))
" "$CONFIG_FILE" "export_paths" "bash")"
    else
        COMMON_ROOT_DATA_DIR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            wanglabneuro/2p_proc:latest \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "data_paths")
        COMMON_ROOT_EXPORT_DIR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            wanglabneuro/2p_proc:latest \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "export_paths")
        LOG_DIR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            wanglabneuro/2p_proc:latest \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import get_common_dir
print(get_common_dir(sys.argv[1], sys.argv[2]))
" "$CONFIG_FILE" "logging")
        EXTRACTOR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            wanglabneuro/2p_proc:latest \
            python /code/paths_params_io.py "$CONFIG_FILE" --get-extraction-method)
        IFS=' ' read -ra SOURCE_DATA_PATHS <<< "$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            wanglabneuro/2p_proc:latest \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import read_data_paths
print(read_data_paths(sys.argv[1], sys.argv[2], sys.argv[3]))
" "$CONFIG_FILE" "data_paths" "bash")"
        IFS=' ' read -ra EXPORT_DATA_PATHS <<< "$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
            wanglabneuro/2p_proc:latest \
            python -c "
import sys
sys.path.append('/code')
from paths_params_io import read_data_paths
print(read_data_paths(sys.argv[1], sys.argv[2], sys.argv[3]))
" "$CONFIG_FILE" "export_paths" "bash")"
    fi

    # Ensure export paths exist
    for path in "${EXPORT_DATA_PATHS[@]}"; do
        if [ ! -d "$path" ]; then
            echo "Creating export path: $path"
            mkdir -p "$path"
        fi
    done

    # Check LOG_DIR
    if [ ! -d "$LOG_DIR" ]; then
        echo "LOG_DIR does not exist. Creating it."
        mkdir -p "$LOG_DIR"
    fi
    if [ ! -w "$LOG_DIR" ]; then
        echo "LOG_DIR is not writable. Setting LOG_DIR to COMMON_ROOT_EXPORT_DIR."
        LOG_DIR=$COMMON_ROOT_EXPORT_DIR
    fi

    echo "Data directory: $COMMON_ROOT_DATA_DIR"
    echo "Export directory: $COMMON_ROOT_EXPORT_DIR"
    echo "Log directory: $LOG_DIR"
else
    # Use provided arguments
    COMMON_ROOT_DATA_DIR=$2
    COMMON_ROOT_EXPORT_DIR=$3
    LOG_DIR=$4
fi

# Get the motion correction and extraction methods from the configuration file
echo "Retrieving motion correction and extraction methods from the configuration file..."
if [ $USE_SINGULARITY -eq 1 ]; then
    MCORR_METHOD=$(singularity run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR $IMAGE_REPO/2p_proc_latest.sif python /code/paths_params_io.py "$CONFIG_FILE" --get-mcorr-method)
    EXTRACTOR_METHOD=$(singularity run -B $CONFIG_FILE_DIR:$CONFIG_FILE_DIR $IMAGE_REPO/2p_proc_latest.sif python /code/paths_params_io.py "$CONFIG_FILE" --get-extraction-method)
else
    MCORR_METHOD=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR wanglabneuro/2p_proc:latest python /code/paths_params_io.py "$CONFIG_FILE" --get-mcorr-method)
    EXTRACTOR_METHOD=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR wanglabneuro/2p_proc:latest python /code/paths_params_io.py "$CONFIG_FILE" --get-extraction-method)
fi
echo "Motion correction method: $MCORR_METHOD"
echo "Extraction method: $EXTRACTOR_METHOD"

# Set current directory for runtime helpers.
CURRENT_DIR=$PWD

# Matplotlib cache handling:
# - KEEP_MPL_CACHE=1 keeps a persistent cache directory across runs.
# - KEEP_MPL_CACHE=0 uses a temporary per-step cache and removes it afterward.
KEEP_MPL_CACHE=${KEEP_MPL_CACHE:-1}
MPL_CACHE_DIR=${MPL_CACHE_DIR:-$CURRENT_DIR/.matplotlib_cache}

setup_mpl_cache() {
    export MPLBACKEND="Agg"
    if [ "$KEEP_MPL_CACHE" = "1" ]; then
        export MPLCONFIGDIR="$MPL_CACHE_DIR"
        if ! mkdir -p "$MPLCONFIGDIR" 2>/dev/null; then
            # Fallback to writable temp cache when configured path is not writable.
            if [ -n "${SLURM_TMPDIR:-}" ] && [ -d "${SLURM_TMPDIR:-}" ]; then
                export MPLCONFIGDIR="$(mktemp -d -p "$SLURM_TMPDIR" mpl_cache.XXXXXX)"
            else
                export MPLCONFIGDIR="$(mktemp -d -p "$CURRENT_DIR" mpl_cache.XXXXXX)"
            fi
        fi
    else
        if [ -n "${SLURM_TMPDIR:-}" ] && [ -d "${SLURM_TMPDIR:-}" ]; then
            export MPLCONFIGDIR="$(mktemp -d -p "$SLURM_TMPDIR" mpl_cache.XXXXXX)"
        else
            export MPLCONFIGDIR="$(mktemp -d -p "$CURRENT_DIR" mpl_cache.XXXXXX)"
        fi
    fi
}

cleanup_mpl_cache() {
    if [ "$KEEP_MPL_CACHE" != "1" ] && [ -n "${MPLCONFIGDIR:-}" ] && [ -d "${MPLCONFIGDIR:-}" ]; then
        rm -rf "$MPLCONFIGDIR"
    fi
}

is_roi_zcorr_requested() {
    local requested
    if [ $USE_SINGULARITY -eq 1 ]; then
        requested=$(singularity run -B "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" $IMAGE_REPO/2p_proc_latest.sif \
            python -c "from pipeline.utils.config_loader import load_config; c=load_config('$CONFIG_FILE'); z=c.get('params_mcorr',{}).get('z_motion_correction',None); zp=c.get('paths',{}).get('zstack_paths',[]); print('1' if (z is not None and isinstance(zp,list) and any(str(p).strip() for p in zp)) else '0')")
    else
        requested=$(docker run --rm -v "$CONFIG_FILE_DIR:$CONFIG_FILE_DIR" wanglabneuro/2p_proc:latest \
            python -c "from pipeline.utils.config_loader import load_config; c=load_config('$CONFIG_FILE'); z=c.get('params_mcorr',{}).get('z_motion_correction',None); zp=c.get('paths',{}).get('zstack_paths',[]); print('1' if (z is not None and isinstance(zp,list) and any(str(p).strip() for p in zp)) else '0')")
    fi
    [ "$requested" = "1" ]
}

#### MOTION CORRECTION STEP

if [ "$MCORR_METHOD" != "none" ]; then
    echo ""
    echo "==============================="
    echo "Running motion correction step."
    echo "==============================="

    # Build python command with optional arguments
    PYTHON_MC_CMD="python -u -m pipeline.pipeline_mcorr $CONFIG_FILE"
    # if [ $save_mcorr_movie -eq 1 ]; then
    #     PYTHON_MC_CMD+=" --save-binary $MCORR_SAVE_OPTS"
    # fi

    echo "Motion correction command: $PYTHON_MC_CMD"

    if [ $USE_SINGULARITY -eq 1 ]; then
        echo "Using Singularity."

        # Create list of mount points to pass to Singularity. Only use unique mount points.
        echo "CURRENT_DIR: $CURRENT_DIR"
        
        # Create an array of directories (only non-empty, absolute paths)
        DIRS=()
        [ -n "$CONFIG_FILE_DIR" ] && [[ "$CONFIG_FILE_DIR" = /* ]] && DIRS+=("$CONFIG_FILE_DIR")
        [ -n "$LOG_DIR" ] && [[ "$LOG_DIR" = /* ]] && DIRS+=("$LOG_DIR")
        if [ -n "$COMMON_ROOT_DATA_DIR" ] && [[ "$COMMON_ROOT_DATA_DIR" = /* ]]; then
            SESSION_ROOT_DIR="$(dirname "$COMMON_ROOT_DATA_DIR")"
            DIRS+=("$SESSION_ROOT_DIR" "$COMMON_ROOT_DATA_DIR")
        fi
        [ -n "$COMMON_ROOT_EXPORT_DIR" ] && [[ "$COMMON_ROOT_EXPORT_DIR" = /* ]] && DIRS+=("$COMMON_ROOT_EXPORT_DIR")
        [ -n "$CURRENT_DIR" ] && [[ "$CURRENT_DIR" = /* ]] && DIRS+=("$CURRENT_DIR")
        [ -n "$SLURM_SUBMIT_DIR" ] && [[ "$SLURM_SUBMIT_DIR" = /* ]] && DIRS+=("$SLURM_SUBMIT_DIR")
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

        setup_mpl_cache

        # Create a temporary directory in COMMON_ROOT_EXPORT_DIR for CaImAn and assign it to CAIMAN_TEMP
        if [ -n "$COMMON_ROOT_EXPORT_DIR" ]; then
            CAIMAN_TEMP=$(mktemp -d -p "$COMMON_ROOT_EXPORT_DIR")
        else
            CAIMAN_TEMP=$(mktemp -d)
        fi

        echo "Starting motion-correction on 2p_proc singularity image."

        if [ $USE_STABLE -eq 1 ]; then
            # To run the pipeline with the stable version of the code repository 
            singularity run \
                -B $MOUNT_POINTS \
                --env CAIMAN_TEMP=$CAIMAN_TEMP,MPLBACKEND=$MPLBACKEND,MPLCONFIGDIR=$MPLCONFIGDIR \
                $IMAGE_REPO/2p_proc_latest.sif \
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
                $IMAGE_REPO/2p_proc_latest.sif \
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
        cleanup_mpl_cache
        :
    else
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        REPO_DIR="$(dirname "$SCRIPT_DIR")"
        CODE_DIR=$REPO_DIR
        echo "Using code directory: $CODE_DIR"
        echo "Starting motion-correction on 2p_proc docker image."
        setup_mpl_cache
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
            wanglabneuro/2p_proc:latest \
            $PYTHON_MC_CMD
        
        # Capture the exit status of the docker command
        DOCKER_EXIT_STATUS=$?
        if [ $DOCKER_EXIT_STATUS -ne 0 ]; then
            PIPELINE_SUCCESS=0
            echo "Docker command failed with exit status $DOCKER_EXIT_STATUS"
            exit $DOCKER_EXIT_STATUS
        fi

        # Remove the temporary directories
        cleanup_mpl_cache
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
                $IMAGE_REPO/2p_proc_latest.sif \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-suite2p-ops --export-path "$EXPORT_PATH")
        else
            OPS=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR -v $EXPORT_PATH:$EXPORT_PATH \
                wanglabneuro/2p_proc:latest \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-suite2p-ops --export-path "$EXPORT_PATH")
        fi

        if command -v jq &> /dev/null; then
            OPS_NFRAMES=$(echo "$OPS" | jq -r '.nframes')
            OPS_LY=$(echo "$OPS" | jq -r '.Ly')
            OPS_LX=$(echo "$OPS" | jq -r '.Lx')
            OPS_FS=$(echo "$OPS" | jq -r '.fs')
            OPS_TAU=$(echo "$OPS" | jq -r '.tau')
            OPS_ZCORR_FILE=$(echo "$OPS" | jq -r '.zcorr_file')
            OPS_OVERRIDES=$(echo "$OPS" | jq -c '.ops_overrides // {}')
        else
            echo "jq not found. Falling back to Python."
            OPS_NFRAMES=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('nframes',''))")
            OPS_LY=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('Ly',''))")
            OPS_LX=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('Lx',''))")
            OPS_FS=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('fs',''))")
            OPS_TAU=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tau',''))")
            OPS_ZCORR_FILE=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('zcorr_file',''))")
            OPS_OVERRIDES=$(echo "$OPS" | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('ops_overrides', {}), separators=(',',':')))")
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
                $IMAGE_REPO/2p_proc_latest.sif \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-output-format)
        else
            output_format_STR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
                wanglabneuro/2p_proc:latest \
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
        echo "  - ops_overrides: $OPS_OVERRIDES"
        # If zcorr_file is not None, include it in the ops parameters
        if [ -n "$OPS_ZCORR_FILE" ]; then
            echo "  - zcorr_file: $OPS_ZCORR_FILE"
        fi

        OPS_PYTHON_ARGS=(
            python /app/scripts/make_ops.py
            --export_path "$EXPORT_PATH"
            --movie "$EXPORT_FILE"
            --h5py_key data
            --nframes "$OPS_NFRAMES"
            --Ly "$OPS_LY"
            --Lx "$OPS_LX"
            --fs "$OPS_FS"
            --tau "$OPS_TAU"
            --ops_overrides_json "$OPS_OVERRIDES"
            --save_mat 1
            --do_registration 0
            --nonrigid 0
        )
        if [ -n "$OPS_ZCORR_FILE" ]; then
            OPS_PYTHON_ARGS+=(--zcorr_file "$OPS_ZCORR_FILE")
        fi

        if [ $USE_SINGULARITY -eq 1 ]; then
            # Use "exec" (not "run") to preserve JSON quoting in --ops_overrides_json.
            singularity exec -B $EXPORT_PATH:$EXPORT_PATH \
                $IMAGE_REPO/suite2p_latest.sif \
                "${OPS_PYTHON_ARGS[@]}"
            OPS_EXIT_STATUS=$?
        else
            docker run --rm -v $EXPORT_PATH:$EXPORT_PATH \
                $IMAGE_REPO/suite2p_latest.sif \
                "${OPS_PYTHON_ARGS[@]}"
            OPS_EXIT_STATUS=$?
        fi
        # Check if ops creation failed
        if [ $OPS_EXIT_STATUS -ne 0 ]; then
            PIPELINE_SUCCESS=0
            echo "Failed to create ops file for $EXPORT_PATH"
            continue
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
    setup_mpl_cache
    if [ $USE_SINGULARITY -eq 1 ]; then
        # Create a temporary directory in COMMON_ROOT_EXPORT_DIR for CaImAn and assign it to CAIMAN_TEMP
        if [ -n "$COMMON_ROOT_EXPORT_DIR" ]; then
            CAIMAN_TEMP=$(mktemp -d -p "$COMMON_ROOT_EXPORT_DIR")
        else
            CAIMAN_TEMP=$(mktemp -d)
        fi
        CNMF_CMD="python -u -m pipeline.pipeline_cnmf $CONFIG_FILE"
        if [ -n "$MCORR_OUTPUT" ]; then
            CNMF_CMD+=" --mcorr-movie $MCORR_OUTPUT"
        fi
        if [ $USE_STABLE -eq 1 ]; then
            singularity run -B $MOUNT_POINTS \
                            --env CAIMAN_TEMP=$CAIMAN_TEMP,MPLBACKEND=$MPLBACKEND,MPLCONFIGDIR=$MPLCONFIGDIR \
                            $IMAGE_REPO/2p_proc_latest.sif $CNMF_CMD
        else
            echo "Using code directory: $PIPELINE_CODE_DIR for CNMF extraction."
            singularity run -B $MOUNT_POINTS \
                            -B $PIPELINE_CODE_DIR:/code \
                            --env CAIMAN_TEMP=$CAIMAN_TEMP,MPLBACKEND=$MPLBACKEND,MPLCONFIGDIR=$MPLCONFIGDIR \
                            $IMAGE_REPO/2p_proc_latest.sif $CNMF_CMD
        fi
        CNMF_EXIT_STATUS=$?
        rm -rf $CAIMAN_TEMP
    else
        CNMF_CMD="python -u -m pipeline.pipeline_cnmf $CONFIG_FILE"
        if [ -n "$MCORR_OUTPUT" ]; then
            CNMF_CMD+=" --mcorr-movie $MCORR_OUTPUT"
        fi
        docker run --rm --user $HOST_USER_ID:$HOST_GROUP_ID -v $COMMON_ROOT_DATA_DIR:$COMMON_ROOT_DATA_DIR -v $COMMON_ROOT_EXPORT_DIR:$COMMON_ROOT_EXPORT_DIR -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR -v $LOG_DIR:$LOG_DIR -v $CODE_DIR:/code -e MPLBACKEND=Agg -e MPLCONFIGDIR=$MPLCONFIGDIR wanglabneuro/2p_proc:latest $CNMF_CMD
        CNMF_EXIT_STATUS=$?
    fi
    cleanup_mpl_cache
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
        setup_mpl_cache
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
        
        cleanup_mpl_cache
        :
    done
fi

# If using the aind extractor, run the extraction capsule on each export path
if [ "$EXTRACTOR_METHOD" = "aind" ]; then
    for EXPORT_PATH in "${EXPORT_DATA_PATHS[@]}"; do
        echo "Running aind-ophys-extraction on $EXPORT_PATH"
        setup_mpl_cache
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

        cleanup_mpl_cache
        :
    done
fi

#### ROI Z-MOTION CORRECTION STEP
if [ "$EXTRACTOR_METHOD" = "suite2p" ] && is_roi_zcorr_requested; then
    echo ""
    echo "================================"
    echo "Running ROI z-motion correction."
    echo "================================"

    setup_mpl_cache
    if [ $USE_SINGULARITY -eq 1 ]; then
        if [ -z "${MOUNT_POINTS:-}" ]; then
            MOUNT_POINTS="$CONFIG_FILE_DIR,$COMMON_ROOT_DATA_DIR,$COMMON_ROOT_EXPORT_DIR,$LOG_DIR,$CODE_DIR"
        fi
        singularity run -B "$MOUNT_POINTS" \
            $IMAGE_REPO/2p_proc_latest.sif \
            python -u -m pipeline.roi_zcorr $CONFIG_FILE
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
            wanglabneuro/2p_proc:latest \
            python -u -m pipeline.roi_zcorr $CONFIG_FILE
        ROI_Z_EXIT_STATUS=$?
    fi
    cleanup_mpl_cache
    :
    if [ $ROI_Z_EXIT_STATUS -ne 0 ]; then
        PIPELINE_SUCCESS=0
        echo "ROI z-motion correction failed with exit status $ROI_Z_EXIT_STATUS"
    fi
elif [ "$EXTRACTOR_METHOD" = "suite2p" ]; then
    echo "Skipping ROI z-motion correction (not requested in config: requires params_mcorr.z_motion_correction and non-empty paths.zstack_paths)."
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
            SLURM_LOG_FILE="./slurm_logs/2P_proc-${SLURM_JOB_ID}.ans"
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
                $IMAGE_REPO/2p_proc_latest.sif \
                python /code/paths_params_io.py "$CONFIG_FILE" --get-output-format)
        else
            output_format_STR=$(docker run --rm -v $CONFIG_FILE_DIR:$CONFIG_FILE_DIR \
                wanglabneuro/2p_proc:latest \
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
