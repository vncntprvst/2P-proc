"""Time the parts of the concatenation step (modules/bruker_concat_tif.py) for one or more raw folders.

For each --src folder: list the files, read the first --n frames as the pipeline does (libtiff),
write them to a multi-page TIFF in --out, then convert it to the BigTIFF with
convert_to_bigtiff. The BigTIFF write is also timed to /dev/shm (memory), to separate encoding
from disk writes. Source files are only read.

    python concat_timing.py --src DIR [--src DIR ...] --out DIR [--n 2000]
"""

import argparse
import glob
import os
import sys
import time

import numpy as np
from libtiff import TIFF, libtiff_ctypes
from tifffile import imwrite

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "modules"))
import bruker_concat_tif as ct  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--src", action="append", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--n", type=int, default=2000)
parser.add_argument("--regex", default="*_Ch2_*.ome.tif")
args = parser.parse_args()
libtiff_ctypes.suppress_warnings()
os.makedirs(args.out, exist_ok=True)


def report(label, seconds, n):
    print(f"  {label:<28} {seconds:8.1f} s   {1000 * seconds / n:6.1f} ms/frame", flush=True)


for src in args.src:
    print(f"\n{src}", flush=True)
    t = time.time()
    files = sorted(glob.glob(os.path.join(src, args.regex)))
    print(f"  list files                   {time.time() - t:8.1f} s   ({len(files)} files)")
    files = files[: args.n]
    n = len(files)
    if n == 0:
        print("  no files found")
        continue

    frames = []
    t = time.time()
    for f in files:
        tif = TIFF.open(f, "r")
        frames.append(np.flipud(tif.read_image()))
        tif.close()
    report("read (libtiff)", time.time() - t, n)
    size_gb = sum(fr.nbytes for fr in frames) / 1e9
    print(f"  {size_gb:.2f} GB, {1000 * size_gb / (time.time() - t):.0f} MB/s")

    mpt = os.path.join(args.out, "timing_mpt.tiff")
    bt = os.path.join(args.out, "timing_bt.tiff")
    t = time.time()
    out_tif = TIFF.open(mpt, mode="w8")
    for fr in frames:
        out_tif.write_image(fr, compression=None)
    out_tif.close()
    os.sync()
    report("write multi-page TIFF", time.time() - t, n)

    t = time.time()
    ct.convert_to_bigtiff(mpt, bt, "lzw", False)
    os.sync()
    report("convert_to_bigtiff", time.time() - t, n)

    shm = "/dev/shm/timing_bt.tiff"
    movie = np.stack(frames)
    t = time.time()
    imwrite(shm, movie, imagej=False, bigtiff=True, metadata=None, dtype=np.uint16,
            compressionargs={"compression": "lzw"})
    report("same write, to memory only", time.time() - t, n)
    print(f"  BigTIFF is {os.path.getsize(shm) / movie.nbytes:.0%} of the raw size")
    for p in (bt, shm):
        os.remove(p)
    del frames, movie
