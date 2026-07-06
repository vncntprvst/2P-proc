"""
Benchmark: z-motion estimation accuracy against a known ground-truth trajectory.

Design
------
A 3D reference volume is sampled along a known z-trajectory to produce a
functional movie; we then run compute_zcorrel() and compare its estimated
z-position trajectory to the ground truth. The reference volume is either:

  - synthetic  — anisotropic Gaussian "cells" (fast, dependency-free), or
  - real        — a Bruker ZSeries z-stack (``--real-zstack``), so the
    benchmark runs on real anatomy with an imposed, exactly-known trajectory.
    This is the "proper" benchmark: real tissue contrast, real PSF, exact
    ground truth.

The imposed trajectory is 3D — axial z-drift plus optional rigid lateral
(x/y) drift (``--xy-amplitude``) and anisotropic in-plane deformation
(``--deform-amp``) — so the estimator is tested under realistic motion that
its internal FOV registration must contend with.

  - Rigid z-motion   → global z-offset per frame, uniform across FOV
  - Non-rigid z-motion → per-patch z-offset, zero global mean per frame
    (different tissue patches drift independently in z). A global estimator
    returns near-zero correlation with any single patch — showing why
    per-patch z-correction is needed.

A separate qualitative mode (``--real-movie``) runs compute_zcorrel on an
actual TSeries recording against the real ZSeries (no ground truth) to exercise
the full real-data path and plot the estimated z-drift.

Metrics
-------
  z_estimation_r       : Pearson r between estimated and true z-position
  z_estimation_rmse    : RMSE in z-plane units (also reported in microns)
  z_amplitude_rms      : RMS of the applied displacement (difficulty measure)

Running
-------
As pytest (fast, synthetic):
    pytest tests/benchmarks/benchmark_zcorr.py -v

Synthetic sweep:
    python tests/benchmarks/benchmark_zcorr.py --save-results results/

Real anatomy (quantitative) + real recording (qualitative):
    python tests/benchmarks/benchmark_zcorr.py \
        --real-zstack /path/to/ZSeries-... --real-movie /path/to/TSeries-... \
        --downsample 3 --xy-amplitude 1 --deform-amp 0.5 --save-results results/

On the cluster:
    sbatch scripts/sbatch_benchmark_zcorr.sh
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Allow running standalone without pytest on PATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.benchmarks.synthetic_zstack import (
    make_3d_volume,
    make_functional_movie,
    make_nonrigid_z_trajectory,
    make_rigid_z_trajectory,
    make_xy_trajectory,
    save_caiman_memmap,
    save_zstack_tiff,
)

# ──────────────────────────────────────────────────────────────────────────────
# Core benchmark runner
# ──────────────────────────────────────────────────────────────────────────────


def run_zcorr_benchmark(
    n_frames,
    height,
    width,
    n_z,
    z_nominal,
    amplitude_planes,
    temporal_smoothness,
    motion_type,
    n_patches_y=4,
    n_patches_x=4,
    volume=None,
    xy_amplitude=0.0,
    deform_amp=0.0,
    z_step_um=1.0,
    tmp_dir=None,
    seed=42,
):
    """Run one z-correction benchmark case.

    Parameters
    ----------
    n_frames : int
    height, width : int
    n_z : int         Number of z-planes in the synthetic z-stack.
    z_nominal : float Focal-plane index (centre of the z-stack).
    amplitude_planes : float  RMS displacement in z-plane units.
    temporal_smoothness : float  Gaussian sigma in time.
    motion_type : str  'rigid' or 'nonrigid'
    n_patches_y, n_patches_x : int  Patch grid for non-rigid.
    volume : ndarray or None
        Real (Z, H, W) reference volume to use instead of synthetic Gaussian
        blobs. When given, its shape overrides n_z/height/width and z_nominal
        defaults to the volume centre — the benchmark then runs on real anatomy
        with a known, imposed z-trajectory (the "proper" benchmark).
    xy_amplitude : float
        RMS rigid lateral (x/y) drift in pixels applied alongside z-motion.
    deform_amp : float
        RMS anisotropic in-plane deformation in pixels (0 disables).
    z_step_um : float
        Micron spacing between z-planes, for reporting metrics in microns.
    tmp_dir : Path or None  Scratch directory for file I/O.
    seed : int

    Returns
    -------
    metrics : dict with keys:
        motion_type, amplitude_planes, temporal_smoothness,
        z_amplitude_rms, z_estimation_r, z_estimation_rmse (+ *_um),
        global_r_vs_patch0  (non-rigid only: demonstrates rigid estimator fails)
    """
    from modules.compute_zcorr import compute_zcorrel

    own_tmp = tmp_dir is None
    if own_tmp:
        _tmp = tempfile.mkdtemp()
        tmp_dir = Path(_tmp)

    try:
        # ── 1. Generate / load the reference volume ─────────────────────────
        if volume is not None:
            volume = np.asarray(volume, dtype=np.float32)
            n_z, height, width = volume.shape
            if z_nominal is None:
                z_nominal = (n_z - 1) / 2.0
        else:
            volume, _ = make_3d_volume(n_z, height, width, n_cells=80, seed=seed)

        if motion_type == "rigid":
            z_offsets = make_rigid_z_trajectory(
                n_frames, amplitude_planes, temporal_smoothness, seed=seed
            )
            patch_size_y = patch_size_x = None
        elif motion_type == "nonrigid":
            z_offsets = make_nonrigid_z_trajectory(
                n_frames, n_patches_y, n_patches_x, amplitude_planes, temporal_smoothness, seed=seed
            )
            patch_size_y = height // n_patches_y
            patch_size_x = width // n_patches_x
        else:
            raise ValueError(f"Unknown motion_type '{motion_type}'")

        # 3D trajectory: lateral rigid drift accompanies the axial motion.
        xy_offsets = None
        if xy_amplitude > 0:
            xy_offsets = make_xy_trajectory(n_frames, xy_amplitude, temporal_smoothness, seed=seed)

        movie, z_field_per_frame = make_functional_movie(
            volume,
            z_nominal,
            z_offsets,
            patch_size_y=patch_size_y,
            patch_size_x=patch_size_x,
            xy_offsets=xy_offsets,
            deform_amp=deform_amp,
            seed=seed,
        )

        # ── 2. Save to disk in the formats compute_zcorrel expects ──────────
        zstack_path = tmp_dir / "zstack.tif"
        save_zstack_tiff(volume, zstack_path)

        memmap_path = save_caiman_memmap(movie, tmp_dir)

        # compute_zcorrel writes z_correlation.npz two directories up from the memmap.
        # We put the memmap one level deep so the parent chain is valid.
        data_dir = tmp_dir / "batch" / "item_0"
        data_dir.mkdir(parents=True, exist_ok=True)
        memmap_path = save_caiman_memmap(movie, data_dir)

        # ── 3. Run compute_zcorrel ───────────────────────────────────────────
        z_correlation = compute_zcorrel(
            zstack_path,
            memmap_path,
            smooth_sigma=3,
            export_path=tmp_dir,
        )

        if z_correlation is None:
            raise RuntimeError("compute_zcorrel returned None — check dimension match")

        zpos_estimated = z_correlation["zpos"].astype(np.float32)  # shape (T,)

        # ── 4. Build ground-truth global z-position per frame ───────────────
        # For rigid: z_offsets is (T,) → ground truth is z_nominal + z_offsets
        # For nonrigid: per-patch offsets → global ground truth is mean over patches
        if motion_type == "rigid":
            z_true_global = z_nominal + z_offsets  # (T,)
        else:
            # Global mean: should be ~z_nominal since offsets sum to zero
            z_true_global = z_nominal + z_offsets.mean(axis=(1, 2))  # (T,)

        # ── 5. Metrics ───────────────────────────────────────────────────────
        r = float(np.corrcoef(z_true_global, zpos_estimated)[0, 1])
        rmse = float(np.sqrt(np.mean((z_true_global - zpos_estimated) ** 2)))
        z_amp_rms = float(np.sqrt(np.mean((z_true_global - z_nominal) ** 2)))

        metrics = {
            "motion_type": motion_type,
            "amplitude_planes": amplitude_planes,
            "temporal_smoothness": temporal_smoothness,
            "xy_amplitude_px": xy_amplitude,
            "deform_amp_px": deform_amp,
            "n_z": n_z,
            "z_nominal": z_nominal,
            "z_step_um": z_step_um,
            "z_amplitude_rms": z_amp_rms,
            "z_amplitude_rms_um": z_amp_rms * z_step_um,
            "z_estimation_r": r,
            "z_estimation_rmse": rmse,
            "z_estimation_rmse_um": rmse * z_step_um,
        }

        # For non-rigid: also show that the global estimator misses per-patch motion
        if motion_type == "nonrigid":
            # Pick patch (0, 0) as representative
            z_patch0 = z_nominal + z_offsets[:, 0, 0]
            r_patch0 = float(np.corrcoef(z_patch0, zpos_estimated)[0, 1])
            metrics["global_r_vs_patch0"] = r_patch0
            # Per-patch ground truth amplitude
            metrics["per_patch_amplitude_rms"] = float(np.sqrt(np.mean(z_offsets**2)))

        return metrics

    finally:
        if own_tmp:
            import shutil

            shutil.rmtree(_tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────────
# Pytest cases — small and fast
# ──────────────────────────────────────────────────────────────────────────────

# (motion_type, amplitude_planes, temporal_smoothness, expected_min_r)
_PYTEST_CASES = [
    # Small rigid drift — should be estimated well
    ("rigid", 2.0, 8, 0.7),
    # Larger rigid drift
    ("rigid", 4.0, 8, 0.7),
    # Non-rigid, zero global mean: global estimator should have low r
    ("nonrigid", 2.0, 8, None),  # no r threshold for global estimator
    # Non-rigid with clear patch structure
    ("nonrigid", 3.0, 6, None),
]


@pytest.mark.parametrize("motion_type,amplitude_planes,temporal_smoothness,min_r", _PYTEST_CASES)
def test_z_estimation(motion_type, amplitude_planes, temporal_smoothness, min_r, tmp_path):
    """compute_zcorrel recovers the known z-trajectory from synthetic data."""
    metrics = run_zcorr_benchmark(
        n_frames=80,
        height=128,
        width=128,
        n_z=20,
        z_nominal=10.0,
        amplitude_planes=amplitude_planes,
        temporal_smoothness=temporal_smoothness,
        motion_type=motion_type,
        tmp_dir=tmp_path,
    )

    print(
        f"\n  [{motion_type}] amp={amplitude_planes} planes  "
        f"r={metrics['z_estimation_r']:.3f}  "
        f"rmse={metrics['z_estimation_rmse']:.2f} planes"
    )

    if min_r is not None:
        assert metrics["z_estimation_r"] >= min_r, (
            f"z-estimation correlation {metrics['z_estimation_r']:.3f} "
            f"< threshold {min_r} for {motion_type} motion"
        )

    # RMSE should be well below the z-stack range
    assert (
        metrics["z_estimation_rmse"] < metrics["n_z"] / 2
    ), f"RMSE {metrics['z_estimation_rmse']:.2f} planes is implausibly large"

    # For non-rigid, demonstrate that the global estimator has poor per-patch correlation
    if motion_type == "nonrigid":
        print(
            f"  [non-rigid] global r vs patch(0,0) = {metrics['global_r_vs_patch0']:.3f} "
            f"(expected near 0 since global mean of offsets is 0)"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Standalone benchmark runner (larger, full parameter sweep)
# ──────────────────────────────────────────────────────────────────────────────

FULL_SWEEP = [
    # (motion_type, amplitude_planes, temporal_smoothness)
    ("rigid", 1.0, 15),
    ("rigid", 2.0, 10),
    ("rigid", 3.0, 8),
    ("rigid", 5.0, 8),
    ("nonrigid", 1.0, 15),
    ("nonrigid", 2.0, 10),
    ("nonrigid", 3.0, 8),
    ("nonrigid", 4.0, 6),
]


def _load_real_volume(zstack_dir, channel, downsample, max_planes):
    """Load a real Bruker ZSeries as the benchmark reference volume.

    Returns (volume, z_step_um). Imported lazily so the synthetic path has no
    dependency on the Bruker loaders.
    """
    from tests.benchmarks.bruker_io import load_bruker_zstack

    volume, z_um = load_bruker_zstack(
        zstack_dir, channel=channel, downsample=downsample, max_planes=max_planes
    )
    if len(z_um) >= 2:
        z_step_um = float(np.median(np.abs(np.diff(z_um))))
    else:
        z_step_um = 1.0
    print(
        f"Loaded real z-stack {volume.shape} from {Path(zstack_dir).name} "
        f"(z-step {z_step_um:.2f} µm)"
    )
    return volume, z_step_um


def run_real_movie_qualitative(
    zstack_dir, tseries_dir, out_dir, channel=2, downsample=1, n_frames=None, max_planes=None
):
    """Run compute_zcorrel on a *real* TSeries against a *real* ZSeries.

    There is no ground-truth z-trajectory for a real recording, so this is a
    qualitative sanity check of the full real-data path: it exercises the
    Bruker loaders → z-stack registration → per-frame correlation, and saves the
    estimated z-position trajectory plus the pipeline's z_drift plot.
    """
    from modules.compute_zcorr import compute_zcorrel
    from tests.benchmarks.bruker_io import load_bruker_tseries

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    volume, z_step_um = _load_real_volume(zstack_dir, channel, downsample, max_planes)
    movie = load_bruker_tseries(
        tseries_dir, channel=channel, n_frames=n_frames, downsample=downsample
    )
    print(f"Loaded real movie {movie.shape} from {Path(tseries_dir).name}")

    zstack_path = out_dir / "real_zstack.tif"
    save_zstack_tiff(volume, zstack_path)
    memmap_path = save_caiman_memmap(movie, out_dir)

    z_correlation = compute_zcorrel(zstack_path, memmap_path, smooth_sigma=3, export_path=out_dir)
    if z_correlation is None:
        raise RuntimeError("compute_zcorrel returned None — z-stack/movie dims differ")

    zpos = z_correlation["zpos"].astype(np.float32)
    np.save(out_dir / "real_zpos.npy", zpos)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 3))
    ax.plot(zpos * z_step_um, lw=1)
    ax.set_xlabel("frame")
    ax.set_ylabel("estimated z (µm from stack top)")
    ax.set_title(f"Real recording z-drift — {Path(tseries_dir).name}")
    fig.tight_layout()
    fig.savefig(out_dir / "real_z_drift.png", dpi=120)
    plt.close(fig)

    summary = {
        "tseries": Path(tseries_dir).name,
        "zstack": Path(zstack_dir).name,
        "n_frames": int(movie.shape[0]),
        "volume_shape": list(volume.shape),
        "z_step_um": z_step_um,
        "zpos_mean_plane": float(zpos.mean()),
        "zpos_std_plane": float(zpos.std()),
        "zpos_ptp_um": float(zpos.ptp() * z_step_um),
    }
    print(
        f"Real-movie z-drift: mean plane {summary['zpos_mean_plane']:.1f}, "
        f"peak-to-peak {summary['zpos_ptp_um']:.1f} µm"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run z-correction benchmark sweep")
    parser.add_argument(
        "--save-results",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory to save per-case JSON results",
    )
    parser.add_argument("--n-frames", type=int, default=300)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--n-z", type=int, default=25)
    # Real-data options
    parser.add_argument(
        "--real-zstack",
        type=Path,
        default=None,
        metavar="DIR",
        help="Bruker ZSeries dir: use real anatomy as the reference "
        "volume with an imposed known z-trajectory (quantitative)",
    )
    parser.add_argument(
        "--real-movie",
        type=Path,
        default=None,
        metavar="DIR",
        help="Bruker TSeries dir: qualitative run of compute_zcorrel "
        "on the actual recording vs --real-zstack (no ground truth)",
    )
    parser.add_argument(
        "--downsample", type=int, default=1, help="Spatial mean-pooling factor for real data"
    )
    parser.add_argument(
        "--max-planes",
        type=int,
        default=None,
        help="Subsample the real z-stack to at most N planes",
    )
    parser.add_argument(
        "--channel", type=int, default=2, help="Bruker acquisition channel (default 2, functional)"
    )
    parser.add_argument(
        "--xy-amplitude",
        type=float,
        default=0.0,
        help="RMS rigid lateral drift (px) added to the trajectory",
    )
    parser.add_argument(
        "--deform-amp", type=float, default=0.0, help="RMS anisotropic in-plane deformation (px)"
    )
    args = parser.parse_args()

    if args.save_results:
        args.save_results.mkdir(parents=True, exist_ok=True)

    # Load the real volume once if requested; it defines the geometry.
    real_volume = None
    z_step_um = 1.0
    if args.real_zstack is not None:
        real_volume, z_step_um = _load_real_volume(
            args.real_zstack, args.channel, args.downsample, args.max_planes
        )
        n_z = real_volume.shape[0]
        z_nominal = None  # centre of the real volume
        height, width = real_volume.shape[1:]
    else:
        n_z = args.n_z
        z_nominal = float(args.n_z // 2)
        height, width = args.height, args.width

    label = "REAL anatomy" if real_volume is not None else "synthetic"
    print(
        f"Benchmark ({label}): {args.n_frames} frames, {height}×{width} px, "
        f"{n_z} z-planes, z-step {z_step_um:.2f} µm, "
        f"xy_amp={args.xy_amplitude}px deform={args.deform_amp}px"
    )
    print(f"{'motion_type':<12} {'amp':>5} {'tau':>5} " f"{'z_amp_um':>10} {'r':>8} {'rmse_um':>8}")
    print("─" * 60)

    all_results = []
    for motion_type, amplitude, tau in FULL_SWEEP:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = run_zcorr_benchmark(
                n_frames=args.n_frames,
                height=height,
                width=width,
                n_z=n_z,
                z_nominal=z_nominal,
                amplitude_planes=amplitude,
                temporal_smoothness=tau,
                motion_type=motion_type,
                volume=real_volume,
                xy_amplitude=args.xy_amplitude,
                deform_amp=args.deform_amp,
                z_step_um=z_step_um,
                tmp_dir=Path(tmp),
            )

        tag_extra = ""
        if motion_type == "nonrigid":
            tag_extra = f"  [global r vs patch0: {metrics.get('global_r_vs_patch0', 'N/A'):.3f}]"

        print(
            f"{motion_type:<12} {amplitude:>5.1f} {tau:>5d} "
            f"{metrics['z_amplitude_rms_um']:>10.3f} "
            f"{metrics['z_estimation_r']:>8.3f} "
            f"{metrics['z_estimation_rmse_um']:>8.3f}" + tag_extra
        )

        all_results.append(metrics)

        if args.save_results:
            fname = f"{motion_type}_amp{amplitude:.0f}_tau{tau}.json"
            (args.save_results / fname).write_text(json.dumps(metrics, indent=2))

    # Optional qualitative pass on the actual recording.
    if args.real_movie is not None:
        if args.real_zstack is None:
            parser.error("--real-movie requires --real-zstack for the reference volume")
        print("\nQualitative real-movie run (no ground truth):")
        real_summary = run_real_movie_qualitative(
            args.real_zstack,
            args.real_movie,
            out_dir=(
                (args.save_results / "real_movie")
                if args.save_results
                else Path(tempfile.mkdtemp())
            ),
            channel=args.channel,
            downsample=args.downsample,
            n_frames=args.n_frames,
            max_planes=args.max_planes,
        )
        if args.save_results:
            (args.save_results / "real_movie_summary.json").write_text(
                json.dumps(real_summary, indent=2)
            )

    if args.save_results:
        (args.save_results / "all_results.json").write_text(json.dumps(all_results, indent=2))
        print(f"\nResults saved to {args.save_results}")


if __name__ == "__main__":
    main()
