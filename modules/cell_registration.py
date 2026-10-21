# -*- coding: utf-8 -*-
"""cell_registration

Match the same cells across separately processed sessions (same field of view).

Methods, validated in validation/registration (split-half known deformations, same-day joint
reference, cross-day controls):
- "roicat" (default): ROICaT tracking (geometric + non-rigid FOV alignment, ROI similarity
  graph, multi-session clustering). Runs in an environment with roicat (Python >= 3.11).
- "track2p": Track2p affine registration of consecutive sessions, IoU + Hungarian + Otsu
  threshold, chained into tracks. Runs in an environment with track2p.
- "caiman": CaImAn register_multisession (optical flow + Jaccard + Hungarian), in-process.

Inputs per session: a pipeline export dir with Suite2p (suite2p/plane0) or CNMF
(cnmf_result.hdf5) outputs. Suite2p ROIs are the iscell ones; their original indices are kept.

Outputs (out_dir): cell_registration.npz / .mat and cell_registration_qc.json, cell_registration.png
- assignments: (n_cells, n_sessions) ROI index per session (extraction order, i.e. suite2p
  stat index or CNMF component), -1 if absent (.mat: 1-based, 0 if absent)
- n_sessions_tracked: per cell
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.io import loadmat, savemat

BACKENDS = Path(__file__).parent / "registration_backends"


# --------------------------------------------------------------------------- sessions


def load_session(export_dir, iscell_file="iscell.npy"):
    """ROI footprints and FOV image of one export (Suite2p iscell ROIs, or CNMF components)."""
    export_dir = Path(export_dir)
    cnmf = export_dir / "cnmf_result.hdf5"
    plane = next((d for d in [export_dir / "suite2p" / "plane0", export_dir / "plane0", export_dir]
                  if (d / "stat.npy").exists()), None)
    if plane is not None:
        stat = np.load(plane / "stat.npy", allow_pickle=True)
        ops = np.load(plane / "ops.npy", allow_pickle=True).item()
        keep = np.load(plane / iscell_file)[:, 0].astype(bool)
        masks = [(s["ypix"].astype(int), s["xpix"].astype(int), s["lam"].astype(np.float32))
                 for s, k in zip(stat, keep) if k]
        return {"masks": masks, "dims": (int(ops["Ly"]), int(ops["Lx"])),
                "image": ops["meanImg"].astype(np.float32), "roi_index": np.flatnonzero(keep),
                "source": str(plane), "extractor": "suite2p"}
    if cnmf.exists():
        from caiman.source_extraction.cnmf.cnmf import load_CNMF

        est = load_CNMF(str(cnmf), n_processes=1).estimates
        A = est.A.tocsc()
        d1, d2 = est.dims
        masks = []
        for i in range(A.shape[1]):
            idx = A[:, i].nonzero()[0]
            yy, xx = np.unravel_index(idx, (d1, d2), order="F")  # CaImAn footprints are F-ordered
            masks.append((yy, xx, A[idx, i].toarray().ravel().astype(np.float32)))
        mat = export_dir / "results_caiman.mat"
        if mat.exists():
            image = loadmat(str(mat), variable_names=["mean_map_motion_corrected"])["mean_map_motion_corrected"]
        else:
            image = np.load(export_dir / "mean_intensity_template.npy")
        return {"masks": masks, "dims": (int(d1), int(d2)), "image": np.asarray(image, np.float32),
                "roi_index": np.arange(len(masks)), "source": str(cnmf), "extractor": "cnmf"}
    raise FileNotFoundError(f"No Suite2p or CNMF outputs in {export_dir}")


def footprint_matrix(session, order="C"):
    """(Ly*Lx, n_roi) sparse footprints; order "F" is CaImAn's convention."""
    Ly, Lx = session["dims"]
    rows, cols, vals = [], [], []
    for k, (yy, xx, w) in enumerate(session["masks"]):
        rows.append(yy * Lx + xx if order == "C" else xx * Ly + yy)
        cols.append(np.full(len(yy), k))
        vals.append(w)
    return sparse.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(Ly * Lx, len(session["masks"])))


def centroids(session):
    return np.array([[np.average(yy, weights=w), np.average(xx, weights=w)] if len(yy) and w.sum() > 0
                     else [np.nan, np.nan] for yy, xx, w in session["masks"]])


def export_sessions(sessions, path):
    out = {"dims": np.array(sessions[0]["dims"]), "n_sessions": len(sessions)}
    for s, ses in enumerate(sessions, 1):
        A = footprint_matrix(ses).T.tocsr()
        out.update({f"A{s}_data": A.data, f"A{s}_indices": A.indices, f"A{s}_indptr": A.indptr,
                    f"A{s}_shape": np.array(A.shape), f"image{s}": ses["image"]})
    np.savez(path, **out)


