"""Test whether cropping the NoRMCorre border rescues Suite2p phase-correlation.

On real motion-corrected movies, Suite2p masked phase-correlation is much jumpier
than the shipped Pearson estimator. The hypothesis is that NoRMCorre's
``border_nan="copy"`` leaves low-information copied strips at the frame edges that
corrupt the masked correlation. This tests the obvious mitigation: **central-crop**
the movie (and z-stack) to remove those strips before estimating z, over a range
of crop fractions, and measure whether phase-correlation stabilises toward the
Pearson estimate.

Metric: number of spurious ≥2-plane frame-to-frame jumps (lower = more stable),
and agreement r between the two estimators. If a crop makes phasecorr's jump count
approach Pearson's while keeping high agreement, the edge artifact is the cause and
is fixable; if not, phasecorr is unsuitable for production regardless.

Run (stable and latest envs):
  pixi run python validation/test_edge_mitigation.py --mcorr-tiff <tif> --zseries <ZSeries>
  pixi run -e latest python validation/test_edge_mitigation.py ...
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).parent.parent))
from tests.benchmarks.bruker_io import load_bruker_zstack
from tests.benchmarks.synthetic_zstack import save_caiman_memmap, save_zstack_tiff


def _jumps(z, thr=2):
    return int(np.sum(np.abs(np.diff(np.asarray(z).astype(int))) >= thr))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mcorr-tiff", type=Path, required=True)
    p.add_argument("--zseries", type=Path, required=True)
    p.add_argument("--zseries-downsample", type=int, default=3)
    p.add_argument("--crops", type=str, default="0.0,0.05,0.10,0.15,0.20")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    import caiman  # noqa: F401 — surface the env version
    import suite2p

    caiman_v = __import__("caiman").__version__
    s2p_v = getattr(suite2p, "version", getattr(suite2p, "__version__", "?"))
    print(f"caiman {caiman_v} | suite2p {s2p_v}")

    from modules.compute_zcorr import compute_zcorrel, compute_zcorrel_suite2p

    movie = tifffile.imread(str(args.mcorr_tiff)).astype(np.float32)
    vol, _ = load_bruker_zstack(args.zseries, channel=2, downsample=args.zseries_downsample)
    h = min(vol.shape[1], movie.shape[1])
    w = min(vol.shape[2], movie.shape[2])
    vol, movie = vol[:, :h, :w], movie[:, :h, :w]
    print(f"movie {movie.shape}  zstack {vol.shape}")

    rows = []
    for cf in [float(c) for c in args.crops.split(",") if c.strip()]:
        cy = int(cf * movie.shape[1])
        cx = int(cf * movie.shape[2])
        if cy > 0:
            m = movie[:, cy:-cy, cx:-cx]
            v = vol[:, cy:-cy, cx:-cx]
        else:
            m, v = movie, vol
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            save_zstack_tiff(v, tmp / "z.tif")
            dd = tmp / "b" / "i"
            dd.mkdir(parents=True)
            mp = save_caiman_memmap(m, dd)
            zc = compute_zcorrel(tmp / "z.tif", mp, smooth_sigma=3, export_path=tmp)
            zs = compute_zcorrel_suite2p(tmp / "z.tif", mp, smooth_sigma=3)
        zc_z, zs_z = zc["zpos"].astype(float), zs["zpos"].astype(float)
        agree = float(np.corrcoef(zc_z, zs_z)[0, 1]) if zc_z.std() and zs_z.std() else float("nan")
        row = {
            "crop_frac": cf,
            "shape": [int(s) for s in m.shape],
            "pearson_jumps": _jumps(zc_z),
            "suite2p_jumps": _jumps(zs_z),
            "pearson_std": float(zc_z.std()),
            "suite2p_std": float(zs_z.std()),
            "agreement_r": agree,
        }
        rows.append(row)
        print(
            f"crop {cf:.2f} -> {m.shape[1]}x{m.shape[2]}: "
            f"jumps pearson={row['pearson_jumps']} suite2p={row['suite2p_jumps']}  "
            f"agreement r={agree:.2f}  (pearson std {zc_z.std():.2f}, suite2p std {zs_z.std():.2f})"
        )

    out = {"caiman": caiman_v, "suite2p": str(s2p_v), "results": rows}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
