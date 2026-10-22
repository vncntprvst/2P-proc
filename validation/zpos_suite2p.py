"""Suite2p-style z-position (compute_zcorrel_suite2p) on a pipeline memmap, saved elsewhere.

compute_zcorrel_suite2p writes z_correlation.npz two levels above the movie, which would replace
the pipeline's own file; the movie is linked into <out>/mm/ so the output lands in <out>.

    pixi run python validation/zpos_suite2p.py <movie.mmap> <zstack_shifted.tif> <out_dir>
"""

import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.compute_zcorr import compute_zcorrel_suite2p  # noqa: E402

mmap, zstack, out = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
(out / "mm").mkdir(parents=True, exist_ok=True)
link = out / "mm" / mmap.name
if not link.exists():
    os.symlink(mmap, link)
t = time.time()
zc = compute_zcorrel_suite2p(zstack, link)
os.replace(out / "z_correlation.npz", out / "z_correlation_suite2p.npz")
print(f"done in {time.time() - t:.0f} s; zpos counts {np.bincount(zc['zpos'].astype(int))}")
