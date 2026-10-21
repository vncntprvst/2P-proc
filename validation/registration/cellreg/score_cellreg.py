"""Score CellReg outputs with the benchmark's own metrics and merge them into the results files.

Reads <outputs>/<case>__cellreg_<rigid|nonrigid>.mat (cell_to_index_map, 1-based, 0 = absent),
and adds "cellreg_rigid" / "cellreg_nonrigid" entries to results_splithalf_D1M2run1.json,
results_sameday_D1M2.json, results_crossday_D1M2.json, results_negative_D1M2.json and
results_fingerprint_D1M2.json, plus CellReg's own estimated false-positive / true-positive
rates at P_same = 0.5 (results_cellreg_estimates_D1M2.json).

Usage: python validation/registration/cellreg/score_cellreg.py <outputs dir> <inputs dir>
"""

import json
import sys
from pathlib import Path

import h5py
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_crossday import affine_residual_um, cycle_consistency  # noqa: E402
from bench_sameday import map_to_joint, reference_pairs  # noqa: E402
from export_cellreg_inputs import P  # noqa: E402
from functional_fingerprint import fingerprint, profiles  # noqa: E402
from regbench import centroids, gt_by_iou, load_suite2p_session, score_pairs  # noqa: E402

TAGS = {"rigid": "cellreg_rigid", "nonrigid": "cellreg_nonrigid"}


def read_map(f):
    with h5py.File(f, "r") as h:
        m = np.array(h["cell_to_index_map"]).T  # MATLAB (n_cells, n_sessions)
        est = {}
        for k in ("p_same_centers_of_bins", "false_positive_per_distance_threshold",
                  "true_positive_per_distance_threshold", "false_positive_per_correlation_threshold",
                  "true_positive_per_correlation_threshold", "uncertain_fraction_centroid_distances",
                  "uncertain_fraction_spatial_correlations"):
            if k in h:
                est[k] = np.array(h[k]).ravel()
        model = "".join(chr(c) for c in np.array(h["best_model_string"]).ravel()) if "best_model_string" in h else ""
    return m.astype(int), est, model


def pairs_from_map(m, a=0, b=1):
    keep = (m[:, a] > 0) & (m[:, b] > 0)
    return [(int(i) - 1, int(j) - 1) for i, j in m[keep][:, [a, b]]]


def estimate_at(est, model, p=0.5):
    if "p_same_centers_of_bins" not in est:
        return {}
    x = est["p_same_centers_of_bins"]
    k = int(np.argmin(np.abs(x - p)))
    key = "correlation" if model.startswith("Spatial") else "distance"
    return {"model": model, "fp_est": float(est[f"false_positive_per_{key}_threshold"][k]),
            "tp_est": float(est[f"true_positive_per_{key}_threshold"][k]),
            "uncertain_fraction": float(est["uncertain_fraction_" + ("spatial_correlations" if key == "correlation"
                                                                     else "centroid_distances")][0])}


def update(name, key, method, value):
    f = HERE / name
    d = json.loads(f.read_text())
    d.setdefault(key, {})[method] = value
    f.write_text(json.dumps(d, indent=1))


def main():
    outputs, inputs = Path(sys.argv[1]), Path(sys.argv[2])
    ses = {k: load_suite2p_session(v) for k, v in P.items() if k != "joint"}
    estimates = {}
    gt_half = gt_by_iou(ses["h1"], ses["h2"])
    maps = [map_to_joint(ses[r], load_suite2p_session(P["joint"], use_iscell=False)) for r in ("run1", "run2")]
    gt_same = reference_pairs(maps[0][0], maps[1][0])
    S = Path("/home/wanglab/data/2P/Scnn1aAi14_D1M2")
    ts = {"d0824": S / "08242026/TSeries-08242026-1336-001", "d0829": S / "08292026/TSeries-08292026-1401-001",
          "d0831": S / "08312026/TSeries-08312026-0951-001"}
    prof = {k: profiles(Path(P[k]).parents[1], v) for k, v in ts.items()}
    crossday_pairs = {}
    for f in sorted(outputs.glob("*__cellreg_*.mat")):
        case, tag = f.stem.split("__cellreg_")
        method = TAGS[tag]
        kind = case.split("__")[0]
        meta = json.loads((inputs / case / "case.json").read_text())
        try:
            m, est, model = read_map(f)
        except Exception as e:
            print(f.name, "unreadable", e)
            continue
        estimates[f"{case} {tag}"] = estimate_at(est, model)
        if kind == "splithalf":
            ids2 = np.array(meta["ids2"])
            pred = [(i, int(ids2[j])) for i, j in pairs_from_map(m)]
            inview = set(ids2.tolist())
            gt = ({p for p in gt_half[0] if p[1] in inview}, gt_half[1], gt_half[2] & inview)
            update("results_splithalf_D1M2run1.json", meta["condition"], method, score_pairs(pred, gt))
        elif kind == "sameday":
            update("results_sameday_D1M2.json", "run1-run2", method, score_pairs(pairs_from_map(m), gt_same))
        elif kind == "crossday" and "pair" in meta:
            a, b = meta["pair"]
            pr = pairs_from_map(m)
            crossday_pairs[(a, b, method)] = pr
            update("results_crossday_D1M2.json", f"{a}:{b}", method,
                   {"n_matches": len(pr), "residual_um": affine_residual_um(pr, ses[a], ses[b])})
            if a in prof and b in prof:
                d = json.loads((HERE / "results_fingerprint_D1M2.json").read_text())
                d[f"{a}:{b} {method}"] = fingerprint(pr, prof[a], prof[b], centroids(ses[a]), centroids(ses[b]))
                (HERE / "results_fingerprint_D1M2.json").write_text(json.dumps(d, indent=1))
        elif kind == "negative":
            update("results_negative_D1M2.json", method, "n_false_matches", len(pairs_from_map(m)))
        print(case, tag, len(m), "cells", estimates[f"{case} {tag}"])
    for method in TAGS.values():
        try:
            cc, n = cycle_consistency(crossday_pairs[("d0824", "d0829", method)],
                                      crossday_pairs[("d0829", "d0831", method)],
                                      crossday_pairs[("d0824", "d0831", method)])
            update("results_crossday_D1M2.json", "cycle d0824:d0829:d0831", method, {"consistency": cc, "n_chains": n})
        except KeyError:
            pass
    (HERE / "results_cellreg_estimates_D1M2.json").write_text(json.dumps(estimates, indent=1))


if __name__ == "__main__":
    main()
