"""Spatially-resolved figures of the F_anat z-motion correction approaches.

Shows, as maps over the FOV, how much residual z-contamination each granularity of
the F_anat subtraction leaves behind — **per-pixel**, **per-patch**, and
**per-ROI** — so the approaches can be compared visually, not just as scalar
recovery numbers.

Contamination metric (per pixel or per ROI): ``|corr(ΔF/F(t), zpos(t))|`` — high
where the trace tracks the z-trajectory (the artifact). A good correction shrinks
this map toward zero *without* removing the true activity.

Modes
-----
``synthetic`` : inject known activity into a real z-stack under response-coupled
    z-motion, correct with all three approaches, and quantify recovery against the
    ground-truth activity. F_anat predictor = the real z-stack registered to the
    FOV and sampled at the (ground-truth) per-frame z.
``real`` : a real motion-corrected movie (TIFF) + its z-stack; estimate zpos with
    the shipped ``compute_zcorrel`` (Pearson), build F_anat, apply the **per-ROI**
    correction (the production method), and map before/after contamination.

Run:
  python validation/plot_correction_spatial.py synthetic --real-zstack <ZSeries> --out DIR
  pixi run python validation/plot_correction_spatial.py real --mcorr-tiff <tif> \
      --zseries <ZSeries> --out DIR
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.benchmarks.bruker_io import load_bruker_zstack
from tests.benchmarks.synthetic_zstack import make_xy_trajectory
from tests.benchmarks.synthetic_activity import (
    detect_somata,
    make_active_functional_movie,
    make_stimulus_locked_traces,
    make_response_coupled_zmotion,
)
from tests.benchmarks.benchmark_correction_methods import (
    _register_zstack_to_fov,
    _correct_per_pixel,
    _correct_per_patch,
    _roi_trace,
)


def _dff_pixels(movie):
    """Per-pixel ΔF/F, shape (T, H*W)."""
    T = movie.shape[0]
    M = movie.reshape(T, -1)
    base = M.mean(0, keepdims=True)
    base = np.where(base == 0, 1.0, base)
    return M / base - 1.0


def _zcontam_map(movie, zpos):
    """Per-pixel |corr(ΔF/F, zpos)| as an (H, W) map."""
    T, H, W = movie.shape
    dff = _dff_pixels(movie)  # (T, HW)
    z0 = zpos - zpos.mean()
    a = dff - dff.mean(0, keepdims=True)
    num = (a * z0[:, None]).sum(0)
    den = np.sqrt((a**2).sum(0)) * np.sqrt((z0**2).sum()) + 1e-12
    return np.abs(num / den).reshape(H, W)


def _corr(a, b):
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def _roi_correct_movie(movie, f_anat, centers, r=3):
    """Apply the per-ROI OLS fit-and-subtract, written back onto ROI pixels.

    Produces a corrected movie for visualization: within each ROI disk, subtract
    ``slope * ΔF/F(F_anat_roi) * pixel_baseline`` (the MATLAB per-ROI correction,
    expressed per pixel so a spatial contamination map can be recomputed).
    Returns (corrected_movie, per_roi_slope).
    """
    T, H, W = movie.shape
    out = movie.astype(np.float32).copy()
    base = movie.mean(0)  # per-pixel baseline
    slopes = np.zeros(len(centers), np.float32)
    for i, (zc, cy, cx) in enumerate(centers):
        y0, y1 = max(0, cy - r), min(H, cy + r + 1)
        x0, x1 = max(0, cx - r), min(W, cx + r + 1)
        f = movie[:, y0:y1, x0:x1].mean(axis=(1, 2))
        a = f_anat[:, y0:y1, x0:x1].mean(axis=(1, 2))
        db = f / (f.mean() or 1.0) - 1.0
        dz = a / (a.mean() or 1.0) - 1.0
        dz0 = dz - dz.mean()
        den = np.sum(dz0**2)
        slope = float(np.sum((db - db.mean()) * dz0) / den) if den > 0 else 0.0
        slopes[i] = slope
        # subtract slope * dz0(t) * baseline_pixel across the disk
        patch_base = base[y0:y1, x0:x1]
        out[:, y0:y1, x0:x1] -= slope * dz0[:, None, None] * patch_base[None]
    return out, slopes


def _roi_mask(shape, centers, r=3):
    """Boolean union of ROI disks (square footprints of half-width r)."""
    H, W = shape
    mask = np.zeros((H, W), bool)
    for zc, cy, cx in centers:
        y0, y1 = max(0, cy - r), min(H, cy + r + 1)
        x0, x1 = max(0, cx - r), min(W, cx + r + 1)
        mask[y0:y1, x0:x1] = True
    return mask


def _panel_maps(fig, gs_row, maps, titles, fov, centers, vmax, roi_mask):
    """Draw a row of contamination maps sharing a color scale.

    Map subtitles report the mean |corr| **over ROI pixels** (where the extracted
    traces live and where the correction matters) — the whole-frame mean would
    hide per-ROI/per-patch gains that only touch cell footprints.
    """
    axes = []
    for k, (m, t) in enumerate(zip(maps, titles)):
        ax = fig.add_subplot(gs_row[k])
        if m is None:  # FOV reference panel
            ax.imshow(fov, cmap="gray")
            ax.scatter(
                centers[:, 2],
                centers[:, 1],
                s=14,
                facecolors="none",
                edgecolors="C1",
                linewidths=0.7,
            )
            ax.set_title(t, fontsize=12)
        else:
            ax.imshow(m, cmap="inferno", vmin=0, vmax=vmax)
            ax.scatter(
                centers[:, 2],
                centers[:, 1],
                s=10,
                facecolors="none",
                edgecolors="cyan",
                linewidths=0.4,
            )
            ax.set_title(f"{t}\nROI-pixel mean |corr| {np.nanmean(m[roi_mask]):.3f}", fontsize=12)
        ax.set_xticks([])
        ax.set_yticks([])
        axes.append(ax)
    return axes


def run_synthetic(args):
    vol, _ = load_bruker_zstack(args.real_zstack, channel=2, downsample=args.downsample)
    znom = (vol.shape[0] - 1) / 2.0
    T = args.n_frames

    centers = detect_somata(
        vol, n_cells=args.n_cells, min_distance=5, margin=8, z_center=znom, z_band=args.z_band
    )
    n = len(centers)

    base = None
    if args.real_zpos is not None and Path(args.real_zpos).exists():
        base = np.load(args.real_zpos)[args.real_zpos_key].astype(np.float32)
        if len(base) < T:
            base = np.tile(base, int(np.ceil(T / len(base))))
        base = base[:T]

    trueC, _, events, responsive, evw = make_stimulus_locked_traces(
        n, T, framerate=20, decay_time=0.15, n_events=args.n_events, seed=args.seed
    )
    base_bg = 0.4 * (base - base.mean()) if base is not None else None
    zoff = make_response_coupled_zmotion(
        T, events, base_zoff=base_bg, kick_amp=args.kick_amp, event_weights=evw, seed=args.seed
    )
    xy = make_xy_trajectory(T, 1.0, 8, seed=args.seed)
    movie, gt = make_active_functional_movie(
        vol,
        znom,
        zoff,
        centers,
        trueC,
        xy_offsets=xy,
        deform_amp=0.6,
        deform_wave=True,
        activity_gain=1500,
        seed=args.seed,
    )
    z_true = gt["z_true"]

    # F_anat predictor: real z-stack registered to the FOV, sampled at the z path.
    fov = movie.mean(0)
    reg = _register_zstack_to_fov(np.flip(vol, axis=1), fov)
    zi = np.clip(z_true.astype(int), 0, reg.shape[0] - 1)
    f_anat = reg[zi]  # (T, H, W)

    # Corrected movies for the three granularities.
    mov_pix = _correct_per_pixel(movie, f_anat)
    mov_patch = _correct_per_patch(movie, f_anat, n_patches=8)
    mov_roi, roi_slopes = _roi_correct_movie(movie, f_anat, centers)

    # Per-pixel contamination maps (shared scale).
    zm_raw = _zcontam_map(movie, z_true)
    zm_pix = _zcontam_map(mov_pix, z_true)
    zm_patch = _zcontam_map(mov_patch, z_true)
    zm_roi = _zcontam_map(mov_roi, z_true)
    vmax = np.percentile(zm_raw, 99)
    roi_mask = _roi_mask(fov.shape, centers)

    # Recovery vs ground-truth activity, per method, on ROI traces.
    true_dff = trueC / (trueC.mean(1, keepdims=True) + 1e-6) - 1.0

    def _recov(mov):
        rs, zr = [], []
        for i, (zc, cy, cx) in enumerate(centers):
            t = _roi_trace(mov, cy, cx)
            d = t / (t.mean() or 1.0) - 1.0
            rs.append(_corr(d, true_dff[i]))
            zr.append(abs(_corr(d, z_true)))
        return np.array(rs), np.array(zr)

    r_none, z_none = _recov(movie)
    r_pix, z_pix = _recov(mov_pix)
    r_patch, z_patch = _recov(mov_patch)
    r_roi, z_roi = _recov(mov_roi)
    methods = ["none", "per-pixel", "per-patch", "per-ROI"]
    recov = [r_none, r_pix, r_patch, r_roi]
    zres = [z_none, z_pix, z_patch, z_roi]

    # ── Figure ───────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(20, 11))
    gs = fig.add_gridspec(2, 5, height_ratios=[1.25, 1.0], hspace=0.32, wspace=0.18)
    row0 = [gs[0, k] for k in range(5)]
    _panel_maps(
        fig,
        row0,
        [None, zm_raw, zm_pix, zm_patch, zm_roi],
        ["FOV + ROIs", "raw (before)", "per-pixel", "per-patch", "per-ROI"],
        fov,
        centers,
        vmax,
        roi_mask,
    )
    # shared colorbar
    cax = fig.add_axes([0.92, 0.55, 0.008, 0.32])
    sm = plt.cm.ScalarMappable(cmap="inferno", norm=plt.Normalize(0, vmax))
    fig.colorbar(sm, cax=cax).set_label("|corr(ΔF/F, z)|", fontsize=12)

    # Bottom row: recovery bars, residual-z bars, patch-scale map, example traces.
    axb = fig.add_subplot(gs[1, 0])
    means = [np.nanmean(r) for r in recov]
    sems = [np.nanstd(r) / np.sqrt(np.sum(np.isfinite(r))) for r in recov]
    axb.bar(methods, means, yerr=sems, color=["0.6", "C2", "C4", "C0"])
    axb.set_ylabel("recovery r (trace vs true)")
    axb.set_title("Activity recovery", fontsize=12)
    axb.tick_params(axis="x", labelrotation=20, labelsize=11)

    axz = fig.add_subplot(gs[1, 1])
    zmeans = [np.nanmean(z) for z in zres]
    zsems = [np.nanstd(z) / np.sqrt(np.sum(np.isfinite(z))) for z in zres]
    axz.bar(methods, zmeans, yerr=zsems, color=["0.6", "C2", "C4", "C0"])
    axz.set_ylabel("residual |corr(trace, z)|")
    axz.set_title("Residual z-contamination (lower=better)", fontsize=12)
    axz.tick_params(axis="x", labelrotation=20, labelsize=11)

    # example: a visible cell where the per-ROI correction clearly helped (largest
    # residual-z reduction among reasonably in-focus, contaminated cells) — so the
    # example illustrates the effect rather than a cell the correction can't touch.
    axe = fig.add_subplot(gs[1, 2:5])
    focus = np.array(
        [np.mean(np.exp(-0.5 * ((z_true - centers[i, 0]) / 2.0) ** 2)) for i in range(len(centers))]
    )
    cand = np.where((focus >= 0.15) & (np.nan_to_num(z_none) >= 0.2))[0]
    if len(cand) == 0:
        cand = np.where(focus >= 0.15)[0]
    if len(cand) == 0:
        cand = np.argsort(focus)[::-1][:5]
    reduction = np.nan_to_num(z_none[cand]) - np.nan_to_num(z_roi[cand])
    sel = int(cand[np.argmax(reduction)])
    cy, cx = centers[sel, 1], centers[sel, 2]

    d_before = _roi_trace(movie, cy, cx)
    d_before = d_before / (d_before.mean() or 1.0) - 1.0
    d_after = _roi_trace(mov_roi, cy, cx)
    d_after = d_after / (d_after.mean() or 1.0) - 1.0
    for e in events:
        axe.axvline(e, color="0.85", lw=0.7, zorder=0)
    # true activity scaled to the ΔF/F range of the corrected trace (shape ref).
    tt = true_dff[sel]
    scl = (np.percentile(d_after, 98) - np.percentile(d_after, 2)) / (
        np.percentile(tt, 98) - np.percentile(tt, 2) + 1e-9
    )
    axe.plot(tt * scl + np.median(d_after), "k", lw=1.0, label="true (scaled)")
    axe.plot(d_before, color="0.6", lw=0.8, label="before")
    axe.plot(d_after, color="C0", lw=0.9, label="per-ROI corrected")
    axe.set_ylabel("ΔF/F", fontsize=10)
    axz2 = axe.twinx()
    axz2.plot(z_true, color="C3", lw=0.7, alpha=0.5)
    axz2.set_ylabel("z-plane", color="C3", fontsize=9)
    axe.set_title(
        f"Example cell {sel} (focus {focus[sel]:.2f}): r {r_none[sel]:.2f}→{r_roi[sel]:.2f}, "
        f"resid-z {z_none[sel]:.2f}→{z_roi[sel]:.2f}",
        fontsize=12,
    )
    axe.legend(loc="upper right", fontsize=7, ncol=3)
    axe.set_xlabel("frame")
    axe.set_yticks([])

    pop = true_dff.mean(0)
    coupling = _corr(pop, z_true)
    fig.suptitle(
        f"F_anat z-correction — granularity comparison on synthetic ground truth "
        f"({n} cells, response-coupled z-motion, activity–z r={coupling:.2f})",
        fontsize=16,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out / "correction_spatial_synthetic.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    stats = {
        "n_cells": int(n),
        "activity_z_coupling": coupling,
        "map_roi_pixel_mean_contam": {
            "raw": float(np.nanmean(zm_raw[roi_mask])),
            "per_pixel": float(np.nanmean(zm_pix[roi_mask])),
            "per_patch": float(np.nanmean(zm_patch[roi_mask])),
            "per_roi": float(np.nanmean(zm_roi[roi_mask])),
        },
        "recovery_r_mean": {m: float(np.nanmean(r)) for m, r in zip(methods, recov)},
        "residual_z_mean": {m: float(np.nanmean(z)) for m, z in zip(methods, zres)},
    }
    (args.out / "correction_spatial_synthetic.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))
    print(f"wrote {args.out/'correction_spatial_synthetic.png'}")


def _detect_somata_2d(img, n_cells=80, min_distance=5, margin=8):
    """Peak-local-max on a 2D DoG of a FOV image → (n, 2) (y, x) soma centers."""
    from scipy.ndimage import gaussian_filter as gf2
    from skimage.feature import peak_local_max

    im = img.astype(np.float32)
    dog = gf2(im, 1.5) - gf2(im, 4.0)
    peaks = peak_local_max(dog, min_distance=min_distance, exclude_border=margin, threshold_rel=0.2)
    if len(peaks) == 0:
        return np.empty((0, 2), int)
    order = np.argsort(dog[tuple(peaks.T)])[::-1]
    return peaks[order[:n_cells]].astype(int)


def run_real(args):
    """Per-ROI correction on a real motion-corrected recording (no ground truth)."""
    import tifffile
    from skimage.measure import block_reduce
    from tests.benchmarks.synthetic_zstack import save_caiman_memmap, save_zstack_tiff
    from modules.compute_zcorr import compute_zcorrel

    # Load the mcorr'd movie (downsample for tractability) and the z-stack.
    with tifffile.TiffFile(args.mcorr_tiff) as tf:
        n = len(tf.pages)
        idx = range(0, n, 1)
        movie = np.stack([tf.pages[j].asarray() for j in idx]).astype(np.float32)
    if args.downsample > 1:
        movie = block_reduce(movie, (1, args.downsample, args.downsample), np.mean).astype(
            np.float32
        )
    # z-stack is loaded to match the movie's on-disk resolution (the asset may
    # already be spatially downsampled); --zseries-downsample sets that factor.
    vol, _ = load_bruker_zstack(args.zseries, channel=2, downsample=args.zseries_downsample)
    h = min(vol.shape[1], movie.shape[1])
    w = min(vol.shape[2], movie.shape[2])
    vol, movie = vol[:, :h, :w], movie[:, :h, :w]

    # Estimate zpos with the shipped Pearson estimator, then build F_anat.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        save_zstack_tiff(vol, tmp / "z.tif")
        dd = tmp / "b" / "i"
        dd.mkdir(parents=True)
        mp = save_caiman_memmap(movie, dd)
        zc = compute_zcorrel(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)
    zpos = zc["zpos"].astype(float)

    fov = movie.mean(0)
    reg = _register_zstack_to_fov(np.flip(vol, axis=1), fov)
    zi = np.clip(zpos.astype(int), 0, reg.shape[0] - 1)
    f_anat = reg[zi]

    centers2d = _detect_somata_2d(fov, n_cells=args.n_cells)
    # give each a dummy z so it matches the (z, y, x) interface
    centers = np.column_stack([np.zeros(len(centers2d), int), centers2d])

    mov_roi, slopes = _roi_correct_movie(movie, f_anat, centers)

    zres_before = np.zeros(len(centers))
    zres_after = np.zeros(len(centers))
    for i, (zc_, cy, cx) in enumerate(centers):
        tb = _roi_trace(movie, cy, cx)
        ta = _roi_trace(mov_roi, cy, cx)
        db = tb / (tb.mean() or 1.0) - 1.0
        da = ta / (ta.mean() or 1.0) - 1.0
        zres_before[i] = abs(_corr(db, zpos))
        zres_after[i] = abs(_corr(da, zpos))

    # Precompute ΔF/F traces once (for the example panels).
    dff_b = np.zeros((len(centers), movie.shape[0]), np.float32)
    dff_a = np.zeros_like(dff_b)
    for i, (zc_, cy, cx) in enumerate(centers):
        tb = _roi_trace(movie, cy, cx)
        ta = _roi_trace(mov_roi, cy, cx)
        dff_b[i] = tb / (tb.mean() or 1.0) - 1.0
        dff_a[i] = ta / (ta.mean() or 1.0) - 1.0

    # ── Figure: 3 maps on top, a variety of example traces below ──────────────
    n_ex = 6
    # Rank by how much the correction actually changed the trace's z-coupling,
    # among reasonably contaminated ROIs — these are where correction matters.
    contaminated = np.where(zres_before >= np.percentile(zres_before, 40))[0]
    effect = (zres_before - zres_after)[contaminated]
    sel = contaminated[np.argsort(effect)[::-1][:n_ex]]

    fig = plt.figure(figsize=(16, 11))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.3, 0.85, 0.85], hspace=0.4, wspace=0.15)
    vmax = np.percentile(zres_before, 95)

    ax0 = fig.add_subplot(gs[0, 0])
    ax0.imshow(fov, cmap="gray")
    ax0.scatter(centers[:, 2], centers[:, 1], s=16, facecolors="none", edgecolors="C1", lw=0.7)
    ax0.scatter(centers[sel, 2], centers[sel, 1], s=45, facecolors="none", edgecolors="C0", lw=1.3)
    ax0.set_title(f"FOV + {len(centers)} ROIs (examples circled)", fontsize=11)
    ax0.axis("off")

    for k, (vals, ttl) in enumerate(
        [(zres_before, "before"), (zres_after, "after per-ROI")], start=1
    ):
        ax = fig.add_subplot(gs[0, k])
        ax.imshow(fov, cmap="gray", alpha=0.5)
        sc = ax.scatter(
            centers[:, 2],
            centers[:, 1],
            c=vals,
            cmap="inferno",
            vmin=0,
            vmax=vmax,
            s=40,
            edgecolors="k",
            linewidths=0.3,
        )
        ax.set_title(f"ROI residual |corr(ΔF/F, z)|\n{ttl}  (mean {vals.mean():.3f})", fontsize=11)
        ax.axis("off")
        fig.colorbar(sc, ax=ax, fraction=0.046)

    for j, i in enumerate(sel):
        ax = fig.add_subplot(gs[1 + j // 3, j % 3])
        ax.plot(dff_b[i], color="0.6", lw=0.8, label="before")
        ax.plot(dff_a[i], color="C0", lw=0.9, label="corrected")
        axz = ax.twinx()
        axz.plot(zpos, color="C3", lw=0.6, alpha=0.4)
        axz.set_yticks([])
        ax.set_title(f"ROI {i}: resid-z {zres_before[i]:.2f}→{zres_after[i]:.2f}", fontsize=9)
        ax.set_ylabel("ΔF/F", fontsize=8)
        ax.tick_params(labelsize=7)
        if j == 0:
            ax.legend(loc="upper right", fontsize=7, ncol=2)
        if j // 3 == 1:
            ax.set_xlabel("frame", fontsize=8)

    fig.suptitle(
        f"Per-ROI z-correction on real data ({Path(args.mcorr_tiff).stem}) — mean residual-z "
        f"{zres_before.mean():.3f} → {zres_after.mean():.3f}; examples = ROIs most changed by "
        "correction",
        fontsize=14,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out / "correction_spatial_real.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    stats = {
        "n_rois": int(len(centers)),
        "mean_residual_z_before": float(zres_before.mean()),
        "mean_residual_z_after": float(zres_after.mean()),
    }
    (args.out / "correction_spatial_real.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))
    print(f"wrote {args.out/'correction_spatial_real.png'}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    ps = sub.add_parser("synthetic")
    ps.add_argument("--real-zstack", type=Path, required=True)
    ps.add_argument("--downsample", type=int, default=2)
    ps.add_argument("--n-frames", type=int, default=500)
    ps.add_argument("--n-cells", type=int, default=60)
    ps.add_argument("--z-band", type=int, default=6)
    ps.add_argument("--n-events", type=int, default=18)
    ps.add_argument("--kick-amp", type=float, default=1.8)
    ps.add_argument(
        "--real-zpos",
        type=Path,
        default=Path(__file__).parent / "report" / "figures" / "zpos_single.npz",
    )
    ps.add_argument("--real-zpos-key", default="zpos_caiman")
    ps.add_argument("--out", type=Path, required=True)
    ps.add_argument("--seed", type=int, default=1)

    pr = sub.add_parser("real")
    pr.add_argument("--mcorr-tiff", type=Path, required=True)
    pr.add_argument("--zseries", type=Path, required=True)
    pr.add_argument(
        "--downsample",
        type=int,
        default=1,
        help="further spatial downsample of the (already-mcorr'd) movie tiff",
    )
    pr.add_argument(
        "--zseries-downsample",
        type=int,
        default=3,
        help="downsample of the raw z-stack to match the movie resolution",
    )
    pr.add_argument("--n-cells", type=int, default=80)
    pr.add_argument("--out", type=Path, required=True)

    args = p.parse_args()
    if args.mode == "synthetic":
        run_synthetic(args)
    elif args.mode == "real":
        run_real(args)


if __name__ == "__main__":
    main()
