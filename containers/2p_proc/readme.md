### Optimouse Container

Runs the 2-photon imaging processing pipeline (optimouse) on a specified configuration file (JSON), which contains paths and parameters.
The data volumes must be mounted in the container.

**Note**: This container now installs optimouse as a package from PyPI instead of copying source files.

#### Example usage
* With Docker:
```bash
docker run --rm -d -v /data:/data wanglabneuro/2p_proc:latest conda run -n mescore python -u -m pipeline.pipeline_mcorr config.json
docker run --rm -d -v /data:/data wanglabneuro/2p_proc:latest conda run -n mescore python -u -m pipeline.pipeline_cnmf config.json
```

* With Singularity:
```bash
singularity run --cleanenv -B /data:/data 2p_proc_latest.sif conda run -n mescore python -u -m pipeline.pipeline_mcorr config.json
singularity run --cleanenv -B /data:/data 2p_proc_latest.sif conda run -n mescore python -u -m pipeline.pipeline_cnmf config.json
```

Per-ROI z-motion correction and cross-session registration (CaImAn method; ROICaT/Track2p need
their own Python >= 3.11 environment, see the main README):
```bash
singularity run --cleanenv -B /data:/data 2p_proc_latest.sif python -u -m pipeline.roi_zcorr config.json
singularity run --cleanenv -B /data:/data 2p_proc_latest.sif python -u -m pipeline.register_sessions \
    --exports <export1> <export2> --out <dir> --method caiman
```

#### Building the container

See [build.sh](build.sh) for simple Docker build, or [build_docker_singularity.sh](build_docker_singularity.sh) for Docker + Singularity build with push to registry.
The image installs optimouse from PyPI at the version pinned in the Dockerfile: release that version first.
To copy the SIF to the cluster, set `SSH_TRANSFER_NODE` (an SSH host) and `HPCC_IMAGE_REPO` (the image folder) in a
`.env` file next to the build script.
