"""
Benchmark stage 3 — z-motion *correction* method comparison, scored by how well
each method recovers known synthetic calcium activity.

Setup (synthetic ground truth)
------------------------------
Real ZSeries volume → inject synthetic calcium activity into detected somata
(see ``synthetic_activity``) → sample along a known 3D z-trajectory. The injected
traces ``trueC`` are the ground truth. z-motion contaminates the per-cell traces;
a good correction removes that contamination while preserving activity.

Methods compared
----------------
- ``none``      : per-ROI trace read straight from the (contaminated) movie.
- ``per_roi``   : the pipeline's approach — project the F_anat (anatomy at the
                  estimated z per frame) onto each ROI footprint, Huber-fit
                  ``F ≈ b·Fz`` and subtract (mirrors ``run_roi_zcorr``).
- ``per_pixel`` : a-priori — regress each pixel's trace on F_anat and subtract,
                  then read ROI traces (the "never worked well" baseline).
- ``per_patch`` : a-priori — same, but one scale per spatial patch.

F_anat here is the *estimated* anatomy movie: the movie's z-stack registered to
the FOV, sampled at the per-frame z-position from ``compute_zcorrel`` (so stage-2
estimation error is included, which is exactly why per-pixel/per-patch struggle).

Metric
------
Mean Pearson r between each method's corrected ROI trace and ``trueC`` across
cells (higher = better activity recovery), plus the residual correlation with the
z-trajectory (lower = less z-contamination left).

Usage
-----
    cd validation && pixi run python ../tests/benchmarks/benchmark_correction_methods.py \
        --real-zstack /path/to/ZSeries-... --downsample 3 --save-results results/
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.registration import phase_cross_correlation
from skimage.transform import AffineTransform, warp
from sklearn.linear_model import HuberRegressor

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.benchmarks.synthetic_zstack import (
    make_rigid_z_trajectory,
    make_xy_trajectory,
    save_caiman_memmap,
    save_zstack_tiff,
)
from tests.benchmarks.synthetic_activity import (
    detect_somata,
    make_calcium_traces,
    make_active_functional_movie,
)


def _register_zstack_to_fov(zstack, fov):
    """Rigidly register every z-plane to the FOV (mirrors compute_zcorrel)."""
    best_shift = None
    best_corr = -np.inf
    for z in range(zstack.shape[0]):
        shift, _, _ = phase_cross_correlation(zstack[z], fov, upsample_factor=10)
        tform = AffineTransform(translation=(shift[1], shift[0]))
        warped = warp(zstack[z].astype(np.float32), tform)
        c = np.corrcoef(fov.ravel(), gaussian_filter(warped, 1).ravel())[0, 1]
        if c > best_corr:
            best_corr, best_shift = c, shift
    tform = AffineTransform(translation=(best_shift[1], best_shift[0]))
    reg = np.stack([warp(zstack[z].astype(np.float32), tform) for z in range(zstack.shape[0])])
    return reg


def _estimate_f_anat(volume, movie, zpos):
    """Estimated anatomy movie: registered z-stack sampled at the per-frame z."""
    fov = movie.mean(axis=0)
    # compute_zcorrel flips the stack along y; match that convention.
    reg = _register_zstack_to_fov(np.flip(volume, axis=1), fov)
    zpos = np.clip(zpos.astype(int), 0, reg.shape[0] - 1)
    return reg[zpos]  # (T, H, W)


def _roi_trace(movie, cy, cx, r=3):
    y0, y1 = max(0, cy - r), cy + r + 1
    x0, x1 = max(0, cx - r), cx + r + 1
    return movie[:, y0:y1, x0:x1].mean(axis=(1, 2))


def _huber_subtract(trace, predictor):
    p0 = predictor.mean()
    hub = HuberRegressor(fit_intercept=False)
    hub.fit((predictor - p0).reshape(-1, 1), trace - trace.mean())
    return trace - hub.coef_[0] * (predictor - p0)


def _correct_per_pixel(movie, f_anat):
    """Regress each pixel trace on F_anat and subtract (vectorised OLS)."""
    T, H, W = movie.shape
    M = movie.reshape(T, -1)
    A = f_anat.reshape(T, -1)
    A0 = A - A.mean(0, keepdims=True)
    M0 = M - M.mean(0, keepdims=True)
    denom = (A0 * A0).sum(0)
    denom[denom == 0] = 1.0
    b = (A0 * M0).sum(0) / denom  # per-pixel scale
    corrected = M - b[None, :] * A0
    return corrected.reshape(T, H, W)


def _correct_per_patch(movie, f_anat, n_patches=8):
    T, H, W = movie.shape
    out = movie.copy()
    ys = np.linspace(0, H, n_patches + 1).astype(int)
    xs = np.linspace(0, W, n_patches + 1).astype(int)
    for i in range(n_patches):
        for j in range(n_patches):
            m = movie[:, ys[i] : ys[i + 1], xs[j] : xs[j + 1]].mean(axis=(1, 2))
            a = f_anat[:, ys[i] : ys[i + 1], xs[j] : xs[j + 1]].mean(axis=(1, 2))
            a0 = a - a.mean()
            denom = (a0 * a0).sum() or 1.0
            b = ((a0) * (m - m.mean())).sum() / denom
            out[:, ys[i] : ys[i + 1], xs[j] : xs[j + 1]] -= (b * a0)[:, None, None]
    return out


def _recovery(traces_by_cell, trueC, z_true):
    rs, zres = [], []
    for i in range(len(trueC)):
        t = traces_by_cell[i]
        if np.std(t) < 1e-9:
            continue
        rs.append(np.corrcoef(t, trueC[i])[0, 1])
        zres.append(abs(np.corrcoef(t, z_true)[0, 1]))
    return {"recovery_r": float(np.nanmean(rs)), "residual_z_r": float(np.nanmean(zres))}


def run_correction_benchmark(
    volume,
    n_frames=200,
    amplitude_planes=3.0,
    temporal_smoothness=8,
    xy_amplitude=1.0,
    deform_amp=0.5,
    n_cells=40,
    z_band=4,
    firerate=1.0,
    activity_gain=1500.0,
    seed=1,
    tmp_dir=None,
    return_traces=False,
):
    from modules.compute_zcorr import compute_zcorrel

    own_tmp = tmp_dir is None
    tmp_dir = Path(tempfile.mkdtemp()) if own_tmp else Path(tmp_dir)
    try:
        volume = np.asarray(volume, dtype=np.float32)
        z_nominal = (volume.shape[0] - 1) / 2.0
        centers = detect_somata(
            volume, n_cells=n_cells, min_distance=5, margin=8, z_center=z_nominal, z_band=z_band
        )
        trueC, _ = make_calcium_traces(
            len(centers), n_frames, framerate=20, decay_time=0.15, firerate=firerate, seed=seed
        )
        z_offsets = make_rigid_z_trajectory(
            n_frames, amplitude_planes, temporal_smoothness, seed=seed
        )
        xy = (
            make_xy_trajectory(n_frames, xy_amplitude, temporal_smoothness, seed=seed)
            if xy_amplitude > 0
            else None
        )
        movie, gt = make_active_functional_movie(
            volume,
            z_nominal,
            z_offsets,
            centers,
            trueC,
            xy_offsets=xy,
            deform_amp=deform_amp,
            activity_gain=activity_gain,
            seed=seed,
        )
        z_true = gt["z_true"]

        # Stage 1-2: estimate z-position (pipeline) and F_anat (registered stack at zpos).
        zstack_path = tmp_dir / "zstack.tif"
        save_zstack_tiff(volume, zstack_path)
        data_dir = tmp_dir / "batch" / "item_0"
        data_dir.mkdir(parents=True, exist_ok=True)
        memmap_path = save_caiman_memmap(movie, data_dir)
        zc = compute_zcorrel(zstack_path, memmap_path, smooth_sigma=3, export_path=tmp_dir)
        zpos = zc["zpos"]
        f_anat = _estimate_f_anat(volume, movie, zpos)

        # Precompute corrected movies for the a-priori methods.
        movie_pix = _correct_per_pixel(movie, f_anat)
        movie_patch = _correct_per_patch(movie, f_anat)

        results = {}
        # none
        traces = {i: _roi_trace(movie, cy, cx) for i, (z, cy, cx) in enumerate(centers)}
        results["none"] = _recovery(traces, trueC, z_true)
        # per_roi (Huber subtract of the F_anat footprint projection)
        traces_roi = {}
        for i, (z, cy, cx) in enumerate(centers):
            t = _roi_trace(movie, cy, cx)
            fz = _roi_trace(f_anat, cy, cx)
            traces_roi[i] = _huber_subtract(t, fz)
        results["per_roi"] = _recovery(traces_roi, trueC, z_true)
        # per_pixel
        traces_pix = {i: _roi_trace(movie_pix, cy, cx) for i, (z, cy, cx) in enumerate(centers)}
        results["per_pixel"] = _recovery(traces_pix, trueC, z_true)
        # per_patch
        traces_patch = {i: _roi_trace(movie_patch, cy, cx) for i, (z, cy, cx) in enumerate(centers)}
        results["per_patch"] = _recovery(traces_patch, trueC, z_true)

        results["_meta"] = {
            "n_cells": int(len(centers)),
            "n_frames": n_frames,
            "amplitude_planes": amplitude_planes,
            "xy_amplitude_px": xy_amplitude,
            "deform_amp_px": deform_amp,
        }
        if return_traces:
            # ΔF/F traces for an example figure: true activity + none + per-ROI.
            def _dff(x):
                m = x.mean()
                return x / (m if m else 1.0) - 1.0

            true_dff = np.stack(
                [trueC[i] / (trueC[i].mean() + 1e-9) - 1.0 for i in range(len(centers))]
            )
            results["_traces"] = {
                "true_dff": true_dff,
                "none": np.stack([_dff(traces[i]) for i in range(len(centers))]),
                "per_roi": np.stack([_dff(traces_roi[i]) for i in range(len(centers))]),
                "z_true": z_true,
                "z_cell": centers[:, 0].astype(float),
            }
        return results
    finally:
        if own_tmp:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(
        description="Benchmark z-motion correction methods vs synthetic ground truth"
    )
    p.add_argument("--real-zstack", type=Path, default=None)
    p.add_argument("--downsample", type=int, default=1)
    p.add_argument("--channel", type=int, default=2)
    p.add_argument("--n-frames", type=int, default=200)
    p.add_argument("--amplitude-planes", type=float, default=3.0)
    p.add_argument("--save-results", type=Path, default=None)
    args = p.parse_args()

    if args.real_zstack is not None:
        from tests.benchmarks.bruker_io import load_bruker_zstack

        volume, _ = load_bruker_zstack(
            args.real_zstack, channel=args.channel, downsample=args.downsample
        )
        print(f"Loaded real z-stack {volume.shape}")
    else:
        from tests.benchmarks.synthetic_zstack import make_3d_volume

        volume, _ = make_3d_volume(25, 256, 256, n_cells=80)
        print("Using synthetic Gaussian volume")

    res = run_correction_benchmark(
        volume, n_frames=args.n_frames, amplitude_planes=args.amplitude_planes
    )
    print(
        f"\n{res['_meta']['n_cells']} cells, {res['_meta']['n_frames']} frames, "
        f"z-amp {res['_meta']['amplitude_planes']} planes\n"
    )
    print(f"{'method':<12} {'recovery_r':>11} {'residual_z_r':>13}")
    print("─" * 40)
    for method in ("none", "per_roi", "per_pixel", "per_patch"):
        m = res[method]
        print(f"{method:<12} {m['recovery_r']:>11.3f} {m['residual_z_r']:>13.3f}")

    if args.save_results:
        args.save_results.mkdir(parents=True, exist_ok=True)
        (args.save_results / "correction_method_comparison.json").write_text(
            json.dumps(res, indent=2)
        )
        print(f"\nSaved to {args.save_results}/correction_method_comparison.json")


if __name__ == "__main__":
    main()
