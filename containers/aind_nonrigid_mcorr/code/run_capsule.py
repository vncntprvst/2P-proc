"""AIND capsule entry point for non-rigid motion correction using CaImAn/NoRMCorre."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("/data")
RESULTS_DIR = Path("/results")


def _ts():
    """Return a UTC ISO-format timestamp string for progress logging."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def main():
    parser = argparse.ArgumentParser(
        description="AIND non-rigid motion correction capsule (CaImAn/NoRMCorre)"
    )
    parser.add_argument(
        "--pw-rigid",
        action="store_true",
        default=True,
        help="Use piecewise-rigid (non-rigid) correction (default: True)",
    )
    parser.add_argument(
        "--no-pw-rigid",
        dest="pw_rigid",
        action="store_false",
        help="Use rigid-only correction",
    )
    parser.add_argument(
        "--max-shifts",
        type=int,
        default=6,
        help="Maximum shift in pixels (applied to both axes, default: 6)",
    )
    parser.add_argument(
        "--strides",
        type=int,
        default=48,
        help="Patch stride in pixels for pw-rigid mode (default: 48)",
    )
    parser.add_argument(
        "--overlaps",
        type=int,
        default=24,
        help="Patch overlap in pixels for pw-rigid mode (default: 24)",
    )
    parser.add_argument(
        "--niter-rig",
        type=int,
        default=1,
        help="Number of rigid correction iterations (default: 1)",
    )
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    start_time = datetime.utcnow().isoformat()

    # Collect parameters for processing.json
    params = {
        "pw_rigid": args.pw_rigid,
        "max_shifts": (args.max_shifts, args.max_shifts),
        "strides": (args.strides, args.strides),
        "overlaps": (args.overlaps, args.overlaps),
        "niter_rig": args.niter_rig,
    }

    print(f"[{_ts()}] AIND non-rigid motion correction capsule starting")
    print(f"[{_ts()}] Parameters: {params}")
    print(f"[{_ts()}] Data dir  : {DATA_DIR}")
    print(f"[{_ts()}] Results dir: {RESULTS_DIR}")

    # ------------------------------------------------------------------
    # 1. Read input movie
    # ------------------------------------------------------------------
    from io_utils import read_input_movie

    print(f"[{_ts()}] Step 1/4 — reading input movie...")
    try:
        movie, source_path = read_input_movie(DATA_DIR)
    except FileNotFoundError as exc:
        print(f"[{_ts()}] ERROR: {exc}")
        sys.exit(1)
    except KeyError as exc:
        print(f"[{_ts()}] ERROR: {exc}")
        sys.exit(1)

    print(f"[{_ts()}] Input: {source_path.name}, shape={movie.shape}")

    # ------------------------------------------------------------------
    # 2. Run motion correction
    # ------------------------------------------------------------------
    from mcorr_utils import run_caiman_mcorr

    print(f"[{_ts()}] Step 2/4 — running CaImAn motion correction...")
    corrected, shifts_dict = run_caiman_mcorr(
        movie,
        pw_rigid=args.pw_rigid,
        max_shifts=(args.max_shifts, args.max_shifts),
        strides=(args.strides, args.strides),
        overlaps=(args.overlaps, args.overlaps),
        niter_rig=args.niter_rig,
    )
    print(f"[{_ts()}] Motion correction finished, corrected shape={corrected.shape}")

    # ------------------------------------------------------------------
    # 3. Write all outputs
    # ------------------------------------------------------------------
    from io_utils import write_corrected_movie, write_projections, write_transforms_csv

    print(f"[{_ts()}] Step 3/4 — writing outputs...")

    # motion_corrected.h5
    write_corrected_movie(corrected, RESULTS_DIR / "motion_corrected.h5")

    # <stem>_transforms.csv — use the source filename stem as prefix
    csv_name = source_path.stem + "_transforms.csv"
    write_transforms_csv(shifts_dict, RESULTS_DIR / csv_name)

    # max_projection.png and mean_projection.png
    write_projections(corrected, RESULTS_DIR)

    # ------------------------------------------------------------------
    # 4. Write processing.json
    # ------------------------------------------------------------------
    from io_utils import write_processing_json

    print(f"[{_ts()}] Step 4/4 — writing processing.json...")
    end_time = datetime.utcnow().isoformat()
    write_processing_json(params, RESULTS_DIR, start_time, end_time)

    print(f"[{_ts()}] Capsule complete. Outputs written to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
