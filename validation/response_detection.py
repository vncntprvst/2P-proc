"""Count significantly excited / suppressed ROIs per z-correction variant (real data).

Per ROI and trial: mean dff in a window minus the pre-stim mean; Wilcoxon signed-rank
across trials of one stimulus, Bonferroni over ROIs. Windows: the z-jump window (where the
spurious band sits) and a later response window. Same ROI set for all variants.

Usage
-----
    python validation/response_detection.py <export_dir> [--rules npz key ...] [--stim 4]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

sys.path.insert(0, str(Path(__file__).resolve().parent))
from real_zcorr_benchmark import fit_model, load_inputs  # noqa: E402
from stim_response_analysis import DEFAULT_PARAMS  # noqa: E402


def count(c, vt, nf, stim, win, base, alpha=0.01):
    x = c.reshape(len(c), -1, nf)[:, vt == stim]
    d = x[..., win].mean(-1) - x[..., base].mean(-1)  # (roi, trial)
    p = np.array([wilcoxon(r).pvalue if np.any(r) else 1 for r in d])
    sig = p < alpha / len(c)
    return int((sig & (d.mean(1) > 0)).sum()), int((sig & (d.mean(1) < 0)).sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("--soft", type=Path, default=None, help="f_cell_anat_soft_sweep.npz")
    ap.add_argument("--soft-key", default="soft_b200_w8_g1")
    ap.add_argument("--stim", type=int, default=4)
    ap.add_argument("--params", type=Path, default=None)
    args = ap.parse_args()
    p = dict(DEFAULT_PARAMS)
    if args.params:
        p.update(json.loads(args.params.read_text()))
    fz = dict(np.load(args.export_dir / "stim_resp" / "F_cell_anat_variants.npz"))
    fz = {"uni": fz["uniform"]}
    if args.soft:
        fz["soft"] = np.load(args.soft)[args.soft_key]
    d = load_inputs(args.export_dir, p, fz)
    nf, vt, fr = d["nf"], d["vec_trial"], d["fr"]
    sec = lambda a, b: slice(round(a * fr), round(b * fr))  # noqa: E731
    base = sec(p["stim_delay"] - 0.5, p["stim_delay"])
    wins = {"z-jump window 1.35-1.6 s": sec(1.35, 1.6), "late 2-3 s": sec(2, 3)}
    variants = [("none", None, None), ("rigid zpos", "zpos", "poly2"),
                ("MATLAB (uni_mm3:ols)", "uni_mm3", "ols"), ("uni_raw:ols", "uni_raw", "ols")]
    if args.soft:
        variants.append((f"soft ({args.soft_key}):ols", "soft_raw", "ols"))
    out = {}
    print(f"{len(d['dff'])} ROIs; counts = (excited, suppressed), p<0.01 Bonferroni")
    for name, reg, fit in variants:
        c = d["dff"] - fit_model(fit, d["dff"], d["regs"].get(reg), d["zpos"], vt, nf)
        out[name] = {w: count(c, vt, nf, args.stim, s, base) for w, s in wins.items()}
        print(f"{name:36s}", "   ".join(f"{w}: {v}" for w, v in out[name].items()))
    (args.export_dir / "benchmark" / "response_detection.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