# --------------------------------------------------------------------------- methods


def _python_for(package, python=None):
    """Interpreter to run a backend: explicit, $<PACKAGE>_PYTHON, or the current one."""
    return python or os.environ.get(f"{package.upper()}_PYTHON") or sys.executable


def _run_backend(script, sessions, python, extra):
    with tempfile.TemporaryDirectory() as td:
        inp, out = Path(td) / "in.npz", Path(td) / "out.npz"
        export_sessions(sessions, inp)
        res = subprocess.run([python, "-I", str(BACKENDS / script), str(inp), str(out), *extra],
                             capture_output=True, text=True)
        if res.returncode:
            raise RuntimeError(f"{script} failed ({python}):\n{res.stderr[-3000:]}")
        return dict(np.load(out, allow_pickle=True))


def labels_from_pair_chain(pair_lists, n_rois):
    """Cluster labels from matched pairs of consecutive sessions (tracks through the chain)."""
    labels = [np.full(n, -1) for n in n_rois]
    nxt = 0
    for s, pairs in enumerate(pair_lists):
        for i, j in pairs:
            if labels[s][i] < 0:
                labels[s][i] = nxt
                nxt += 1
            labels[s + 1][j] = labels[s][i]
    return labels


def register(sessions, method="roicat", um_per_pixel=1.45, python=None, **kw):
    """Cluster label per ROI and session (-1 = not tracked), for the chosen method."""
    if method == "roicat":
        extra = ["--um-per-pixel", str(um_per_pixel)] + (["--cpu"] if kw.get("cpu") else [])
        r = _run_backend("run_roicat.py", sessions, _python_for("roicat", python), extra)
        labels = [np.asarray(r[f"labels{s + 1}"]) for s in range(len(sessions))]
        # a label seen in a single session is not a match
        counts = np.bincount(np.concatenate([lab[lab >= 0] for lab in labels]))
        return [np.where((lab >= 0) & (counts[np.maximum(lab, 0)] > 1), lab, -1) for lab in labels]
    if method == "track2p":
        r = _run_backend("run_track2p.py", sessions, _python_for("track2p", python),
                         ["--transform", kw.get("transform", "affine")])
        pairs = [r[f"pairs{s + 1}"] for s in range(len(sessions) - 1)]
        return labels_from_pair_chain(pairs, [len(s["masks"]) for s in sessions])
    if method == "caiman":
        from caiman.base.rois import register_multisession

        A = [footprint_matrix(s, "F") for s in sessions]
        _, assignments, _ = register_multisession(
            A=A, dims=sessions[0]["dims"], templates=[s["image"] for s in sessions],
            thresh_cost=kw.get("thresh_cost", 0.7), max_dist=kw.get("max_dist", 10))
        labels = [np.full(len(s["masks"]), -1) for s in sessions]
        for c, row in enumerate(assignments):
            if np.sum(np.isfinite(row)) > 1:
                for s, v in enumerate(row):
                    if np.isfinite(v):
                        labels[s][int(v)] = c
        return labels
    raise ValueError(f"Unknown registration method: {method}")


# --------------------------------------------------------------------------- outputs


def assignments_from_labels(labels):
    """(n_cells, n_sessions) index into each session's ROI list (-1 absent), most-tracked first."""
    ids = np.unique(np.concatenate([lab[lab >= 0] for lab in labels]))
    A = np.full((len(ids), len(labels)), -1)
    pos = {c: k for k, c in enumerate(ids)}
    for s, lab in enumerate(labels):
        for i, c in enumerate(lab):
            if c >= 0:
                A[pos[c], s] = i
    order = np.argsort(-(A >= 0).sum(1), kind="stable")
    return A[order]


def affine_residual_um(s1, s2, pairs, um_per_pixel):
    """Median centroid distance of matched pairs after a robust affine fit (s2 onto s1)."""
    if len(pairs) < 10:
        return float("nan")
    P = np.asarray(pairs)
    a, b = centroids(s1)[P[:, 0]], centroids(s2)[P[:, 1]]
    X = np.c_[b, np.ones(len(b))]
    keep = np.ones(len(b), bool)
    for _ in range(2):
        coef, *_ = np.linalg.lstsq(X[keep], a[keep], rcond=None)
        res = np.linalg.norm(X @ coef - a, axis=1)
        keep = res <= np.quantile(res, 0.8)
    return float(np.median(res) * um_per_pixel)


