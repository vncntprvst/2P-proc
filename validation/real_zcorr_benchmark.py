"""Benchmark per-ROI z-motion correction on a real trial-structured recording.

Starts from the MATLAB-equivalent dff (``stim_response_analysis.compute_dff``) and z-model
regressors derived from F_anat (F_cell_anat normalised by its pre-stim mean per block),
and compares ways of building / fitting the z-model. All variants are evaluated on the same
ROI set (ROIs kept without z-correction), so the R2 > 0.25 rejection does not bias them.

Regressors (``--regressors``)
-----------------------------
uni_mm3   MATLAB reference: uniform ROI pixel mean of F_anat, 3-frame movmean
uni_raw   uniform pixel mean, no temporal smoothing
lam_mm3   Suite2p lam-weighted pixel mean, 3-frame movmean
lam_raw   lam-weighted, no smoothing
zpos      global z-position only (MATLAB 'rigid' path, fitted as poly2)

Fits
----
ols       per-ROI OLS slope over all frames (MATLAB)
huber     robust (Huber) slope
resid     slope fitted after removing the per-stimulus trial average (trial-to-trial
          fluctuations only, so stimulus-locked responses are not absorbed)
lag       multiple regression on the regressor at t-1, t, t+1 (timing mismatch)
quad      regression on dffz and dffz^2 (non-linear defocus)

Metrics
-------
zlock_corr      across-ROI corr between the trial-averaged residual and the trial-averaged
                (unscaled) dffz in the stimulus-locked z-jump window       (0 is best)
trial_zdep      held-out: fit on even trials; on odd trials, per-ROI corr across trials of the
                dff step at the z-jump frame vs the dffz step (per-stim means removed),
                mean over the 25% most z-loaded ROIs                       (0 is best, <0 = over)
spont_jump      |dff| step at spontaneous >= 2-plane zpos jumps outside the stim window
fast_drop       physiologically impossible drops of the trial average (faster than GCaMP decay)
inject_indep    GROUND TRUTH: fraction kept of synthetic GCaMP responses added at the z-jump
                with trial-variable amplitude independent of z                (1 is best)
inject_coupled  same, amplitude proportional to the trial's z-step (worst case)  (1 is best)

Usage
-----
    python validation/real_zcorr_benchmark.py <export_dir> --out DIR
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
from stim_response_analysis import (  # noqa: E402
    DEFAULT_PARAMS,
    bad_neurons,
    compute_dff,
    load_extraction,
    movmean3,
    trial_vector,
)

VARIANTS = [
    ("none", None),
    ("zpos", "poly2"),
    ("uni_mm3", "ols"),
    ("uni_mm3", "huber"),
    ("uni_mm3", "resid"),
    ("uni_mm3", "lag"),
    ("uni_mm3", "quad"),
    ("uni_raw", "ols"),
    ("uni_raw", "lag"),
    ("lam_mm3", "ols"),
    ("lam_raw", "ols"),
    ("lam_raw", "lag"),
]


def _centre(x):
    return x - x.mean(-1, keepdims=True)


def _remove_stim_mean(x, vec_trial, nf):
    x3 = x.reshape(len(x), -1, nf).copy()
    for s in np.unique(vec_trial):
        m = vec_trial == s
        x3[:, m] -= x3[:, m].mean(1, keepdims=True)
    return x3.reshape(len(x), -1)


def _lagged(x, nf):
    """Stack x(t-1), x(t), x(t+1) within trials (edge frames repeated)."""
    x3 = x.reshape(len(x), -1, nf)
    prev = np.concatenate([x3[..., :1], x3[..., :-1]], -1)
    nxt = np.concatenate([x3[..., 1:], x3[..., -1:]], -1)
    return np.stack([prev, x3, nxt], 1).reshape(len(x), 3, -1)


def _huber_slope(y, x, eps=1.35, n_iter=20):
    xc, yc = _centre(x), _centre(y)
    b = (xc * yc).sum(1) / (xc**2).sum(1)
    for _ in range(n_iter):
        r = yc - b[:, None] * xc
        s = np.median(np.abs(r), 1, keepdims=True) / 0.6745 + 1e-12
        w = np.minimum(1, eps * s / np.maximum(np.abs(r), 1e-12))
        b = (w * xc * yc).sum(1) / (w * xc**2).sum(1)
    return b


def _multi_ols(y, X):
    """Per-ROI OLS of centred y on centred regressors X (n, k, T); returns coefs (n, k)."""
    Xc, yc = _centre(X), _centre(y)
    G = np.einsum("nkt,nlt->nkl", Xc, Xc)
    h = np.einsum("nkt,nt->nk", Xc, yc)
    return np.linalg.solve(G + 1e-12 * np.eye(X.shape[1]), h[..., None])[..., 0]


def fit_model(fit, dff, reg, zpos, vec_trial, nf, train=None):
    """Return the z-model (n_roi, T) for one fit; coefficients estimated on ``train`` frames."""
    tr = np.ones(dff.shape[1], bool) if train is None else train
    if fit is None:
        return np.zeros_like(dff)
    if fit == "poly2":
        z = zpos.astype(float)
        A = np.stack([np.ones_like(z), z, z**2], 1)
        coef, *_ = np.linalg.lstsq(A[tr], dff[:, tr].T, rcond=None)
        return (A @ coef).T
    if fit == "ols":
        X = reg[:, None]
    elif fit == "lag":
        X = _lagged(reg, nf)
    elif fit == "quad":
        X = np.stack([reg, reg**2], 1)
    elif fit == "huber":
        b = _huber_slope(dff[:, tr], reg[:, tr])
        return reg * b[:, None]
    elif fit == "resid":
        vt = vec_trial[tr.reshape(-1, nf)[:, 0]]
        b = _multi_ols(
            _remove_stim_mean(dff[:, tr], vt, nf), _remove_stim_mean(reg[:, tr], vt, nf)[:, None]
        )
        return reg * b
    else:
        raise ValueError(fit)
    coef = _multi_ols(dff[:, tr], X[..., tr])
    return np.einsum("nk,nkt->nt", coef, X)


def trial_avg(x, nf, trials=None):
    x3 = x.reshape(len(x), -1, nf)
    return (x3 if trials is None else x3[:, trials]).mean(1)


def step(x, nf, j):
    """Per-trial step at frame j: mean(j..j+2) - mean(j-3..j-1); returns (n_roi, n_trial)."""
    x3 = x.reshape(len(x), -1, nf)
    return x3[..., j : j + 3].mean(-1) - x3[..., j - 3 : j].mean(-1)


def fast_drop(avg, fr, tau):
    k = np.exp(-1 / (fr * tau))
    allowed = np.where(avg[:, :-1] > 0, avg[:, :-1] * k, avg[:, :-1])
    noise = np.median(np.abs(np.diff(avg, axis=1)), 1, keepdims=True) / 0.6745
    return np.clip(allowed - avg[:, 1:] - 2 * noise, 0, None).sum(1)


def gcamp_kernel(n, fr, tau_rise=0.02, tau_decay=0.3):
    t = np.arange(n) / fr
    k = np.exp(-t / tau_decay) - np.exp(-t / tau_rise)
    return k / k.max()


def load_inputs(exp, p, fz_variants):
    F, Fneu, _ = load_extraction(exp)
    zpos = np.load(exp / "z_correlation.npz")["zpos"].astype(float)
    fr = p["fr"]
    nf = round(fr * p["trial_duration"])
    vec_trial = trial_vector(p)
    blocks = [np.sum(vec_trial == s) for s in range(1, vec_trial.max() + 1)]
    dff, F0, baseline = compute_dff(F, Fneu, p, blocks)
    lim = np.r_[0, np.cumsum(blocks) * nf]

    def to_dffz(Fz):
        out = np.zeros_like(Fz)
        for a, b in zip(lim[:-1], lim[1:]):
            blk = Fz[:, a:b]
            out[:, a:b] = blk / blk[:, baseline[a:b]].mean(1, keepdims=True) - 1
        return out

    regs = {}
    for name, Fz in fz_variants.items():
        regs[f"{name}_raw"] = to_dffz(Fz)
        regs[f"{name}_mm3"] = to_dffz(movmean3(Fz))
    bad, _ = bad_neurons(dff, F0, np.zeros(len(dff)), baseline, p)
    keep = ~bad & np.all([np.isfinite(r).all(1) & (r.std(1) > 0) for r in regs.values()], 0)
    regs = {k: v[keep] for k, v in regs.items()}
    return dict(dff=dff[keep], regs=regs, zpos=zpos, vec_trial=vec_trial, nf=nf, fr=fr,
                baseline=baseline, keep=keep)


def evaluate(d, variants, seed=0, stim=4):
    dff, regs, zpos, vt, nf, fr = d["dff"], d["regs"], d["zpos"], d["vec_trial"], d["nf"], d["fr"]
    n_roi, n_trial = len(dff), len(vt)
    nf_delay = round(fr * DEFAULT_PARAMS["stim_delay"])
    ref = regs["uni_mm3"]

    zt = zpos.reshape(-1, nf)
    zt = zt - zt[:, :nf_delay].mean(1, keepdims=True)
    zavg = zt.mean(0)
    jump = int(np.argmax(np.diff(zavg[nf_delay - 1 :])) + nf_delay)
    win = slice(jump - 1, jump + 3)
    dz = np.abs(np.diff(zt, axis=1))
    spont = [(i, j + 1) for i, j in zip(*np.nonzero(dz >= 2))
             if (j + 1 < nf_delay - 1 or j + 1 > nf_delay + round(2 * fr)) and 3 <= j + 1 < nf - 3]

    # injections (ground truth): GCaMP response starting at the z-jump in 30% of ROIs
    rng = np.random.default_rng(seed)
    inj_rois = rng.random(n_roi) < 0.3
    amp = 3 * dff[:, d["baseline"][: dff.shape[1]]].std(1) * inj_rois
    kern = np.zeros(nf)
    kern[jump:] = gcamp_kernel(nf - jump, fr)
    zstep_trial = zt[:, jump : jump + 3].mean(1) - zt[:, jump - 3 : jump].mean(1)
    trial_gain = {
        "indep": rng.lognormal(0, 0.5, n_trial),
        "coupled": np.clip(zstep_trial, 0, None) / max(np.clip(zstep_trial, 0, None).mean(), 1e-9),
    }
    injected = {k: (amp[:, None, None] * g[None, :, None] * kern[None, None]).reshape(n_roi, -1)
                for k, g in trial_gain.items()}

    even = np.repeat(np.arange(n_trial) % 2 == 0, nf)
    odd_trials = np.arange(n_trial) % 2 == 1
    zload = np.abs(trial_avg(ref, nf)[:, win].mean(1) - trial_avg(ref, nf)[:, nf_delay - 4 : nf_delay].mean(1))
    top = zload >= np.quantile(zload, 0.75)

    results, corrected = {}, {}
    for reg_name, fit in variants:
        name = reg_name if fit is None else f"{reg_name}:{fit}"
        reg = regs.get(reg_name)
        model = fit_model(fit, dff, reg, zpos, vt, nf)
        c = dff - model
        corrected[name] = c
        r = {}
        avg = trial_avg(c, nf)
        a_res = avg[:, win].mean(1) - avg[:, nf_delay - 4 : nf_delay].mean(1)
        a_z = trial_avg(ref, nf)[:, win].mean(1) - trial_avg(ref, nf)[:, nf_delay - 4 : nf_delay].mean(1)
        r["zlock_corr"] = float(np.corrcoef(a_res, a_z)[0, 1])
        # held-out trial-wise z dependence
        m_tr = fit_model(fit, dff, reg, zpos, vt, nf, train=even)
        c_odd = (dff - m_tr).reshape(n_roi, -1, nf)[:, odd_trials].reshape(n_roi, -1)
        z_odd = ref.reshape(n_roi, -1, nf)[:, odd_trials].reshape(n_roi, -1)
        vt_odd = vt[odd_trials]
        s_c = step(_remove_stim_mean(c_odd, vt_odd, nf), nf, jump)
        s_z = step(_remove_stim_mean(z_odd, vt_odd, nf), nf, jump)
        cc = [np.corrcoef(a, b)[0, 1] for a, b in zip(s_c[top], s_z[top])]
        r["trial_zdep"] = float(np.nanmean(cc))
        x3 = c.reshape(n_roi, -1, nf)
        r["spont_jump"] = float(np.mean([np.abs(x3[:, i, j : j + 3].mean(1) - x3[:, i, j - 3 : j].mean(1)).mean()
                                         for i, j in spont])) if spont else float("nan")
        r["fast_drop"] = float(fast_drop(trial_avg(c, nf, vt == stim), fr, 0.3).mean())
        for k, inj in injected.items():
            ci = (dff + inj) - fit_model(fit, dff + inj, reg, zpos, vt, nf)
            gain = trial_avg(ci - c, nf)[inj_rois]
            truth = trial_avg(inj, nf)[inj_rois]
            r[f"inject_{k}"] = float((gain * truth).sum() / (truth**2).sum())
        results[name] = r
    meta = dict(n_roi=int(n_roi), jump_frame=jump, jump_time_s=(jump + 1) / fr, n_spont_jumps=len(spont),
                n_top_zloaded=int(top.sum()))
    return results, corrected, meta


def plot_heatmaps(d, corrected, names, out, stim=4, jump=28):
    dff, ref, nf, vt, fr = d["dff"], d["regs"]["uni_mm3"], d["nf"], d["vec_trial"], d["fr"]
    jump_win = slice(jump - 1, jump + 3)
    order = np.argsort(trial_avg(ref, nf)[:, jump_win].mean(1))
    t = np.arange(1, nf + 1) / fr
    vmax = np.quantile(np.abs(trial_avg(dff, nf, vt == stim)), 0.99)
    fig, axes = plt.subplots(1, len(names) + 1, figsize=(2.6 * (len(names) + 1), 5), sharey=True)
    for ax, n in zip(axes, names + ["dffz"]):
        x = ref if n == "dffz" else corrected[n]
        ax.imshow(trial_avg(x, nf, vt == stim)[order], aspect="auto", cmap="RdBu_r", vmin=-vmax,
                  vmax=vmax, extent=[t[0], t[-1], len(order), 0], interpolation="nearest")
        ax.axvline(1, color="k", ls="--", lw=0.6)
        ax.set_title("dffz (F_anat, unscaled)" if n == "dffz" else n, fontsize=8)
        ax.set_xlabel("time (s)")
    axes[0].set_ylabel("ROI (sorted by z-locked dffz)")
    fig.suptitle(f"stim {stim}, all trials, common ROI set (n={len(order)}); colour = ΔF/F", fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fz", type=Path, default=None, help="F_cell_anat_variants.npz")
    ap.add_argument("--rules", type=Path, default=None,
                    help="f_cell_anat_rules.npz (fanat_variants.py): benchmark each F_anat rule")
    ap.add_argument("--tag", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--params", type=Path, default=None, help="json overriding DEFAULT_PARAMS")
    ap.add_argument("--stim", type=int, default=4, help="stim ID for fast_drop and heatmaps")
    args = ap.parse_args()
    p = dict(DEFAULT_PARAMS)
    if args.params:
        p.update(json.loads(args.params.read_text()))
    args.out.mkdir(parents=True, exist_ok=True)
    fz = np.load(args.fz or args.export_dir / "stim_resp" / "F_cell_anat_variants.npz")
    fz = {"uni": fz["uniform"], "lam": fz["lam"]}
    variants = VARIANTS
    heat = ["none", "zpos:poly2", "uni_mm3:ols", "uni_raw:lag", "lam_raw:lag"]
    if args.rules:
        rules = dict(np.load(args.rules))
        fz.update(rules)
        variants = [("none", None), ("uni_mm3", "ols"), ("uni_raw", "ols")]
        variants += [(f"{k}_raw", f) for k in rules for f in ("ols", "lag")]
        heat = ["none", "uni_mm3:ols"] + [f"{k}_raw:ols" for k in list(rules)[:4]]
    d = load_inputs(args.export_dir, p, fz)
    results, corrected, meta = evaluate(d, variants, args.seed, args.stim)
    tag = f"_{args.tag}" if args.tag else ""
    (args.out / f"real_zcorr_benchmark{tag}.json").write_text(json.dumps(dict(meta=meta, results=results), indent=2))
    plot_heatmaps(d, corrected, heat, args.out / f"real_zcorr_methods_heatmaps{tag}.png", args.stim, meta["jump_frame"])
    print(json.dumps(meta))
    cols = list(next(iter(results.values())).keys())
    print(f"{'variant':16s}" + "".join(f"{c:>15s}" for c in cols))
    for n, r in results.items():
        print(f"{n:16s}" + "".join(f"{r[c]:15.3f}" for c in cols))


if __name__ == "__main__":
    main()
