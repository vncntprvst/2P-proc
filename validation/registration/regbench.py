"""Cell-registration benchmark: footprint loading, synthetic sessions with known identity,
registration methods behind one interface, and pair-level metrics.

A session is a dict:
    masks   list of (ypix, xpix, weights) per ROI
    dims    (Ly, Lx)
    mean    mean image (float32), meanE: enhanced mean image if available
    ids     optional ground-truth identity per ROI (synthetic data)

Methods take two sessions and return matched index pairs (i in s1, j in s2) and a score.
"""

from pathlib import Path

import cv2
import numpy as np
from scipy import sparse
from scipy.ndimage import gaussian_filter

# ----------------------------------------------------------------------------- loading


def load_suite2p_session(plane_dir, iscell_file="iscell.npy", use_iscell=True):
    plane_dir = Path(plane_dir)
    stat = np.load(plane_dir / "stat.npy", allow_pickle=True)
    ops = np.load(plane_dir / "ops.npy", allow_pickle=True).item()
    keep = np.ones(len(stat), bool)
    if use_iscell:
        keep = np.load(plane_dir / iscell_file)[:, 0].astype(bool)
    masks = [(s["ypix"].astype(int), s["xpix"].astype(int), s["lam"].astype(np.float32))
             for s, k in zip(stat, keep) if k]
    return {
        "masks": masks,
        "dims": (ops["Ly"], ops["Lx"]),
        "mean": ops["meanImg"].astype(np.float32),
        "meanE": ops.get("meanImgE", ops["meanImg"]).astype(np.float32),
        "roi_index": np.flatnonzero(keep),
        "source": str(plane_dir),
    }


def to_sparse(session, order="C", binary=False):
    """(npix, n) sparse matrix of footprints; order F matches CaImAn's convention."""
    Ly, Lx = session["dims"]
    rows, cols, vals = [], [], []
    for k, (yy, xx, w) in enumerate(session["masks"]):
        idx = yy * Lx + xx if order == "C" else xx * Ly + yy
        rows.append(idx)
        cols.append(np.full(len(idx), k))
        vals.append(np.ones(len(idx), np.float32) if binary else w)
    return sparse.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(Ly * Lx, len(session["masks"])))


def centroids(session):
    return np.array([[np.average(yy, weights=w), np.average(xx, weights=w)] if len(yy) and w.sum() > 0
                     else [np.nan, np.nan] for yy, xx, w in session["masks"]])


# ------------------------------------------------------------------- synthetic sessions


def displacement_field(dims, amp_px, scale_px, rot_deg=0.0, shift_px=(0.0, 0.0), seed=0):
    """Smooth random displacement u(y, x) (pixels) with RMS amplitude amp_px over ~scale_px,
    plus a rotation about the centre and a translation."""
    Ly, Lx = dims
    rng = np.random.default_rng(seed)
    uy, ux = np.zeros(dims, np.float32), np.zeros(dims, np.float32)
    if amp_px > 0:
        for u in (uy, ux):
            f = gaussian_filter(rng.standard_normal(dims), scale_px, mode="reflect")
            u += (f / np.sqrt((f**2).mean()) * amp_px / np.sqrt(2)).astype(np.float32)
    yy, xx = np.mgrid[0:Ly, 0:Lx].astype(np.float32)
    th = np.deg2rad(rot_deg)
    cy, cx = (Ly - 1) / 2, (Lx - 1) / 2
    uy += (np.sin(th) * (xx - cx) + np.cos(th) * (yy - cy)) - (yy - cy) + shift_px[0]
    ux += (np.cos(th) * (xx - cx) - np.sin(th) * (yy - cy)) - (xx - cx) + shift_px[1]
    return uy, ux


