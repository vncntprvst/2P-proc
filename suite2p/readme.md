# Suite2P

Use the repository environment script (from repo root):

```bash
bash environments/s2p_venv_script.sh
source .suite2p/bin/activate
```

Optional local tools:

```bash
uv pip install suite2p[gui,io] jupyterlab
```

Quick checks:

```bash
python -m suite2p --version
suite2p
```

## Pipeline config behavior

For pipeline runs (`scripts/2P_proc_template.sh`), `params_extraction.main` is now passed through to Suite2p ops creation:

- Keep only required imaging fields (`fr`/`fs`, `Npixel_x`, `Npixel_y`) plus `decay_time` or `tau`.
- Add any Suite2p ops key you want under `params_extraction.main`; it will override the Suite2p default at ops creation.
- `decay_time` is backward-compatible and mapped to `tau`.
- MATLAB export remains enabled by default (`save_mat=1` in batch script).

## Practical parameter recommendations

See docs: https://suite2p.readthedocs.io/en/latest/parameters/

- Start with: `tau`, `threshold_scaling`, `max_overlap`, `diameter`, `inner_neuropil_radius`, `snr_thresh`.
- Registration is done with CaImAn by default, but in case you want to test Suite2p's registration, these parameters are available: `do_registration`, `nonrigid`, `maxregshift`, `smooth_sigma`, `spatial_taper`.
- Common advanced controls in local usage: `batch_size`, `functional_chan`, `max_iterations`, `sparse_mode`, `pre_smooth`.
