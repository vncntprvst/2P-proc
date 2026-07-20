"""Motion-correct one real TSeries and save a downsampled TIFF for figures.

Produces a reusable real-data motion-corrected movie so the per-ROI correction
figure (and other real-data plots) don't each re-run NoRMCorre.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import tifffile
from skimage.measure import block_reduce

sys.path.insert(0, str(Path(__file__).parent.parent))
from tests.benchmarks.bruker_io import load_bruker_tseries
from zpos_compare_data import _mcorr_session  # noqa: E402  (same dir)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tseries", type=Path, required=True)
    p.add_argument("--downsample", type=int, default=3)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--work-dir", type=Path, default=Path("/tmp/mcorr_asset_work"))
    args = p.parse_args()

    import caiman as cm

    full = load_bruker_tseries(args.tseries, channel=2, downsample=1)
    print(f"loaded {full.shape}, running NoRMCorre...", flush=True)
    c, dview, n = cm.cluster.setup_cluster(
        backend="multiprocessing", n_processes=8, single_thread=False
    )
    try:
        mcorr = _mcorr_session(full, dview, args.work_dir)
    finally:
        cm.stop_server(dview=dview)
    if args.downsample > 1:
        mcorr = block_reduce(mcorr, (1, args.downsample, args.downsample), np.mean).astype(
            np.float32
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(args.out, mcorr.astype(np.float32))
    print(f"wrote {args.out}  {mcorr.shape}")


if __name__ == "__main__":
    main()
