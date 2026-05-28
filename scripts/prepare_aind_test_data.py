"""Convert a TIFF or memmap movie to AIND-format HDF5 for capsule testing.

The AIND non-rigid mcorr capsule expects *.h5 files with a 'data' dataset
of shape (T, H, W) float32.  This script wraps an existing movie in that
format so it can be fed directly to the capsule without running the
full mesoscope-splitter stage.

Usage
-----
    python prepare_aind_test_data.py INPUT OUTPUT_DIR [--frames N]

    INPUT       Path to a TIFF stack, memmap file, or existing HDF5/H5 file.
    OUTPUT_DIR  Directory that will be mounted as /data inside the capsule.
    --frames N  Keep only the first N frames (handy for small test runs).
    --plane P   If INPUT is a multi-plane file, extract plane index P (0-based).

Examples
--------
    # Convert the first 200 frames of a TIFF stack
    python prepare_aind_test_data.py /data/subject/session/movie.tif \
        /scratch/aind_test_data/plane0 --frames 200

    # Use an existing HDF5 file (just re-wraps if key differs)
    python prepare_aind_test_data.py /data/subject/session/movie.h5 \
        /scratch/aind_test_data/plane0 --frames 500
"""

import argparse
import sys
from pathlib import Path

import h5py
import numpy as np


def load_tiff(path, n_frames=None, plane=None):
    import tifffile
    print(f"Loading TIFF: {path}")
    movie = tifffile.memmap(path) if path.suffix.lower() in (".tif", ".tiff") else tifffile.imread(path)
    if movie.ndim == 4 and plane is not None:
        # (T, Z, H, W) or (Z, T, H, W) — try both
        if movie.shape[1] > movie.shape[0]:
            movie = movie[:, plane]
        else:
            movie = movie[plane]
    if movie.ndim == 4:
        movie = movie[:, 0]  # default: first plane
    if n_frames is not None:
        movie = movie[:n_frames]
    return movie.astype(np.float32)


def load_hdf5(path, n_frames=None):
    print(f"Loading HDF5: {path}")
    with h5py.File(path, "r") as f:
        # Try common key names
        for key in ("data", "mov", "movie", "frames"):
            if key in f:
                arr = f[key][:n_frames] if n_frames else f[key][()]
                return arr.astype(np.float32)
        keys = list(f.keys())
        raise KeyError(f"No recognised dataset key in {path}. Found: {keys}")


def load_memmap(path, n_frames=None):
    print(f"Loading memmap: {path}")
    # CaImAn memmaps are Fortran-order float32 with shape encoded in filename
    # Fall back to numpy memmap with shape inference
    arr = np.load(path, mmap_mode="r")
    if arr.ndim == 2:
        # CaImAn (pixels, T) layout
        raise ValueError(
            "Memmap appears to be 2-D (pixels × T). "
            "Use caiman.mmapping.load_memmap() to reshape it first."
        )
    if n_frames:
        arr = arr[:n_frames]
    return arr.astype(np.float32)


def main():
    parser = argparse.ArgumentParser(description="Prepare AIND-format HDF5 test data for the non-rigid mcorr capsule")
    parser.add_argument("input", type=Path, help="Input movie file (.tif/.tiff/.h5/.hdf5/.npy)")
    parser.add_argument("output_dir", type=Path, help="Output directory (will be mounted as /data)")
    parser.add_argument("--frames", type=int, default=None, metavar="N", help="Keep only first N frames")
    parser.add_argument("--plane", type=int, default=None, metavar="P", help="Plane index for multi-plane files")
    parser.add_argument("--out-name", default="movie.h5", help="Output filename (default: movie.h5)")
    args = parser.parse_args()

    suffix = args.input.suffix.lower()
    if suffix in (".tif", ".tiff"):
        movie = load_tiff(args.input, args.frames, args.plane)
    elif suffix in (".h5", ".hdf5"):
        movie = load_hdf5(args.input, args.frames)
    elif suffix in (".npy", ".mmap"):
        movie = load_memmap(args.input, args.frames)
    else:
        print(f"ERROR: unsupported file type '{suffix}'. Supported: .tif/.tiff, .h5/.hdf5, .npy/.mmap", file=sys.stderr)
        sys.exit(1)

    print(f"Movie shape: {movie.shape}  dtype: {movie.dtype}")
    if movie.ndim != 3:
        print(f"ERROR: expected 3-D array (T, H, W), got shape {movie.shape}", file=sys.stderr)
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / args.out_name

    print(f"Writing AIND HDF5 to {out_path} ...")
    with h5py.File(out_path, "w") as f:
        f.create_dataset("data", data=movie, compression="gzip", compression_opts=4)
    print(f"Done. File size: {out_path.stat().st_size / 1e6:.1f} MB")
    print(f"\nMount this directory as /data when running the capsule:")
    print(f"  singularity run -B {args.output_dir}:/data,<results_dir>:/results <image.sif>")


if __name__ == "__main__":
    main()
