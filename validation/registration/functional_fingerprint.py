"""Functional check of cross-day matches: do matched cells respond alike?

For each session, the MATLAB-equivalent dff (piecewise-linear pre-stimulus baseline) of the
iscell ROIs is trial-averaged per stimulus (trial labels from the Bruker VoltageOutput files).
For a pair of sessions, a shared response profile is built from the stimuli both received
(matched by pulse width) and compared per ROI pair by Pearson correlation. Matched pairs are
compared with nearest-neighbour non-matched pairs (closest centroid in session 2 after the
affine map, excluding the match) and with random pairs.

Usage (module): profiles(export, tseries_dir) -> (profile per stim width, centroid), fingerprint(...)
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stim_response_analysis import DEFAULT_PARAMS, compute_dff, load_suite2p, params_from_bruker  # noqa: E402


def profiles(export, tseries_dir):
    """{pulse width (s): trial-averaged dff (n_roi, n_frames)} for the iscell ROIs."""
    p = dict(DEFAULT_PARAMS)
    p.update(params_from_bruker(tseries_dir))
    vt = np.asarray(p["vec_trial"])
    nf = round(p["fr"] * p["trial_duration"])
    F, Fneu, _ = load_suite2p(Path(export) / "suite2p" / "plane0")
    blocks = [len(vt)] if vt.max() == 1 else [int(np.sum(vt == s)) for s in range(1, vt.max() + 1)]
    dff, _, _ = compute_dff(F, Fneu, p, blocks)
    x3 = dff.reshape(len(dff), -1, nf)
    return {round(w, 3): x3[:, vt == s + 1].mean(1) for s, w in enumerate(p["stim_duration"])}


def shared_profile(pa, pb):
    widths = sorted(set(pa) & set(pb))
    return np.concatenate([pa[w] for w in widths], 1), np.concatenate([pb[w] for w in widths], 1), widths


def _corr_rows(a, b):
    a = a - a.mean(1, keepdims=True)
    b = b - b.mean(1, keepdims=True)
    return (a * b).sum(1) / np.sqrt((a**2).sum(1) * (b**2).sum(1) + 1e-12)


def fingerprint(pairs, prof_a, prof_b, cent_a, cent_b, seed=0):
    """Median response correlation for matched, nearest-neighbour non-matched and random pairs."""
    A, B, widths = shared_profile(prof_a, prof_b)
    P = np.array(pairs, int).reshape(-1, 2)
    if len(P) < 10:
        return {"n": len(P)}
    # affine map of session-b centroids onto a, from the matches
    X = np.c_[cent_b[P[:, 1]], np.ones(len(P))]
    coef, *_ = np.linalg.lstsq(X, cent_a[P[:, 0]], rcond=None)
    cb = np.c_[cent_b, np.ones(len(cent_b))] @ coef
    nn = []
    for i, j in P:
        d = np.linalg.norm(cb - cent_a[i], axis=1)
        d[j] = np.inf
        nn.append(int(np.argmin(d)))
    rng = np.random.default_rng(seed)
    rnd = rng.integers(0, len(B), len(P))
    r_match = _corr_rows(A[P[:, 0]], B[P[:, 1]])
    r_nn = _corr_rows(A[P[:, 0]], B[nn])
    r_rnd = _corr_rows(A[P[:, 0]], B[rnd])
    ok = np.isfinite(r_match) & np.isfinite(r_nn)
    return {"n": int(len(P)), "widths": widths, "r_match": float(np.nanmedian(r_match)),
            "r_neighbour": float(np.nanmedian(r_nn)), "r_random": float(np.nanmedian(r_rnd)),
            "frac_match_gt_neighbour": float(np.mean(r_match[ok] > r_nn[ok]))}
