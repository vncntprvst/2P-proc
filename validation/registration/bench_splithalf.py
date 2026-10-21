"""Split-half registration benchmark: Suite2p run separately on the two halves of one
motion-corrected recording (same frame, real segmentation variability); reference pairs from
IoU in the shared frame; half 2 then deformed with known fields; methods must recover the pairs.

Usage: python validation/registration/bench_splithalf.py <half1 plane dir> <half2 plane dir> --out results.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regbench import (deform, gt_by_iou, load_suite2p_session, match_caiman, match_roicat,  # noqa: E402
                      match_track2p, score_pairs)

UM = 1.4542
CONDITIONS = [  # amp_um (RMS non-rigid), rot_deg, shift_um
    (0, 0, (0, 0)), (0, 1.5, (10, -8)), (3, 1.5, (10, -8)), (6, 1.5, (10, -8)), (10, 1.5, (10, -8)),
]
METHODS = {
    "caiman": lambda a, b: match_caiman(a, b),
    "caiman_meanE": lambda a, b: match_caiman(a, b, template="meanE"),
    "track2p_affine": lambda a, b: match_track2p(a, b, "affine"),
    "track2p_nonrigid": lambda a, b: match_track2p(a, b, "nonrigid"),
    "roicat": lambda a, b: match_roicat(a, b, UM),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half1")
    ap.add_argument("half2")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--methods", nargs="+", default=list(METHODS))
    args = ap.parse_args()
    h1, h2 = load_suite2p_session(args.half1), load_suite2p_session(args.half2)
    gt = gt_by_iou(h1, h2)
    print(f"ROIs {len(h1['masks'])}/{len(h2['masks'])}; reference pairs {len(gt[0])}, "
          f"uncertain {len(gt[1])}/{len(gt[2])}", flush=True)
    res = json.loads(args.out.read_text()) if args.out.exists() else {}
    for amp, rot, shift in CONDITIONS:
        key = f"amp{amp}_rot{rot}_shift{shift[0]},{shift[1]}"
        b = deform(h2, amp, UM, rot_deg=rot, shift_um=shift, seed=int(amp * 10 + rot * 7))
        for m in args.methods:
            if res.get(key, {}).get(m):
                continue
            t = time.time()
            try:
                # deformed-session indices -> original ROI ids; GT restricted to ROIs still in view
                pred = [(i, int(b["ids"][j])) for i, j in METHODS[m](h1, b)]
                inview = set(int(v) for v in b["ids"])
                gt_b = ({p for p in gt[0] if p[1] in inview}, gt[1], gt[2] & inview)
                r = score_pairs(pred, gt_b)
            except Exception as e:  # keep going; record the failure
                r = {"error": str(e)[-500:]}
            r["time_s"] = round(time.time() - t, 1)
            res.setdefault(key, {})[m] = r
            print(key, m, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)
            args.out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
