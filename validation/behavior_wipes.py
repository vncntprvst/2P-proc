"""Classify trials as wipe / no-wipe from DLC keypoints (port of Analysis_2P ``analyze_behavior.m``).

Uses the branch without hand-drawn face ROIs (``labeled_face`` empty, l.211-217):
a wipe is the left paw within ``radius`` px of the median left whisker-pad
position. Trials are split by the onset of the first wipe (l.268-345):
before stim (< stim_delay), early (within 1 s after stim), late (later).
"trials_with_wipe" follows the MATLAB figure selection: early | late.

Keypoint names default to the Tube_2P_face DLC model (lefthand / whisker_left).

Usage
-----
    python validation/behavior_wipes.py <dlc.csv> --out wipes.npz [--fr 60] [--n-trial 100]
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def load_dlc(csv):
    df = pd.read_csv(csv, header=[0, 1, 2], index_col=0)
    df.columns = df.columns.droplevel(0)
    return df


def _clean(x, p, thr, nf_trial, n_trial, win):
    """NaN low-likelihood points, per-trial moving median, linear fill (MATLAB l.27-53)."""
    x = np.where(p < thr, np.nan, x)[: nf_trial * n_trial].reshape(n_trial, nf_trial)
    x = pd.DataFrame(x.T).rolling(win, center=True, min_periods=1).median().to_numpy().T.ravel()
    return pd.Series(x).interpolate(limit_direction="both").to_numpy()


def classify(df, fr, n_trial, trial_duration=4.0, stim_delay=1.0, radius=50.0,
             paw="lefthand", pad="whisker_left"):
    nf_trial = round(fr * trial_duration)
    win = max(round(10 / 200 * fr), 1)  # MATLAB: 10 frames at 200 Hz
    px = _clean(df[paw]["x"].to_numpy(), df[paw]["likelihood"].to_numpy(), 0.1, nf_trial, n_trial, win)
    py = _clean(df[paw]["y"].to_numpy(), df[paw]["likelihood"].to_numpy(), 0.1, nf_trial, n_trial, win)
    wx = df[pad]["x"].to_numpy()[: nf_trial * n_trial]
    wy = df[pad]["y"].to_numpy()[: nf_trial * n_trial]
    ok = df[pad]["likelihood"].to_numpy()[: nf_trial * n_trial] >= 0.9
    dist = np.hypot(px - np.median(wx[ok]), py - np.median(wy[ok]))
    wipe = (dist < radius).reshape(n_trial, nf_trial)

    first = np.full(n_trial, np.nan)
    for i in range(n_trial):
        on = np.flatnonzero(np.diff(wipe[i].astype(int)) > 0)
        if len(on):
            first[i] = (on[0] + 1) / fr
    before = first < stim_delay
    early = (first >= stim_delay) & (first < stim_delay + 1)
    late = first >= stim_delay + 1
    return dict(
        wipe=wipe, dist=dist.reshape(n_trial, nf_trial), wipe_latency=first,
        trials_with_wipe_before_stim=before, trials_with_early_wipe=early,
        trials_with_late_wipe=late, trials_with_wipe=early | late,
        trials_wo_wipe=~wipe.any(1),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dlc_csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fr", type=float, default=60.0)
    ap.add_argument("--n-trial", type=int, default=100)
    ap.add_argument("--radius", type=float, default=50.0)
    args = ap.parse_args()

    r = classify(load_dlc(args.dlc_csv), args.fr, args.n_trial, radius=args.radius)
    np.savez_compressed(args.out, **r)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    t = np.arange(r["wipe"].shape[1]) / args.fr
    ax[0].imshow(r["wipe"], aspect="auto", extent=[t[0], t[-1], len(r["wipe"]), 0], cmap="gray_r")
    ax[0].axvline(1, color="r", ls="--")
    ax[0].set(xlabel="time (s)", ylabel="trial", title="paw at whisker pad")
    ax[1].plot(t, r["dist"].T, lw=0.3, color="0.5")
    ax[1].axhline(args.radius, color="r")
    ax[1].set(xlabel="time (s)", ylabel="paw-whisker pad distance (px)", ylim=(0, 400))
    fig.tight_layout()
    fig.savefig(args.out.with_suffix(".png"), dpi=110)
    print({k: int(v.sum()) for k, v in r.items() if k.startswith("trials")})


if __name__ == "__main__":
    main()
