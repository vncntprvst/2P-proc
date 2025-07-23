# This Dockerfile is used to build the Allen Neural Dynamics Ophys Extraction Suite2P container.
ARG CAPSULE_NAME=aind-ophys-extraction-suite2p

# Use the Allen Neural Dynamics Ophys Extraction Suite2P base image
FROM ghcr.io/allenneuraldynamics/${CAPSULE_NAME}-docker-local:latest

LABEL description="Analysis 2P pipeline container based on Allen Neural Dynamics Suite2P"
LABEL version="1.0"

# Create directory for the Analysis 2P code
# WORKDIR /workspace/Analysis_2P

# Copy Analysis 2P code to container
# COPY . /workspace/Analysis_2P/

# Install additional dependencies for Analysis 2P
# RUN pip install -r requirements.txt || echo "No requirements.txt found, skipping"

# Set up entrypoint to be more flexible with arguments
# ENTRYPOINT ["python", "-m", "Mesmerize.batch_mcorr_cnmf"]







