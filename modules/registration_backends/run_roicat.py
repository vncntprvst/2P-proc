"""ROICaT tracking of N sessions (runs in an environment with roicat installed, Python >= 3.11).

Input npz (written by modules.cell_registration.export_sessions): per session s = 1..N,
footprints as CSR (n_roi, Ly*Lx) in C order (A{s}_data/_indices/_indptr/_shape) and the FOV
image (image{s}). Output npz: labels{s}, one cluster label per ROI (-1 = not tracked).

Usage: python run_roicat.py <in.npz> <out.npz> --um-per-pixel 1.45 [--cpu] [--seed 0]
"""

import argparse

import numpy as np
import roicat
from scipy import sparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--um-per-pixel", type=float, required=True)
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    d = np.load(args.inp, allow_pickle=True)
    n_sess = int(d["n_sessions"])
    sf, fov = [], []
    for s in range(1, n_sess + 1):
        sf.append(sparse.csr_matrix((d[f"A{s}_data"], d[f"A{s}_indices"], d[f"A{s}_indptr"]),
                                    shape=tuple(d[f"A{s}_shape"])).astype(np.float32))
        img = d[f"image{s}"].astype(np.float32)
        fov.append((img - img.min()) / (np.ptp(img) + 1e-9))
    data = roicat.data_importing.Data_roicat()
    data.set_spatialFootprints(spatialFootprints=sf, um_per_pixel=args.um_per_pixel)
    data.set_FOV_images(FOV_images=fov)
    data.transform_spatialFootprints_to_ROIImages(out_height_width=(36, 36))
    params = {
        "general": {"use_GPU": not args.cpu, "verbose": False, "random_seed": args.seed},
        "data_loading": {"data_kind": "roicat", "common": {"um_per_pixel": args.um_per_pixel}},
        "results_saving": {"dir_save": None},
    }
    results, _, _ = roicat.pipelines.pipeline_tracking(params, custom_data=data)
    labels = results["clusters"]["labels_bySession"]
    np.savez(args.out, **{f"labels{s + 1}": np.asarray(labels[s]) for s in range(n_sess)},
             roicat_version=roicat.__version__)


if __name__ == "__main__":
    main()
