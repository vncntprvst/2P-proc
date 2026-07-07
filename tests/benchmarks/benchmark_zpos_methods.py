"""
Benchmark stage 1 — z-position estimation method comparison.

Two implementations estimate the per-frame focal plane by correlating each movie
frame against an anatomical z-stack:

  - ``compute_zcorrel``          — full-frame Pearson correlation (this pipeline)
  - ``compute_zcorrel_suite2p``  — Suite2p's phase-correlation masks port

We run both on the *same* synthetic case (real z-stack sampled along a known 3D
trajectory) and score each against the ground-truth trajectory, report their
mutual agreement, and time them. Runs in the pixi env (needs suite2p).

Usage
-----
    cd validation && pixi run python ../tests/benchmarks/benchmark_zpos_methods.py \
        --real-zstack /path/to/ZSeries-... --downsample 3 --save-results results/
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.benchmarks.synthetic_zstack import (
    make_functional_movie,
    make_nonrigid_z_trajectory,
    make_rigid_z_trajectory,
    make_xy_trajectory,
    save_caiman_memmap,
    save_zstack_tiff,
)


def _metrics(z_true, zpos, z_step_um):
    zpos = np.asarray(zpos, dtype=np.float32)
    if np.std(z_true) < 1e-6 or np.std(zpos) < 1e-6:
        r = float("nan")
    else:
        r = float(np.corrcoef(z_true, zpos)[0, 1])
    rmse = float(np.sqrt(np.mean((z_true - zpos) ** 2)))
    return {"r": r, "rmse_planes": rmse, "rmse_um": rmse * z_step_um}


def run_case(
    volume,
    motion_type,
    amplitude_planes,
    temporal_smoothness,
    n_frames,
    z_nominal,
    z_step_um=1.0,
    xy_amplitude=0.0,
    deform_amp=0.0,
    smooth_sigma=3,
    tmp_dir=None,
    seed=42,
):
    """Generate one synthetic case and run both z-pos methods on it."""
    from modules.compute_zcorr import compute_zcorrel, compute_zcorrel_suite2p

    own_tmp = tmp_dir is None
    if own_tmp:
        tmp_dir = Path(tempfile.mkdtemp())
    tmp_dir = Path(tmp_dir)

    try:
        volume = np.asarray(volume, dtype=np.float32)
        n_z = volume.shape[0]
        if z_nominal is None:
            z_nominal = (n_z - 1) / 2.0

        if motion_type == "rigid":
            z_offsets = make_rigid_z_trajectory(
                n_frames, amplitude_planes, temporal_smoothness, seed=seed
            )
            z_true = z_nominal + z_offsets
            psy = psx = None
        else:
            z_offsets = make_nonrigid_z_trajectory(
                n_frames, 4, 4, amplitude_planes, temporal_smoothness, seed=seed
            )
            z_true = z_nominal + z_offsets.mean(axis=(1, 2))
            psy, psx = volume.shape[1] // 4, volume.shape[2] // 4

        xy_offsets = (
            make_xy_trajectory(n_frames, xy_amplitude, temporal_smoothness, seed=seed)
            if xy_amplitude > 0
            else None
        )
        movie, _ = make_functional_movie(
            volume,
            z_nominal,
            z_offsets,
            patch_size_y=psy,
            patch_size_x=psx,
            xy_offsets=xy_offsets,
            deform_amp=deform_amp,
            seed=seed,
        )

        zstack_path = tmp_dir / "zstack.tif"
        save_zstack_tiff(volume, zstack_path)
        data_dir = tmp_dir / "batch" / "item_0"
        data_dir.mkdir(parents=True, exist_ok=True)
        memmap_path = save_caiman_memmap(movie, data_dir)

        t0 = time.time()
        zc_caiman = compute_zcorrel(
            zstack_path, memmap_path, smooth_sigma=smooth_sigma, export_path=tmp_dir
        )
        t_caiman = time.time() - t0

        t0 = time.time()
        zc_s2p = compute_zcorrel_suite2p(zstack_path, memmap_path, smooth_sigma=smooth_sigma)
        t_s2p = time.time() - t0

        if zc_caiman is None or zc_s2p is None:
            raise RuntimeError("a z-pos method returned None (dimension mismatch)")

        zp_caiman = zc_caiman["zpos"].astype(np.float32)
        zp_s2p = zc_s2p["zpos"].astype(np.float32)

        result = {
            "motion_type": motion_type,
            "amplitude_planes": amplitude_planes,
            "xy_amplitude_px": xy_amplitude,
            "deform_amp_px": deform_amp,
            "z_step_um": z_step_um,
            "caiman": {**_metrics(z_true, zp_caiman, z_step_um), "time_s": t_caiman},
            "suite2p": {**_metrics(z_true, zp_s2p, z_step_um), "time_s": t_s2p},
            "agreement": _metrics(zp_caiman, zp_s2p, z_step_um),
        }
        return result
    finally:
        if own_tmp:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)


SWEEP = [
    ("rigid", 2.0, 10),
    ("rigid", 4.0, 8),
    ("nonrigid", 3.0, 8),
]


def main():
    p = argparse.ArgumentParser(description="Compare compute_zcorrel vs compute_zcorrel_suite2p")
    p.add_argument("--real-zstack", type=Path, default=None)
    p.add_argument("--downsample", type=int, default=1)
    p.add_argument("--max-planes", type=int, default=None)
    p.add_argument("--channel", type=int, default=2)
    p.add_argument("--n-frames", type=int, default=200)
    p.add_argument("--xy-amplitude", type=float, default=1.0)
    p.add_argument("--deform-amp", type=float, default=0.5)
    p.add_argument("--save-results", type=Path, default=None)
    args = p.parse_args()

    if args.real_zstack is not None:
        from tests.benchmarks.bruker_io import load_bruker_zstack

        volume, z_um = load_bruker_zstack(
            args.real_zstack,
            channel=args.channel,
            downsample=args.downsample,
            max_planes=args.max_planes,
        )
        z_step_um = float(np.median(np.abs(np.diff(z_um)))) if len(z_um) >= 2 else 1.0
        print(f"Loaded real z-stack {volume.shape} (z-step {z_step_um:.2f} µm)")
    else:
        from tests.benchmarks.synthetic_zstack import make_3d_volume

        volume, _ = make_3d_volume(25, 256, 256, n_cells=80)
        z_step_um = 1.0
        print("Using synthetic Gaussian volume")

    if args.save_results:
        args.save_results.mkdir(parents=True, exist_ok=True)

    print(f"{'case':<22} {'method':<9} {'r':>7} {'rmse_um':>9} {'time_s':>8}")
    print("─" * 60)
    results = []
    for motion_type, amp, tau in SWEEP:
        with tempfile.TemporaryDirectory() as tmp:
            res = run_case(
                volume,
                motion_type,
                amp,
                tau,
                args.n_frames,
                None,
                z_step_um=z_step_um,
                xy_amplitude=args.xy_amplitude,
                deform_amp=args.deform_amp,
                tmp_dir=Path(tmp),
            )
        tag = f"{motion_type} amp{amp:.0f}"
        for method in ("caiman", "suite2p"):
            m = res[method]
            print(f"{tag:<22} {method:<9} {m['r']:>7.3f} {m['rmse_um']:>9.3f} {m['time_s']:>8.2f}")
        ag = res["agreement"]
        print(f"{'  agreement (c vs s)':<22} {'':<9} {ag['r']:>7.3f} {ag['rmse_um']:>9.3f}")
        results.append(res)

    if args.save_results:
        (args.save_results / "zpos_method_comparison.json").write_text(
            json.dumps(results, indent=2)
        )
        print(f"\nSaved to {args.save_results}/zpos_method_comparison.json")


if __name__ == "__main__":
    main()
