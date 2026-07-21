"""Export the synthetic ground-truth dataset as inspectable TIFFs + sidecar.

Builds the response-coupled synthetic functional movie used in the correction
benchmarks (real z-stack anatomy + injected calcium activity + a known z-motion
trajectory whose downward onsets cluster on stimulus responses) and writes it to
disk so it can be opened in ImageJ/napari and shared.

Outputs (into --out):
  synthetic_movie.tif        (T, H, W) uint16  — the functional movie to inspect
  synthetic_baseline.tif     (T, H, W) uint16  — oracle anatomy under the same
                                                 motion, NO activity (the F_anat
                                                 predictor the correction uses)
  synthetic_anatomy.tif      (Z, H, W) uint16  — the real z-stack (anatomy volume)
  synthetic_ground_truth.npz — trueC, cell_centers, z_true (per-frame focal
                                 plane), zoff, events, framerate, scale
  synthetic_dataset_README.md — provenance + how the movie was built

Run: python validation/export_synthetic_movie.py --real-zstack <ZSeries> --out DIR
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.benchmarks.bruker_io import load_bruker_zstack
from tests.benchmarks.synthetic_zstack import make_xy_trajectory, make_functional_movie
from tests.benchmarks.synthetic_activity import (
    detect_somata,
    make_active_functional_movie,
    make_stimulus_locked_traces,
    make_response_coupled_zmotion,
)


def _to_uint16(movie):
    """Scale a float movie to the full uint16 range for viewing (shared scale)."""
    lo, hi = np.percentile(movie, 0.1), np.percentile(movie, 99.9)
    m = np.clip((movie - lo) / max(hi - lo, 1e-6), 0, 1)
    return (m * 65535).astype(np.uint16)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--real-zstack", type=Path, required=True)
    p.add_argument("--downsample", type=int, default=2)
    p.add_argument("--n-frames", type=int, default=600)
    p.add_argument("--n-cells", type=int, default=60)
    p.add_argument("--z-band", type=int, default=6)
    p.add_argument("--n-events", type=int, default=20)
    p.add_argument("--kick-amp", type=float, default=1.8)
    p.add_argument(
        "--real-zpos",
        type=Path,
        default=Path(__file__).parent / "report" / "figures" / "zpos_single.npz",
        help="npz with a real estimated zpos trajectory used as the background "
        "z-fluctuation (on top of the response-coupled kicks)",
    )
    p.add_argument("--real-zpos-key", default="zpos_caiman")
    p.add_argument("--framerate", type=float, default=20.0)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vol, _ = load_bruker_zstack(args.real_zstack, channel=2, downsample=args.downsample)
    znom = (vol.shape[0] - 1) / 2.0
    T = args.n_frames

    centers = detect_somata(
        vol, n_cells=args.n_cells, min_distance=5, margin=8, z_center=znom, z_band=args.z_band
    )
    n = len(centers)

    base = None
    if args.real_zpos is not None and args.real_zpos.exists():
        base = np.load(args.real_zpos)[args.real_zpos_key].astype(np.float32)
        # tile/trim the real trajectory to T frames
        if len(base) < T:
            base = np.tile(base, int(np.ceil(T / len(base))))
        base = base[:T]

    # Stimulus-locked responses + response-coupled downward z-motion.
    trueC, trueS, events, responsive = make_stimulus_locked_traces(
        n, T, framerate=args.framerate, decay_time=0.15, n_events=args.n_events, seed=args.seed
    )
    base_bg = 0.4 * (base - base.mean()) if base is not None else None
    zoff = make_response_coupled_zmotion(
        T,
        events,
        base_zoff=base_bg,
        framerate=args.framerate,
        kick_amp=args.kick_amp,
        seed=args.seed,
    )

    xy = make_xy_trajectory(T, 1.0, 8, seed=args.seed)
    movie, gt = make_active_functional_movie(
        vol,
        znom,
        zoff,
        centers,
        trueC,
        xy_offsets=xy,
        deform_amp=0.5,
        activity_gain=1500,
        seed=args.seed,
    )
    baseline, _ = make_functional_movie(
        vol, znom, zoff, xy_offsets=xy, deform_amp=0.5, noise_factor=0.0, seed=args.seed
    )

    pop = (trueC / (trueC.mean(1, keepdims=True) + 1e-6)).mean(0)
    coupling = float(np.corrcoef(pop, gt["z_true"])[0, 1])

    # ── Write TIFFs (uint16 for easy viewing) ────────────────────────────────
    tifffile.imwrite(args.out / "synthetic_movie.tif", _to_uint16(movie))
    tifffile.imwrite(args.out / "synthetic_baseline.tif", _to_uint16(baseline))
    tifffile.imwrite(args.out / "synthetic_anatomy.tif", _to_uint16(vol.astype(np.float32)))

    np.savez(
        args.out / "synthetic_ground_truth.npz",
        trueC=trueC.astype(np.float32),
        trueS=trueS.astype(np.float32),
        cell_centers=gt["cell_centers"].astype(int),
        responsive=responsive,
        z_true=gt["z_true"].astype(np.float32),
        zoff=zoff.astype(np.float32),
        events=np.asarray(events, dtype=int),
        framerate=np.float32(args.framerate),
    )

    meta = {
        "n_frames": int(T),
        "shape_TYX": [int(s) for s in movie.shape],
        "n_cells": int(n),
        "n_responsive": int(responsive.sum()),
        "n_events": int(len(events)),
        "z_planes": int(vol.shape[0]),
        "z_nominal_plane": float(znom),
        "z_std_planes": float(zoff.std()),
        "z_ptp_planes": float(zoff.max() - zoff.min()),
        "activity_z_coupling_r": coupling,
        "downsample": int(args.downsample),
        "source_zstack": str(args.real_zstack),
        "framerate_hz": float(args.framerate),
    }
    (args.out / "synthetic_ground_truth_meta.json").write_text(json.dumps(meta, indent=2))
    (args.out / "synthetic_dataset_README.md").write_text(
        "# Synthetic z-motion dataset\n\n"
        "Ground-truth functional movie for z-motion-correction validation. NAOMi-lite: "
        f"real anatomy from `{Path(args.real_zstack).name}` (Ch2, {args.downsample}x "
        f"downsampled) as the volume, {n} somata detected near the focal plane, injected "
        "with spike->AR(1) GCaMP activity, sampled along a **known** 3D trajectory (rigid z "
        "+ xy jitter + mild deformation). An axial-Gaussian gain models defocus, so z-motion "
        "attenuates cells (the artifact to correct).\n\n"
        "The z-motion is **response-coupled**: downward (negative) displacement onsets cluster "
        f"around {len(events)} stimulus events, so brain motion co-occurs with responses "
        f"(activity-z coupling r = {coupling:.2f}), as in the real protocol.\n\n"
        "## Files\n"
        "- `synthetic_movie.tif` — the functional movie (T, Y, X), uint16, shared display scale.\n"
        "- `synthetic_baseline.tif` — same motion, NO activity (the oracle F_anat predictor).\n"
        "- `synthetic_anatomy.tif` — the real z-stack volume (Z, Y, X).\n"
        "- `synthetic_ground_truth.npz` — trueC/trueS, cell_centers (z,y,x), responsive mask, "
        "z_true (per-frame focal plane), zoff, events, framerate.\n\n"
        "The `.tif` is uint16-scaled for viewing; use the npz for exact ground truth.\n"
    )

    print(
        f"movie {movie.shape}  {n} cells ({int(responsive.sum())} responsive), "
        f"{len(events)} events"
    )
    print(
        f"z: std {zoff.std():.2f}, p2p {zoff.max()-zoff.min():.1f} planes | "
        f"activity-z coupling r={coupling:.2f}"
    )
    for f in sorted(args.out.glob("synthetic_*")):
        print(f"  {f.name}  ({f.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
