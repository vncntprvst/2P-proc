### Analysis 2P container
  
Runs the 2P analysis pipeline on a specified path file (accepts .json or csv, see Mesmerize/batch_mcorr_cnmf.py), contains paths to the data.
The data volumes must be mounted in the container.  

#### Example usage
* With Docker:  
`docker run --rm -d -v /data:/data wanglabneuro/analysis-2p conda run -n mescore python -u /code/Mesmerize/batch_mcorr_cnmf.py path_file.json`
 
* With Singularity:
`singularity run --cleanenv -B /data:/data analysis-2p_latest.sif conda run -n mescore python -u /code/Mesmerize/batch_mcorr_cnmf.py path_file.json`

