"""
Benchmark: z-motion estimation accuracy using synthetic ground-truth data.

Design
------
We generate a synthetic 3D fluorescence volume, apply known z-motion to
produce a functional movie, then run compute_zcorrel() and compare its
estimated z-position trajectory to the ground truth.

The key distinction from a pure 2D motion benchmark:
  - Rigid z-motion   → global z-offset per frame, uniform across FOV
  - Non-rigid z-motion → per-patch z-offset, zero global mean per frame
    (different tissue patches drift independently in z)

For non-rigid motion with zero global mean, a rigid estimator returns
near-zero correlation with any individual patch — demonstrating exactly
why per-patch z-correction is needed.

Metrics
-------
  z_estimation_r   : Pearson r between estimated and true z-position
  z_estimation_rmse: RMSE in z-plane units
  z_amplitude_rms  : RMS of the applied displacements (difficulty measure)

Running
-------
As pytest (fast, small datasets):
    pytest tests/benchmarks/benchmark_zcorr.py -v

As a standalone script (larger, more realistic datasets):
    python tests/benchmarks/benchmark_zcorr.py --save-results results/

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
    save_caiman_memmap,
    save_zstack_tiff,
)


# ──────────────────────────────────────────────────────────────────────────────
# Core benchmark runner
# ──────────────────────────────────────────────────────────────────────────────

def run_zcorr_benchmark(n_frames, height, width, n_z,
                         z_nominal, amplitude_planes,
                         temporal_smoothness, motion_type,
                         n_patches_y=4, n_patches_x=4,
                         tmp_dir=None, seed=42):
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
    tmp_dir : Path or None  Scratch directory for file I/O.
    seed : int

    Returns
    -------
    metrics : dict with keys:
        motion_type, amplitude_planes, temporal_smoothness,
        z_amplitude_rms, z_estimation_r, z_estimation_rmse,
        global_r_vs_patch0  (non-rigid only: demonstrates rigid estimator fails)
    """
    from modules.compute_zcorr import compute_zcorrel

    own_tmp = tmp_dir is None
    if own_tmp:
        _tmp = tempfile.mkdtemp()
        tmp_dir = Path(_tmp)

    try:
        # ── 1. Generate synthetic data ──────────────────────────────────────
        volume, _ = make_3d_volume(
            n_z, height, width, n_cells=80, seed=seed
        )

        if motion_type == 'rigid':
            z_offsets = make_rigid_z_trajectory(
                n_frames, amplitude_planes, temporal_smoothness, seed=seed
            )
            patch_size_y = patch_size_x = None
        elif motion_type == 'nonrigid':
            z_offsets = make_nonrigid_z_trajectory(
                n_frames, n_patches_y, n_patches_x,
                amplitude_planes, temporal_smoothness, seed=seed
            )
            patch_size_y = height // n_patches_y
            patch_size_x = width // n_patches_x
        else:
            raise ValueError(f"Unknown motion_type '{motion_type}'")

        movie, z_field_per_frame = make_functional_movie(
            volume, z_nominal, z_offsets,
            patch_size_y=patch_size_y,
            patch_size_x=patch_size_x,
            seed=seed,
        )

        # ── 2. Save to disk in the formats compute_zcorrel expects ──────────
        zstack_path = tmp_dir / 'zstack.tif'
        save_zstack_tiff(volume, zstack_path)

        memmap_path = save_caiman_memmap(movie, tmp_dir)

        # compute_zcorrel writes z_correlation.npz two directories up from the memmap.
        # We put the memmap one level deep so the parent chain is valid.
        data_dir = tmp_dir / 'batch' / 'item_0'
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

        zpos_estimated = z_correlation['zpos'].astype(np.float32)  # shape (T,)

        # ── 4. Build ground-truth global z-position per frame ───────────────
        # For rigid: z_offsets is (T,) → ground truth is z_nominal + z_offsets
        # For nonrigid: per-patch offsets → global ground truth is mean over patches
        if motion_type == 'rigid':
            z_true_global = z_nominal + z_offsets                # (T,)
        else:
            # Global mean: should be ~z_nominal since offsets sum to zero
            z_true_global = z_nominal + z_offsets.mean(axis=(1, 2))  # (T,)

        # ── 5. Metrics ───────────────────────────────────────────────────────
        r = float(np.corrcoef(z_true_global, zpos_estimated)[0, 1])
        rmse = float(np.sqrt(np.mean((z_true_global - zpos_estimated) ** 2)))
        z_amp_rms = float(np.sqrt(np.mean((z_true_global - z_nominal) ** 2)))

        metrics = {
            'motion_type': motion_type,
            'amplitude_planes': amplitude_planes,
            'temporal_smoothness': temporal_smoothness,
            'n_z': n_z,
            'z_nominal': z_nominal,
            'z_amplitude_rms': z_amp_rms,
            'z_estimation_r': r,
            'z_estimation_rmse': rmse,
        }

        # For non-rigid: also show that the global estimator misses per-patch motion
        if motion_type == 'nonrigid':
            # Pick patch (0, 0) as representative
            z_patch0 = z_nominal + z_offsets[:, 0, 0]
            r_patch0 = float(np.corrcoef(z_patch0, zpos_estimated)[0, 1])
            metrics['global_r_vs_patch0'] = r_patch0
            # Per-patch ground truth amplitude
            metrics['per_patch_amplitude_rms'] = float(
                np.sqrt(np.mean(z_offsets ** 2))
            )

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
    ('rigid',    2.0, 8,  0.7),
    # Larger rigid drift
    ('rigid',    4.0, 8,  0.7),
    # Non-rigid, zero global mean: global estimator should have low r
    ('nonrigid', 2.0, 8,  None),   # no r threshold for global estimator
    # Non-rigid with clear patch structure
    ('nonrigid', 3.0, 6,  None),
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

    print(f"\n  [{motion_type}] amp={amplitude_planes} planes  "
          f"r={metrics['z_estimation_r']:.3f}  "
          f"rmse={metrics['z_estimation_rmse']:.2f} planes")

    if min_r is not None:
        assert metrics['z_estimation_r'] >= min_r, (
            f"z-estimation correlation {metrics['z_estimation_r']:.3f} "
            f"< threshold {min_r} for {motion_type} motion"
        )

    # RMSE should be well below the z-stack range
    assert metrics['z_estimation_rmse'] < metrics['n_z'] / 2, (
        f"RMSE {metrics['z_estimation_rmse']:.2f} planes is implausibly large"
    )

    # For non-rigid, demonstrate that the global estimator has poor per-patch correlation
    if motion_type == 'nonrigid':
        print(f"  [non-rigid] global r vs patch(0,0) = {metrics['global_r_vs_patch0']:.3f} "
              f"(expected near 0 since global mean of offsets is 0)")


