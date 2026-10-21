"""Figures for the cell-registration benchmark report.

fig_splithalf.png    F1 / recall vs known non-rigid deformation (split-half, D1M2 run1)
fig_crossday.png     cross-day: matches, cycle consistency, negative controls per method
fig_fingerprint.png  response similarity of matched vs neighbour vs random pairs

Usage: python validation/registration/make_registration_figures.py --out DIR
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
METHODS = [  # key, label, colour
    ("caiman", "CaImAn (current)", "#2a78d6"),
    ("track2p_affine", "Track2p affine", "#1baf7a"),
    ("track2p_nonrigid", "Track2p non-rigid", "#eda100"),
    ("roicat", "ROICaT", "#eb6834"),
    ("cellreg_rigid", "CellReg rigid", "#6250d6"),
    ("cellreg_nonrigid", "CellReg non-rigid", "#e87ba4"),
]


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def fig_splithalf(out):
    d = json.loads((HERE / "results_splithalf_D1M2run1.json").read_text())
    keys = [k for k in d if k.startswith("amp") and "rot1.5" in k]
    amps = [float(k.split("_")[0][3:]) for k in keys]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, metric in zip(axes, ("f1", "recall")):
        for m, lab, col in METHODS:
            y = [d[k].get(m, {}).get(metric, np.nan) for k in keys]
            ax.plot(amps, y, "-o", color=col, lw=2, ms=5, label=lab)
            for a, v in zip(amps, y):
                if np.isnan(v):
                    ax.plot(a, 0.62, "x", color=col, ms=7, mew=2)
        ax.set_xlabel("non-rigid deformation, RMS (µm); plus 1.5° rotation and 13 µm shift", fontsize=8, color=MUTED)
        ax.set_ylabel(metric.upper() if metric == "f1" else "recall", fontsize=9, color=MUTED)
        ax.set_ylim(0.2, 1.02)
        ax.set_xlim(-0.5, 10.5)
        _style(ax)
    axes[0].legend(fontsize=7.5, frameon=False, loc="lower left")
    axes[1].text(10.4, 0.62, "x = alignment\nrejected", fontsize=7, color=MUTED, va="center")
    fig.suptitle(f"Split-half: Suite2p run separately on two halves of D1M2 run1, "
                 f"{d[keys[0]]['caiman']['n_true']} reference pairs", fontsize=9.5, color=INK)
    fig.tight_layout()
    fig.savefig(out / "fig_splithalf.png", dpi=150)
    plt.close(fig)


def fig_crossday(out):
    d = json.loads((HERE / "results_crossday_D1M2.json").read_text())
    neg = json.loads((HERE / "results_negative_D1M2.json").read_text())
    panels = [
        ("matches, 2 days (08/29–08/31)", lambda m: d["d0829:d0831"].get(m, {}).get("n_matches")),
        ("matches, 5 days (08/24–08/29)", lambda m: d["d0824:d0829"].get(m, {}).get("n_matches")),
        ("cycle consistency 08/24→29→31", lambda m: d["cycle d0824:d0829:d0831"].get(m, {}).get("consistency")
         if d["cycle d0824:d0829:d0831"].get(m, {}).get("n_chains", 0) >= 10 else None),
        ("false matches, footprints shifted 60 µm*", lambda m: neg.get(m, {}).get("n_false_matches")),
        ("matches to a different plane (08/28)", lambda m: d["d0829:d0828"].get(m, {}).get("n_matches")),
    ]
    fig, axes = plt.subplots(1, len(panels), figsize=(15, 3.8), sharey=True)
    y = np.arange(len(METHODS))
    for ax, (title, f) in zip(axes, panels):
        vals = [f(m) for m, _, _ in METHODS]
        ax.barh(y, [0 if v is None else v for v in vals], color=[c for _, _, c in METHODS], height=0.6)
        for yi, v in zip(y, vals):
            txt = " fails / n.a." if v is None else (f" {v:.2f}" if isinstance(v, float) and v <= 1 else f" {v}")
            ax.text(0 if v is None else v, yi, txt, va="center", fontsize=8, color=MUTED if v is None else INK)
        ax.set_title(title, fontsize=8.5, color=INK)
        _style(ax)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([lab for _, lab, _ in METHODS], fontsize=8.5, color=INK)
    axes[0].invert_yaxis()
    fig.suptitle("Cross-day, D1M2 (Suite2p iscell ROIs: 1200 / 860 / 510 on 08/24, 08/29, 08/31). "
                 "*not a valid control for CellReg, which aligns on footprints only", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(out / "fig_crossday.png", dpi=150)
    plt.close(fig)


def fig_fingerprint(out):
    d = json.loads((HERE / "results_fingerprint_D1M2.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), sharey=True)
    for ax, (pair, title) in zip(axes, [("d0829:d0831", "2 days, 52.5 mJ responses"),
                                         ("d0824:d0829", "5 days, five laser energies")]):
        y = np.arange(len(METHODS))
        for k, (m, lab, col) in enumerate(METHODS):
            r = d.get(f"{pair} {m}")
            if not r or "r_match" not in r:
                ax.text(0.03, k, "fails", fontsize=7.5, color=MUTED, va="center", transform=ax.get_yaxis_transform())
                continue
            ax.plot([r["r_random"], r["r_neighbour"]], [k, k], color=GRID, lw=6, solid_capstyle="round")
            ax.scatter([r["r_random"]], [k], s=40, color="#b0afab", zorder=3)
            ax.scatter([r["r_neighbour"]], [k], s=40, facecolor="white", edgecolor=col, lw=1.5, zorder=3)
            ax.scatter([r["r_match"]], [k], s=60, color=col, zorder=4)
            ax.annotate(f"{r['r_match']:.2f} (n={r['n']})", (r["r_match"], k), xytext=(8, 0),
                        textcoords="offset points", fontsize=7.5, color=INK, va="center")
        ax.set_yticks(y)
        ax.set_yticklabels([lab for _, lab, _ in METHODS], fontsize=8.5, color=INK)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=9, color=INK)
        ax.set_xlabel("median correlation of trial-averaged responses", fontsize=8, color=MUTED)
        ax.set_xlim(right=ax.get_xlim()[1] + 0.45 * np.ptp(ax.get_xlim()))
        _style(ax)
    fig.suptitle("Matched pairs (filled) vs nearest non-matched neighbour (open) vs random pair (grey)",
                 fontsize=9.5, color=INK)
    fig.tight_layout()
    fig.savefig(out / "fig_fingerprint.png", dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE.parent / "report" / "registration")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fig_splithalf(args.out)
    fig_crossday(args.out)
    fig_fingerprint(args.out)


if __name__ == "__main__":
    main()
