### Optimouse Container

Runs the 2-photon imaging processing pipeline (optimouse) on a specified configuration file (JSON), which contains paths and parameters.
The data volumes must be mounted in the container.

**Note**: This container now installs optimouse as a package from PyPI instead of copying source files.

#### Example usage
* With Docker:
```bash
docker run --rm -d -v /data:/data wanglabneuro/optimouse:latest conda run -n mescore python -u -m pipeline.pipeline_mcorr config.json
docker run --rm -d -v /data:/data wanglabneuro/optimouse:latest conda run -n mescore python -u -m pipeline.pipeline_cnmf config.json
```

* With Singularity:
```bash
singularity run --cleanenv -B /data:/data optimouse_latest.sif conda run -n mescore python -u -m pipeline.pipeline_mcorr config.json
singularity run --cleanenv -B /data:/data optimouse_latest.sif conda run -n mescore python -u -m pipeline.pipeline_cnmf config.json
```

#### Building the container

See [build.sh](build.sh) for simple Docker build, or [build_docker_singularity.sh](build_docker_singularity.sh) for Docker + Singularity build with push to registry.