# ──────────────────────────────────────────────────────────────────────────────
# Standalone benchmark runner (larger, full parameter sweep)
# ──────────────────────────────────────────────────────────────────────────────

FULL_SWEEP = [
    # (motion_type, amplitude_planes, temporal_smoothness)
    ('rigid',    1.0, 15),
    ('rigid',    2.0, 10),
    ('rigid',    3.0, 8),
    ('rigid',    5.0, 8),
    ('nonrigid', 1.0, 15),
    ('nonrigid', 2.0, 10),
    ('nonrigid', 3.0, 8),
    ('nonrigid', 4.0, 6),
]


def main():
    parser = argparse.ArgumentParser(description="Run z-correction benchmark sweep")
    parser.add_argument('--save-results', type=Path, default=None, metavar='DIR',
                        help='Directory to save per-case JSON results')
    parser.add_argument('--n-frames', type=int, default=300)
    parser.add_argument('--height', type=int, default=256)
    parser.add_argument('--width', type=int, default=256)
    parser.add_argument('--n-z', type=int, default=25)
    args = parser.parse_args()

    if args.save_results:
        args.save_results.mkdir(parents=True, exist_ok=True)

    z_nominal = args.n_z // 2

    print(f"Benchmark: {args.n_frames} frames, {args.height}×{args.width} px, "
          f"{args.n_z} z-planes, nominal z={z_nominal}")
    print(f"{'motion_type':<12} {'amp':>5} {'tau':>5} "
          f"{'z_amp_rms':>10} {'r':>8} {'rmse':>8}")
    print('─' * 60)

    all_results = []
    for motion_type, amplitude, tau in FULL_SWEEP:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = run_zcorr_benchmark(
                n_frames=args.n_frames,
                height=args.height,
                width=args.width,
                n_z=args.n_z,
                z_nominal=float(z_nominal),
                amplitude_planes=amplitude,
                temporal_smoothness=tau,
                motion_type=motion_type,
                tmp_dir=Path(tmp),
            )

        tag_extra = ""
        if motion_type == 'nonrigid':
            tag_extra = f"  [global r vs patch0: {metrics.get('global_r_vs_patch0', 'N/A'):.3f}]"

        print(f"{motion_type:<12} {amplitude:>5.1f} {tau:>5d} "
              f"{metrics['z_amplitude_rms']:>10.3f} "
              f"{metrics['z_estimation_r']:>8.3f} "
              f"{metrics['z_estimation_rmse']:>8.3f}"
              + tag_extra)

        all_results.append(metrics)

        if args.save_results:
            fname = f"{motion_type}_amp{amplitude:.0f}_tau{tau}.json"
            (args.save_results / fname).write_text(json.dumps(metrics, indent=2))

    if args.save_results:
        (args.save_results / 'all_results.json').write_text(
            json.dumps(all_results, indent=2)
        )
        print(f"\nResults saved to {args.save_results}")


if __name__ == '__main__':
    main()
