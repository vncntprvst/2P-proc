#!/bin/bash

# Copy the Mesmerize and modules folder one level above, to the context folder
rsync -avzP --include="utils/" --include="paths/" --include="parameters/" --include="*.py" --include="*.ipynb" --include="*.md" --exclude="*/" ../../Mesmerize/ context/Mesmerize/
rsync -avzP ../../modules context/
rsync -avzP ../../pipeline context/
# rsync -avzP ../../Matlab context/
rsync -avzP ../../readme.md context/
rsync -avzP ../../LICENSE.md context/

# Build Docker image
docker build -t wanglabneuro/analysis-2p:latest -t wanglabneuro/analysis-2p:0.5.2 -f Dockerfile context --no-cache

# Delete the Mesmerize and modules folder from the context folder
rm -rf context/Mesmerize
rm -rf context/modules
rm -rf context/pipeline
# rm -rf context/Matlab
rm -f context/readme.md
rm -f context/LICENSE.md

# v0.5.2: quick fix for dark mcorr_u8 and compare_og_mcorr, fix ops nframes detection not working when zcorrection not requested, with sidecar json file + robust fallbacks
# v0.5.1: h5 and bin export + Suite2P extraction
# v0.5.0: Updated to use the latest Mesmerize base image (overhauled the Dockerfile and reduced image size 3x), and added the modularized Analysis 2P pipeline. 
# v0.3.+ ... v0.4.0: Generated through GH CI/CD pipeline.
# v0.3.0: Getting close to v1.0. Matlab pipeline (with intregated DLC and rastermap calls) working locally and on remote server.    
# v0.2.6: Solving out-of-memory errors. 
        # Adds Context manager to close files and free memory in pipeline, for mcorr and cnmf steps.
        # Also updates batch scrip, adding --env MESMERIZE_N_PROCESSES=$SLURM_CPUS_ON_NODE to singularity call
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