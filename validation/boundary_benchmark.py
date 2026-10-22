"""Run boundaries of concatenated recordings: z-position estimators and per-ROI z-fit variants.

For one export (Suite2p F/stat/iscell, z_correlation.npz, patch_depth_profiles.npz and
stim_sequence.json), reports:

- z-position per run and at each run boundary, for the pipeline estimate (Pearson) and any
  alternative zpos given with --zpos (e.g. the Suite2p phase-correlation port);
- per-ROI fluorescence steps at run boundaries, against the step F_anat predicts from depth,
  and against the same statistic at made-up boundaries inside runs;
- held-out z-dependence left after the per-ROI fit (slope fitted on alternate 400-frame
  blocks, scored on the others) for: one baseline over all runs (previous pipeline), per-run
  baselines (current pipeline), per-run baselines with frames after each boundary excluded;
- for each zpos estimate (and the same with / without the pipeline's 5-frame median filter), the held-out fraction of ROI fluorescence explained by its F_anat,
  and cross-scores (residual after correcting with A, regressed on F_anat from B).

Usage
-----
    pixi run python validation/boundary_benchmark.py <export_dir> \
        [--zpos suite2p=path/z_correlation_suite2p.npz] [--out results.json]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, median_filter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import modules.compute_zcorr as cz  # noqa: E402
from modules.bruker_concat_tif import run_frame_counts  # noqa: E402

BLOCK = 400  # frames per cross-validation block
STEP_W = 400  # frames on each side of a boundary for step statistics


def find_s2p(export):
    for d in [export / "suite2p" / "plane0", export]:
        if (d / "F.npy").exists():
            return d
    raise FileNotFoundError(f"no Suite2p F.npy under {export}")


def dff_segments(x, segments):
    out = np.empty(x.shape, np.float64)
    for s, e in segments:
        x0 = x[:, s:e].mean(1, keepdims=True)
        x0[x0 == 0] = 1
        out[:, s:e] = x[:, s:e] / x0 - 1
    return out


def demean_segments(x, segments, mask=None):
    out = np.array(x, np.float64)
    for s, e in segments:
        m = slice(s, e) if mask is None else np.flatnonzero(mask[s:e]) + s
        out[:, m] -= out[:, m].mean(1, keepdims=True)
    return out


def slope(y, x):
    y = y - y.mean(1, keepdims=True)
    x = x - x.mean(1, keepdims=True)
    return (x * y).sum(1) / np.maximum((x * x).sum(1), 1e-12)


def r2_on(y, x, segments, mask):
    """Per-ROI R^2 of y regressed on x over mask frames, both demeaned within each run."""
    yd = demean_segments(y, segments, mask)[:, mask]
    xd = demean_segments(x, segments, mask)[:, mask]
    num = (xd * yd).sum(1) ** 2
    return num / np.maximum((xd * xd).sum(1) * (yd * yd).sum(1), 1e-12)


def heldout(F, Fa, segments, variant, exclude=0, score_against=None):
    """Mean over the two folds of the held-out residual R^2 with F_anat (per ROI)."""
    T = F.shape[1]
    run_seg = segments
    fit_seg = segments if variant != "one_baseline" else [(0, T)]
    y = dff_segments(F, fit_seg)
    x = dff_segments(Fa, fit_seg)
    xs = x if score_against is None else dff_segments(score_against, fit_seg)
    fold = (np.arange(T) // BLOCK) % 2
    keep = np.ones(T, bool)
    for s, _ in segments[1:]:
        keep[s : s + exclude] = False
    res, expl = [], []
    for f in (0, 1):
        tr, te = (fold != f) & keep, fold == f
        b = slope(y[:, tr], x[:, tr])
        resid = y - b[:, None] * x
        res.append(r2_on(resid, xs, run_seg, te))
        # fraction of (within-run) variance of y explained on held-out frames
        yd = demean_segments(y, run_seg, te)[:, te]
        rd = demean_segments(resid, run_seg, te)[:, te]
        expl.append(1 - (rd**2).sum(1) / np.maximum((yd**2).sum(1), 1e-12))
    return np.mean(res, 0), np.mean(expl, 0)


def boundary_steps(x, starts):
    """Relative change of the median over STEP_W frames after vs before each start (NaN if 0)."""
    out = []
    for b in starts:
        before = np.median(x[:, b - STEP_W : b], 1)
        after = np.median(x[:, b : b + STEP_W], 1)
        out.append(np.where(before > 0, after / np.where(before > 0, before, 1) - 1, np.nan))
    return np.stack(out, 1)


def summarise(v, top=None):
    out = {"median": float(np.median(v))}
    if top is not None:
        out["median_top25"] = float(np.median(v[top]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path)
    ap.add_argument("--zpos", action="append", default=[], help="name=path to an npz with zpos")
    ap.add_argument("--runs", type=int, nargs="+", default=None, help="frames per run")
    ap.add_argument("--exclude", type=int, default=200, help="frames excluded after boundaries")
    ap.add_argument("--depth-mode", default="argmax", help="argmax, or soft<beta> (e.g. soft200)")
    ap.add_argument("--zstack", default=None, help="shifted z-stack, if not at the path saved in the profiles")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    exp = args.export
    p = find_s2p(exp)
    F = np.load(p / "F.npy").astype(np.float64)
    stat = np.load(p / "stat.npy", allow_pickle=True)
    iscell = np.load(p / "iscell.npy")[:, 0] > 0
    T = F.shape[1]
    counts = args.runs or run_frame_counts(exp)
    assert counts and sum(counts) == T, (counts, T)
    starts = np.cumsum([0] + counts)
    segments = list(zip(starts[:-1], starts[1:]))
    bounds = list(starts[1:-1])

    zc = np.load(exp / "z_correlation.npz")
    zp = {"pearson": zc["zpos"].astype(int)}
    if "zcorr" in zc.files:  # the same estimate before its 5-frame temporal median filter
        zp["pearson_raw"] = np.argmax(gaussian_filter(zc["zcorr"], sigma=3, axes=0), axis=0)
    for spec in args.zpos:
        name, path = spec.split("=", 1)
        zp[name] = np.load(path)["zpos"].astype(int)
        assert len(zp[name]) == T
        zp[f"{name}_med5"] = median_filter(zp[name], size=5, mode="nearest")

    prof = np.load(exp / "patch_depth_profiles.npz")
    rois = [(s["ypix"].astype(int), s["xpix"].astype(int)) for s in stat]
    zstack = args.zstack or str(prof["zstack_path"])
    w = cz.roi_patch_weights(prof["lims"], cz.load_zplanes(zstack), rois)
    if args.depth_mode == "argmax":
        mode, beta, half = "argmax", 200.0, 5
    else:
        mode, beta, half = "soft", float(args.depth_mode[4:] or 200), 8
    Fa = {k: cz.roi_f_anat_traces(prof["r"], z, w, len(rois), mode, beta, half, 1.0) for k, z in zp.items()}

    ok = iscell & (F.mean(1) > 0)
    for v in Fa.values():
        ok &= v.mean(1) > 0
    F = F[ok]
    Fa = {k: v[ok] for k, v in Fa.items()}
    R = {"export": str(exp), "runs": counts, "n_rois": int(ok.sum()), "depth_mode": args.depth_mode}

    # z-position per run and at boundaries
    R["zpos"] = {}
    for k, z in zp.items():
        d = {"run_median": [float(np.median(z[s:e])) for s, e in segments],
             "run_p5_p95": [np.percentile(z[s:e], [5, 95]).tolist() for s, e in segments],
             "jumps_ge2_per_1000": [float(1000 * np.mean(np.abs(np.diff(z[s:e])) >= 2)) for s, e in segments],
             "boundary_jump": [float(np.median(z[b : b + 200]) - np.median(z[b - 200 : b])) for b in bounds],
             "frac_at_stack_edge": float(np.mean((z == 0) | (z == prof["r"].shape[2] - 1)))}
        R["zpos"][k] = d
    if len(zp) > 1:
        names = list(zp)
        R["zpos_agreement_r"] = {f"{a}-{b}": float(np.corrcoef(zp[a], zp[b])[0, 1])
                                 for i, a in enumerate(names) for b in names[i + 1 :]}

    # fluorescence steps at boundaries vs depth prediction and vs made-up boundaries
    if bounds:
        sF = boundary_steps(F, bounds)
        fake = [b for s, e in segments for b in range(s + STEP_W + BLOCK, e - STEP_W, 2 * BLOCK)]
        sfake = boundary_steps(F, fake) if fake else np.zeros((len(F), 1))
        R["F_step"] = {"abs_median_per_boundary": np.nanmedian(np.abs(sF), 0).tolist(),
                       "abs_median_made_up_boundaries": float(np.nanmedian(np.abs(sfake))),
                       "made_up_p95_of_boundary_medians":
                           float(np.percentile(np.nanmedian(np.abs(sfake), 0), 95))}
        for k, v in Fa.items():
            sA = boundary_steps(v, bounds)
            R["F_step"][f"F_anat_{k}_abs_median"] = np.nanmedian(np.abs(sA), 0).tolist()
            ok_ = np.isfinite(sF) & np.isfinite(sA)
            R["F_step"][f"corr_F_vs_F_anat_{k}"] = [
                float(np.corrcoef(sF[ok_[:, i], i], sA[ok_[:, i], i])[0, 1]) for i in range(len(bounds))]

    # fit variants (pipeline zpos)
    Fp = Fa["pearson"]
    _, expl0 = heldout(F, Fp, segments, "per_run")
    top = expl0 >= np.quantile(expl0, 0.75)
    R["fit"] = {}
    for name, var, ex in [("one_baseline", "one_baseline", 0), ("per_run", "per_run", 0),
                          (f"per_run_excl{args.exclude}", "per_run", args.exclude)]:
        res, expl = heldout(F, Fp, segments, var, ex)
        R["fit"][name] = {"heldout_resid_r2": summarise(res, top), "heldout_explained": summarise(expl, top)}
    R["fit"]["no_correction_r2"] = summarise(r2_on(dff_segments(F, segments), dff_segments(Fp, segments),
                                                   segments, np.ones(T, bool)), top)

    # zpos estimators: explained variance and cross-scores
    if len(zp) > 1:
        from scipy.stats import wilcoxon

        R["zpos_fit"] = {}
        expl_ref = None
        for a in Fa:
            res, expl = heldout(F, Fa[a], segments, "per_run")
            d = {"heldout_explained": summarise(expl, top), "heldout_resid_r2_self": summarise(res, top)}
            if expl_ref is None:
                expl_ref = expl
            else:  # paired, per ROI, against the pipeline estimate (top 25% z-loaded ROIs)
                diff = expl[top] - expl_ref[top]
                d["vs_pearson_median_gain_top25"] = float(np.median(diff))
                d["vs_pearson_wilcoxon_p"] = float(wilcoxon(diff).pvalue)
            for b in Fa:
                if b != a:
                    rb, _ = heldout(F, Fa[a], segments, "per_run", score_against=Fa[b])
                    d[f"resid_r2_vs_{b}"] = summarise(rb, top)
            R["zpos_fit"][a] = d
        # per run, so a failing run is visible
        R["zpos_fit_per_run"] = {}
        for i, (s, e) in enumerate(segments):
            seg1 = [(0, e - s)]
            R["zpos_fit_per_run"][f"run{i + 1}"] = {
                a: float(np.median(heldout(F[:, s:e], Fa[a][:, s:e], seg1, "per_run")[1][top])) for a in Fa}

    print(json.dumps(R, indent=1))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(R, open(args.out, "w"), indent=1)


if __name__ == "__main__":
    main()