def _inverse_maps(uy, ux, n_iter=10):
    """Backward maps for cv2.remap: q -> p with p + u(p) = q (fixed-point inversion)."""
    Ly, Lx = uy.shape
    yy, xx = np.mgrid[0:Ly, 0:Lx].astype(np.float32)
    py, px = yy.copy(), xx.copy()
    for _ in range(n_iter):
        ry = cv2.remap(uy, px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        rx = cv2.remap(ux, px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        py, px = yy - ry, xx - rx
    return py, px


def warp_session(session, uy, ux, keep, gain=1.0, noise=0.0, footprint_jitter=0.0, seed=0):
    """Session seen after the tissue moved by u: images and footprints remapped.
    keep: boolean mask of ROIs detected in this session. footprint_jitter: fraction of
    boundary pixels randomly added/removed (segmentation variability)."""
    rng = np.random.default_rng(seed)
    Ly, Lx = session["dims"]
    py, px = _inverse_maps(uy, ux)
    out = {"dims": (Ly, Lx), "source": "synthetic"}
    for key in ("mean", "meanE"):
        img = cv2.remap(session[key], px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        img = img * gain + noise * img.std() * rng.standard_normal(img.shape).astype(np.float32)
        out[key] = img.astype(np.float32)
    masks, ids = [], []
    pad = int(np.ceil(np.abs(np.r_[uy.ravel(), ux.ravel()]).max())) + 3
    for k, (yy, xx, w) in enumerate(session["masks"]):
        if not keep[k]:
            continue
        # destination bounding box: source bbox moved by the local displacement
        cyy, cxx = int(np.mean(yy)), int(np.mean(xx))
        dy, dx = uy[cyy, cxx], ux[cyy, cxx]
        y0, y1 = max(int(yy.min() + dy) - pad, 0), min(int(yy.max() + dy) + pad + 1, Ly)
        x0, x1 = max(int(xx.min() + dx) - pad, 0), min(int(xx.max() + dx) + pad + 1, Lx)
        sy0, sy1 = max(yy.min() - 2, 0), min(yy.max() + 3, Ly)
        sx0, sx1 = max(xx.min() - 2, 0), min(xx.max() + 3, Lx)
        src = np.zeros((sy1 - sy0, sx1 - sx0), np.float32)
        src[yy - sy0, xx - sx0] = w
        mapy = py[y0:y1, x0:x1] - sy0
        mapx = px[y0:y1, x0:x1] - sx0
        dst = cv2.remap(src, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        m = dst > 0.1 * dst.max() if dst.max() > 0 else dst > 0
        if footprint_jitter > 0 and m.any():
            edge = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) ^ cv2.erode(
                m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            flip = edge & (rng.random(m.shape) < footprint_jitter)
            m = m ^ flip
        ny, nx = np.nonzero(m)
        if len(ny) < 5:
            continue
        masks.append((ny + y0, nx + x0, np.maximum(dst[ny, nx], 1e-3 * dst.max()).astype(np.float32)))
        ids.append(k)
    out["masks"] = masks
    out["ids"] = np.array(ids)
    return out


def synthetic_pair(session, amp_um, um_per_px, scale_um=150, rot_deg=0.0, shift_um=(0, 0),
                   p_detect=0.85, gain=1.0, noise=0.2, footprint_jitter=0.2, seed=0):
    """Two sessions from one real session: A = identity transform, B = deformed; each keeps an
    independent random 85% of the ROIs (detection variability). Identities known."""
    rng = np.random.default_rng(seed)
    n = len(session["masks"])
    keepA, keepB = rng.random(n) < p_detect, rng.random(n) < p_detect
    zero = np.zeros(session["dims"], np.float32)
    A = warp_session(session, zero, zero, keepA, noise=noise, footprint_jitter=footprint_jitter, seed=seed + 1)
    uy, ux = displacement_field(session["dims"], amp_um / um_per_px, scale_um / um_per_px, rot_deg,
                                (shift_um[0] / um_per_px, shift_um[1] / um_per_px), seed=seed + 2)
    B = warp_session(session, uy, ux, keepB, gain=gain, noise=noise, footprint_jitter=footprint_jitter,
                     seed=seed + 3)
    return A, B, (uy, ux)


# ----------------------------------------------------------------------------- metrics


def pair_metrics(pairs, s1, s2):
    """Precision/recall/F1 of matched pairs against identities (ids) of two sessions."""
    truth = set(np.intersect1d(s1["ids"], s2["ids"]))
    tp = sum(s1["ids"][i] == s2["ids"][j] for i, j in pairs)
    n_pred = len(pairs)
    prec = tp / n_pred if n_pred else float("nan")
    rec = tp / len(truth) if truth else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if n_pred and tp else 0.0
    return {"precision": prec, "recall": rec, "f1": f1, "n_true": len(truth), "n_pred": n_pred, "tp": int(tp)}


# ----------------------------------------------------------------------------- methods


def match_caiman(s1, s2, **kw):
    """CaImAn register_ROIs (current lab default: optical flow on templates, Jaccard + Hungarian,
    thresh_cost=0.7, max_dist=10 px). Templates: enhanced mean images unless kw['template']."""
    from caiman.base.rois import register_ROIs

    tkey = kw.pop("template", "mean")
    A1, A2 = to_sparse(s1, "F"), to_sparse(s2, "F")
    m1, m2, *_ = register_ROIs(A1, A2, s1["dims"], template1=s1[tkey], template2=s2[tkey],
                               plot_results=False, **kw)
    return list(zip(np.asarray(m1), np.asarray(m2)))


VENVS = Path("/home/wanglab/venvs")
ADAPTERS = Path(__file__).resolve().parent / "adapters"


def export_sessions(sessions, path):
    """npz with footprints as (n, Ly*Lx) CSR (C order) and mean / enhanced mean images."""
    out = {"dims": np.array(sessions[0]["dims"]), "n_sessions": len(sessions)}
    for s, ses in enumerate(sessions, 1):
        A = to_sparse(ses, "C").T.tocsr()
        out.update({f"A{s}_data": A.data, f"A{s}_indices": A.indices, f"A{s}_indptr": A.indptr,
                    f"A{s}_shape": np.array(A.shape), f"mean{s}": ses["mean"], f"meanE{s}": ses["meanE"]})
    np.savez(path, **out)


def _run_adapter(venv, script, sessions, extra=()):
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        inp, out = Path(td) / "in.npz", Path(td) / "out.npz"
        export_sessions(sessions, inp)
        res = subprocess.run([str(VENVS / venv / "bin" / "python"), "-I", str(ADAPTERS / script),
                              str(inp), str(out), *extra], capture_output=True, text=True)
        if res.returncode:
            raise RuntimeError(f"{script} failed:\n{res.stderr[-3000:]}")
        return dict(np.load(out))


def match_track2p(s1, s2, transform="affine", image="mean"):
    r = _run_adapter("track2p", "run_track2p.py", [s1, s2], ["--transform", transform, "--image", image])
    return list(zip(r["i1"], r["i2"]))


def labels_to_pairs(l1, l2):
    """Pairs of ROIs sharing a cluster label (>= 0) between two sessions."""
    idx2 = {lab: j for j, lab in enumerate(l2) if lab >= 0}
    return [(i, idx2[lab]) for i, lab in enumerate(l1) if lab >= 0 and lab in idx2]


def match_roicat(s1, s2, um_per_pixel=1.45, image="meanE"):
    r = _run_adapter("roicat", "run_roicat.py", [s1, s2],
                     ["--um-per-pixel", str(um_per_pixel), "--image", image])
    return labels_to_pairs(r["labels1"], r["labels2"])


def iou_matrix(s1, s2, max_dist_px=20):
    """Sparse-ish IoU between binary footprints of two sessions in the same frame."""
    B1, B2 = to_sparse(s1, binary=True), to_sparse(s2, binary=True)
    inter = (B1.T @ B2).toarray()
    a1, a2 = np.asarray(B1.sum(0)).ravel(), np.asarray(B2.sum(0)).ravel()
    iou = inter / np.maximum(a1[:, None] + a2[None, :] - inter, 1)
    d = np.linalg.norm(centroids(s1)[:, None] - centroids(s2)[None], axis=2)
    iou[~(d <= max_dist_px)] = 0  # also zero for empty ROIs (nan centroid)
    return iou


def gt_by_iou(s1, s2, sure=0.5, absent=0.2):
    """Reference pairs for two sessions in the same frame: mutual best IoU >= sure.
    ROIs whose best IoU lies in [absent, sure) are 'uncertain' and excluded from scoring."""
    iou = iou_matrix(s1, s2)
    b12, b21 = iou.argmax(1), iou.argmax(0)
    m1, m2 = iou.max(1), iou.max(0)
    pairs = {(i, b12[i]) for i in range(len(b12)) if m1[i] >= sure and b21[b12[i]] == i}
    unc1 = set(np.flatnonzero((m1 >= absent) & ~np.isin(np.arange(len(m1)), [p[0] for p in pairs])))
    unc2 = set(np.flatnonzero((m2 >= absent) & ~np.isin(np.arange(len(m2)), [p[1] for p in pairs])))
    return pairs, unc1, unc2


def score_pairs(pred, gt):
    """Precision / recall / F1 of predicted pairs vs (pairs, uncertain1, uncertain2)."""
    pairs, unc1, unc2 = gt
    p1 = {i for i, _ in pairs}
    p2 = {j for _, j in pairs}
    scored = [(i, j) for i, j in pred if not ((i in unc1 or j in unc2) and (i, j) not in pairs
                                              and i not in p1 and j not in p2)]
    tp = sum((i, j) in pairs for i, j in scored)
    prec = tp / len(scored) if scored else float("nan")
    rec = tp / len(pairs) if pairs else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if tp else 0.0
    return {"precision": prec, "recall": rec, "f1": f1, "n_true": len(pairs), "n_pred": len(scored), "tp": tp}


def deform(session, amp_um, um_per_px, scale_um=150, rot_deg=0.0, shift_um=(0, 0), seed=0):
    """Session with all ROIs kept, after a known deformation (ids = original index)."""
    uy, ux = displacement_field(session["dims"], amp_um / um_per_px, scale_um / um_per_px, rot_deg,
                                (shift_um[0] / um_per_px, shift_um[1] / um_per_px), seed=seed)
    return warp_session(session, uy, ux, np.ones(len(session["masks"]), bool), seed=seed)
