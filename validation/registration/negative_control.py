"""Negative control: session-2 footprints shifted by a fixed offset while its FOV image is kept,
so image alignment cannot bring footprints back onto the cells; every match is false.

Usage: python validation/registration/negative_control.py <plane1> <plane2> --shift-um 60 --out results.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_splithalf import METHODS  # noqa: E402
from regbench import load_suite2p_session  # noqa: E402

UM = 1.4542


def shift_footprints(s, dx_px):
    Lx = s["dims"][1]
    masks = []
    for yy, xx, w in s["masks"]:
        x = xx + dx_px
        ok = (x >= 0) & (x < Lx)
        if ok.sum() >= 5:
            masks.append((yy[ok], x[ok], w[ok]))
    return {**s, "masks": masks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plane1")
    ap.add_argument("plane2")
    ap.add_argument("--shift-um", type=float, default=60)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--methods", nargs="+", default=list(METHODS))
    args = ap.parse_args()
    s1, s2 = load_suite2p_session(args.plane1), load_suite2p_session(args.plane2)
    s2 = shift_footprints(s2, int(round(args.shift_um / UM)))
    res = {}
    for m in args.methods:
        try:
            res[m] = {"n_false_matches": len(METHODS[m](s1, s2)), "n_rois": [len(s1["masks"]), len(s2["masks"])]}
        except Exception as e:
            res[m] = {"error": str(e)[-300:]}
        print(m, res[m], flush=True)
        args.out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
