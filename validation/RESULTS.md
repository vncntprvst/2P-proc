# Z-motion correction — validation & benchmarking results

Environment: `validation/pixi.toml` (CaImAn 1.12.2 + Suite2p 0.14.0, the production
stability pins). Data: `C57_O1M2/10022023` (TSeries-001 + ZSeries-1300-004, a real
41-plane / 1 µm z-stack). Run benchmarks with `pixi run python ...` from `validation/`.

## 1. End-to-end pipeline validation (real TSeries-001 subset)

The full chain runs on real data: motion correction → z-motion (`z_correlation.npz`
+ non-rigid `F_anat` movie) → CNMF extraction → `run_roi_zcorr` → `F_roi_zcorrected.npz`.

Getting there required fixing **7 bugs** in paths that had drifted out of sync with the
pinned CaImAn/Suite2p (the per-ROI correction is normally done later in MATLAB, so it
was under-exercised):

| # | File | Fix |
|---|---|---|
| 1 | `extraction.py` | clamp `create_components_movie` excerpt to movie length (short recordings) |
| 2 | `extraction.py` | save `cnmf_result.hdf5` so `run_roi_zcorr` can load CNMF output |
| 3 | `motion_correction.py` | `load_CNMF(..., n_processes=1)` (empty `CNMF()` unsupported in ≥1.12) |
| 4 | `motion_correction.py` | raw F = `C + YrA` (no `estimates.F` in 1.12) |
| 5 | `motion_correction.py` | dims from `cnm.dims` (no `estimates.d1/d2`) |
| 6 | `compute_zcorr.py` | `np.ascontiguousarray` after flip (Suite2p torch rejects negative strides) |
| 7 | `compute_zcorr.py` | fetch `rigid` inside the joblib worker (was undefined in subprocess) |

Env note: the pipeline can't run bare on a host where `python` = Python 2 (mesmerize-core
subprocess); run inside an activated env (`pixi run`). Consider making the runfile use
`sys.executable`.

## 2. Stage 1 — z-position estimation (`compute_zcorrel` vs `compute_zcorrel_suite2p`)

Real anatomy, 192², 150 frames, imposed rigid drift + lateral jitter + deformation:

| case | method | r | RMSE (µm) | time (s) |
|---|---|---|---|---|
| drift ≈2 planes | compute_zcorrel | 0.79 | 1.29 | ~3–14 |
| | suite2p | **0.95** | **0.66** | ~8–83 |
| drift ≈4 planes | compute_zcorrel | 0.94 | 1.41 | 2.6 |
| | suite2p | **0.98** | **0.76** | 7.9 |

**Suite2p is more accurate (≈½ the RMSE, better at small drift) but ~3–6× slower.**
`compute_zcorrel`'s error floors near 1 plane (argmax discretization). Suggested
improvements to `compute_zcorrel`: sub-plane interpolation of the correlation peak;
masked/phase correlation for small drift.

## 3. Stage 3 — correction method (recovery of injected synthetic activity)

Real z-stack + injected spike→GCaMP activity (NAOMi-lite), 20 cells near the focal plane.
`recovery_r` = corrected-trace vs ground-truth activity; `residual_z_r` = leftover
z-contamination (lower is better):

| z-drift | none | per_roi | per_pixel | per_patch |
|---|---|---|---|---|
| 3 planes | 0.675 / 0.236 | **0.690 / 0.169** | 0.687 / 0.192 | 0.680 / 0.211 |
| 6 planes | 0.519 / 0.250 | 0.531 / **0.182** | 0.540 / 0.201 | 0.531 / 0.190 |
| 9 planes | 0.400 / 0.317 | 0.427 / **0.209** | 0.424 / 0.268 | 0.421 / 0.226 |

**Per-ROI correction removes the most z-contamination at every amplitude** (lowest
`residual_z_r`), confirming its robustness; per-pixel/per-patch trail. Recovery gains are
modest because z-motion also *attenuates* the true signal via defocus, which additive
subtraction cannot restore — the correction's value is in removing additive contamination,
not recovering lost signal.

## Reproduce

```
cd validation
pixi run python ../tests/benchmarks/benchmark_zpos_methods.py --real-zstack <ZSeries> --downsample 4 --save-results results/
pixi run python ../tests/benchmarks/benchmark_correction_methods.py --real-zstack <ZSeries> --downsample 4 --save-results results/
python plot_roi_zcorr.py <export_dir>   # real-data raw-vs-corrected trace figure + roi_zcorr_viz.npz
```

## Open / next

- Validate the **Suite2p ROI-correction path** (`run_roi_zcorr` reading `F.npy`/`stat.npy`).
- Run the **full TSeries-001** (single session; concatenated set only after).
- Consider the `compute_zcorrel` sub-plane improvement suggested by stage 1.
