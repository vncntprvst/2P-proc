#!/bin/bash

# Copy the Mesmerize and modules folder one level above, to the context folder
rsync -avzP --include="utils/" --include="paths/" --include="parameters/" --include="*.py" --include="*.ipynb" --include="*.md" --exclude="*/" ../../Mesmerize/ context/Mesmerize/
rsync -avzP ../../modules context/
rsync -avzP ../../pipeline context/
# rsync -avzP ../../Matlab context/
rsync -avzP ../../readme.md context/
rsync -avzP ../../LICENSE.md context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p:latest -t wanglabneuro/analysis-2p:0.5.1 -f Dockerfile context --no-cache

# Delete the Mesmerize and modules folder from the context folder
rm -rf context/Mesmerize
rm -rf context/modules
rm -rf context/pipeline
# rm -rf context/Matlab
rm -f context/readme.md
rm -f context/LICENSE.md

# Push to Docker registry
docker push --all-tags wanglabneuro/analysis-2p

# Convert Docker image to Singularity image
# Requires Singularity installed on your system.
if ! command -v apptainer &> /dev/null
then
    echo "apptainer could not be found"
    echo "Please install apptainer from https://apptainer.org/docs/admin/main/installation.html#install-ubuntu-packages"
    exit
else
    # If a hash file exists, check the hash matches the current Docker image. If not, build a new Singularity image.
    if [ -f "analysis-2p_latest.sif.hash" ]; then
        if [ "$(docker inspect wanglabneuro/analysis-2p:latest --format='{{.Id}}')" == "$(cat analysis-2p_latest.sif.hash)" ]; then
            echo "Docker image has not changed. Not building Singularity image."
            build_singularity=0
        else
            echo "Docker image has changed. Building Singularity image."
            build_singularity=1
        fi
    else
        echo "Hash file not found. Building Singularity image."
        build_singularity=1
    fi
          
    if [ $build_singularity -eq 1 ]; then
        echo "Building Singularity image."
        # docker login
        apptainer build -F analysis-2p_latest.sif docker://wanglabneuro/analysis-2p:latest
        # docker logout
        # store a hash of the Docker image in a file
        docker inspect wanglabneuro/analysis-2p:latest --format='{{.Id}}' > analysis-2p_latest.sif.hash
    fi

fi

# If the .env script exists, get the HPCC_IMAGE_REPO variable
if [ -f "../../scripts/utils/.env" ]; then
    echo "Get server information from .env file."
    # Read .env robustly: skip empty lines and comments, require '=' in the line
    while IFS= read -r line || [ -n "$line" ]; do
        # remove leading/trailing whitespace
        line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        # skip empty lines
        if [ -z "$line" ]; then
            continue
        fi
        # skip comments
        case "$line" in
            \#*) continue ;;
        esac
        # skip lines without an equals sign
        if [[ "$line" != *"="* ]]; then
            continue
        fi
        key="${line%%=*}"
        value="${line#*=}"
    # strip surrounding double or single quotes from value if present
    value="${value%\"}"; value="${value#\"}"
    value="${value%'}"; value="${value#'}"
    # export the variable; allow expansion of references to previously exported vars
    # use eval so values containing $VAR are expanded
    eval "export $key=\"$value\""
    done < "../../scripts/utils/.env"

    # Only build SSH_HPCC_IMAGE_REPO if both components exist
    if [ -n "${SSH_TRANSFER_NODE:-}" ] && [ -n "${HPCC_IMAGE_REPO:-}" ]; then
        # base form: host:path
        host_part="${SSH_TRANSFER_NODE}"
        path_part="${HPCC_IMAGE_REPO}"
        # add user@ if missing (use SSH_USER from .env or current $USER)
        # if [[ "$host_part" != *"@"* ]]; then
        #     ssh_user="${SSH_USER:-$USER}"
        #     host_part="${ssh_user}@${host_part}"
        # fi
        # validate host doesn't contain slashes (common mistake when variables weren't expanded)
        raw_host="${host_part%%@*}"
        if [[ "$raw_host" == *"/"* ]]; then
            echo "Warning: derived SSH host contains '/': $raw_host. Not setting SSH_HPCC_IMAGE_REPO"
        else
            export SSH_HPCC_IMAGE_REPO="${host_part}:${path_part}"
        fi
    else
        echo "Warning: SSH_TRANSFER_NODE or HPCC_IMAGE_REPO not set from .env; not setting SSH_HPCC_IMAGE_REPO"
    fi
fi

# check if hppc_image_repo variable exists
if [ -n "${SSH_HPCC_IMAGE_REPO+x}" ]; then
    echo "Copying Singularity image to HPCC."
    echo "Resolved SSH_HPCC_IMAGE_REPO=$SSH_HPCC_IMAGE_REPO"
    # Show quick sanity checks
    host_check="${SSH_HPCC_IMAGE_REPO%%:*}"
    path_check="${SSH_HPCC_IMAGE_REPO#*:}"
    echo "  host: $host_check"
    echo "  path: $path_check"
    if [[ "$host_check" == *"/"* ]]; then
        echo "Aborting rsync: host contains '/'. Check .env variables."
    else
        rsync -aP analysis-2p_latest.sif "$SSH_HPCC_IMAGE_REPO/" # -z compression flag tends to screw up the transfer when using the script. May not be necessary anyway.
    fi
else
    echo "HPCC_IMAGE_REPO variable not set. Not copying to HPCC."
fi