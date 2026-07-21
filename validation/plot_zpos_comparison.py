"""z-position method comparison figure: Pearson (shipped) vs Suite2p phase-corr.

Consolidates the z-pos evidence for the v1 report into one figure:

  A. Synthetic ground truth  — accuracy (Pearson r, RMSE in planes) of both
     methods against the known trajectory (from zpos_synthetic.json).
  B. Real single session      — both methods' estimated z over time on a real
     motion-corrected recording (zpos_single.npz).
  C. Real concatenated (mcorr) — both methods over 3 concatenated sessions with
     boundaries, on production NoRMCorre output (zpos_concat_mcorr.npz).

Message: Suite2p is more accurate on *synthetic* data, but on *real NoRMCorre*
output its phase correlation latches onto the deepest plane (mcorr edge
artifacts), while Pearson + temporal smoothing tracks a stable trajectory —
so the pipeline ships Pearson.

Run: python validation/plot_zpos_comparison.py --report-dir validation/report --out <png>
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _jumps(z, thr=2):
    return int(np.sum(np.abs(np.diff(np.asarray(z).astype(int))) >= thr))


def _plot_real(ax, npz_path, title):
    d = np.load(npz_path)
    zc, zs = d["zpos_caiman"], d["zpos_suite2p"]
    bnds = d["boundaries"] if "boundaries" in d else np.array([])
    ax.plot(zc, color="C0", lw=0.9, label=f"Pearson (shipped)  [{_jumps(zc)} ≥2-plane jumps]")
    ax.plot(
        zs,
        color="C3",
        lw=0.9,
        alpha=0.8,
        label=f"Suite2p phase-corr  [{_jumps(zs)} ≥2-plane jumps]",
    )
    for b in np.atleast_1d(bnds):
        ax.axvline(int(b), color="0.6", ls="--", lw=0.8)
    agree = np.corrcoef(zc, zs)[0, 1] if np.std(zc) > 0 and np.std(zs) > 0 else np.nan
    ax.set_title(f"{title}   (agreement r={agree:.2f})", fontsize=10)
    ax.set_xlabel("frame")
    ax.set_ylabel("estimated z-plane")
    ax.legend(loc="upper right", fontsize=8)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report-dir", type=Path, default=Path(__file__).parent / "report" / "figures")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    rd = args.report_dir
    out = args.out or (rd / "zpos_comparison.png")

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.0, 1.0, 1.0], hspace=0.42, wspace=0.28)

    # ── A. synthetic accuracy ────────────────────────────────────────────────
    axr = fig.add_subplot(gs[0, 0])
    axe = fig.add_subplot(gs[0, 1])
    syn = rd / "zpos_synthetic.json"
    if syn.exists():
        s = json.loads(syn.read_text())
        methods = ["Pearson", "Suite2p"]
        keys = ["caiman", "suite2p"]
        rmeans = [np.mean(s[k]["r"]) for k in keys]
        rsem = [np.std(s[k]["r"]) for k in keys]
        emeans = [np.mean(s[k]["rmse"]) for k in keys]
        esem = [np.std(s[k]["rmse"]) for k in keys]
        axr.bar(methods, rmeans, yerr=rsem, color=["C0", "C3"])
        axr.set_ylim(0, 1)
        axr.set_ylabel("Pearson r vs ground truth")
        axr.set_title("Synthetic accuracy: correlation (higher=better)", fontsize=10)
        for i, v in enumerate(rmeans):
            axr.text(i, v + 0.02, f"{v:.3f}", ha="center", fontsize=9)
        axe.bar(methods, emeans, yerr=esem, color=["C0", "C3"])
        axe.set_ylabel("RMSE (planes)")
        axe.set_title("Synthetic accuracy: error (lower=better)", fontsize=10)
        for i, v in enumerate(emeans):
            axe.text(i, v + 0.03, f"{v:.2f}", ha="center", fontsize=9)
        axe.text(
            0.5,
            0.9,
            "Suite2p wins on synthetic\nground truth",
            transform=axe.transAxes,
            ha="center",
            va="top",
            fontsize=9,
            color="0.3",
        )

    # ── B. real single session ───────────────────────────────────────────────
    axs = fig.add_subplot(gs[1, :])
    single = rd / "zpos_single.npz"
    if single.exists():
        _plot_real(axs, single, "Real single session (NoRMCorre-corrected)")

    # ── C. real concatenated (mcorr) ─────────────────────────────────────────
    axc = fig.add_subplot(gs[2, :])
    concat = rd / "zpos_concat_mcorr.npz"
    concat_fallback = rd / "zpos_concat.npz"
    use = concat if concat.exists() else (concat_fallback if concat_fallback.exists() else None)
    if use is not None:
        tag = (
            "3 sessions, real NoRMCorre"
            if use == concat
            else "concatenated (raw frames — mcorr pending)"
        )
        _plot_real(axc, use, f"Real concatenated: {tag}")

    fig.suptitle(
        "z-position estimation: Pearson (shipped) vs Suite2p phase-correlation",
        fontsize=13,
        y=0.97,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
