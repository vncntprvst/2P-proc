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

### Stage 1b — sub-plane interpolation (tested, `test_subplane_precision.py`)

Parabolic interpolation of the correlation peak was expected to sharpen the integer
`argmax` z-estimate (and the per-patch depth used for F_anat). **Tested: negligible
improvement**, for both:

| lever | integer | sub-plane |
|---|---|---|
| global z RMSE (planes), amp 1/2/4 | 2.26 / 2.79 / 1.81 | 2.26 / 2.77 / 1.79 |
| F_anat correction recovery_r, amp 3/6 | 0.721 / 0.548 | 0.722 / 0.549 |

The error is dominated by **discrete multi-plane misassignments** (under lateral
jitter/deformation) and by **signal attenuation from defocus** — not ±0.5-plane
quantization. So sub-plane interpolation is not worth adding. The real levers are
plane-selection robustness (temporal regularisation of `zpos`; better lateral-motion
handling) or the more accurate Suite2p estimator.

### Stage 1c — z-position deep-dive: synthetic + real (single & concatenated)

Both methods run on identical inputs (`zpos_compare_data.py`); see PDF §5.

| dataset | metric | compute_zcorrel | suite2p |
|---|---|---|---|
| synthetic (6 seeds, GT) | Pearson r | 0.911 ± 0.029 | **0.972 ± 0.002** |
| synthetic (6 seeds, GT) | RMSE (planes) | 1.74 ± 0.44 | **0.74 ± 0.02** |
| real single (raw, no GT) | agreement r | 0.748 | (vs caiman) |
| real single | ≥2-plane jumps /1600 | 24 | 44 |
| real concat (4×1600) | agreement r | 0.761 | (vs caiman) |
| real concat | mean \|jump\| at boundaries | 1.00 | **0.33** |

**Suite2p is decisively more accurate on ground truth** and far more consistent; on
real data the two agree well, Suite2p is marginally noisier frame-to-frame but handles
concatenation boundaries **better**. Caveat: Suite2p's z-pos is unstable on the *mcorr'd*
movie (NoRMCorre edge artifacts drive it to the stack boundary) — must be handled since
z-pos runs after mcorr. **Recommendation:** adopt Suite2p for z-position (worth the 3–6×
cost) with light temporal smoothing; verify on the mcorr'd movie before switching.

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

## Coverage

- **Both extraction backends validated** end-to-end (mcorr → z-motion → extraction →
  `run_roi_zcorr` → `F_roi_zcorrected`): CNMF and Suite2p (the Suite2p ROI branch reads
  `F.npy`/`stat.npy` and worked without further fixes).
- **Full TSeries-001** (1600 frames) runs end-to-end: real z-drift planes 9–16 (~7 µm,
  σ≈1 µm); CNMF → 593 ROIs → `F_roi_zcorrected` (593×1600). See `plot_roi_zcorr.py` output.

## Open / next

- Concatenated 4-session run (expected z-pos artifacts at session boundaries — validate
  single-session first, done).
- Improve z-estimation robustness (the real bottleneck, per stage 1b): temporal
  regularisation of `zpos` to suppress multi-plane misassignments, or default to the
  more accurate Suite2p estimator (weigh its ~3–6× cost).
- Larger cell counts / activity regimes in the stage-3 sweep to further separate methods.
