# Z-motion correction — validation & benchmarking handoff

Branch: `benchmark`. Working tree clean (except the untracked `tests/benchmarks/benchmarking notes.md`, your working notes). A safety branch `backup-benchmark-presplit` exists — delete once happy (`git branch -D backup-benchmark-presplit`).

## Goal
Validate and benchmark the (novel) z-motion correction method on real data for publication, and find what actually works best. NOT bug-fixing production per se — but validation surfaced real bugs, which were fixed. Test data: `C57_O1M2/10022023` (functional TSeries + real 41-plane ZSeries @ 1 µm).

## Environment
- **Testing/benchmarking**: `validation/pixi.toml` (+ `pixi.lock`), pinned to production: **CaImAn 1.12.2 + Suite2p 0.14.0**, Python 3.10. `cd validation && pixi install && pixi run setup-caiman`. Run things with `pixi run python ...`.
- `.proc2P` (uv venv) also works for anything not needing Suite2p.
- **Gotcha**: the pipeline can't run where bare `python` is Python 2 (mesmerize-core spawns a subprocess) — always run inside an activated env (`pixi run`). Consider making mesmerize's runfile use `sys.executable`.
- Disk was 97% full earlier (blocked the concat NoRMCorre); now has headroom.

## What was done

### 1. Pipeline validated end-to-end on real data
mcorr → z-motion (`F_anat_non_rigid`) → extraction (CNMF **and** Suite2p) → `run_roi_zcorr` → `F_roi_zcorrected`. Ran on TSeries-001 subset (200 fr) and full session (1600 fr; real z-drift planes 9–16). **7 bugs fixed** in the under-tested per-ROI path (`f56d957`, `1416e66`, `75180d0`, and `compute_zcorr` suite2p fixes): excerpt overflow on short recordings; CNMF now writes `cnmf_result.hdf5`; `load_CNMF(n_processes=1)`, raw F = `C+YrA`, dims from `cnm.dims` (caiman ≥1.12); `compute_zcorrel_suite2p` contiguous-flip + worker-scope `rigid` (suite2p 0.14). Formatting-only reformat of the two touched files is split into its own commit `f06087f`.

### 2. Per-ROI ΔF/F z-correction fixed to the MATLAB reference (`ec82e0c`)
`run_roi_zcorr` was producing wrong traces (straight-line jumps, flat ends). Reimplemented per `Analysis_2P/Matlab/analyze_2p_with_Beh_func.m` (l.313+): work in **ΔF/F**, 3-point temporal smoothing of `F_anat`, **uniform mean over ROI pixels**, **OLS slope**, subtract — **removed the NaN-and-interpolate step** that caused the artifacts. Output keys: `dff`, `dff_corrected`, `dffz`, `roi_z_scaling`, `roi_z_R2`.

### 3. `compute_zcorrel` optimized; `compute_zcorrel_legacy` kept (`ce5fc6e`, `471026e`)
- `compute_zcorrel_legacy` = original full-frame Pearson (comparison/fallback).
- New `compute_zcorrel` default = **Pearson + temporal median smoothing** of zpos (safe, real win). `method="phasecorr"` (Suite2p) and `edge_crop` are **opt-in, OFF by default** — validated to *degrade on mcorr'd data*. **No Suite2p dependency by default** (only in the phasecorr branch, with graceful fallback).

### 4. Benchmarks (all in `tests/benchmarks/` + `validation/`)
- `synthetic_zstack.py` / `bruker_io.py` — real z-stack → known-trajectory movie harness (3D: z + xy + deform).
- `synthetic_activity.py` — NAOMi-lite: inject spike→GCaMP activity into real somata; **`make_stimulus_locked_traces` + `make_response_coupled_zmotion`** model the protocol (downward z-onsets clustered on stimulus responses).
- `benchmark_zcorr.py` (stage 0 harness), `benchmark_zpos_methods.py` (stage 1), `benchmark_correction_methods.py` (stage 3).
- `validation/`: `zpos_compare_data.py` (synthetic/single/concat zpos), `test_subplane_precision.py`, `test_new_compute_zcorrel.py`, `synthetic_correction_demo.py`, `plot_roi_zcorr.py`, `make_report.py`.

### 5. Methodology report
**`validation/report/zmotion_report.pdf`** (regenerate: `pixi run python validation/make_report.py --results <dir> --out ...`). Data JSON/npz + figures committed alongside. Full write-up in `validation/RESULTS.md`.