def fov_similarity(img1, img2):
    """Correlation of two FOV images after the best rigid shift (phase correlation)."""
    from skimage.registration import phase_cross_correlation

    shift, _, _ = phase_cross_correlation(img1, img2, upsample_factor=1)
    dy, dx = (int(round(v)) for v in shift)
    b = np.roll(img2, (dy, dx), axis=(0, 1))
    Ly, Lx = img1.shape
    ys = slice(max(dy, 0), Ly + min(dy, 0))
    xs = slice(max(dx, 0), Lx + min(dx, 0))
    return float(np.corrcoef(img1[ys, xs].ravel(), b[ys, xs].ravel())[0, 1]), (dy, dx)


def quality_control(sessions, assignments, um_per_pixel, min_fov_similarity=0.5):
    n = len(sessions)
    qc = {"n_rois": [len(s["masks"]) for s in sessions],
          "n_cells_tracked_in_k_sessions": {k: int(((assignments >= 0).sum(1) == k).sum()) for k in range(2, n + 1)},
          "pairs": {}}
    for a in range(n):
        for b in range(a + 1, n):
            m = (assignments[:, a] >= 0) & (assignments[:, b] >= 0)
            pairs = assignments[m][:, [a, b]]
            sim, shift = fov_similarity(sessions[a]["image"], sessions[b]["image"])
            if sim < min_fov_similarity:
                print(f"Warning: sessions {a + 1} and {b + 1} have FOV similarity {sim:.2f} after rigid "
                      f"alignment; they may not be the same field of view or plane.")
            qc["pairs"][f"{a + 1}-{b + 1}"] = {
                "fov_similarity": sim, "rigid_shift_px": list(shift),
                "n_matched": int(m.sum()),
                "frac_of_smaller_session": float(m.sum() / max(min(qc["n_rois"][a], qc["n_rois"][b]), 1)),
                "affine_residual_um": affine_residual_um(sessions[a], sessions[b], pairs, um_per_pixel)}
    return qc


def plot_registration(sessions, assignments, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(sessions)
    fig, axes = plt.subplots(1, n, figsize=(4.2 * n, 4.4))
    axes = np.atleast_1d(axes)
    full = (assignments >= 0).all(1)
    for s, ax in enumerate(axes):
        img = sessions[s]["image"]
        ax.imshow(img, cmap="gray", vmin=np.percentile(img, 1), vmax=np.percentile(img, 99.5))
        c = centroids(sessions[s])
        tracked = assignments[:, s][assignments[:, s] >= 0]
        ax.scatter(c[:, 1], c[:, 0], s=3, color="#b0afab", linewidths=0)
        ax.scatter(c[tracked, 1], c[tracked, 0], s=4, color="#2a78d6", linewidths=0)
        ax.scatter(c[assignments[full, s], 1], c[assignments[full, s], 0], s=5, color="#eb6834", linewidths=0)
        ax.set_title(f"session {s + 1}: {len(c)} ROIs, {len(tracked)} tracked", fontsize=9)
        ax.axis("off")
    fig.suptitle("grey: not tracked, blue: tracked in >= 2 sessions, orange: in all sessions", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run_registration(export_dirs, out_dir, method="roicat", um_per_pixel=1.45, python=None,
                     iscell_file="iscell.npy", **kw):
    """Register sessions, save assignments / QC / figure in out_dir, return the assignments."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sessions = [load_session(e, iscell_file) for e in export_dirs]
    labels = register(sessions, method, um_per_pixel, python, **kw)
    assign_local = assignments_from_labels(labels)
    # map to extraction-order ROI indices (suite2p stat index / CNMF component)
    assignments = np.full_like(assign_local, -1)
    for s, ses in enumerate(sessions):
        m = assign_local[:, s] >= 0
        assignments[m, s] = ses["roi_index"][assign_local[m, s]]
    qc = quality_control(sessions, assign_local, um_per_pixel)
    qc.update({"method": method, "um_per_pixel": um_per_pixel, "sessions": [str(e) for e in export_dirs],
               "extractor": [s["extractor"] for s in sessions], "iscell_file": iscell_file})
    np.savez(out_dir / "cell_registration.npz", assignments=assignments,
             n_sessions_tracked=(assignments >= 0).sum(1), sessions=np.array([str(e) for e in export_dirs]))
    savemat(out_dir / "cell_registration.mat",
            {"assignments": assignments + 1, "n_sessions_tracked": (assignments >= 0).sum(1),
             "sessions": np.array([str(e) for e in export_dirs], dtype=object), "method": method})
    (out_dir / "cell_registration_qc.json").write_text(json.dumps(qc, indent=2))
    plot_registration(sessions, assign_local, out_dir / "cell_registration.png")
    return assignments, qc
