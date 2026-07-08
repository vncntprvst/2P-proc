"""Validate the optimized compute_zcorrel vs the legacy (and raw suite2p) estimator.

Two tests:
  1. Synthetic ground truth (multi-seed): accuracy (r, RMSE in planes) of
     compute_zcorrel_legacy vs compute_zcorrel (new) vs compute_zcorrel_suite2p.
  2. Real mcorr'd single run: zpos trajectories of legacy vs new — the mcorr'd
     movie is where raw suite2p is unstable (NoRMCorre edges); the new function's
     edge crop + temporal smoothing should keep it stable.

Writes stage1d_new_zcorrel.json and new_zcorrel_real.npz + a trajectory figure.

Run (pixi env): pixi run python test_new_compute_zcorrel.py \
    --real-zstack <ZSeries> --mcorr-tiff <mcorr_movie.tiff> --out DIR
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.benchmarks.bruker_io import load_bruker_zstack
from tests.benchmarks.synthetic_zstack import (
    make_rigid_z_trajectory,
    make_xy_trajectory,
    make_functional_movie,
    save_zstack_tiff,
    save_caiman_memmap,
)
from validation.zpos_compare_data import _load_tiff_downsampled


def _rmse_r(z_true, zpos):
    zpos = np.asarray(zpos, float)
    return (
        float(np.corrcoef(z_true, zpos)[0, 1]),
        float(np.sqrt(np.mean((z_true - zpos) ** 2))),
    )


def synthetic(vol, seeds):
    from modules.compute_zcorr import (
        compute_zcorrel,
        compute_zcorrel_legacy,
        compute_zcorrel_suite2p,
    )

    znom = (vol.shape[0] - 1) / 2
    stats = {m: {"r": [], "rmse": [], "t": []} for m in ("legacy", "new", "suite2p")}
    for s in range(seeds):
        T = 200
        zoff = make_rigid_z_trajectory(T, 3.0, 8, seed=s + 1)
        z_true = znom + zoff
        xy = make_xy_trajectory(T, 1.0, 8, seed=s + 1)
        mov, _ = make_functional_movie(vol, znom, zoff, xy_offsets=xy, deform_amp=0.5, seed=s + 1)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            save_zstack_tiff(vol, tmp / "z.tif")
            dd = tmp / "b" / "i"
            dd.mkdir(parents=True)
            mp = save_caiman_memmap(mov, dd)
            calls = [
                ("legacy", lambda: compute_zcorrel_legacy(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)),
                ("new", lambda: compute_zcorrel(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)),
                ("suite2p", lambda: compute_zcorrel_suite2p(tmp / "z.tif", mp, smooth_sigma=3)),
            ]
            for name, call in calls:
                t0 = time.time()
                zc = call()
                dt = time.time() - t0
                r, rmse = _rmse_r(z_true, zc["zpos"])
                stats[name]["r"].append(r)
                stats[name]["rmse"].append(rmse)
                stats[name]["t"].append(dt)
        print(
            f"seed {s+1}: "
            + "  ".join(
                f"{m} r={stats[m]['r'][-1]:.3f} rmse={stats[m]['rmse'][-1]:.2f}" for m in stats
            )
        )
    return stats


def real_single(vol, mcorr_tiff, downsample, out_dir):
    from modules.compute_zcorr import compute_zcorrel, compute_zcorrel_legacy

    movie = _load_tiff_downsampled(mcorr_tiff, downsample)
    v = vol
    h = min(v.shape[1], movie.shape[1])
    w = min(v.shape[2], movie.shape[2])
    v = v[:, :h, :w]
    movie = movie[:, :h, :w]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        save_zstack_tiff(v, tmp / "z.tif")
        dd = tmp / "b" / "i"
        dd.mkdir(parents=True)
        mp = save_caiman_memmap(movie, dd)
        zl = compute_zcorrel_legacy(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)
        zn = compute_zcorrel(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)
    zl, zn = zl["zpos"].astype(float), zn["zpos"].astype(float)
    np.savez(out_dir / "new_zcorrel_real.npz", zpos_legacy=zl, zpos_new=zn)
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(zl, color="0.5", lw=0.8, label="legacy (Pearson)")
    ax.plot(zn, color="C0", lw=0.9, label="new (phasecorr + edge-crop + smoothing)")
    ax.set_xlabel("frame")
    ax.set_ylabel("estimated z-plane")
    ax.legend(fontsize=8)
    jl = int(np.sum(np.abs(np.diff(zl)) >= 2))
    jn = int(np.sum(np.abs(np.diff(zn)) >= 2))
    ax.set_title(
        f"Optimized vs legacy z-pos on mcorr'd real run — " f"≥2-plane jumps: legacy {jl}, new {jn}"
    )
    fig.tight_layout()
    fig.savefig(out_dir / "new_zcorrel_real.png", dpi=130)
    plt.close(fig)
    print(f"real: legacy jumps {jl}, new jumps {jn}, agreement r={np.corrcoef(zl, zn)[0,1]:.3f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--real-zstack", type=Path, required=True)
    p.add_argument("--mcorr-tiff", type=Path, default=None)
    p.add_argument("--downsample", type=int, default=4)
    p.add_argument("--seeds", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vol, _ = load_bruker_zstack(args.real_zstack, channel=2, downsample=args.downsample)

    print("== synthetic (ground truth) ==")
    st = synthetic(vol, args.seeds)
    summary = {
        m: {
            "r_mean": float(np.mean(st[m]["r"])),
            "r_std": float(np.std(st[m]["r"])),
            "rmse_mean": float(np.mean(st[m]["rmse"])),
            "rmse_std": float(np.std(st[m]["rmse"])),
            "t_mean": float(np.mean(st[m]["t"])),
        }
        for m in st
    }
    (args.out / "stage1d_new_zcorrel.json").write_text(json.dumps(summary, indent=2))
    for m in summary:
        s = summary[m]
        print(
            f"{m:<8} r={s['r_mean']:.3f}±{s['r_std']:.3f}  "
            f"rmse={s['rmse_mean']:.2f}±{s['rmse_std']:.2f}  t={s['t_mean']:.1f}s"
        )

    if args.mcorr_tiff is not None:
        print("\n== real mcorr'd single run ==")
        real_single(vol, args.mcorr_tiff, args.downsample, args.out)


if __name__ == "__main__":
    main()
