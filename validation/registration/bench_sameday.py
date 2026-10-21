"""Same-day registration benchmark against a joint-processing reference.

Runs recorded the same day are processed separately (their own motion-correction frame and
segmentation) and jointly (concatenated). Each run's ROIs are mapped to the joint ROIs after a
rigid shift between mean images (phase correlation); a run-A ROI and a run-B ROI that map to
the same joint ROI (mutual best IoU >= 0.5) form a reference pair. ROIs with best IoU in
[0.2, 0.5) are uncertain and not scored. Methods then match the runs in their own frames.

Usage: python validation/registration/bench_sameday.py --runs <plane dir> <plane dir> ... \
           --joint <plane dir> --out results.json [--methods ...]
"""

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
from skimage.registration import phase_cross_correlation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_splithalf import METHODS  # noqa: E402
from regbench import gt_by_iou, load_suite2p_session, score_pairs  # noqa: E402


def shift_session(s, dy, dx):
    Ly, Lx = s["dims"]
    masks = []
    for yy, xx, w in s["masks"]:
        y, x = yy + dy, xx + dx
        ok = (y >= 0) & (y < Ly) & (x >= 0) & (x < Lx)
        masks.append((y[ok], x[ok], w[ok]))
    return {**s, "masks": masks}


def map_to_joint(run, joint):
    """Run ROI -> joint ROI (or -1 / -2 for uncertain), after a rigid shift onto the joint frame."""
    shift, err, _ = phase_cross_correlation(joint["mean"], run["mean"], upsample_factor=1)
    dy, dx = int(round(shift[0])), int(round(shift[1]))
    pairs, unc_run, _ = gt_by_iou(shift_session(run, dy, dx), joint)
    m = np.full(len(run["masks"]), -1)
    for i, k in pairs:
        m[i] = k
    m[list(unc_run)] = -2
    return m, (dy, dx)


def reference_pairs(mA, mB):
    jointB = {k: j for j, k in enumerate(mB) if k >= 0}
    pairs = {(i, jointB[k]) for i, k in enumerate(mA) if k >= 0 and k in jointB}
    uncA = set(np.flatnonzero(mA == -2))
    uncB = set(np.flatnonzero(mB == -2))
    return pairs, uncA, uncB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--joint", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--methods", nargs="+", default=list(METHODS))
    args = ap.parse_args()
    runs = [load_suite2p_session(r) for r in args.runs]
    joint = load_suite2p_session(args.joint, use_iscell=False)
    maps = [map_to_joint(r, joint) for r in runs]
    res = json.loads(args.out.read_text()) if args.out.exists() else {}
    res["_meta"] = {"runs": args.runs, "joint": args.joint, "n_rois": [len(r["masks"]) for r in runs],
                    "shift_to_joint_px": [list(m[1]) for m in maps],
                    "mapped_to_joint": [int((m[0] >= 0).sum()) for m in maps]}
    print(res["_meta"], flush=True)
    for a, b in itertools.combinations(range(len(runs)), 2):
        key = f"run{a + 1}-run{b + 1}"
        gt = reference_pairs(maps[a][0], maps[b][0])
        res.setdefault(key, {})["n_reference_pairs"] = len(gt[0])
        for m in args.methods:
            if isinstance(res[key].get(m), dict) and "f1" in res[key][m]:
                continue
            t = time.time()
            try:
                r = score_pairs(METHODS[m](runs[a], runs[b]), gt)
            except Exception as e:
                r = {"error": str(e)[-500:]}
            r["time_s"] = round(time.time() - t, 1)
            res[key][m] = r
            print(key, m, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)
            args.out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
