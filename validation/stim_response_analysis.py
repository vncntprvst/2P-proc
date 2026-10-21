"""Python port of the stimulus-response part of Analysis_2P ``analyze_2p_with_Beh_func.m``.

Reproduces, from a pipeline export (Suite2p + ``F_anat_non_rigid*.tiff``), the
trial-averaged response heatmaps used to judge the non-rigid z-motion
subtraction (``subtract_z = 'nonrigid'`` vs ``'none'``), following the MATLAB
reference step by step (line numbers refer to analyze_2p_with_Beh_func.m):

  1) trial structure from the randomized stimulus sequence           (l.121-188)
  2) Suite2p F of iscell ROIs, uniform ROI pixel lists               (l.193-222)
  3) dff with a piecewise-linear baseline fitted on pre-stim frames  (l.307-333)
  4) non-rigid z-correction: F_cell_anat -> dffz -> OLS slope -> subtract (l.340-414)
  5) bad-neuron removal (F0, R2 > 0.25, max SNR < 6, noise level)    (l.446-520)
  6) baseline-std normalisation, trial averages per stimulus         (l.570-624)
 11) rastermap ordering on resp_norm with trial borders zeroed      (l.938-983)
 12) heatmap + excitation/suppression maps per 1-s window           (l.1036-1067)

Only the 'F' / 'raw' path is ported (no OASIS deconvolution, no DLC); wipe
trials are passed in as a boolean vector (see ``behavior_wipes.py``).

Usage
-----
    python validation/stim_response_analysis.py <export_dir> --out DIR \
        [--wipes wipes.npz] [--stim 4]
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Defaults for Scnn1aAi14_D1M2/08292026/run1 (laser, 5 durations at 0.3 W).
# rand_stim_seq is the one in params_matlab_template.json; the Bruker voltage
# outputs differ at block position 11 (see ``bruker_stim_sequence``).
DEFAULT_PARAMS = {
    "fr": 20.0,
    "trial_duration": 4.0,
    "stim_delay": 1.0,
    "rand_stim_seq": [1, 4, 5, 1, 4, 2, 5, 5, 3, 2, 4, 3, 2, 4, 2, 5, 3, 1, 1, 3],
    "rand_rep": 5,
    "stim_duration": [0.075, 0.125, 0.175, 0.225, 0.3],
    "intensity": 0.3,  # W
    "target": "E2",
    "virus": "AAV.PHP.eB.syn.riboL1.GCAMP8m",
    "threshold_resp": 0.0,  # min mean F0 (list-file parameter, run specific)
    "rastermap": {"n_clusters": 100, "n_PCs": 200, "locality": 0.75, "lag": 3, "mean_time": True},
}


def bruker_stim_sequence(tseries_dir):
    """Per-cycle laser pulse width (s) read from the Bruker VoltageOutput xmls."""
    import xml.etree.ElementTree as ET

    widths = []
    for f in sorted(Path(tseries_dir).glob("*_Cycle*_VoltageOutput_001.xml")):
        root = ET.parse(f).getroot()
        w = root.find("Waveform").find("WaveformComponent_PulseTrain")
        widths.append(float(w.findtext("PulseWidth")) / 1000)
    return np.array(widths)


def trial_vector(p):
    """vec_trial: 1-based stim ID of each trial (MATLAB l.121-132, randomized run).

    An explicit p["vec_trial"] (e.g. from ``params_from_bruker``) takes precedence.
    """
    if "vec_trial" in p:
        return np.asarray(p["vec_trial"])
    return np.tile(np.asarray(p["rand_stim_seq"]), p["rand_rep"])


def params_from_bruker(tseries_dir, intensity=0.3, target="E2"):
    """Trial structure from what Bruker delivered: stim IDs = rank of the laser pulse width."""
    import xml.etree.ElementTree as ET

    widths = bruker_stim_sequence(tseries_dir)
    durations = np.unique(widths)
    tseries_dir = Path(tseries_dir)
    root = ET.parse(tseries_dir / f"{tseries_dir.name}.xml").getroot()
    # saved-frame rate from timestamps within the first cycle (framePeriod ignores averaging)
    t = [float(f.get("relativeTime")) for f in root.find("Sequence").findall("Frame")]
    period = np.median(np.diff(t))
    n_frames = len(root.findall(".//Frame"))
    return {
        "vec_trial": (np.searchsorted(durations, widths) + 1).tolist(),
        "stim_duration": durations.tolist(),
        "fr": round(1 / period),
        "trial_duration": round(n_frames / len(widths) * period, 1),
        "intensity": intensity,
        "target": target,
    }


def load_suite2p(plane_dir, with_lam=False, iscell_file="iscell.npy"):
    plane_dir = Path(plane_dir)
    iscell = np.load(plane_dir / iscell_file)[:, 0].astype(bool)
    F = np.load(plane_dir / "F.npy")[iscell].astype(np.float64)
    Fneu = np.load(plane_dir / "Fneu.npy")[iscell].astype(np.float64)
    stat = np.load(plane_dir / "stat.npy", allow_pickle=True)[iscell]
    rois = [(s["ypix"].astype(int), s["xpix"].astype(int)) for s in stat]
    if with_lam:
        return F, Fneu, rois, [s["lam"] / s["lam"].sum() for s in stat]
    return F, Fneu, rois


def load_cnmf(hdf5_path):
    """CaImAn F per MATLAB 'caiman' branch (l.224-264, raw, not denoised).

    F = (C + YrA) * mean(A over ROI pixels) + sum_b quantile(f_b, 0.1) * mean(b_b over ROI pixels).
    Returns F, a background trace per ROI (for the neuropil step), ROI pixel lists and A weights.
    """
    from caiman.source_extraction.cnmf.cnmf import load_CNMF

    est = load_CNMF(str(hdf5_path), n_processes=1).estimates
    A = est.A.tocsc()
    d1, d2 = est.dims
    q_bg = np.quantile(est.f, 0.1, axis=1)
    b = np.asarray(est.b)
    bg_trace = (b.mean(0) @ est.f)  # mean over FOV of the background, per frame
    F, rois, lams, Fbg = [], [], [], []
    for i in range(A.shape[1]):
        idx = A[:, i].nonzero()[0]
        w = A[idx, i].toarray().ravel()
        yy, xx = np.unravel_index(idx, (d1, d2), order="F")
        F.append((est.C[i] + est.YrA[i]) * w.mean() + (b[idx].mean(0) * q_bg).sum())
        rois.append((yy.astype(int), xx.astype(int)))
        lams.append(w / w.sum())
        Fbg.append(bg_trace)
    return np.array(F, np.float64), np.array(Fbg, np.float64), rois, lams


def load_extraction(export_dir, with_lam=False, iscell_file=None):
    """Suite2p (suite2p/plane0) or CNMF (cnmf_result.hdf5) outputs of a pipeline export.

    iscell_file (Suite2p) defaults to $ISCELL_FILE or iscell.npy, e.g. a curated iscell_manuel.npy.
    """
    import os

    iscell_file = iscell_file or os.environ.get("ISCELL_FILE", "iscell.npy")
    export_dir = Path(export_dir)
    if (export_dir / "cnmf_result.hdf5").exists():
        F, Fbg, rois, lams = load_cnmf(export_dir / "cnmf_result.hdf5")
        return (F, Fbg, rois, lams) if with_lam else (F, Fbg, rois)
    plane = next(d for d in [export_dir / "suite2p" / "plane0", export_dir / "plane0", export_dir]
                 if (d / "F.npy").exists())
    return load_suite2p(plane, with_lam, iscell_file)


def f_cell_anat_variants(f_anat_path, rois, lams, chunk=500):
    """Unsmoothed projections of F_anat on ROIs: uniform pixel mean and Suite2p lam-weighted.

    Temporal smoothing commutes with the spatial projection, so movmean variants can be
    applied to these traces afterwards (``movmean3``).
    """
    from tifffile import TiffFile

    with TiffFile(f_anat_path) as tif:
        n = len(tif.pages)
        uni = np.zeros((len(rois), n), np.float64)
        lam = np.zeros((len(rois), n), np.float64)
        for s in range(0, n, chunk):
            mov = np.stack([tif.pages[i].asarray() for i in range(s, min(s + chunk, n))])
            mov = mov.astype(np.float32)
            for i, ((yy, xx), w) in enumerate(zip(rois, lams)):
                px = mov[:, yy, xx]
                uni[i, s : s + len(mov)] = px.mean(1)
                lam[i, s : s + len(mov)] = px @ w
    return uni, lam


def movmean3(x):
    """MATLAB movmean(x, 3, 2): centred 3-point mean, shrinking at the ends."""
    y = x.copy()
    y[:, 1:-1] = (x[:, :-2] + x[:, 1:-1] + x[:, 2:]) / 3
    y[:, 0] = x[:, :2].mean(1)
    y[:, -1] = x[:, -2:].mean(1)
    return y


def f_cell_anat(f_anat_path, rois, chunk=500):
    """Uniform mean over ROI pixels of the 3-frame moving average of F_anat (l.346-377)."""
    from scipy.ndimage import uniform_filter1d
    from tifffile import TiffFile

    with TiffFile(f_anat_path) as tif:
        n = len(tif.pages)
        out = np.zeros((len(rois), n), np.float64)
        # read with a 1-frame halo so the 3-point movmean is exact at chunk edges
        for s in range(0, n, chunk):
            a, b = max(s - 1, 0), min(s + chunk + 1, n)
            mov = np.stack([tif.pages[i].asarray() for i in range(a, b)]).astype(np.float32)
            # MATLAB movmean shrinks the window at the ends (mean of 2 frames)
            sm = uniform_filter1d(mov, 3, axis=0, mode="nearest")
            if a == 0:
                sm[0] = mov[:2].mean(0)
            if b == n:
                sm[-1] = mov[-2:].mean(0)
            sm = sm[s - a : s - a + min(chunk, n - s)]
            for i, (yy, xx) in enumerate(rois):
                out[i, s : s + sm.shape[0]] = sm[:, yy, xx].mean(axis=1)
    return out


def _poly1_baseline(y, x, mask):
    """Least-squares line fitted on y[mask], evaluated on all x (MATLAB fit poly1 + Exclude)."""
    A = np.stack([x[mask], np.ones(mask.sum())], 1)
    coef, *_ = np.linalg.lstsq(A, y[:, mask].T, rcond=None)  # (2, n_neuron)
    return (np.outer(x, coef[0]) + coef[1]).T


def compute_dff(F, Fneu, p, n_trial_per_block):
    """dff with piecewise-linear baseline on pre-stim frames (l.307-333)."""
    nf_trial = round(p["fr"] * p["trial_duration"])
    nf_delay = round(p["fr"] * p["stim_delay"])
    T = F.shape[1]
    baseline = np.tile(np.r_[np.ones(nf_delay, bool), np.zeros(nf_trial - nf_delay, bool)], T // nf_trial)
    F = F.copy()
    F0 = np.zeros_like(F)
    limits = np.r_[0, np.cumsum(n_trial_per_block) * nf_trial]
    subtract_bg = not any(k in p["virus"] for k in ("soma", "Ribo", "ribo"))
    for a, b in zip(limits[:-1], limits[1:]):
        x = np.arange(a + 1, b + 1, dtype=float)
        m = baseline[a:b]
        F0[:, a:b] = _poly1_baseline(F[:, a:b], x, m)
        if subtract_bg:
            bg = 0.7 * Fneu[:, a:b]
            F[:, a:b] = F[:, a:b] - bg + _poly1_baseline(bg, x, m)
    dff = F / F0 - 1
    return dff, F0, baseline


def zcorrect_nonrigid(dff, F_cell_anat, baseline, n_trial_per_block, nf_trial):
    """dffz from F_cell_anat (baseline-mean normalised per block), OLS slope, subtract (l.395-414)."""
    dffz = np.zeros_like(dff)
    limits = np.r_[0, np.cumsum(n_trial_per_block) * nf_trial]
    for a, b in zip(limits[:-1], limits[1:]):
        blk = F_cell_anat[:, a:b]
        dffz[:, a:b] = blk / blk[:, baseline[a:b]].mean(1, keepdims=True) - 1
    md, mz = dff.mean(1, keepdims=True), dffz.mean(1, keepdims=True)
    slope = ((dff - md) * (dffz - mz)).sum(1) / ((dffz - mz) ** 2).sum(1)
    dffz = dffz * slope[:, None]
    R2 = 1 - ((dff - dffz) ** 2).sum(1) / (dff**2).sum(1)
    return dff - dffz, dffz, slope, R2


def bad_neurons(dff, F0, R2, baseline, p):
    """MATLAB l.446-475."""
    mean_F0 = F0[:, baseline].mean(1)
    max_snr = dff.max(1) / dff[:, baseline].std(1, ddof=1)
    noise = np.median(np.abs(np.diff(dff * 100, axis=1)), axis=1) / np.sqrt(p["fr"])
    bad = (
        (mean_F0 < p["threshold_resp"])
        | (R2 > 0.25)
        | ~np.isfinite(dff).any(1)
        | (max_snr < 6)
        | (noise > 10)
    )
    return bad, dict(mean_F0=mean_F0, max_snr=max_snr, noise=noise)


def rastermap_sort(resp_norm, frame_mask, p):
    """Rastermap isort (MATLAB sort_ROI_by_rastermap / run_rastermap.py), via an isolated uv env."""
    rp = p["rastermap"]
    x = resp_norm.copy()
    x[:, ~frame_mask] = 0
    with tempfile.TemporaryDirectory() as td:
        np.save(Path(td) / "x.npy", x.astype(np.float32))
        code = (
            "import numpy as np,sys; from rastermap import Rastermap\n"
            f"x=np.load('{td}/x.npy')\n"
            f"m=Rastermap(n_clusters={rp['n_clusters']},n_PCs={rp['n_PCs']},locality={rp['locality']},"
            f"time_lag_window={rp['lag']},mean_time={rp['mean_time']}).fit(x)\n"
            f"np.save('{td}/isort.npy',np.argsort(m.embedding[:,0]))\n"
        )
        subprocess.run(
            ["uv", "run", "--no-project", "--python", "3.11", "--with", "rastermap==1.0",
             "python", "-c", code],
            check=True, capture_output=True,
        )
        return np.load(Path(td) / "isort.npy")


def analyze(F, Fneu, rois, p, F_cell_anat=None, subtract_z="none"):
    """Run MATLAB steps 3-6 for one condition; returns a dict of per-ROI arrays."""
    nf_trial = round(p["fr"] * p["trial_duration"])
    vec_trial = trial_vector(p)
    n_stim = vec_trial.max()
    n_trial_per_block = [np.sum(vec_trial == s) for s in range(1, n_stim + 1)]
    dff, F0, baseline = compute_dff(F, Fneu, p, n_trial_per_block)
    dff_before = dff.copy()
    if subtract_z == "nonrigid":
        dff, dffz, slope, R2 = zcorrect_nonrigid(dff, F_cell_anat, baseline, n_trial_per_block, nf_trial)
    else:
        dffz, slope, R2 = np.zeros_like(dff), np.zeros(len(dff)), np.full(len(dff), np.nan)
    bad, stats = bad_neurons(dff, F0, R2, baseline, p)
    keep = ~bad
    dff = dff[keep]
    std_base = dff[:, baseline].std(1, ddof=1)
    resp_norm = dff / std_base[:, None]
    # trials x neurons x frames
    stim_ind = np.repeat(vec_trial, nf_trial)
    by_stim = {
        s: dff[:, stim_ind == s].reshape(len(dff), -1, nf_trial).transpose(1, 0, 2)
        for s in range(1, n_stim + 1)
    }
    return dict(
        keep=keep, dff=dff, dff_before=dff_before[keep], dffz=dffz[keep], slope=slope[keep],
        R2=R2[keep], resp_norm=resp_norm, by_stim=by_stim, baseline=baseline,
        vec_trial=vec_trial, stats=stats, rois=[r for r, k in zip(rois, keep) if k],
    )


def roi_map(rois, order, shape):
    m = np.full(shape, len(order), int)
    for rank, i in enumerate(order):
        m[rois[i]] = rank
    return m


def plot_avg_resp(avg, rois, order, p, lim, title, shape=(765, 765), ax_heat=None, fig=None):
    """Heatmap (rows = ROIs in rastermap order) + 4 excitation / suppression maps (make_fig_avg_resp.m)."""
    fr = p["fr"]
    nf_delay = round(p["stim_delay"] * fr)
    nf = avg.shape[1]
    t = np.arange(1, nf + 1) / fr
    avg = avg[order]
    fig = plt.figure(figsize=(14, 5.2))
    gs = fig.add_gridspec(2, 5, width_ratios=[1.2, 1, 1, 1, 1])
    ax = fig.add_subplot(gs[:, 0])
    im = ax.imshow(avg, aspect="auto", cmap="viridis", vmin=lim[0], vmax=lim[1],
                   extent=[t[0] - 0.5 / fr, t[-1] + 0.5 / fr, len(avg) + 0.5, 0.5],
                   interpolation="nearest")
    ax.axvline(p["stim_delay"], color="r", ls="--", lw=1)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("ROI (rastermap order)")
    fig.colorbar(im, ax=ax, fraction=0.08)
    n = len(order)
    jet = plt.cm.jet(np.linspace(0.15, 0.85, n))[:, :3]
    rmap = roi_map(rois, order, shape)
    nb = round(fr)
    for k in range(4):
        a = nf_delay - (nb - 1) + k * nb - 1
        w = slice(a, a + nb)
        for row, (sign, norm) in enumerate([(1, lim[1] / 2), (-1, -lim[0])]):
            r = np.clip(sign * avg[:, w].mean(1) / norm, 0, 1)
            cmap = np.vstack([jet * r[:, None], [0.1, 0.1, 0.1]])
            axm = fig.add_subplot(gs[row, k + 1])
            axm.imshow(cmap[rmap], interpolation="nearest")
            axm.set_axis_off()
            if row == 0:
                axm.set_title(f"{(a + 1) / fr:.2f}s to {(a + nb) / fr:.0f}s", fontsize=9)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    return fig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--wipes", type=Path, default=None, help="npz with trials_with_wipe (bool, n_trial)")
    ap.add_argument("--stim", type=int, default=4, help="1-based stim ID to plot")
    ap.add_argument("--params", type=Path, default=None, help="json overriding DEFAULT_PARAMS")
    ap.add_argument("--no-rastermap", action="store_true")
    ap.add_argument("--fz-npz", type=Path, default=None,
                    help="npz of alternative unsmoothed F_cell_anat traces (fanat_variants.py)")
    ap.add_argument("--fz-key", default=None, help="key in --fz-npz")
    ap.add_argument("--no-movmean", action="store_true", help="skip the 3-frame movmean of F_anat")
    ap.add_argument("--tag", default="", help="suffix for the corrected-condition outputs")
    args = ap.parse_args()

    p = dict(DEFAULT_PARAMS)
    if args.params:
        p.update(json.loads(args.params.read_text()))
    exp = args.export_dir
    F, Fneu, rois = load_extraction(exp)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    cache = out / "F_cell_anat.npy"
    if cache.exists():
        Fz = np.load(cache)
    else:
        Fz = f_cell_anat(next(exp.glob("F_anat_non_rigid*.tiff")), rois)
        np.save(cache, Fz)
    if args.fz_npz:
        Fz = np.load(args.fz_npz)[args.fz_key]
        Fz = Fz if args.no_movmean else movmean3(Fz)

    stim = args.stim
    energy = p["intensity"] * p["stim_duration"][stim - 1] * 1000
    vec_trial = trial_vector(p)
    trials = np.flatnonzero(vec_trial == stim)
    sel = np.ones(len(trials), bool)
    label = ""
    if args.wipes:
        w = np.load(args.wipes)
        sel = w["trials_with_wipe"][trials]
        label = " during wipes"

    conds = ("none", "nonrigid") if not args.tag else ("nonrigid",)
    res = {c: analyze(F, Fneu, rois, p, Fz, c) for c in conds}
    sfx = f"_{args.tag}" if args.tag else ""
    nf_trial = round(p["fr"] * p["trial_duration"])
    border = np.tile(np.r_[np.ones(p["rastermap"]["lag"], bool),
                           np.zeros(nf_trial - 2 * p["rastermap"]["lag"], bool),
                           np.ones(p["rastermap"]["lag"], bool)], len(vec_trial))
    summary = {}
    for c, r in res.items():
        order = np.arange(len(r["dff"])) if args.no_rastermap else rastermap_sort(r["resp_norm"], ~border, p)
        r["order"] = order
        avg_all = {s: v.mean(0) for s, v in r["by_stim"].items()}
        lim = (np.quantile(np.concatenate([a for a in avg_all.values()], 1).min(1), 0.05),
               np.quantile(np.concatenate([a for a in avg_all.values()], 1).max(1), 0.95))
        avg = r["by_stim"][stim][sel].mean(0)
        title = (f"[{'with' if c == 'nonrigid' else 'without'} subtraction{sfx}] Avg resp to laser "
                 f"{energy:g}mJ on {p['target']}{label}, n = {sel.sum()} trials, "
                 f"{len(order)} ROIs (top: excitation, bottom: suppression)")
        fig = plot_avg_resp(avg, r["rois"], order, p, lim, title)
        fig.savefig(out / f"avg_resp_stim{stim}_{c}{sfx}.png", dpi=130)
        plt.close(fig)
        summary[c] = dict(n_roi=int(len(order)), lim=[float(x) for x in lim])
        np.savez_compressed(
            out / f"avg_resp_{c}{sfx}.npz", order=order, keep=r["keep"], dff=r["dff"].astype(np.float32),
            dff_before=r["dff_before"].astype(np.float32), dffz=r["dffz"].astype(np.float32),
            slope=r["slope"], R2=r["R2"], vec_trial=vec_trial, trial_sel=sel,
            avg=avg.astype(np.float32),
        )
    (out / f"summary{sfx}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
