#!/bin/bash

# Copy the Mesmerize folder one level above, to the context folder
rsync -avzP ../Mesmerize context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p:latest -t wanglabneuro/analysis-2p:0.2.2 -f Dockerfile context --no-cache

# Delete the Mesmerize folder from the context folder
rm -rf context/Mesmerize

# v0.0.1: Initial release
# v0.0.2: Removed ENTRYPOINT from Dockerfile
# v0.0.3: Added conda init for user wanglab. Switched default user to wanglab.
# v0.0.4: Initialize conda for all users
# v0.0.5: Updated base mesmerize image
# v0.1.0: Adds z-motion correction on pixels
# v0.2.0: Adds z-motion correction on patches
# v0.2.1: z-motion correction on patches with subtraction on pixels 
# v0.2.2: removed Suite2p package and tested on remote server 

# Test with docker run --rm -it wanglabneuro/analysis-2p /bin/bash, or singularity run docker://wanglabneuro/analysis-2p:latest /bin/bash