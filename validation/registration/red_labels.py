"""tdTomato (Ch1) labels for GCaMP ROIs, used to estimate registration false positives.

Per run: mean of the raw Ch1 and Ch2 frames; the raw-Ch2 -> motion-corrected-mean shift
(phase correlation) is applied to Ch1, which shares the motion. Each ROI gets a red contrast
= mean Ch1 in the footprint / mean Ch1 in an annulus around it; red+ above a threshold chosen
by Otsu on the log contrast of all ROIs.

A matched pair with discordant labels is an error. With a fraction p of red+ ROIs and errors
pairing an ROI with an unrelated neighbour, a false-positive rate f produces a discordance
~ 2 p (1 - p) f, so f ~ discordance / (2 p (1 - p)).

Usage (as a module): red_image(tseries_dir, mcorr_mean), roi_red_contrast(session, red)
"""

from pathlib import Path

import cv2
import numpy as np
from skimage.filters import threshold_otsu
from skimage.registration import phase_cross_correlation
from tifffile import TiffFile


def raw_mean(tseries_dir, channel, max_frames=2000):
    files = sorted(Path(tseries_dir).glob(f"*_Ch{channel}_*.ome.tif"))[:max_frames]
    acc = None
    for f in files:
        # read only this file's own page (tifffile would otherwise assemble the whole OME series)
        with TiffFile(str(f)) as tif:
            img = tif.pages[0].asarray().astype(np.float64)
        acc = img if acc is None else acc + img
    return (acc / len(files)).astype(np.float32)


def red_image(tseries_dir, mcorr_mean, cache_dir=None):
    """Ch1 mean image in the motion-corrected frame of mcorr_mean (Ch2)."""
    cache = Path(cache_dir) / "raw_means_ch1_ch2.npz" if cache_dir else None
    if cache is not None and cache.exists():
        d = np.load(cache)
        ch1, ch2 = d["ch1"], d["ch2"]
    else:
        ch2, ch1 = raw_mean(tseries_dir, 2), raw_mean(tseries_dir, 1)
        if cache is not None:
            np.savez(cache, ch1=ch1, ch2=ch2)
    # the pipeline movie is vertically flipped relative to the raw Bruker frames
    ch1, ch2 = np.flipud(ch1), np.flipud(ch2)
    shift, _, _ = phase_cross_correlation(mcorr_mean, ch2, upsample_factor=10)
    M = np.float32([[1, 0, shift[1]], [0, 1, shift[0]]])
    return cv2.warpAffine(ch1, M, ch1.shape[::-1], flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT), shift


def roi_red_contrast(session, red, inner=2, outer=6):
    Ly, Lx = session["dims"]
    k_in = np.ones((2 * inner + 1,) * 2, np.uint8)
    k_out = np.ones((2 * outer + 1,) * 2, np.uint8)
    out = np.zeros(len(session["masks"]))
    for n, (yy, xx, _) in enumerate(session["masks"]):
        y0, y1 = max(yy.min() - outer - 1, 0), min(yy.max() + outer + 2, Ly)
        x0, x1 = max(xx.min() - outer - 1, 0), min(xx.max() + outer + 2, Lx)
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        m[yy - y0, xx - x0] = 1
        ring = cv2.dilate(m, k_out).astype(bool) & ~cv2.dilate(m, k_in).astype(bool)
        crop = red[y0:y1, x0:x1]
        out[n] = crop[m.astype(bool)].mean() / max(crop[ring].mean(), 1e-6) if ring.any() else np.nan
    return out


def red_labels(contrast):
    lc = np.log(np.clip(contrast, 1e-3, None))
    thr = threshold_otsu(lc[np.isfinite(lc)])
    return lc > thr, float(np.exp(thr))


def discordance_fp(pairs, lab1, lab2):
    """Discordance of red labels among matched pairs, and the implied false-positive rate."""
    if not pairs:
        return {"discordance": float("nan"), "fp_est": float("nan"), "n_pairs": 0}
    disc = np.mean([lab1[i] != lab2[j] for i, j in pairs])
    p = 0.5 * (lab1.mean() + lab2.mean())
    return {"discordance": float(disc), "fp_est": float(disc / (2 * p * (1 - p))), "n_pairs": len(pairs),
            "red_fraction": float(p)}
