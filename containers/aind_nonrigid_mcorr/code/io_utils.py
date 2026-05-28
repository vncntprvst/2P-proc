"""
AIND capsule I/O utilities for non-rigid motion correction.

Handles HDF5 read/write, CSV shift export, projection images, and
AIND-compatible processing.json metadata.
"""

import json
from pathlib import Path

import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read_input_movie(data_dir):
    """Scan data_dir for .h5 files and read the 'data' dataset.

    Parameters
    ----------
    data_dir : Path
        Directory to search for input HDF5 files.

    Returns
    -------
    tuple[np.ndarray, Path]
        Array of shape (T, H, W) as float32 and the source file path.

    Raises
    ------
    FileNotFoundError
        If no .h5 file is found in data_dir.
    KeyError
        If the found HDF5 file does not contain a 'data' dataset.
    """
    data_dir = Path(data_dir)
    h5_files = sorted(data_dir.glob("*.h5"))
    if not h5_files:
        raise FileNotFoundError(f"No .h5 file found in {data_dir}")

    # Use the first file found; warn if multiple are present
    source_path = h5_files[0]
    if len(h5_files) > 1:
        print(
            f"[io_utils] WARNING: multiple .h5 files found; using {source_path.name}. "
            f"Others: {[f.name for f in h5_files[1:]]}"
        )

    print(f"[io_utils] Reading input movie from {source_path}")
    with h5py.File(source_path, "r") as f:
        if "data" not in f:
            available = list(f.keys())
            raise KeyError(
                f"Dataset 'data' not found in {source_path}. "
                f"Available keys: {available}"
            )
        movie = f["data"][()].astype(np.float32)

    print(f"[io_utils] Loaded movie shape={movie.shape} dtype=float32")
    return movie, source_path


def write_corrected_movie(corrected, output_path):
    """Write motion-corrected movie to HDF5 under dataset key 'data'.

    Parameters
    ----------
    corrected : np.ndarray
        Corrected movie array, shape (T, H, W).
    output_path : Path
        Destination .h5 file path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[io_utils] Writing corrected movie to {output_path}")
    with h5py.File(output_path, "w") as f:
        f.create_dataset("data", data=corrected, compression="gzip", compression_opts=4)
    print(f"[io_utils] Wrote corrected movie shape={corrected.shape}")


def write_transforms_csv(shifts, output_path):
    """Write per-frame shift estimates to CSV.

    Parameters
    ----------
    shifts : dict
        Must contain keys 'frame', 'x_shift', 'y_shift'. For non-rigid
        corrections, 'patch_x' and 'patch_y' are written if present.
    output_path : Path
        Destination CSV file path.
    """
    import csv

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["frame", "x_shift", "y_shift"]
    if "patch_x" in shifts:
        fieldnames += ["patch_x", "patch_y"]

    print(f"[io_utils] Writing transforms CSV to {output_path} ({len(shifts['frame'])} frames)")
    with open(output_path, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for i, frame in enumerate(shifts["frame"]):
            row = {
                "frame": frame,
                "x_shift": shifts["x_shift"][i],
                "y_shift": shifts["y_shift"][i],
            }
            if "patch_x" in shifts:
                row["patch_x"] = shifts["patch_x"][i]
                row["patch_y"] = shifts["patch_y"][i]
            writer.writerow(row)


def write_projections(movie, results_dir):
    """Compute and save max and mean projection images as PNG.

    Parameters
    ----------
    movie : np.ndarray
        Movie array shape (T, H, W).
    results_dir : Path
        Directory where PNG files will be written.
    """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    print("[io_utils] Computing projections...")
    max_proj = movie.max(axis=0)
    mean_proj = movie.mean(axis=0)

    for proj, name in [(max_proj, "max_projection.png"), (mean_proj, "mean_projection.png")]:
        out_path = results_dir / name
        fig, ax = plt.subplots(1, 1, figsize=(6, 6))
        ax.imshow(proj, cmap="gray", aspect="auto")
        ax.axis("off")
        fig.tight_layout(pad=0)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[io_utils] Saved {out_path}")


def write_processing_json(params, results_dir, start_time, end_time):
    """Write AIND-compatible processing.json metadata file.

    Parameters
    ----------
    params : dict
        Motion correction parameters that were used.
    results_dir : Path
        Directory where processing.json will be written.
    start_time : str
        ISO-format UTC start timestamp.
    end_time : str
        ISO-format UTC end timestamp.
    """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    processing = {
        "capsule_name": "aind-nonrigid-mcorr",
        "version": "1.0.0",
        "algorithm": "CaImAn/NoRMCorre non-rigid motion correction",
        "start_time": start_time,
        "end_time": end_time,
        "parameters": params,
        "outputs": [
            "motion_corrected.h5",
            "*_transforms.csv",
            "max_projection.png",
            "mean_projection.png",
        ],
    }

    out_path = results_dir / "processing.json"
    with open(out_path, "w") as f:
        json.dump(processing, f, indent=2)
    print(f"[io_utils] Wrote {out_path}")
