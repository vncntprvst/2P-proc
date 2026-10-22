### Registration container

Matches cells across separately processed sessions of the same field of view with ROICaT
(`pipeline.register_sessions`, method `roicat`). Inputs are pipeline export folders with Suite2p
(`suite2p/plane0`) or CNMF (`results_caiman.mat`) outputs. CaImAn is not installed; the `caiman`
method runs in the `2p_proc` image instead. Track2p pins numpy 2.0.2 and ROICaT numpy 2.4.6, so they
cannot share an image; use `--python` with a Track2p environment if needed.

Validation and method comparison: `validation/report/registration/registration_report.html`.

#### Usage
On the cluster, use `scripts/register_sessions.sh`, which picks this image (or `2p_proc` for
`--method caiman`) from `IMAGE_REPO`:
```bash
sbatch scripts/register_sessions.sh --exports <export_day1> <export_day2> ... --out <dir>
```
Directly:
```bash
singularity run --cleanenv -B /orcd:/orcd 2p_registration_latest.sif python -m pipeline.register_sessions \
    --exports <export_day1> <export_day2> --out <dir> --cpu
```

#### Building
`./build_docker_singularity.sh` builds the image, pushes it to Docker Hub, builds the SIF and copies it to
the cluster (`SSH_TRANSFER_NODE` and `HPCC_IMAGE_REPO` from a `.env` file, as for `2p_proc`).
The image installs optimouse from PyPI at the pinned version: release it first.
