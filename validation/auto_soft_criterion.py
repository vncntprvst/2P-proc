"""Prototype of a trial-free criterion for choosing soft vs argmax depth in F_anat.

At F_anat time the pipeline has neither trials nor ROIs. For each patch p, the functional
patch-mean y_p(t) is compared with the patch-mean F_anat predicted by a depth rule,
x_p(t) = sum_z q[t, p, z] * mean(Zstack[z, patch p]). At z-events (frames where zpos changes),
the fluorescence step of y is regressed on the step of x; slopes are fitted on one half of
the recording (alternating blocks) and tested on the other. A rule wins if it predicts the
held-out z-event steps better, paired across patches.

Compared with the ROI-level benchmark (real_zcorr_benchmark.py) on the sessions processed so far.

Usage
-----
    python validation/auto_soft_criterion.py <export_dir> [<export_dir> ...]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fanat_variants import load_zstack, select_production, soft_rule  # noqa: E402


def patch_means(mmap, lims, chunk=500):
    from caiman.mmapping import load_memmap

    Yr, dims, T = load_memmap(str(mmap))
    y = np.zeros((T, len(lims)), np.float64)
    for s in range(0, T, chunk):
        e = min(s + chunk, T)
        mov = np.clip(np.reshape(Yr[:, s:e].T, [e - s] + list(dims), order="F"), 0, 2**16 - 1)
        for k, (y0, y1, x0, x1) in enumerate(lims):
            y[s:e, k] = mov[:, y0:y1, x0:x1].mean((1, 2))
    return y


def event_steps(x, zpos, w=2, min_dz=1):
    """Steps mean(t..t+w) - mean(t-w..t-1) at frames where zpos changes by >= min_dz."""
    dz = np.abs(np.diff(zpos))
    ev = np.flatnonzero(dz >= min_dz) + 1
    ev = ev[(ev >= w) & (ev + w <= len(zpos))]
    st = np.stack([x[e : e + w].mean(0) - x[e - w : e].mean(0) for e in ev])
    return st, ev


def heldout_score(y_st, x_st, fold):
    """Per-patch held-out R^2 of y steps predicted by x steps (slope through 0, 2-fold)."""
    sse = np.zeros(y_st.shape[1])
    sst = np.zeros(y_st.shape[1])
    for f in (0, 1):
        tr, te = fold != f, fold == f
        b = (x_st[tr] * y_st[tr]).sum(0) / ((x_st[tr] ** 2).sum(0) + 1e-12)
        sse += ((y_st[te] - b * x_st[te]) ** 2).sum(0)
        sst += (y_st[te] ** 2).sum(0)
    return 1 - sse / sst


def evaluate(exp, block=400):
    d = np.load(exp / "fanat_variants" / "fanat_profiles.npz")
    r, zpos, lims = d["r"], d["zpos"].astype(int), d["lims"]
    import json

    cfg = json.loads((exp / "run_mcorr_arguments.json").read_text())
    zdir = Path(cfg.get("parameters", cfg).get("zstack_path", ""))
    Z = load_zstack(zdir / "zstack_shifted.tif")
    zm = np.stack([Z[:, y0:y1, x0:x1].mean((1, 2)) for y0, y1, x0, x1 in lims], 1)  # (Nz, P)
    mmap = next(exp.glob("*/*.mmap"))
    y = patch_means(mmap, lims)
    rules = {"argmax": None, "soft400": 400, "soft200": 200, "soft100": 100}
    xs = {}
    for name, beta in rules.items():
        if beta is None:
            z = select_production(r, zpos)
            xs[name] = zm[z, np.arange(len(lims))[None]]
        else:
            q = soft_rule(r, zpos, beta, 8, 1)
            xs[name] = np.einsum("tpz,zp->tp", q, zm)
    y_st, ev = event_steps(y, zpos)
    fold = (ev // block) % 2
    scores = {n: heldout_score(y_st, event_steps(x, zpos)[0], fold) for n, x in xs.items()}
    out = {"n_events": int(len(ev))}
    for n in rules:
        out[n] = float(np.median(scores[n]))
    for n in ("soft400", "soft200", "soft100"):
        diff = scores[n] - scores["argmax"]
        out[f"{n}-argmax"] = float(np.median(diff))
        out[f"p_{n}"] = float(wilcoxon(diff, alternative="greater").pvalue)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exports", type=Path, nargs="+")
    args = ap.parse_args()
    for exp in args.exports:
        o = evaluate(exp)
        print(exp.relative_to(exp.parents[2]), " ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}"
                                                       for k, v in o.items()))


if __name__ == "__main__":
    main()
