"""ROICaT tracking on N sessions from custom footprints (run inside the roicat venv).

Footprints and FOV images are passed through roicat.data_importing.Data_roicat and the
default tracking pipeline (roicat.pipelines.pipeline_tracking) is run with um_per_pixel set.
Output: one cluster label per ROI and session (-1 = unmatched).

Usage: python run_roicat.py <in.npz> <out.npz> [--um-per-pixel 1.45] [--image mean|meanE] [--cpu]
"""

import argparse

import numpy as np
import roicat
from scipy import sparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--um-per-pixel", type=float, default=1.45)
    ap.add_argument("--image", default="meanE")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()
    d = np.load(args.inp, allow_pickle=True)
    dims = tuple(int(v) for v in d["dims"])
    n_sess = int(d["n_sessions"])
    sf, fov = [], []
    for s in range(1, n_sess + 1):
        A = sparse.csr_matrix((d[f"A{s}_data"], d[f"A{s}_indices"], d[f"A{s}_indptr"]),
                              shape=tuple(d[f"A{s}_shape"]))
        sf.append(A.astype(np.float32))
        img = d[f"{args.image}{s}"].astype(np.float32)
        fov.append((img - img.min()) / (np.ptp(img) + 1e-9))
    data = roicat.data_importing.Data_roicat()
    data.set_spatialFootprints(spatialFootprints=sf, um_per_pixel=args.um_per_pixel)
    data.set_FOV_images(FOV_images=fov)
    data.transform_spatialFootprints_to_ROIImages(out_height_width=(36, 36))
    params = {
        "general": {"use_GPU": not args.cpu, "verbose": False, "random_seed": 0},
        "data_loading": {"data_kind": "roicat", "common": {"um_per_pixel": args.um_per_pixel}},
        "results_saving": {"dir_save": None},
    }
    results, _, _ = roicat.pipelines.pipeline_tracking(params, custom_data=data)
    labels = results["clusters"]["labels_bySession"]
    np.savez(args.out, **{f"labels{s + 1}": np.asarray(labels[s]) for s in range(n_sess)})


if __name__ == "__main__":
    main()
