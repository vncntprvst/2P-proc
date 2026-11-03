"""Time reading raw single-page TIFFs with 1 or more threads, on files not read before in the job.

    python read_timing.py --src DIR --threads 1 8 32 [--n 200] [--skip 2000]
"""

import argparse
import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from libtiff import TIFF, libtiff_ctypes

parser = argparse.ArgumentParser()
parser.add_argument("--src", required=True)
parser.add_argument("--threads", type=int, nargs="+", default=[1, 8, 32])
parser.add_argument("--n", type=int, default=200)
parser.add_argument("--skip", type=int, default=2000)
parser.add_argument("--regex", default="*_Ch2_*.ome.tif")
args = parser.parse_args()
libtiff_ctypes.suppress_warnings()


def read(f):
    tif = TIFF.open(f, "r")
    img = np.flipud(tif.read_image())
    tif.close()
    return img


files = sorted(glob.glob(os.path.join(args.src, args.regex)))
print(f"{args.src}: {len(files)} files", flush=True)
start = args.skip
for k in args.threads:
    batch = files[start : start + args.n]
    start += args.n
    t = time.time()
    with ThreadPoolExecutor(k) as pool:
        frames = list(pool.map(read, batch))
    dt = time.time() - t
    mb = sum(fr.nbytes for fr in frames) / 1e6
    print(f"  {k:3d} threads: {1000 * dt / len(batch):6.1f} ms/frame, {mb / dt:6.0f} MB/s", flush=True)
