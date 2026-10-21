"""Track2p matching of N sessions, consecutive pairs (runs in an environment with track2p).

Uses Track2p's own steps for each consecutive pair (s, s+1): elastix affine registration of
the session-(s+1) FOV image onto session s, the same transform applied to binary ROIs,
1 - IoU cost (centroids within iou_dist_thr px), Hungarian assignment, Otsu threshold on the
matched IoUs. Output npz: pairs{s} (n, 2) indices into sessions s and s+1.

Usage: python run_track2p.py <in.npz> <out.npz> [--transform affine]
"""

import argparse

import numpy as np
from scipy import sparse
from scipy.optimize import linear_sum_assignment
from skimage.filters import threshold_otsu
from track2p.match.utils import get_cross_iou_mat, get_iou
from track2p.ops.default import DefaultTrackOps
from track2p.register.elastix import itk_reg_all_roi, reg_img_elastix


def dense_rois(A, dims):
    out = np.zeros((dims[0] * dims[1], A.shape[0]), np.uint8)
    for k in range(A.shape[0]):
        out[A[k].indices, k] = 1
    return out.reshape(dims[0], dims[1], A.shape[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--transform", default="affine")
    args = ap.parse_args()
    d = np.load(args.inp, allow_pickle=True)
    dims = tuple(int(v) for v in d["dims"])
    n_sess = int(d["n_sessions"])
    A = [sparse.csr_matrix((d[f"A{s}_data"], d[f"A{s}_indices"], d[f"A{s}_indptr"]),
                           shape=tuple(d[f"A{s}_shape"])) for s in range(1, n_sess + 1)]
    ops = DefaultTrackOps()
    ops.transform_type = args.transform
    out = {}
    for s in range(n_sess - 1):
        _, params = reg_img_elastix(d[f"image{s + 1}"].astype(np.float32),
                                    d[f"image{s + 2}"].astype(np.float32), ops)
        r1 = dense_rois(A[s], dims)
        r2 = itk_reg_all_roi(dense_rois(A[s + 1], dims), params)
        cost = 1 - get_cross_iou_mat(r1, r2, dist_thr=ops.iou_dist_thr)
        i1, i2 = linear_sum_assignment(cost)
        iou = get_iou(r1[:, :, i1], r2[:, :, i2])
        keep = iou > threshold_otsu(iou)
        out[f"pairs{s + 1}"] = np.c_[i1[keep], i2[keep]]
    np.savez(args.out, **out)


if __name__ == "__main__":
    main()
