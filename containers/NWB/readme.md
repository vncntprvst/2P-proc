### NWB conversion container

Container image for converting 2P imaging data and associated processing results to [Neurodata Without Borders (NWB)](https://www.nwb.org/) files.

This image includes `pynwb`, `neuroconv`, and the `nwbinspector` validator. The conversion script is copied to `/code` and the default entrypoint runs `nwb_conversion.py`.

#### Example usage
* With Docker:
`docker run --rm -v /data:/data -v /exports:/exports wanglabneuro/analysis-2p-nwb:latest /data/config.json`

* With Singularity:
`singularity run -B /data:/data -B /exports:/exports analysis-2p-nwb_latest.sif /data/config.json`
