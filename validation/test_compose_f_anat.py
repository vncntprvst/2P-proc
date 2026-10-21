"""Check compose_f_anat_non_rigid (memory-light) against make_composite_f_anat (zone averaging).

Runs patch_regress on a few real motion-corrected frames, builds F_anat both ways and
reports the max absolute difference (both are truncated to uint16 as when saved).

Usage
-----
    python validation/test_compose_f_anat.py <mcorr.mmap> <zstack_shifted.tif> <z_correlation.npz>
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from caiman.mmapping import load_memmap
from tifffile import TiffFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules import compute_zcorr as cz  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mmap")
    ap.add_argument("zstack")
    ap.add_argument("zcorr")
    ap.add_argument("--frames", type=int, nargs="+", default=list(range(0, 8000, 333)))
    args = ap.parse_args()

    Yr, dims, T = load_memmap(args.mmap)
    Ny, Nx = dims
    with TiffFile(args.zstack) as tif:
        Z = np.stack([p.asarray() for p in tif.pages], -1).astype(np.float32)
    Z = np.flip(np.clip(Z, 0, 2**16 - 1), axis=0)
    zpos = np.load(args.zcorr)["zpos"]

    rows = []
    for k, f in enumerate(args.frames):
        frame = np.clip(np.reshape(Yr[:, f], dims, order="F"), 0, 2**16 - 1)
        valid = [z for z in range(zpos[f] - 5, zpos[f] + 6) if 0 <= z < Z.shape[2]]
        res = cz.patch_regress((k, frame, Z, Nx, Ny, [60, 60], [36, 36], zpos[f], valid))
        rows += res
    df = pd.DataFrame(rows)
    labeled_zones, _ = cz.calculate_zones(df, Ny, Nx)

    old = np.concatenate(
        [cz.make_composite_f_anat(g, labeled_zones)[0] for _, g in df.groupby("frame_num")]
    )
    old = np.clip(old, 0, 2**16 - 1).astype(np.float32).astype(np.uint16)
    new = cz.compose_f_anat_non_rigid(df.drop(columns="Z_patch"), Z, len(args.frames))
    d = np.abs(old.astype(np.int32) - new.astype(np.int32))
    print(f"frames: {len(args.frames)}, max |old-new|: {d.max()}, "
          f"pixels differing: {(d > 0).mean():.2e}, mean F_anat: {old.mean():.1f}")
    return 0 if d.max() <= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