## Key findings
- **z-position method (stage 1):** phase correlation (Suite2p) is most accurate on synthetic ground truth (RMSE ~0.7 vs ~1.7 planes) **but does NOT transfer to mcorr'd production data** — phasecorr latches onto the deepest plane; `edge_crop` collapses Pearson to plane 0. Since z-pos runs after NoRMCorre, neither is usable there. **The robust win is Pearson + temporal smoothing** (same drift as legacy, 44 vs 290 spurious ≥2-plane jumps on the real run). → **Keep Pearson (the new default); do not adopt phasecorr for production.**
- **Sub-plane interpolation (stage 1b):** negligible gain for both global zpos and F_anat — error is dominated by discrete misassignments + defocus attenuation, not ±0.5-plane quantization. Not worth adding.
- **Correction method (stage 3):** per-ROI fit-and-subtract removes the most z-contamination at every drift amplitude; per-pixel/per-patch trail.
- **Synthetic ground-truth correction (§6c):** with response-coupled z-motion (activity–z coupling r ≈ −0.17), the most z-impacted cells recover **r 0.24 → 0.62** and shed most z-contamination; clean cells untouched. **Limit:** because the artifact overlaps the responses, residual z after correction (~0.18–0.22) is higher than the uncoupled case (~0.14) — the correction can't remove z time-locked to signal without risking the signal.

## Deliverables (committed)
- Pipeline fixes: `modules/compute_zcorr.py`, `modules/motion_correction.py`, `modules/extraction.py`.
- Test data: `scripts/make_test_fixture.py`, `scripts/download_test_data.sh` (points at a `test-data-v2` GH release asset — **needs uploading**, see below).
- Env: `validation/pixi.toml` + `pixi.lock`; `uv.lock` for the package.
- Benchmarks + report: `tests/benchmarks/*`, `validation/*`, `validation/report/zmotion_report.pdf`, `validation/RESULTS.md`.
- **Parked (built prematurely):** `containers/aind_zmotion_correction/` + `scripts/sbatch_zmotion_correction.sh` — an AIND capsule for z-correction. Not part of validation; keep or remove.

## Next steps
1. **Upload the test fixture**: `python scripts/make_test_fixture.py` → attach `Mesmerize/test_data.tar.gz` to a `test-data-v2` release on `vncntprvst/2P-proc` (the download URL is set to it; override with `TEST_DATA_URL`).
2. **Full-res concat rerun with real NoRMCorre**: the concatenated 4-session z-pos comparison used raw (un-mcorr'd) frames because disk was full; rerun properly now that disk allows, to get production concat numbers.
3. **Ship Pearson + temporal smoothing** as the z-pos default (done in code); optionally tune `temporal_smooth` and expose it in the config.
4. **Improve mcorr-edge handling** if phasecorr is ever wanted (mask borders before z-pos) — but current evidence says stick with Pearson.
5. **Real-data trace figures for your judgement**: `validation/plot_roi_zcorr.py <export_dir>` → per-ROI raw-vs-corrected + `roi_zcorr_viz.npz`.
6. Decide on the parked AIND capsule (§Deliverables).
7. Tests: `pytest tests/` runs unit tests + the synthetic z-benchmark cases (real-data integration test skips unless the fixture is present).

## Reproduce
```
cd validation && pixi install && pixi run setup-caiman
# pipeline on real data (build a config; template pipeline/configs/config_template_cnmf.json fits C57_O1M2/10022023)
pixi run python -m pipeline.pipeline_mcorr <config.json>   # mcorr + z-motion (set params_mcorr.z_motion_correction.non_rigid=true)
pixi run python -m pipeline.pipeline_cnmf  <config.json>   # CNMF extraction
pixi run python -m pipeline.roi_zcorr      <config.json>   # per-ROI ΔF/F correction
# benchmarks
pixi run python ../tests/benchmarks/benchmark_zpos_methods.py --real-zstack <ZSeries> --downsample 4 --save-results r/
python validation/synthetic_correction_demo.py --real-zstack <ZSeries> --coupled --real-zpos validation/report/new_zcorrel_real.npz --out r/
python validation/make_report.py --results r/ --out validation/report/zmotion_report.pdf
```
Commit style: terse one-line, no signature.
