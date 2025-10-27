### Analysis 2P container

Runs the 2P analysis pipeline on a specified configuration file (JSON), which contains paths and parameters.
The data volumes must be mounted in the container.

#### Example usage
* With Docker:
`docker run --rm -d -v /data:/data wanglabneuro/analysis-2p conda run -n mescore python -u /code/Mesmerize/batch_mcorr.py config.json`
`docker run --rm -d -v /data:/data wanglabneuro/analysis-2p conda run -n mescore python -u /code/Mesmerize/batch_cnmf.py config.json`

* With Singularity:
`singularity run --cleanenv -B /data:/data analysis-2p_latest.sif conda run -n mescore python -u /code/Mesmerize/batch_mcorr.py config.json`
`singularity run --cleanenv -B /data:/data analysis-2p_latest.sif conda run -n mescore python -u /code/Mesmerize/batch_cnmf.py config.json`
