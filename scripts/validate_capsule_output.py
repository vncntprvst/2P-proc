"""Validate the outputs of the aind_nonrigid_mcorr capsule.

Run this after a test run to confirm the capsule produced well-formed outputs
before submitting a PR to the AIND pipeline.

Usage
-----
    python validate_capsule_output.py RESULTS_DIR [INPUT_H5]

    RESULTS_DIR   Directory written by the capsule (/results mount target).
    INPUT_H5      (Optional) Original input HDF5 to check shape consistency.

Exit code 0 = all checks passed.  Non-zero = at least one check failed.
"""

import argparse
import json
import sys
from pathlib import Path

import h5py
import numpy as np


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return condition


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("input_h5", type=Path, nargs="?", default=None)
    args = parser.parse_args()

    results = args.results_dir
    failures = 0

    print(f"\nValidating capsule outputs in: {results}\n")

    # ── motion_corrected.h5 ──────────────────────────────────────────────────
    print("motion_corrected.h5:")
    mc_path = results / "motion_corrected.h5"
    if not check("file exists", mc_path.exists()):
        failures += 1
    else:
        try:
            with h5py.File(mc_path, "r") as f:
                has_data = "data" in f
                if not check("'data' dataset present", has_data):
                    failures += 1
                else:
                    arr = f["data"]
                    shape_ok = arr.ndim == 3
                    if not check("dataset is 3-D (T, H, W)", shape_ok, f"shape={arr.shape}"):
                        failures += 1
                    else:
                        dtype_ok = np.issubdtype(arr.dtype, np.floating)
                        if not check("dtype is float", dtype_ok, str(arr.dtype)):
                            failures += 1
                        # Compare shape with input if provided
                        if args.input_h5 and args.input_h5.exists():
                            with h5py.File(args.input_h5, "r") as fin:
                                for key in ("data", "mov", "movie"):
                                    if key in fin:
                                        in_shape = fin[key].shape
                                        shapes_match = arr.shape == in_shape
                                        if not check(
                                            "shape matches input",
                                            shapes_match,
                                            f"corrected={arr.shape} input={in_shape}",
                                        ):
                                            failures += 1
                                        break
        except Exception as exc:
            print(f"  [FAIL] could not open HDF5: {exc}")
            failures += 1

    # ── *_transforms.csv ────────────────────────────────────────────────────
    print("\ntransforms CSV:")
    csv_files = list(results.glob("*_transforms.csv"))
    if not check("at least one *_transforms.csv", len(csv_files) > 0):
        failures += 1
    else:
        import csv
        for csv_path in csv_files:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    has_cols = {"frame", "x_shift", "y_shift"}.issubset(reader.fieldnames or [])
                    if not check(f"{csv_path.name}: required columns present", has_cols,
                                 str(reader.fieldnames)):
                        failures += 1
                    if not check(f"{csv_path.name}: non-empty ({len(rows)} rows)", len(rows) > 0):
                        failures += 1
            except Exception as exc:
                print(f"  [FAIL] {csv_path.name}: {exc}")
                failures += 1

    # ── projection PNGs ─────────────────────────────────────────────────────
    print("\nprojection PNGs:")
    for name in ("max_projection.png", "mean_projection.png"):
        png_path = results / name
        exists = png_path.exists()
        if not check(f"{name} exists", exists):
            failures += 1
        elif exists:
            size_ok = png_path.stat().st_size > 1000
            if not check(f"{name} size > 1 KB", size_ok, f"{png_path.stat().st_size} bytes"):
                failures += 1

    # ── processing.json ─────────────────────────────────────────────────────
    print("\nprocessing.json:")
    proc_path = results / "processing.json"
    if not check("file exists", proc_path.exists()):
        failures += 1
    else:
        try:
            with open(proc_path) as f:
                proc = json.load(f)
            required_keys = {"capsule_name", "version", "algorithm", "start_time", "end_time", "parameters"}
            missing = required_keys - proc.keys()
            if not check("required keys present", not missing, f"missing: {missing}"):
                failures += 1
            # Sanity-check parameters
            params = proc.get("parameters", {})
            if not check("parameters non-empty", bool(params)):
                failures += 1
        except Exception as exc:
            print(f"  [FAIL] could not parse JSON: {exc}")
            failures += 1

    # ── summary ─────────────────────────────────────────────────────────────
    print(f"\n{'─' * 50}")
    if failures == 0:
        print(f"All checks passed. Capsule output looks good.")
    else:
        print(f"{failures} check(s) FAILED. Review output above before submitting PR.")
    return failures


if __name__ == "__main__":
    sys.exit(main())
