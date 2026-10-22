"""Figures for the run-boundary report (validation/boundary_benchmark.py results).

fig_boundary_zpos.png    z-position over concatenated runs, pipeline (Pearson) vs Suite2p-style
fig_boundary_steps.png   fluorescence step at each run boundary vs the step depth explains
fig_boundary_fit.png     held-out z-dependence left by the per-ROI fit: one baseline vs per run
fig_zpos_methods.png     z-position estimators: held-out fluorescence explained vs the pipeline
fig_phasecorr_bug.png    Suite2p-style correlation profiles before / after the worker fix

Usage: python validation/make_boundary_figures.py --out DIR
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
RES = HERE / "results" / "boundary"
DATA = Path("/home/wanglab/data/2P/Analysis_2P")
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, GREEN, AMBER, ORANGE, VIOLET = "#2a78d6", "#1baf7a", "#eda100", "#eb6834", "#6250d6"

DATASETS = [  # label, export (under DATA), results stem, what changes between runs
    ("D1M2 08/29, runs 1–2", "Scnn1aAi14_D1M2/08292026/run1run2", "D1M2_08292026_run1run2",
     ["same settings, 44 min gap"]),
    ("D1M2 08/21, runs 1–2", "Scnn1aAi14_D1M2/08212026/run1run2", "D1M2_08212026_run1run2",
     ["laser setting +4%, 46 min gap"]),
    ("B2M0 04/22, runs 1–2", "Scnn1aAi14_B2M0/04222024/run1run2", "B2M0_04222024_run1run2",
     ["raw Ch2 −21% (cause unknown), 10 min gap"]),
    ("C57_O1M2 10/19, runs 3–5", "C57_O1M2/10192023/run3run4run5", "C57_O1M2_10192023_run3run4run5",
     ["laser setting +8%, 8 min gap", "same settings, 8 min gap"]),
    ("2P11 07/11, runs 3–5", "Scnn1aAi14_2P11/07112024/run3run4run5", "2P11_07112024_run3run4run5",
     ["stage +0.6 µm, 11 min gap", "stage refocus +9.2 µm, 12 min gap"]),
]


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def available():
    out = []
    for lab, exp, stem, notes in DATASETS:
        f = RES / f"{stem}.json"
        if f.exists():
            out.append((lab, DATA / exp, json.loads(f.read_text()), stem, notes))
    return out


def fig_zpos(ds, out):
    fig, axes = plt.subplots(len(ds), 1, figsize=(10, 1.7 * len(ds)), squeeze=False)
    for ax, (lab, exp, R, _, notes) in zip(axes[:, 0], ds):
        zp = np.load(exp / "z_correlation.npz")["zpos"].astype(float)
        zs = np.load(exp / "zpos_suite2p" / "z_correlation_suite2p.npz")["zpos"].astype(float)
        t = np.arange(len(zp)) / 20 / 60
        ax.plot(t, zs, color=ORANGE, lw=0.4, alpha=0.7, label="Suite2p-style (phase correlation)")
        ax.plot(t, zp, color=BLUE, lw=0.6, label="pipeline (Pearson, 5-frame median)")
        for i, b in enumerate(np.cumsum(R["runs"])[:-1]):
            ax.axvline(b / 20 / 60, color=INK, lw=1, ls="--")
            ax.text(b / 20 / 60, 1.02, " " + notes[i], transform=ax.get_xaxis_transform(),
                    fontsize=7, color=MUTED, va="bottom")
        ax.set_ylabel("z-plane", fontsize=8, color=MUTED)
        ax.set_title(lab, fontsize=9, color=INK, loc="left", pad=12)
        ax.invert_yaxis()
        _style(ax)
    axes[-1, 0].set_xlabel("time in the concatenated recording (min, 20 Hz)", fontsize=8, color=MUTED)
    axes[0, 0].legend(fontsize=7, frameon=False, loc="lower right", ncol=2)
    fig.tight_layout()
    fig.savefig(out / "fig_boundary_zpos.png", dpi=150)
    plt.close(fig)


def fig_steps(ds, out):
    rows = []
    for lab, _, R, _, notes in ds:
        st = R["F_step"]
        for i, v in enumerate(st["abs_median_per_boundary"]):
            rows.append((f"{lab.split(',')[0]} · boundary {i + 1}: {notes[i]}", v,
                         st["F_anat_pearson_abs_median"][i], st["made_up_p95_of_boundary_medians"],
                         st["corr_F_vs_F_anat_pearson"][i]))
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(rows) + 1.2))
    y = np.arange(len(rows))[::-1]
    for yi, (lab, meas, pred, fake, r) in zip(y, rows):
        ax.plot([0, fake * 100], [yi, yi], color=GRID, lw=7, solid_capstyle="butt")
        ax.plot(pred * 100, yi, "o", color=GREEN, ms=7, mec="white", mew=1.5)
        ax.plot(meas * 100, yi, "o", color=INK, ms=7, mec="white", mew=1.5)
        ax.text(max(meas, pred) * 100 + 0.8, yi, f"r = {r:.2f}", fontsize=7, color=MUTED, va="center")
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=8, color=INK)
    ax.set_xlabel("median |change in F| across the boundary, % (400 frames each side)", fontsize=8, color=MUTED)
    ax.plot([], [], "o", color=INK, label="measured step")
    ax.plot([], [], "o", color=GREEN, label="step predicted from depth (F_anat)")
    ax.plot([], [], color=GRID, lw=7, label="95th percentile at made-up boundaries inside runs")
    fig.legend(*ax.get_legend_handles_labels(), fontsize=7.5, frameon=False, loc="lower center", ncol=3)
    _style(ax)
    ax.grid(axis="y", visible=False)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(out / "fig_boundary_steps.png", dpi=150)
    plt.close(fig)


def fig_fit(ds, out):
    fig, axes = plt.subplots(1, 2, figsize=(10, 0.5 * len(ds) + 1.6), sharey=True)
    variants = [("no_correction_r2", "no correction", MUTED), ("one_baseline", "one baseline (before)", ORANGE),
                ("per_run", "per-run baselines (now)", BLUE)]
    for ax, mode in zip(axes, ("argmax", "soft200")):
        y = np.arange(len(ds))[::-1]
        for yi, (lab, _, R, stem, _) in zip(y, ds):
            f = RES / f"{stem}_soft200.json" if mode == "soft200" else None
            RR = json.loads(f.read_text()) if f and f.exists() else (R if mode == "argmax" else None)
            if RR is None:
                continue
            for k, vlab, col in variants:
                v = RR["fit"][k]["median"] if k == "no_correction_r2" else RR["fit"][k]["heldout_resid_r2"]["median"]
                ax.plot(v * 100, yi, "o", color=col, ms=7, mec="white", mew=1.5, label=vlab if yi == y[0] else None)
        ax.set_xscale("log")
        ax.set_yticks(y)
        ax.set_yticklabels([d[0] for d in ds], fontsize=8, color=INK)
        ax.set_title("argmax depth" if mode == "argmax" else "soft depth (β = 200)", fontsize=9, color=INK, loc="left")
        ax.set_xlabel("within-run variance of ΔF/F explained by depth, % (held out; median cell)", fontsize=7.5, color=MUTED)
        _style(ax)
    fig.legend(*axes[0].get_legend_handles_labels(), fontsize=7.5, frameon=False, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(out / "fig_boundary_fit.png", dpi=150)
    plt.close(fig)


def fig_methods(ds, out):
    est = [("pearson_raw", "Pearson, no median filter", BLUE), ("suite2p", "Suite2p-style", ORANGE),
           ("suite2p_med5", "Suite2p-style + 5-frame median", VIOLET)]
    fig, axes = plt.subplots(1, 2, figsize=(10, 0.5 * len(ds) + 1.6), sharey=True)
    for ax, mode in zip(axes, ("argmax", "soft200")):
        y = np.arange(len(ds))[::-1]
        ax.axvline(0, color=INK, lw=1)
        for yi, (lab, _, R, stem, _) in zip(y, ds):
            f = RES / (f"{stem}_soft200.json" if mode == "soft200" else f"{stem}.json")
            if not f.exists():
                continue
            zf = json.loads(f.read_text())["zpos_fit"]
            for j, (k, elab, col) in enumerate(est):
                if k not in zf:
                    continue
                g, p = zf[k]["vs_pearson_median_gain_top25"] * 100, zf[k]["vs_pearson_wilcoxon_p"]
                ax.plot(g, yi + (j - 1) * 0.18, "o", ms=6, color=col, mfc=col if p < 0.01 else "white", mew=1.5,
                        label=elab if yi == y[0] else None)
        ax.set_yticks(y)
        ax.set_yticklabels([d[0] for d in ds], fontsize=8, color=INK)
        ax.set_title("argmax depth" if mode == "argmax" else "soft depth (β = 200)", fontsize=9, color=INK, loc="left")
        ax.set_xlabel("gain in % variance explained", fontsize=8, color=MUTED)
        _style(ax)
    fig.legend(*axes[0].get_legend_handles_labels(), fontsize=7.5, frameon=False, loc="lower center", ncol=3,
               title="held-out ΔF/F variance explained by depth vs the pipeline z-position (median of the 25% most "
                     "depth-affected cells); filled: p < 0.01, paired Wilcoxon", title_fontsize=7.5)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(out / "fig_zpos_methods.png", dpi=150)
    plt.close(fig)


def fig_bug(out):
    d = DATA / "C57_O1M2/10022023/run1run2/test_optimouse"
    a = np.load(d / "zpos_suite2p" / "z_correlation_suite2p_before_fix.npz")
    b = np.load(d / "zpos_suite2p" / "z_correlation_suite2p.npz")
    zp = np.load(d / "z_correlation.npz")["zpos"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.2))
    ax = axes[0]
    for z, col, lab in [(a, ORANGE, "before fix"), (b, BLUE, "after fix")]:
        m = z["zcorr"].mean(1)
        ax.plot(np.arange(len(m)), m, color=col, lw=2, label=lab)
    ax.set_xlabel("z-plane", fontsize=8, color=MUTED)
    ax.set_ylabel("phase-correlation peak (mean over frames)", fontsize=8, color=MUTED)
    ax.legend(fontsize=7, frameon=False)
    _style(ax)
    ax = axes[1]
    bins = np.arange(-0.5, 41.5)
    ax.hist(a["zpos"], bins, color=ORANGE, alpha=0.6, label="Suite2p-style, before fix")
    ax.hist(b["zpos"], bins, color=BLUE, alpha=0.6, label="Suite2p-style, after fix")
    ax.hist(zp, bins, histtype="step", color=INK, lw=1.5, label="pipeline (Pearson)")
    ax.set_xlabel("estimated z-plane", fontsize=8, color=MUTED)
    ax.set_ylabel("frames", fontsize=8, color=MUTED)
    ax.legend(fontsize=7, frameon=False)
    _style(ax)
    fig.suptitle("C57_O1M2 10/02 runs 1–2 (C-order memmap)", fontsize=9, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out / "fig_phasecorr_bug.png", dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "report" / "boundary")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    ds = available()
    fig_zpos(ds, args.out)
    fig_steps(ds, args.out)
    fig_fit(ds, args.out)
    fig_methods(ds, args.out)
    fig_bug(args.out)
    print("datasets:", [d[0] for d in ds])


if __name__ == "__main__":
    main()
