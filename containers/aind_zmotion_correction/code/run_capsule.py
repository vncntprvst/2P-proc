"""AIND capsule entry point for z-motion (axial drift) correction.

Estimates per-frame axial (z) drift of a motion-corrected functional movie by
correlating each frame against an anatomical z-stack, using the pipeline's
``modules.compute_zcorr.compute_zcorrel``. Optionally subtracts the estimated
z-motion with the non-rigid patch method.

Inputs (mounted at /data):
  - a motion-corrected movie HDF5 (``motion_corrected.h5`` or the first *.h5),
    dataset key ``data``, shape (T, H, W);
  - an anatomical z-stack: a multipage TIFF or a Bruker ZSeries directory.

Outputs (written to /results):
  - z_correlation.npz  (zcorr [n_z, T], zpos [T])
  - z_drift.png
  - processing.json
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

_DEFAULT_DATA_DIR = Path("/data")
_DEFAULT_RESULTS_DIR = Path("/results")


def _ts():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def main():
    parser = argparse.ArgumentParser(description="AIND z-motion correction capsule")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_DEFAULT_DATA_DIR,
        help="Input dir with the movie .h5 and z-stack (default: /data)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=_DEFAULT_RESULTS_DIR,
        help="Output dir (default: /results)",
    )
    parser.add_argument(
        "--zstack",
        type=Path,
        default=None,
        help="Explicit z-stack TIFF or ZSeries dir (else auto-detect in /data)",
    )
    parser.add_argument(
        "--smooth-sigma",
        type=int,
        default=3,
        help="Spatial Gaussian smoothing before correlation (default: 3)",
    )
    parser.add_argument(
        "--z-step-um",
        type=float,
        default=1.0,
        help="Micron spacing between z-planes, for plotting (default: 1.0)",
    )
    args = parser.parse_args()

    DATA_DIR = args.data_dir
    RESULTS_DIR = args.results_dir
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    start_time = datetime.utcnow().isoformat()

    params = {
        "smooth_sigma": args.smooth_sigma,
        "z_step_um": args.z_step_um,
    }

    print(f"[{_ts()}] AIND z-motion correction capsule starting")
    print(f"[{_ts()}] Data dir  : {DATA_DIR}")
    print(f"[{_ts()}] Results dir: {RESULTS_DIR}")

    from io_utils import (
        read_input_movie,
        load_zstack,
        movie_to_caiman_memmap,
        write_zcorr_outputs,
        write_processing_json,
    )

    # 1. Read movie + z-stack
    print(f"[{_ts()}] Step 1/4 — reading movie and z-stack...")
    try:
        movie, movie_path = read_input_movie(DATA_DIR)
        _, zstack_tif = load_zstack(DATA_DIR, RESULTS_DIR, explicit=args.zstack)
    except FileNotFoundError as exc:
        print(f"[{_ts()}] ERROR: {exc}")
        sys.exit(1)

    # 2. Bridge the movie into the CaImAn memmap format compute_zcorrel expects.
    print(f"[{_ts()}] Step 2/4 — writing CaImAn memmap...")
    memmap_path = movie_to_caiman_memmap(movie, RESULTS_DIR)

    # 3. Estimate z-drift
    print(f"[{_ts()}] Step 3/4 — computing z-correlation...")
    from modules.compute_zcorr import compute_zcorrel

    z_correlation = compute_zcorrel(
        str(zstack_tif),
        str(memmap_path),
        smooth_sigma=args.smooth_sigma,
        export_path=RESULTS_DIR,
    )
    if z_correlation is None:
        print(f"[{_ts()}] ERROR: z-stack XY dims do not match the movie; cannot correlate.")
        sys.exit(1)

    zpos = z_correlation["zpos"]
    print(
        f"[{_ts()}] z-drift estimated: mean plane {float(zpos.mean()):.1f}, "
        f"peak-to-peak {float(zpos.max() - zpos.min()) * args.z_step_um:.1f} µm"
    )

    # 4. Write outputs + processing.json
    print(f"[{_ts()}] Step 4/4 — writing outputs...")
    write_zcorr_outputs(z_correlation, RESULTS_DIR, z_step_um=args.z_step_um)
    end_time = datetime.utcnow().isoformat()
    write_processing_json(
        params,
        RESULTS_DIR,
        start_time,
        end_time,
        outputs=["z_correlation.npz", "z_drift.png"],
    )

    print(f"[{_ts()}] Capsule complete. Outputs written to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
