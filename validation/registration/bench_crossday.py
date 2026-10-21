"""Cross-day registration benchmark without ground truth.

For each session pair, every method's matches are recorded, and scored by:
  n_matches         matched pairs
  flip_matches      matches against a left-right flipped copy of session 2 (all false)
  residual_um       median centroid distance of matched pairs after a least-squares affine fit
                    of session-2 onto session-1 centroids (robust: refit on the best 80%)
  cycle             for a triplet A, B, C: fraction of A->B->C chains that agree with A->C
Pairs found by each method are saved for agreement and functional analyses.

Usage: python validation/registration/bench_crossday.py --sessions name=<plane dir> ... \
           --pairs A:B A:C B:C --triplets A:B:C --out results.json [--methods ...]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_splithalf import METHODS  # noqa: E402
from regbench import centroids, load_suite2p_session  # noqa: E402

UM = 1.4542


def flip_lr(s):
    Lx = s["dims"][1]
    return {**s, "masks": [(yy, Lx - 1 - xx, w) for yy, xx, w in s["masks"]],
            "mean": s["mean"][:, ::-1].copy(), "meanE": s["meanE"][:, ::-1].copy()}


def affine_residual_um(pairs, s1, s2):
    if len(pairs) < 10:
        return float("nan")
    c1, c2 = centroids(s1), centroids(s2)
    P = np.array(pairs)
    a, b = c1[P[:, 0]], c2[P[:, 1]]
    X = np.c_[b, np.ones(len(b))]
    keep = np.ones(len(b), bool)
    for _ in range(2):
        coef, *_ = np.linalg.lstsq(X[keep], a[keep], rcond=None)
        res = np.linalg.norm(X @ coef - a, axis=1)
        keep = res <= np.quantile(res, 0.8)
    return float(np.median(res) * UM)


def cycle_consistency(p_ab, p_bc, p_ac):
    ab, bc, ac = dict(p_ab), dict(p_bc), dict(p_ac)
    chains = [(a, bc[b]) for a, b in ab.items() if b in bc]
    if not chains:
        return float("nan"), 0
    agree = [ac.get(a) == c for a, c in chains]
    return float(np.mean(agree)), len(chains)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", nargs="+", required=True, help="name=plane_dir")
    ap.add_argument("--pairs", nargs="+", required=True)
    ap.add_argument("--triplets", nargs="*", default=[])
    ap.add_argument("--flip", nargs="*", default=[], help="pairs A:B to also run against flipped B")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--methods", nargs="+", default=list(METHODS))
    args = ap.parse_args()
    ses = {kv.split("=")[0]: load_suite2p_session(kv.split("=")[1]) for kv in args.sessions}
    res = json.loads(args.out.read_text()) if args.out.exists() else {}
    res["_meta"] = {k: {"n_rois": len(v["masks"]), "source": v["source"]} for k, v in ses.items()}
    pairs_dir = args.out.with_suffix("")
    pairs_dir.mkdir(exist_ok=True)

    jobs = [(p, False) for p in args.pairs] + [(p, True) for p in args.flip]
    for pair, flipped in jobs:
        a, b = pair.split(":")
        key = f"{a}:{b}" + (":flipped" if flipped else "")
        s2 = flip_lr(ses[b]) if flipped else ses[b]
        for m in args.methods:
            f = pairs_dir / f"{key.replace(':', '_')}__{m}.npy"
            if not f.exists():
                t = time.time()
                try:
                    pr = np.array(METHODS[m](ses[a], s2), int).reshape(-1, 2)
                except Exception as e:
                    res.setdefault(key, {})[m] = {"error": str(e)[-400:]}
                    print(key, m, "FAILED", str(e)[-300:], flush=True)
                    continue
                np.save(f, pr)
                res.setdefault(key, {}).setdefault(m, {})["time_s"] = round(time.time() - t, 1)
            pr = [tuple(x) for x in np.load(f)]
            r = res.setdefault(key, {}).setdefault(m, {})
            r["n_matches"] = len(pr)
            if not flipped:
                r["residual_um"] = affine_residual_um(pr, ses[a], s2)
            print(key, m, r, flush=True)
            args.out.write_text(json.dumps(res, indent=1))

    for trip in args.triplets:
        a, b, c = trip.split(":")
        for m in args.methods:
            ld = lambda x, y: [tuple(v) for v in np.load(pairs_dir / f"{x}_{y}__{m}.npy")]  # noqa: E731
            try:
                cc, n = cycle_consistency(ld(a, b), ld(b, c), ld(a, c))
            except FileNotFoundError:
                continue
            res.setdefault(f"cycle {trip}", {})[m] = {"consistency": cc, "n_chains": n}
            print("cycle", trip, m, cc, n, flush=True)
    args.out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
