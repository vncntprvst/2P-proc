#!/bin/bash

# Copy the Mesmerize folder one level above, to the context folder
rsync -avzP ../../Mesmerize context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p:latest -t wanglabneuro/analysis-2p:0.2.5 -f Dockerfile context --no-cache

# Delete the Mesmerize folder from the context folder
rm -rf context/Mesmerize

# Versions:
# v0.2.5: Adds caiman_data directory to IM_USER home and set default environment variables for caiman_data and caiman_temp 
        # CAIMAN_DATA=/home/$IM_USER/caiman_data
        # CAIMAN_TEMP=/home/$IM_USER/caiman_data/temp
# v0.2.4: Matlab analysis scripts updates
# v0.2.3: finalizing z-motion correction options
# v0.2.2: removed Suite2p package and tested on remote server 
# v0.2.1: z-motion correction on patches with subtraction on pixels 
# v0.2.0: Adds z-motion correction on patches
# v0.1.0: Adds z-motion correction on pixels
# v0.0.5: Updated base mesmerize image
# v0.0.4: Initialize conda for all users
# v0.0.3: Added conda init for user wanglab. Switched default user to wanglab.
# v0.0.2: Removed ENTRYPOINT from Dockerfile
# v0.0.1: Initial release

# Test with docker run --rm -it wanglabneuro/analysis-2p /bin/bash, or singularity run docker://wanglabneuro/analysis-2p:latest /bin/bash