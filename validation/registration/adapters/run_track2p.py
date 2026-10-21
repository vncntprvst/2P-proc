"""Track2p matching on two sessions (run inside the track2p venv).

Uses Track2p's own steps: elastix registration of session-2 mean image onto session 1
(affine or nonrigid), the same transform applied to binary ROIs, 1 - IoU cost (centroids
within iou_dist_thr px), Hungarian assignment, Otsu threshold on the matched IoUs.

Usage: python run_track2p.py <in.npz> <out.npz> [--transform affine|nonrigid] [--image mean|meanE]
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
    """(Ly, Lx, n) binary ROI array from (n, Ly*Lx) sparse rows (C order)."""
    out = np.zeros((dims[0], dims[1], A.shape[0]), np.uint8)
    for k in range(A.shape[0]):
        idx = A[k].indices
        out.reshape(-1, A.shape[0])[idx, k] = 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--transform", default="affine")
    ap.add_argument("--image", default="mean")
    args = ap.parse_args()
    d = np.load(args.inp, allow_pickle=True)
    dims = tuple(d["dims"])
    A1 = sparse.csr_matrix((d["A1_data"], d["A1_indices"], d["A1_indptr"]), shape=tuple(d["A1_shape"]))
    A2 = sparse.csr_matrix((d["A2_data"], d["A2_indices"], d["A2_indptr"]), shape=tuple(d["A2_shape"]))
    ops = DefaultTrackOps()
    ops.transform_type = args.transform
    img1, img2 = d[f"{args.image}1"].astype(np.float32), d[f"{args.image}2"].astype(np.float32)
    _, params = reg_img_elastix(img1, img2, ops)
    r1 = dense_rois(A1, dims)
    r2 = itk_reg_all_roi(dense_rois(A2, dims), params)
    cost = 1 - get_cross_iou_mat(r1, r2, dist_thr=ops.iou_dist_thr)
    i1, i2 = linear_sum_assignment(cost)
    iou = get_iou(r1[:, :, i1], r2[:, :, i2])
    thr = threshold_otsu(iou)
    keep = iou > thr
    np.savez(args.out, i1=i1[keep], i2=i2[keep], iou=iou[keep], thr=thr)


if __name__ == "__main__":
    main()
