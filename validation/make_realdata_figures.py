"""Figures for the real-data z-correction benchmark (report).

fig_reproduction.png   D1M2 run1 67.5 mJ: trial-averaged zpos, heatmaps (same ROI order) without
                       correction / MATLAB reference / soft-depth F_anat, and the F_anat prediction
fig_mechanism.png      per-ROI deflection in the z-jump window vs the F_anat-predicted deflection
fig_methods.png        per-ROI fitting methods across sessions (dots = sessions, bar = mean)
fig_fanat_rules.png    F_anat construction rules across sessions

Usage
-----
    python validation/make_realdata_figures.py --out DIR
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from real_zcorr_benchmark import fit_model, load_inputs, trial_avg  # noqa: E402
from stim_response_analysis import DEFAULT_PARAMS  # noqa: E402

A = Path("/home/wanglab/data/2P/Analysis_2P")
CFG = Path(__file__).resolve().parent / "configs"
SESSIONS = {  # label: (export dir, params json or None, stim)
    "D1M2 laser (S2P)": (A / "Scnn1aAi14_D1M2/08292026/run1", CFG / "params_D1M2_run1.json", 4),
    "D1M2 laser (CNMF)": (A / "Scnn1aAi14_D1M2/08292026/run1_cnmf", CFG / "params_D1M2_run1.json", 4),
    "D1M2 vF": (A / "Scnn1aAi14_D1M2/08292026/run2", CFG / "params_D1M2_run2.json", 1),
    "B1M0 laser": (A / "Scnn1aAi14_B1M0/04182024/run1", CFG / "params_B1M0_04182024.json", 5),
    "B2M0 laser": (A / "Scnn1aAi14_B2M0/04192024/run3", CFG / "params_B2M0_04192024.json", 5),
    "A2M0 laser": (A / "Scnn1aAi14_A2M0/12152023/run1", CFG / "params_A2M0_12152023.json", 5),
}
SOFT = "soft_b200_w8_g1"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C_NONE, C_MATLAB, C_SOFT = "#8a8985", "#2a78d6", "#eb6834"

METHODS = [  # label, (benchmark file tag, variant key)
    ("none", ("", "none")),
    ("rigid zpos (poly2)", ("", "zpos:poly2")),
    ("MATLAB: F_anat, movmean3, OLS", ("", "uni_mm3:ols")),
    ("F_anat, no movmean, OLS", ("", "uni_raw:ols")),
    ("F_anat, no movmean, lagged OLS", ("", "uni_raw:lag")),
    ("F_anat, robust (Huber)", ("", "uni_mm3:huber")),
    ("F_anat, fit on trial residuals", ("", "uni_mm3:resid")),
    ("soft-depth F_anat, OLS", ("soft", f"{SOFT}_raw:ols")),
]
RULES = [
    ("one depth for all patches (zpos)", "global_raw:ols"),
    ("fixed per-patch offset from zpos", "offset_raw:ols"),
    ("argmax depth, temporal median 3", "tmed3_raw:ols"),
    ("argmax depth, spatial median 3x3", "smed3_raw:ols"),
    ("argmax depth, no z-smoothing of R²", "nosmooth_raw:ols"),
    ("argmax depth (production)", "prod_raw:ols"),
    ("argmax depth, ±8 planes", "win8_raw:ols"),
    ("soft depth β=200, ±8, σ=1", f"{SOFT}_raw:ols"),
]
METRICS = [
    ("trial_zdep", "held-out trial-wise z-dependence\n(0 = none left)"),
    ("zlock_corr", "z-locked residual vs F_anat\n(across-ROI corr, 0 best)"),
    ("inject_coupled", "injected z-coupled signal kept\n(ground truth, 1 best)"),
]


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)


def load_results():
    res = {}
    for label, (exp, _, _) in SESSIONS.items():
        r = {}
        for tag in ("", "rules", "soft"):
            f = exp / "benchmark" / f"real_zcorr_benchmark{'_' + tag if tag else ''}.json"
            if f.exists():
                r[tag] = json.loads(f.read_text())["results"]
        if r:
            res[label] = r
    return res


def dot_panel(fig_path, res, rows, title):
    sessions = list(res)
    fig, axes = plt.subplots(1, len(METRICS), figsize=(4.2 * len(METRICS), 0.42 * len(rows) + 1.4),
                             sharey=True)
    for ax, (key, lab) in zip(axes, METRICS):
        for i, (_, (tag, var)) in enumerate(rows):
            vals = [res[s].get(tag, {}).get(var, {}).get(key) for s in sessions]
            vals = np.array([v for v in vals if v is not None], float)
            if not len(vals):
                continue
            ax.scatter(vals, np.full(len(vals), i) + np.linspace(-0.12, 0.12, len(vals)), s=14,
                       color="#b0afab", zorder=2, linewidths=0)
            ax.plot([vals.mean()] * 2, [i - 0.3, i + 0.3], color=INK, lw=2, zorder=3)
        ref = 1 if key.startswith("inject") else 0
        ax.axvline(ref, color=MUTED, lw=0.8, ls="--", zorder=1)
        ax.set_title(lab, fontsize=9, color=INK)
        ax.grid(axis="x", color=GRID, lw=0.6)
        _style(ax)
    axes[0].set_yticks(range(len(rows)))
    axes[0].set_yticklabels([r[0] for r in rows], fontsize=8.5, color=INK)
    axes[0].invert_yaxis()
    fig.suptitle(f"{title}  (grey dots = sessions: {', '.join(sessions)}; bar = mean)", fontsize=9,
                 color=MUTED)
    fig.tight_layout()
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)


def corrected_variants(label):
    exp, params, stim = SESSIONS[label]
    p = dict(DEFAULT_PARAMS)
    if params and params.exists():
        p.update(json.loads(params.read_text()))
    fz = np.load(exp / "stim_resp" / "F_cell_anat_variants.npz")
    fz = {"uni": fz["uniform"], "soft": np.load(exp / "fanat_variants" / "f_cell_anat_soft_sweep.npz")[SOFT]}
    d = load_inputs(exp, p, fz)
    out = {}
    for name, reg, fit in [("none", None, None), ("matlab", "uni_mm3", "ols"), ("soft", "soft_raw", "ols")]:
        out[name] = d["dff"] - fit_model(fit, d["dff"], d["regs"].get(reg), d["zpos"], d["vec_trial"], d["nf"])
    return d, out, stim, p


def fig_reproduction(out_dir, label="D1M2 laser (S2P)"):
    d, c, stim, p = corrected_variants(label)
    nf, fr, vt = d["nf"], d["fr"], d["vec_trial"]
    sel = vt == stim
    t = np.arange(1, nf + 1) / fr
    zt = d["zpos"].reshape(-1, nf)[sel]
    zt = zt - zt[:, : round(fr)].mean(1, keepdims=True)
    ref = trial_avg(d["regs"]["uni_raw"], nf, sel)
    jump = int(np.argmax(np.diff(zt.mean(0)[round(fr) - 1 :])) + round(fr))
    order = np.argsort(ref[:, jump - 1 : jump + 3].mean(1))
    vmax = np.quantile(np.abs(trial_avg(d["dff"], nf, sel)), 0.99)
    fig = plt.figure(figsize=(13, 6.2))
    gs = fig.add_gridspec(2, 4, height_ratios=[1, 4.2], hspace=0.08, wspace=0.08)
    for k, (name, title) in enumerate([("none", "no z-correction"), ("matlab", "MATLAB reference"),
                                       ("soft", "soft-depth F_anat (proposed)"), ("pred", "F_anat prediction (dffz)")]):
        ax = fig.add_subplot(gs[1, k])
        x = ref if name == "pred" else trial_avg(c[name], nf, sel)
        im = ax.imshow(x[order], aspect="auto", cmap="RdBu_r", vmin=-vmax, vmax=vmax,
                       extent=[t[0] - 0.5 / fr, t[-1] + 0.5 / fr, len(order), 0], interpolation="nearest")
        ax.axvline(p["stim_delay"], color=INK, ls="--", lw=0.7)
        ax.set_xlabel("time (s)", fontsize=8, color=MUTED)
        if k:
            ax.set_yticklabels([])
        else:
            ax.set_ylabel(f"ROIs (n={len(order)}), sorted by F_anat prediction", fontsize=8, color=MUTED)
        _style(ax)
        axz = fig.add_subplot(gs[0, k], sharex=ax)
        if k == 0:
            m, s = zt.mean(0), zt.std(0) / np.sqrt(len(zt))
            axz.fill_between(t, m - s, m + s, color="#b7d3f6", lw=0)
            axz.plot(t, m, color=C_MATLAB, lw=1.5)
            axz.set_ylabel("Δz (planes)", fontsize=8, color=MUTED)
            axz.axvline(p["stim_delay"], color=INK, ls="--", lw=0.7)
            _style(axz)
        else:
            axz.axis("off")
        axz.set_title(title, fontsize=9.5, color=INK)
        plt.setp(axz.get_xticklabels(), visible=False)
    cb = fig.colorbar(im, ax=fig.axes, fraction=0.015, pad=0.01)
    cb.set_label("ΔF/F (trial average)", fontsize=8, color=MUTED)
    cb.ax.tick_params(labelsize=7, colors=MUTED)
    fig.suptitle(f"{label}: 67.5 mJ, all {sel.sum()} trials. Top: stimulus-locked z-motion (mean ± SEM)",
                 fontsize=10, color=INK)
    fig.savefig(out_dir / "fig_reproduction.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_mechanism(out_dir, label="D1M2 laser (S2P)"):
    d, c, stim, p = corrected_variants(label)
    nf, fr, vt = d["nf"], d["fr"], d["vec_trial"]
    zavg = d["zpos"].reshape(-1, nf).mean(0)
    jump = int(np.argmax(np.diff(zavg[round(fr) - 1 :])) + round(fr))
    win, base = slice(jump - 1, jump + 3), slice(round(fr) - 4, round(fr))

    def defl(x):
        a = trial_avg(x, nf)
        return a[:, win].mean(1) - a[:, base].mean(1)

    xz = defl(d["regs"]["uni_raw"])
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharex=True, sharey=True)
    for ax, (name, title, col) in zip(axes, [("none", "no z-correction", C_NONE),
                                            ("matlab", "MATLAB reference", C_MATLAB),
                                            ("soft", "soft-depth F_anat", C_SOFT)]):
        y = defl(c[name])
        ax.scatter(xz, y, s=7, color=col, alpha=0.6, linewidths=0)
        r = np.corrcoef(xz, y)[0, 1]
        ax.axhline(0, color=MUTED, lw=0.6)
        ax.axvline(0, color=MUTED, lw=0.6)
        ax.set_title(f"{title}   r = {r:.2f}", fontsize=9.5, color=INK)
        ax.set_xlabel("F_anat-predicted deflection (dffz, unscaled)", fontsize=8, color=MUTED)
        ax.grid(color=GRID, lw=0.5)
        _style(ax)
    axes[0].set_ylabel("observed ΔF/F deflection at the z-jump", fontsize=8, color=MUTED)
    fig.suptitle(f"{label}, all trials: per-ROI deflection in the z-jump window ({(jump) / fr:.2f}-"
                 f"{(jump + 3) / fr:.2f} s) vs pre-stimulus", fontsize=9.5, color=INK)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_mechanism.png", dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    res = load_results()
    print("sessions with results:", list(res))
    dot_panel(args.out / "fig_methods.png", res, METHODS, "Per-ROI z-correction methods")
    dot_panel(args.out / "fig_fanat_rules.png", res, [(n, ("rules" if not v.startswith("soft_") else "soft", v)) for n, v in RULES],
              "F_anat construction (all fitted with OLS, no movmean)")
    fig_reproduction(args.out)
    fig_mechanism(args.out)
    summary = {s: {tag: {k: v for k, v in r.items()} for tag, r in rr.items()} for s, rr in res.items()}
    (args.out / "realdata_benchmark_summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
