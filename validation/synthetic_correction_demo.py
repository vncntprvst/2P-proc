"""Demonstrate & quantify per-ROI z-motion correction on synthetic ground truth.

On real data the correction's benefit is hard to see (no ground truth). Here we
inject known calcium activity into a real z-stack, impose z-motion, then apply the
pipeline's per-ROI fit-and-subtract (the MATLAB method: ΔF/F, project the
anatomical movie onto each ROI, OLS-regress and subtract). Because we know the
true activity, we can pick the cells **most impacted by z-motion** and quantify
how much the correction recovers.

Outputs (into --out):
  roi_zcorr_synthetic.png    top z-impacted cells: true / before / corrected + z
  roi_zcorr_synthetic_summary.png   recovery r before vs after, all cells
  roi_zcorr_synthetic.json   per-cell + aggregate recovery stats

The anatomical predictor here is the *oracle* F_anat (the no-activity baseline
movie under the same motion), so this isolates the correction method's ceiling;
z-position/F_anat estimation error (benchmarked elsewhere) would add to it.

Run: python validation/synthetic_correction_demo.py --real-zstack <ZSeries> --out DIR
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.benchmarks.bruker_io import load_bruker_zstack
from tests.benchmarks.synthetic_zstack import (
    make_rigid_z_trajectory,
    make_xy_trajectory,
    make_functional_movie,
)
from tests.benchmarks.synthetic_activity import (
    detect_somata,
    make_calcium_traces,
    make_active_functional_movie,
)


def _dff(x):
    x0 = x.mean(axis=-1, keepdims=True)
    x0 = np.where(x0 == 0, 1.0, x0)
    return x / x0 - 1.0


def _roi_trace(movie, cy, cx, r=3):
    return movie[:, max(0, cy - r) : cy + r + 1, max(0, cx - r) : cx + r + 1].mean(axis=(1, 2))


def _corr(a, b):
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--real-zstack", type=Path, required=True)
    p.add_argument("--downsample", type=int, default=2)
    p.add_argument("--n-frames", type=int, default=400)
    p.add_argument("--amplitude-planes", type=float, default=4.0)
    p.add_argument("--n-cells", type=int, default=60)
    p.add_argument("--z-band", type=int, default=6)
    p.add_argument("--n-show", type=int, default=6)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vol, _ = load_bruker_zstack(args.real_zstack, channel=2, downsample=args.downsample)
    znom = (vol.shape[0] - 1) / 2.0
    T = args.n_frames

    # Cells spanning a band around the focal plane so some sit off-focus and are
    # strongly modulated by z-motion (the interesting cases).
    centers = detect_somata(
        vol, n_cells=args.n_cells, min_distance=5, margin=8, z_center=znom, z_band=args.z_band
    )
    trueC, _ = make_calcium_traces(
        len(centers), T, framerate=20, decay_time=0.15, firerate=1.0, seed=args.seed
    )
    zoff = make_rigid_z_trajectory(T, args.amplitude_planes, 8, seed=args.seed)
    xy = make_xy_trajectory(T, 1.0, 8, seed=args.seed)
    movie, gt = make_active_functional_movie(
        vol,
        znom,
        zoff,
        centers,
        trueC,
        xy_offsets=xy,
        deform_amp=0.5,
        activity_gain=1500,
        seed=args.seed,
    )
    # Oracle anatomical predictor: same motion, NO activity, no noise.
    baseline, _ = make_functional_movie(
        vol, znom, zoff, xy_offsets=xy, deform_amp=0.5, noise_factor=0.0, seed=args.seed
    )

    n = len(centers)
    r_before = np.full(n, np.nan)
    r_after = np.full(n, np.nan)
    zc_before = np.full(n, np.nan)
    zc_after = np.full(n, np.nan)
    dff_before = np.zeros((n, T), np.float32)
    dff_after = np.zeros((n, T), np.float32)
    true_dff = _dff(trueC.astype(np.float32))
    zpos = gt["z_true"]

    for i, (zc, cy, cx) in enumerate(centers):
        F = _roi_trace(movie, cy, cx)
        Fanat = _roi_trace(baseline, cy, cx)
        db = _dff(F)
        dz = _dff(Fanat)
        # OLS slope of db on dz (MATLAB reference), subtract.
        dz0 = dz - dz.mean()
        den = np.sum(dz0**2)
        slope = np.sum((db - db.mean()) * dz0) / den if den > 0 else 0.0
        dc = db - slope * dz0
        dff_before[i], dff_after[i] = db, dc
        r_before[i] = _corr(db, true_dff[i])
        r_after[i] = _corr(dc, true_dff[i])
        zc_before[i] = abs(_corr(db, zpos))
        zc_after[i] = abs(_corr(dc, zpos))

    # z-impact = how contaminated the raw trace is by the z-trajectory.
    order = np.argsort(np.nan_to_num(zc_before))[::-1]
    sel = order[: args.n_show]

    # ── Figure 1: top z-impacted cells ───────────────────────────────────────
    def _z(x):  # z-score for display (traces live on very different scales)
        return (x - x.mean()) / (x.std() + 1e-9)

    fig, axes = plt.subplots(len(sel), 1, figsize=(11, 1.9 * len(sel)), sharex=True)
    if len(sel) == 1:
        axes = [axes]
    for ax, i in zip(axes, sel):
        ax.plot(_z(true_dff[i]), color="k", lw=1.0, alpha=0.9, label="true activity")
        ax.plot(_z(dff_before[i]), color="0.6", lw=0.8, label="before (z-contaminated)")
        ax.plot(_z(dff_after[i]), color="C0", lw=0.9, label="z-corrected")
        ax.set_ylabel(f"cell {i}\nr:{r_before[i]:.2f}→{r_after[i]:.2f}", fontsize=7)
        ax.set_yticks([])
        axz = ax.twinx()
        axz.plot(zpos, color="C3", lw=0.6, alpha=0.5)
        axz.set_ylabel("z", color="C3", fontsize=7)
        axz.tick_params(axis="y", labelsize=6, colors="C3")
    axes[0].legend(loc="upper right", fontsize=7, ncol=3)
    axes[-1].set_xlabel("frame")
    fig.suptitle(
        f"Per-ROI z-correction on synthetic ground truth — "
        f"top {len(sel)} z-impacted cells (z-drift {args.amplitude_planes:.0f} planes)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(args.out / "roi_zcorr_synthetic.png", dpi=130)
    plt.close(fig)

    # ── Figure 2: recovery summary ───────────────────────────────────────────
    valid = np.isfinite(r_before) & np.isfinite(r_after)
    fig, ax = plt.subplots(1, 2, figsize=(9, 4))
    ax[0].scatter(r_before[valid], r_after[valid], s=18, c=zc_before[valid], cmap="viridis")
    lim = [min(np.nanmin(r_before), 0), 1]
    ax[0].plot(lim, lim, "k--", lw=0.8)
    ax[0].set_xlabel("r(before, true)")
    ax[0].set_ylabel("r(corrected, true)")
    ax[0].set_title("Activity recovery (color = z-contamination)")
    cb = fig.colorbar(ax[0].collections[0], ax=ax[0])
    cb.set_label("|corr(before, z)|", fontsize=8)
    # residual z-contamination before vs after
    ax[1].scatter(zc_before[valid], zc_after[valid], s=18, color="C0")
    ax[1].plot([0, 1], [0, 1], "k--", lw=0.8)
    ax[1].set_xlabel("|corr(before, z)|")
    ax[1].set_ylabel("|corr(corrected, z)|")
    ax[1].set_title("Residual z-contamination")
    fig.suptitle("z-correction: recovery and residual contamination (all cells)", fontsize=11)
    fig.tight_layout()
    fig.savefig(args.out / "roi_zcorr_synthetic_summary.png", dpi=130)
    plt.close(fig)

    # ── Stats ────────────────────────────────────────────────────────────────
    top = order[: max(10, args.n_show)]
    stats = {
        "n_cells": int(n),
        "z_drift_planes": args.amplitude_planes,
        "all_cells": {
            "r_before_mean": float(np.nanmean(r_before)),
            "r_after_mean": float(np.nanmean(r_after)),
            "resid_z_before_mean": float(np.nanmean(zc_before)),
            "resid_z_after_mean": float(np.nanmean(zc_after)),
        },
        "top_z_impacted": {
            "n": int(len(top)),
            "r_before_mean": float(np.nanmean(r_before[top])),
            "r_after_mean": float(np.nanmean(r_after[top])),
            "resid_z_before_mean": float(np.nanmean(zc_before[top])),
            "resid_z_after_mean": float(np.nanmean(zc_after[top])),
        },
    }
    (args.out / "roi_zcorr_synthetic.json").write_text(json.dumps(stats, indent=2))
    a, t = stats["all_cells"], stats["top_z_impacted"]
    print(f"{n} cells, z-drift {args.amplitude_planes:.0f} planes")
    print(
        f"ALL cells   : recovery r {a['r_before_mean']:.3f} -> {a['r_after_mean']:.3f}  "
        f"| resid-z {a['resid_z_before_mean']:.3f} -> {a['resid_z_after_mean']:.3f}"
    )
    print(
        f"TOP z-impacted ({t['n']}): recovery r {t['r_before_mean']:.3f} -> {t['r_after_mean']:.3f}  "
        f"| resid-z {t['resid_z_before_mean']:.3f} -> {t['resid_z_after_mean']:.3f}"
    )


if __name__ == "__main__":
    main()
