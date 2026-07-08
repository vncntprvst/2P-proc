"""Test whether sub-plane (parabolic) interpolation of the z-correlation peak
improves z-position estimation and non-rigid F_anat correction.

Motivation: `compute_zcorrel` picks the best plane by integer argmax, so one might
expect its precision to be capped at ±0.5 plane and improvable by interpolating
the correlation peak — and the same for the per-patch depth used to build the
non-rigid F_anat movie.

Result (tested here): **negligible improvement**, for both the global z-position
and F_anat-based correction. The error is dominated by discrete multi-plane
misassignments (under lateral jitter / deformation) and by signal attenuation
from defocus, not by sub-plane quantization. So sub-plane interpolation is not
worth adding; the real levers are plane-selection robustness (e.g. temporal
regularisation) or the more accurate Suite2p estimator (see benchmark_zpos_methods).

Run: cd validation && pixi run python test_subplane_precision.py --real-zstack <ZSeries>
"""

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.benchmarks.synthetic_zstack import (
    make_rigid_z_trajectory,
    make_xy_trajectory,
    make_functional_movie,
    save_zstack_tiff,
    save_caiman_memmap,
)
from tests.benchmarks.synthetic_activity import (
    detect_somata,
    make_calcium_traces,
    make_active_functional_movie,
)
from tests.benchmarks.benchmark_correction_methods import (
    _register_zstack_to_fov,
    _roi_trace,
    _huber_subtract,
    _recovery,
)


def subpixel_zpos(zcorr, sigma=3):
    """Parabolic interpolation of the (z-smoothed) correlation peak per frame."""
    c = gaussian_filter(zcorr, sigma=sigma, axes=0)
    p = np.argmax(c, axis=0)
    out = p.astype(float)
    nz = c.shape[0]
    for t in range(c.shape[1]):
        z = p[t]
        if 0 < z < nz - 1:
            a, b, d = c[z - 1, t], c[z, t], c[z + 1, t]
            den = a - 2 * b + d
            if den != 0:
                out[t] = z + np.clip(0.5 * (a - d) / den, -0.5, 0.5)
    return out


def _fanat_from_z(reg, zf):
    """Anatomy movie sampled at fractional z (linear interp between planes)."""
    nz = reg.shape[0]
    zf = np.clip(zf, 0, nz - 1)
    lo = np.floor(zf).astype(int)
    hi = np.minimum(lo + 1, nz - 1)
    fr = zf - lo
    return reg[lo] * (1 - fr)[:, None, None] + reg[hi] * fr[:, None, None]


def main():
    from modules.compute_zcorr import compute_zcorrel

    p = argparse.ArgumentParser()
    p.add_argument("--real-zstack", type=Path, required=True)
    p.add_argument("--downsample", type=int, default=4)
    p.add_argument("--channel", type=int, default=2)
    args = p.parse_args()

    from tests.benchmarks.bruker_io import load_bruker_zstack

    vol, _ = load_bruker_zstack(args.real_zstack, channel=args.channel, downsample=args.downsample)
    znom = (vol.shape[0] - 1) / 2

    print("== Global z-position (RMSE in planes vs continuous ground truth) ==")
    print(f"{'z_amp':>5} {'method':<10} {'r':>7} {'rmse_planes':>12}")
    for amp in [1.0, 2.0, 4.0]:
        T = 300
        zoff = make_rigid_z_trajectory(T, amp, 8, seed=3)
        z_true = znom + zoff
        xy = make_xy_trajectory(T, 1.0, 8, seed=3)
        mov, _ = make_functional_movie(vol, znom, zoff, xy_offsets=xy, deform_amp=0.5, seed=3)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            save_zstack_tiff(vol, tmp / "z.tif")
            dd = tmp / "b" / "i"
            dd.mkdir(parents=True)
            mp = save_caiman_memmap(mov, dd)
            zc = compute_zcorrel(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)
        for name, zp in [
            ("integer", zc["zpos"].astype(float)),
            ("subplane", subpixel_zpos(zc["zcorr"])),
        ]:
            r = np.corrcoef(z_true, zp)[0, 1]
            rmse = np.sqrt(np.mean((z_true - zp) ** 2))
            print(f"{amp:>5.0f} {name:<10} {r:>7.3f} {rmse:>12.3f}")

    print("\n== F_anat-based per-ROI correction (recovery of injected activity) ==")
    print(f"{'z_amp':>5} {'F_anat':<10} {'recovery_r':>11} {'residual_z_r':>13}")
    for amp in [3.0, 6.0]:
        T = 200
        centers = detect_somata(vol, 40, 5, margin=8, z_center=znom, z_band=4)
        tc, _ = make_calcium_traces(len(centers), T, 20, 0.15, 1.0, seed=1)
        zoff = make_rigid_z_trajectory(T, amp, 8, seed=1)
        xy = make_xy_trajectory(T, 1.0, 8, seed=1)
        mov, gt = make_active_functional_movie(
            vol, znom, zoff, centers, tc, xy_offsets=xy, deform_amp=0.5, activity_gain=1500, seed=1
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            save_zstack_tiff(vol, tmp / "z.tif")
            dd = tmp / "b" / "i"
            dd.mkdir(parents=True)
            mp = save_caiman_memmap(mov, dd)
            zc = compute_zcorrel(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)
        reg = _register_zstack_to_fov(np.flip(vol, axis=1), mov.mean(0))
        for name, zf in [
            ("integer", zc["zpos"].astype(float)),
            ("subplane", subpixel_zpos(zc["zcorr"])),
        ]:
            fanat = _fanat_from_z(reg, zf)
            traces = {
                i: _huber_subtract(_roi_trace(mov, cy, cx), _roi_trace(fanat, cy, cx))
                for i, (z, cy, cx) in enumerate(centers)
            }
            rec = _recovery(traces, tc, gt["z_true"])
            print(f"{amp:>5.1f} {name:<10} {rec['recovery_r']:>11.3f} {rec['residual_z_r']:>13.3f}")


if __name__ == "__main__":
    main()
