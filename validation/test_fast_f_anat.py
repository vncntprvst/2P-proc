"""Check compute_zcorr.f_anat_non_rigid_fast (argmax) against a production F_anat tiff.

Usage
-----
    python validation/test_fast_f_anat.py <mcorr.mmap> <zstack_shifted.tif> <z_correlation.npz> \
        <F_anat_non_rigid.tiff> [--frames 0 400]
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from caiman.mmapping import load_memmap
from tifffile import TiffFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules import compute_zcorr as cz  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mmap")
    ap.add_argument("zstack")
    ap.add_argument("zcorr")
    ap.add_argument("f_anat")
    ap.add_argument("--frames", type=int, nargs=2, default=[0, 400])
    args = ap.parse_args()
    a, b = args.frames

    Yr, dims, T = load_memmap(args.mmap)
    mov = np.reshape(Yr[:, a:b].T, [b - a] + list(dims), order="F")
    mov = np.clip(mov, 0, 2**16 - 1).astype(np.float32)
    with TiffFile(args.zstack) as tif:
        Z = np.stack([p.asarray() for p in tif.pages], -1).astype(np.float32)
    Z = np.flip(np.clip(Z, 0, 2**16 - 1), axis=0)
    zpos = np.load(args.zcorr)["zpos"][a:b]
    t0 = time.time()
    fast, _, _ = cz.f_anat_non_rigid_fast(mov, Z, {"strides": [36, 36], "overlaps": [24, 24]}, zpos)
    dt = time.time() - t0
    with TiffFile(args.f_anat) as tif:
        ref = np.stack([tif.pages[i].asarray() for i in range(a, b)])
    d = np.abs(fast.astype(np.int32) - ref.astype(np.int32))
    print(f"{b - a} frames in {dt:.1f} s; max |fast-ref| {d.max()}, "
          f"frac pixels differing {(d > 0).mean():.2e}, frac > 1 {(d > 1).mean():.2e}")


if __name__ == "__main__":
    main()
