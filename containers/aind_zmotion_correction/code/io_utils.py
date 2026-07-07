"""
AIND capsule I/O utilities for z-motion correction.

Reads the motion-corrected movie (HDF5) and an anatomical z-stack from /data,
bridges the movie into the CaImAn memmap format that
``modules.compute_zcorr.compute_zcorrel`` consumes, and writes the z-drift
estimate, plot, and AIND-compatible processing.json to /results.
"""

import glob
import json
from pathlib import Path

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile


def read_input_movie(data_dir, prefer="motion_corrected.h5"):
    """Read the (T, H, W) movie from an HDF5 file in data_dir under key 'data'.

    Prefers ``motion_corrected.h5`` (the upstream mcorr capsule's output) if
    present, otherwise the first ``*.h5`` file.
    """
    data_dir = Path(data_dir)
    preferred = data_dir / prefer
    if preferred.exists():
        source_path = preferred
    else:
        h5_files = sorted(data_dir.glob("*.h5"))
        if not h5_files:
            raise FileNotFoundError(f"No .h5 movie found in {data_dir}")
        source_path = h5_files[0]

    print(f"[io_utils] Reading movie from {source_path}")
    with h5py.File(source_path, "r") as f:
        key = "data" if "data" in f else next(iter(f.keys()))
        if key != "data":
            print(f"[io_utils] WARNING: 'data' key absent; using '{key}'")
        movie = f[key][()].astype(np.float32)
    print(f"[io_utils] Movie shape={movie.shape} dtype=float32")
    return movie, source_path


def load_zstack(data_dir, results_dir, explicit=None):
    """Prepare an anatomical z-stack for compute_zcorrel.

    Accepts either a multipage TIFF file or a Bruker ``ZSeries`` directory of
    per-plane OME-TIFFs. A compute_zcorrel-ready TIFF is always written to
    ``<results_dir>/_zstack.tif`` (never into /data, which is read-only in a
    Code Ocean capsule).

    The stack is pre-flipped along y: compute_zcorrel applies an unconditional
    ``np.flip(axis=1)`` internally, so pre-flipping here leaves the on-disk
    stack correctly oriented relative to the movie (matches
    ``tests/benchmarks/synthetic_zstack.save_zstack_tiff``).
    """
    data_dir = Path(data_dir)
    results_dir = Path(results_dir)
    if explicit is not None:
        src = Path(explicit)
    else:
        tifs = sorted(p for p in data_dir.glob("*.tif*") if not p.name.startswith("_"))
        zdirs = sorted(data_dir.glob("ZSeries*")) + sorted(data_dir.glob("*[Zz]stack*"))
        if tifs:
            src = tifs[0]
        elif zdirs:
            src = zdirs[0]
        else:
            raise FileNotFoundError(f"No z-stack (*.tif or ZSeries* dir) found in {data_dir}")

    if src.is_dir():
        print(f"[io_utils] Assembling z-stack from Bruker dir {src}")
        files = sorted(glob.glob(f"{src}/{src.name}_Cycle00001_Ch2_*.ome.tif"))
        if not files:
            files = sorted(glob.glob(f"{src}/*Ch2_*.ome.tif"))
        if not files:
            raise FileNotFoundError(f"No Ch2 OME-TIFFs in {src}")
        planes = [tifffile.imread(f, is_ome=False) for f in files]
        volume = np.stack([p if p.ndim == 2 else p[0] for p in planes], axis=0)
    else:
        print(f"[io_utils] Reading z-stack TIFF {src}")
        volume = tifffile.imread(src)

    results_dir.mkdir(parents=True, exist_ok=True)
    zstack_tif = results_dir / "_zstack.tif"
    # Pre-flip along y to cancel compute_zcorrel's internal np.flip(axis=1).
    tifffile.imwrite(
        zstack_tif,
        np.flip(volume.astype(np.uint16), axis=1),
        photometric="minisblack",
    )
    print(f"[io_utils] Z-stack shape={volume.shape}; prepared {zstack_tif}")
    return volume, Path(zstack_tif)


def movie_to_caiman_memmap(movie, out_dir, base_name="Yr"):
    """Write a (T, H, W) movie as a CaImAn F-order memmap and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    T, H, W = movie.shape
    fname = f"{base_name}_d1_{H}_d2_{W}_d3_1_order_F_frames_{T}_.mmap"
    fpath = out_dir / fname
    mmap = np.memmap(fpath, dtype=np.float32, mode="w+", shape=(H * W, T), order="F")
    for t in range(T):
        mmap[:, t] = movie[t].ravel(order="F")
    mmap.flush()
    del mmap
    print(f"[io_utils] Wrote CaImAn memmap {fpath}")
    return fpath


def write_zcorr_outputs(z_correlation, results_dir, z_step_um=1.0):
    """Save z_correlation.npz and a z-drift plot to results_dir."""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    npz_path = results_dir / "z_correlation.npz"
    np.savez(npz_path, **z_correlation)
    print(f"[io_utils] Wrote {npz_path}")

    zpos = z_correlation["zpos"].astype(np.float32)
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.plot(zpos * z_step_um, lw=1)
    ax.set_xlabel("frame")
    ax.set_ylabel("estimated z (µm)")
    ax.set_title("Estimated z-drift")
    fig.tight_layout()
    plot_path = results_dir / "z_drift.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"[io_utils] Wrote {plot_path}")


def write_processing_json(params, results_dir, start_time, end_time, outputs):
    """Write AIND-compatible processing.json metadata."""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    processing = {
        "capsule_name": "aind-zmotion-correction",
        "version": "1.0.0",
        "algorithm": "compute_zcorrel z-drift estimation (CaImAn memmap + anatomical z-stack)",
        "start_time": start_time,
        "end_time": end_time,
        "parameters": params,
        "outputs": outputs,
    }
    out_path = results_dir / "processing.json"
    with open(out_path, "w") as f:
        json.dump(processing, f, indent=2)
    print(f"[io_utils] Wrote {out_path}")
