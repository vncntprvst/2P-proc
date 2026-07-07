"""Visualise per-ROI z-motion correction on a real export, for manual judgement.

Loads a pipeline export directory (after run_roi_zcorr) and plots, for the ROIs
most affected by z-motion, the raw vs. z-corrected fluorescence trace with the
estimated z-position overlaid. Also writes a single loadable ``roi_zcorr_viz.npz``
bundling raw/corrected traces, the z-scaling per ROI, and zpos.

Usage
-----
    python validation/plot_roi_zcorr.py <export_dir> [--n-rois 6] [--out DIR]
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("export_dir", type=Path)
    p.add_argument("--n-rois", type=int, default=6)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    export = args.export_dir
    out = args.out or export
    out.mkdir(parents=True, exist_ok=True)

    zpos = np.load(export / "z_correlation.npz")["zpos"].astype(float)
    d = np.load(export / "F_roi_zcorrected.npz")
    corrected = d["F_roi_zcorrected"]
    baseline = d["F_roi_zbaseline"]  # the subtracted z-motion component (b*(Fz-Fz0))
    scaling = d["roi_z_scaling"]
    raw = corrected + baseline  # run_roi_zcorr computed corrected = raw - baseline

    # Rank ROIs by how strongly z-motion loaded onto them (|scaling| * baseline swing).
    z_load = np.abs(scaling) * baseline.std(axis=1)
    order = np.argsort(z_load)[::-1]
    sel = order[: args.n_rois]

    fig, axes = plt.subplots(len(sel), 1, figsize=(11, 1.8 * len(sel)), sharex=True)
    if len(sel) == 1:
        axes = [axes]
    for ax, i in zip(axes, sel):
        ax.plot(raw[i], color="0.6", lw=0.8, label="raw")
        ax.plot(corrected[i], color="C0", lw=0.9, label="z-corrected")
        ax.set_ylabel(f"ROI {i}", fontsize=8)
        axz = ax.twinx()
        axz.plot(zpos, color="C3", lw=0.6, alpha=0.6)
        axz.set_ylabel("z", color="C3", fontsize=7)
        axz.tick_params(axis="y", labelsize=6, colors="C3")
    axes[0].legend(loc="upper right", fontsize=7)
    axes[-1].set_xlabel("frame")
    fig.suptitle(
        f"Per-ROI z-motion correction — {export.name} " f"(top {len(sel)} z-loaded ROIs)",
        fontsize=10,
    )
    fig.tight_layout()
    fig_path = out / "roi_zcorr_traces.png"
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)

    np.savez(
        out / "roi_zcorr_viz.npz",
        raw=raw,
        corrected=corrected,
        baseline=baseline,
        roi_z_scaling=scaling,
        zpos=zpos,
    )
    print(f"Wrote {fig_path}")
    print(f"Wrote {out / 'roi_zcorr_viz.npz'}  (raw/corrected/baseline/scaling/zpos)")
    print(
        f"ROIs: {corrected.shape[0]}, frames: {corrected.shape[1]}, "
        f"median |z-scaling|: {np.median(np.abs(scaling)):.3f}"
    )


if __name__ == "__main__":
    main()
