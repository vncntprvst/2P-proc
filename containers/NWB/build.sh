#!/bin/bash

# Copy conversion script to context directory
cp nwb_conversion.py context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p-nwb:latest -f Dockerfile context

# Clean up context directory
rm -f context/nwb_conversion.py

# Push to Docker registry
docker push wanglabneuro/analysis-2p-nwb:latest

# Convert Docker image to Apptainer
if command -v apptainer &> /dev/null; then
    apptainer pull --name NWB_latest.sif docker://wanglabneuro/analysis-2p-nwb:latest
fi

# Load and export variables from .env
if [ -f "../../scripts/utils/.env" ]; then
  set -a                           # auto-export all variables
  # shellcheck disable=SC1091
  . "../../scripts/utils/.env"     # source the .env (trusted file)
  set +a
fi

# Build SSH_HPCC_IMAGE_REPO if both pieces exist
if [ -n "${SSH_TRANSFER_NODE:-}" ] && [ -n "${HPCC_IMAGE_REPO:-}" ]; then
export SSH_HPCC_IMAGE_REPO="${SSH_TRANSFER_NODE}:${HPCC_IMAGE_REPO}"
else
echo "Warning: SSH_TRANSFER_NODE or HPCC_IMAGE_REPO not set from .env; not setting SSH_HPCC_IMAGE_REPO"
fi

# Copy SIF to HPCC if SSH_HPCC_IMAGE_REPO is set (format: host:path)
if [ -n "${SSH_HPCC_IMAGE_REPO:-}" ]; then
  IFS=: read -r host path <<<"$SSH_HPCC_IMAGE_REPO"
  echo "Copying Singularity image to HPCC:"
  echo "  host: ${host:-<empty>}"
  echo "  path: ${path:-<empty>}"
  if [ -z "$host" ] || [ -z "$path" ] || [[ "$host" == *"/"* ]]; then
    echo "Invalid SSH_HPCC_IMAGE_REPO='$SSH_HPCC_IMAGE_REPO'; skipping rsync."
  else
    rsync -aP NWB_latest.sif "$host:$path/"
  fi
else
  echo "SSH_HPCC_IMAGE_REPO not set; not copying to HPCC."
fi