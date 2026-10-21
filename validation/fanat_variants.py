"""Fast evaluation of F_anat (non-rigid) construction variants at the ROI level.

The production F_anat (compute_zcorr.subtract_z_motion_patches) picks, per frame and per
patch, the z-stack plane (within zpos +/- 5) maximising the Gaussian-smoothed Pearson R^2
between the functional patch and the z-stack patch; each pixel is then the mean over its
covering patches of the z-stack at those depths. Hence, for an ROI with uniform pixel
weights:

    F_cell_anat(roi, t) = sum_p A[roi, p, z_p(t)],
    A[roi, p, z] = sum_{pixels of roi in patch p} Zstack[z, y, x] / (count(y, x) * npix(roi))

This module computes once the Pearson profile r[t, p, z] for all planes (BLAS, all frames)
and the projection tensor A, so that any depth-selection rule z_p(t) can be turned into
F_cell_anat traces in seconds and benchmarked (real_zcorr_benchmark).

Usage
-----
    python validation/fanat_variants.py profiles <mcorr.mmap> <zstack_shifted.tif> <z_correlation.npz> \
        <export dir> --out DIR
    python validation/fanat_variants.py variants DIR    # F_cell_anat_<variant>.npy for each rule
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def patch_grid(Ny, Nx, patch_size=(60, 60), step_size=(36, 36)):
    """Patch limits in patch_regress order (incl. its border rules), as (y0, y1, x0, x1)."""
    lims = []
    patch_size_x = patch_size_y = None
    for i in range(0, Nx, step_size[1]):
        for j in range(0, Ny, step_size[0]):
            if (i + patch_size[1] > Nx and patch_size_x < patch_size[1]
                    and patch_size_y < patch_size[0]):
                continue
            if j + patch_size[0] > Ny and patch_size_y < patch_size[0]:
                continue
            patch_size_x = patch_size[1] if i + patch_size[1] <= Nx else Nx - i
            patch_size_y = patch_size[0] if j + patch_size[0] <= Ny else Ny - j
            lims.append((j, j + patch_size_y, i, i + patch_size_x))
    return lims


def load_zstack(path):
    from tifffile import TiffFile

    with TiffFile(path) as tif:
        Z = np.stack([p.asarray() for p in tif.pages]).astype(np.float32)  # (Nz, Ny, Nx)
    return np.flip(np.clip(Z, 0, 2**16 - 1), axis=1)  # same flip as subtract_z_motion_patches


def pearson_profiles(mov, Z, lims, chunk=1000):
    """r[t, p, z]: Pearson correlation of each functional patch with each z-stack plane."""
    T = mov.shape[0]
    r = np.zeros((T, len(lims), Z.shape[0]), np.float32)
    for k, (y0, y1, x0, x1) in enumerate(lims):
        zp = Z[:, y0:y1, x0:x1].reshape(Z.shape[0], -1).astype(np.float64)
        zp = zp - zp.mean(1, keepdims=True)
        zp /= np.linalg.norm(zp, axis=1, keepdims=True) + 1e-12
        for s in range(0, T, chunk):
            fp = mov[s : s + chunk, y0:y1, x0:x1].reshape(min(chunk, T - s), -1).astype(np.float64)
            fp = fp - fp.mean(1, keepdims=True)
            fp /= np.linalg.norm(fp, axis=1, keepdims=True) + 1e-12
            r[s : s + chunk, k] = fp @ zp.T
    return r


def projection_tensor(lims, Z, rois, Ny, Nx):
    """A[roi, p, z] (dense over z, sparse over (roi, p) pairs stored as arrays)."""
    count = np.zeros((Ny, Nx), np.float32)
    for y0, y1, x0, x1 in lims:
        count[y0:y1, x0:x1] += 1
    roi_idx, patch_idx, w = [], [], []
    for i, (yy, xx) in enumerate(rois):
        for k, (y0, y1, x0, x1) in enumerate(lims):
            m = (yy >= y0) & (yy < y1) & (xx >= x0) & (xx < x1)
            if m.any():
                roi_idx.append(i)
                patch_idx.append(k)
                w.append((Z[:, yy[m], xx[m]] / count[yy[m], xx[m]]).sum(1) / len(yy))
    return np.array(roi_idx), np.array(patch_idx), np.array(w, np.float32)  # w: (pairs, Nz)


def select_production(r, zpos, half=5, sigma=1.0, signed=False):
    """z_p(t) as in patch_regress: argmax of Gaussian-smoothed R^2 over the valid planes."""
    T, P, Nz = r.shape
    score = r if signed else r**2
    z = np.zeros((T, P), np.int16)
    for t in range(T):
        lo, hi = max(zpos[t] - half, 0), min(zpos[t] + half + 1, Nz)
        s = score[t, :, lo:hi]
        if sigma:
            s = gaussian_filter1d(s, sigma, axis=1, mode="reflect")
        z[t] = lo + np.argmax(s, 1)
    return z


def f_cell_from_z(z, roi_idx, patch_idx, w, n_roi):
    """F_cell_anat (n_roi, T) for integer depths z (T, P)."""
    T = z.shape[0]
    out = np.zeros((n_roi, T), np.float64)
    contrib = w[np.arange(len(w))[:, None], z[:, patch_idx].T]  # (pairs, T)
    np.add.at(out, roi_idx, contrib)
    return out


def f_cell_from_weights(q, roi_idx, patch_idx, w, n_roi):
    """F_cell_anat for soft depth weights q (T, P, Nz) summing to 1 over z."""
    out = np.zeros((n_roi, q.shape[0]), np.float64)
    contrib = np.einsum("tkz,kz->kt", q[:, patch_idx], w)
    np.add.at(out, roi_idx, contrib)
    return out


def soft_rule(r, zpos, beta, half, sigma):
    """Soft depth weights: softmax(beta * R^2) within zpos +/- half, R^2 optionally z-smoothed."""
    T, P, Nz = r.shape
    s = r**2
    if sigma:
        s = gaussian_filter1d(s, sigma, axis=2, mode="reflect")
    q = np.zeros_like(r)
    for t in range(T):
        lo, hi = max(zpos[t] - half, 0), min(zpos[t] + half + 1, Nz)
        x = beta * s[t, :, lo:hi]
        e = np.exp(x - x.max(1, keepdims=True))
        q[t, :, lo:hi] = e / e.sum(1, keepdims=True)
    return q


def soft_sweep(d, out_dir):
    out = {}
    for beta in (100, 200, 400, 1000):
        for half in (5, 8):
            for sigma in (0, 1):
                q = soft_rule(d["r"], d["zpos"], beta, half, sigma)
                out[f"soft_b{beta}_w{half}_g{sigma}"] = f_cell_from_weights(
                    q, d["roi_idx"], d["patch_idx"], d["w"], int(d["n_roi"]))
    np.savez(out_dir / "f_cell_anat_soft_sweep.npz", **out)
    print(f"saved {list(out)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("profiles")
    a.add_argument("mmap")
    a.add_argument("zstack")
    a.add_argument("zcorr")
    a.add_argument("plane_dir")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--strides", type=int, default=36, help="mcorr strides (patch step)")
    a.add_argument("--overlaps", type=int, default=24, help="mcorr overlaps")
    b = sub.add_parser("variants")
    b.add_argument("dir", type=Path)
    b.add_argument("--nf-trial", type=int, default=80)
    c = sub.add_parser("soft")
    c.add_argument("dir", type=Path)
    args = ap.parse_args()

    if args.cmd == "profiles":
        from caiman.mmapping import load_memmap

        from stim_response_analysis import load_extraction

        args.out.mkdir(parents=True, exist_ok=True)
        Yr, dims, T = load_memmap(args.mmap)
        Ny, Nx = dims
        mov = np.clip(np.reshape(Yr.T, [T, Ny, Nx], order="F"), 0, 2**16 - 1).astype(np.float32)
        Z = load_zstack(args.zstack)
        ps = args.strides + args.overlaps
        lims = patch_grid(Ny, Nx, (ps, ps), (args.strides, args.strides))
        r = pearson_profiles(mov, Z, lims)
        _, _, rois = load_extraction(args.plane_dir)
        roi_idx, patch_idx, w = projection_tensor(lims, Z, rois, Ny, Nx)
        np.savez(args.out / "fanat_profiles.npz", r=r, lims=np.array(lims),
                 zpos=np.load(args.zcorr)["zpos"], roi_idx=roi_idx, patch_idx=patch_idx, w=w,
                 n_roi=len(rois))
        print(f"profiles {r.shape}, pairs {len(w)}")
        return

    d = np.load(args.dir / "fanat_profiles.npz")
    if args.cmd == "soft":
        soft_sweep(d, args.dir)
        return
    r, zpos, roi_idx, patch_idx, w, n_roi = (d[k] for k in ["r", "zpos", "roi_idx", "patch_idx", "w", "n_roi"])
    n_roi = int(n_roi)
    nf = args.nf_trial
    T, P, Nz = r.shape
    rules = {}
    rules["prod"] = select_production(r, zpos)
    rules["win8"] = select_production(r, zpos, half=8)
    rules["nosmooth"] = select_production(r, zpos, sigma=0)
    rules["signed"] = select_production(r, zpos, signed=True)
    z_t = rules["prod"].reshape(-1, nf, P)
    rules["tmed3"] = median_filter(z_t, size=(1, 3, 1), mode="nearest").reshape(T, P)
    # spatial median of depth over the patch grid (patches ordered column-major on a grid)
    ny = len(np.unique(d["lims"][:, 0]))
    zg = rules["prod"].reshape(T, -1, ny)
    rules["smed3"] = median_filter(zg, size=(1, 3, 3), mode="nearest").reshape(T, P)
    # rigid offset per patch: global zpos + the patch's median offset (tilted / curved plane)
    off = np.round(np.median(rules["prod"] - zpos[:, None], 0)).astype(int)
    rules["offset"] = np.clip(zpos[:, None] + off[None], 0, Nz - 1)
    rules["global"] = np.repeat(zpos[:, None], P, 1)
    out = {}
    for k, z in rules.items():
        out[k] = f_cell_from_z(z.astype(int), roi_idx, patch_idx, w, n_roi)
    # soft (sub-plane) depth: softmax of r^2 within the production window
    for beta in (50, 200):
        q = np.zeros_like(r)
        for t in range(T):
            lo, hi = max(zpos[t] - 5, 0), min(zpos[t] + 6, Nz)
            s = beta * r[t, :, lo:hi] ** 2
            e = np.exp(s - s.max(1, keepdims=True))
            q[t, :, lo:hi] = e / e.sum(1, keepdims=True)
        out[f"soft{beta}"] = f_cell_from_weights(q, roi_idx, patch_idx, w, n_roi)
    np.savez(args.dir / "f_cell_anat_rules.npz", **out)
    pinned = np.mean(np.abs(rules["prod"] - zpos[:, None]) == 5)
    print(f"saved {list(out)}; fraction of patch depths at the +/-5 bound: {pinned:.3f}")


if __name__ == "__main__":
    main()
