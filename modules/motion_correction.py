"""
Motion Correction Module for Analysis 2P Pipeline

This module handles the motion correction workflow including:
- Raw data concatenation 
- Motion correction using CaImAn/Mesmerize
- Z-motion correction (optional)
- Movie output generation
- File optimization and cleanup

Authors: Manuel Levy, Vincent Prevosto
Date: 2024-07-22
License: CC-BY-SA 4.0
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
import numpy as np
import h5py
from tifffile import TiffWriter, TiffFile, imread
import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import mode
from sklearn.linear_model import HuberRegressor

# Import CaImAn and Mesmerize components
import mesmerize_core as mc
# from caiman.mmapping import load_memmap

from modules import bruker_concat_tif as ct
from modules import compute_zcorr as cz

from pipeline.utils.pipeline_utils import (
    log_and_print,
    create_mp4_movie,
    overwrite_movie_memmap,
    load_mmap_movie,
    clip_range,
    cat_movies_to_mp4,
    memory_manager,
    load_caiman_memmap,
)

def to_uint8_robust(arr, p_lo=0.1, p_hi=99.9):
    # Compute robust range on the array (handles negatives, ignores outliers)
    vmin, vmax = np.percentile(arr, (p_lo, p_hi))
    if vmax <= vmin:
        vmax = vmin + 1.0  # fallback to avoid divide-by-zero
    arr = np.clip(arr, vmin, vmax)
    arr = (arr - vmin) * (255.0 / (vmax - vmin))
    return arr.astype(np.uint8), float(vmin), float(vmax)

def create_mcorr_movie(mcorr_movie_path, export_path, batch, index=0, format='mp4', diff_corr=True, to_uint8=True, excerpt=None):
    """
    Save the motion corrected movie (memmaped array) as a BigTIFF file or a mp4 movie.
    If diff_corr is true (default), concatenate the original movie and the motion corrected movie horizontally.
    """
    # # Load the movie from the memmap file
    # mcorr_movie_16bit , dims, T = load_memmap(mcorr_path)
    # # Reshape the array to the desired dimensions
    # mcorr_movie_16bit = np.reshape(mcorr_movie_16bit.T, [T] + list(dims), order='F')
    # # At this point the images should already be transposed
    # # mcorr_movie_16bit = mcorr_movie_16bit.transpose(0, 2, 1)
    # # image = mcorr_movie_16bit[0,:,:]  

    # Load the movie from the memmap file
    loaded_mcorr_movie = load_mmap_movie(mcorr_movie_path)

    # If excerpt is not None, keep only the first x frames of the movie
    if excerpt is not None:
        loaded_mcorr_movie = loaded_mcorr_movie[:excerpt]
        
    # Convert values to uint8
    if to_uint8:
        # Data is originally uint12, and is loaded as float 32, but is 16 bit range.
        scale_factor = 255 / (2**16-1)
        mcorr_movie_ = to_uint8_robust(loaded_mcorr_movie) #(loaded_mcorr_movie * scale_factor).astype('uint8')
    else:
        mcorr_movie_ = loaded_mcorr_movie.astype(np.uint16)
    
    if format == 'mp4':
        if diff_corr:
            # Load the data frame from the batch
            df = mc.load_batch(batch)
            # Get the original movie as a memmaped numpy array
            original_movie = df.iloc[index].caiman.get_input_movie()
            if excerpt is not None:
                original_movie = original_movie[:excerpt]

            # Convert values to uint8
            if to_uint8:
                scale_factor = 255 / (2**16-1)
                original_movie_ = to_uint8_robust(original_movie) #(original_movie * scale_factor).astype('uint8')
            else:
                original_movie_ = original_movie.astype(np.uint16)
            # Set the path of the mp4 movie
            movie_path = Path.joinpath(export_path, f"compare_og_mcorr.mp4")
            # Concatenate the two movies horizontally
            cat_movies_to_mp4(original_movie_, mcorr_movie_, movie_path)
            log_and_print(f"Saved original vs motion corrected movie to {movie_path}.")

            return movie_path
        else:
            # Save the motion corrected movie as a mp4 movie
            # movie_path = Path.joinpath(export_path, f"mcorr.mp4")
            create_mp4_movie(mcorr_movie_, export_path, 'mcorr.mp4')
            log_and_print(f"Saved motion corrected movie to {export_path}/mcorr.mp4")
            
            return Path.joinpath(export_path, 'mcorr.mp4')
    else:
        # Save the motion corrected movie as a BigTIFF file (8 bit by default)
        if to_uint8:
            mcorr_tif_path = Path.joinpath(export_path, f"mcorr_u8.tiff")
        else:
            mcorr_tif_path = Path.joinpath(export_path, f"mcorr_u16.tiff")
        with TiffWriter(mcorr_tif_path, bigtiff=True) as tif:
            tif.write(mcorr_movie_, photometric='minisblack')  
        if to_uint8:
            log_and_print(f"Saved 8 bit motion corrected movie to {mcorr_tif_path}.")
        else:
            log_and_print(f"Saved 16 bit motion corrected movie to {mcorr_tif_path}.")
            
        return mcorr_tif_path

def compute_movie_residuals(mcorr_movie_path, zcorr_movie, export_path):
    """
    Compute the residuals between the motion corrected movie (x/y), and the z-motion corrected movie (z).
    """
    # Load the motion corrected movie
    # loaded_mcorr_movie , dims, T = load_memmap(clipped_mcorr_path)
    # loaded_mcorr_movie = np.reshape(loaded_mcorr_movie.T, [T] + list(dims), order='F')
    # loaded_mcorr_movie = loaded_mcorr_movie.transpose(0, 2, 1)
    loaded_mcorr_movie = load_caiman_memmap(mcorr_movie_path)

    # Compute the difference between the motion corrected movie and the z-motion corrected movie (residuals for each frame)
    residual_movie = np.zeros_like(loaded_mcorr_movie)
    for i, frame in enumerate(loaded_mcorr_movie):
        residual_movie[i] = zcorr_movie[i] - frame
        
    # Convert all three movies' values to uint8, then concatenate them horizontally and save as a mp4 movie
    mcorr_movie_ = (loaded_mcorr_movie / (2**16-1) * 255).astype('uint8')
    zcorr_movie_ = (zcorr_movie / (2**16-1) * 255).astype('uint8')
    residual_movie_ = (residual_movie / (2**16-1) * 255).astype('uint8')
    
    # Set the path of the mp4 movie
    movie_path = Path.joinpath(export_path, f"compare_mcorr_zcorr_residuals.mp4")
    
    # Concatenate the three movies horizontally
    cat_movie = np.concatenate((mcorr_movie_, zcorr_movie_, residual_movie_), axis=2)
    create_mp4_movie(cat_movie, export_path, 'compare_mcorr_zcorr_residuals.mp4')


def run_roi_zcorr(export_path, parameters):
    """Correct ROI fluorescence traces for z-motion artifacts.

    Parameters
    ----------
    export_path : str or Path
        Directory containing extraction outputs and z-motion files.
    parameters : dict
        Dictionary with processing parameters (unused, reserved for future use).
    """

    export_path = Path(export_path)
    log_and_print("Starting ROI z-motion correction.")

    zcorr_file = export_path / "z_correlation.npz"
    f_anat_files = sorted(export_path.glob("F_anat_non_rigid*.tiff"))

    cnmf_file = export_path / "cnmf_result.hdf5"

    # Locate Suite2p outputs flexibly: root, suite2p/plane0, any suite2p/plane*, or stray plane0
    s2p_dir = None
    s2p_files = None
    candidates = []
    # Root-level outputs
    candidates.append(export_path)
    # Standard suite2p plane0
    candidates.append(export_path / "suite2p" / "plane0")
    # Any suite2p plane*
    candidates.extend(sorted((export_path / "suite2p").glob("plane*"))) if (export_path / "suite2p").exists() else None
    # Stray plane0 directly under export_path (seen in some save_mat behaviors)
    candidates.append(export_path / "plane0")

    for cdir in [c for c in candidates if c]:
        Fp = cdir / "F.npy"
        Sp = cdir / "stat.npy"
        if Fp.exists() and Sp.exists():
            s2p_dir = cdir
            s2p_files = [Fp, Sp]
            try:
                log_and_print(f"Detected Suite2p outputs in: {s2p_dir}")
            except Exception:
                pass
            break

    if not zcorr_file.exists() or not f_anat_files:
        log_and_print(
            "Required files for ROI z-motion correction missing. Skipping.",
            level="warning",
        )
        return None

    if cnmf_file.exists():
        extractor = "cnmf"
    elif s2p_dir is not None:
        extractor = "suite2p"
    else:
        log_and_print(
            "No supported extraction outputs found in export path. Skipping.",
            level="warning",
        )
        return None

    with memory_manager("roi z-motion correction"):
        zpos = np.load(zcorr_file)["zpos"]
        f_anat_movie = imread(str(f_anat_files[0]))
        # tifffile returns (T, Y, X); transpose to (Y, X, T)
        if f_anat_movie.shape[0] == zpos.shape[0]:
            f_anat_movie = np.transpose(f_anat_movie, (1, 2, 0))

        if extractor == "cnmf":
            from caiman.source_extraction.cnmf.cnmf import CNMF

            cnm = CNMF()
            cnm.load(str(cnmf_file))
            F = cnm.estimates.F
            A = cnm.estimates.A.tocsc()
            d1 = cnm.estimates.d1
            d2 = cnm.estimates.d2
            n_neuron, n_frame = F.shape

            Fz = np.zeros((n_neuron, n_frame))
            Fz_rescaled = np.zeros_like(F)
            Fcorrected = np.zeros_like(F)
            b = np.zeros(n_neuron)

            for i in range(n_neuron):
                ind = A[:, i].nonzero()[0]
                y, x = np.unravel_index(ind, (d1, d2))
                weights = np.full(len(x), 1 / len(x))
                for w, yy, xx in zip(weights, y, x):
                    Fz[i] += w * f_anat_movie[yy, xx, :]
                F0 = F[i].mean()
                Fz0 = Fz[i].mean()
                huber = HuberRegressor(fit_intercept=False)
                huber.fit((Fz[i] - Fz0).reshape(-1, 1), F[i] - F0)
                b[i] = huber.coef_[0]
                Fz_rescaled[i] = b[i] * (Fz[i] - Fz0)
                Fcorrected[i] = F[i] - Fz_rescaled[i]

        else:  # Suite2p
            F = np.load(str(s2p_files[0]))
            stat = np.load(str(s2p_files[1]), allow_pickle=True)
            n_neuron, n_frame = F.shape
            Fz = np.zeros((n_neuron, n_frame))
            Fz_rescaled = np.zeros_like(F)
            Fcorrected = np.zeros_like(F)
            b = np.zeros(n_neuron)

            for i, cell in enumerate(stat):
                ypix = cell["ypix"].astype(int)
                xpix = cell["xpix"].astype(int)
                lam = cell["lam"].astype(float)
                weights = lam / lam.sum() if lam.sum() != 0 else np.full(len(lam), 1 / len(lam))
                for w, yy, xx in zip(weights, ypix, xpix):
                    Fz[i] += w * f_anat_movie[yy, xx, :]
                F0 = F[i].mean()
                Fz0 = Fz[i].mean()
                huber = HuberRegressor(fit_intercept=False)
                huber.fit((Fz[i] - Fz0).reshape(-1, 1), F[i] - F0)
                b[i] = huber.coef_[0]
                Fz_rescaled[i] = b[i] * (Fz[i] - Fz0)
                Fcorrected[i] = F[i] - Fz_rescaled[i]

        z_mode = mode(zpos, keepdims=False).mode
        if np.ndim(z_mode) > 0:
            z_mode = z_mode[0]
        missing = np.abs(zpos - z_mode) > 5
        if np.any(missing):
            Fcorrected[:, missing] = np.nan
            Fcorrected = (
                pd.DataFrame(Fcorrected)
                .interpolate(method="linear", axis=1, limit_direction="both")
                .to_numpy()
            )

        # Save results
        np.savez_compressed(export_path / "F_roi_zcorrected.npz",
                            F_roi_zcorrected=Fcorrected,
                            F_roi_zbaseline=Fz_rescaled,
                            roi_z_scaling=b)

        try:
            import matplotlib.pyplot as plt

            plots_dir = export_path / "plots"
            plots_dir.mkdir(parents=True, exist_ok=True)

            plt.figure()
            plt.plot(zpos)
            plt.xlabel("Frame")
            plt.ylabel("Z position (µm)")
            plt.tight_layout()
            plt.savefig(plots_dir / "roi_z_drift.png")
            plt.close()

            plt.figure()
            plt.hist(b, bins=30)
            plt.xlabel("Scaling factor")
            plt.ylabel("Count")
            plt.tight_layout()
            plt.savefig(plots_dir / "roi_z_scaling_hist.png")
            plt.close()
        except Exception as e:
            log_and_print(f"Could not save diagnostic plots: {e}", level="warning")

    log_and_print("ROI z-motion correction completed.")
    return export_path
   
def save_movie_as_h5(memmap_path, h5_path, parameters, dtype_out='uint16', scale=None, chunk_size=256):
    """
    Streamed save of motion-corrected movie as HDF5 (AIND / Suite2p extraction-ready).

    Avoids loading full movie in RAM by iterating through CaImAn memmap frames.
    """
    log_and_print(f"Saving final movie to {h5_path} (dtype_out={dtype_out})")
    adapter = load_caiman_memmap(memmap_path)
    T, Ly, Lx = adapter.shape
    log_and_print(f"Memmap adapter: frames={T}, Ly={Ly}, Lx={Lx}, dtype={adapter.dtype}")

    # Metadata extraction
    try:
        imaging = parameters.get('imaging', {}) if parameters else {}
    except Exception:
        imaging = {}
    frame_rate = imaging.get('fr') or imaging.get('fs') or 30.0
    pixel_size_um = imaging.get('microns_per_pixel', 1.0)

    if dtype_out not in ('uint16','float32'):
        raise ValueError("dtype_out must be 'uint16' or 'float32'")

    running_min = np.inf
    running_max = -np.inf

    # Create a figure of pixel values histograms
    # fig, axs = plt.subplots(1, 2, figsize=(12, 6))
    # axs[0].hist(adapter.flatten(), bins=100, color='gray')
    # axs[0].set_title('Histogram of Pixel Values (Memmap)')
    # axs[0].set_xlabel('Pixel Value')
    # axs[0].set_ylabel('Frequency')

    with h5py.File(h5_path, 'w') as f:
        if dtype_out == 'uint16':
            dset = f.create_dataset('data', shape=(T, Ly, Lx), dtype='uint16', compression=None)
        else:
            dset = f.create_dataset('data', shape=(T, Ly, Lx), dtype='float32', compression=None)
        dset.attrs['fs'] = frame_rate
        dset.attrs['n_frames'] = int(T)
        dset.attrs['Ly'] = int(Ly)
        dset.attrs['Lx'] = int(Lx)
        dset.attrs['pixel_size_um'] = float(pixel_size_um)

        for start in range(0, T, chunk_size):
            stop = min(T, start + chunk_size)
            block = adapter[start:stop].astype(np.float32, copy=False)  # (chunk, Ly, Lx)
            if scale is not None:
                block *= scale
            # Update stats before conversion
            blk_min = float(block.min())
            blk_max = float(block.max())
            if blk_min < running_min: running_min = blk_min
            if blk_max > running_max: running_max = blk_max

            if dtype_out == 'uint16':
                if block.min() < 0:
                    # shift to positive per-chunk if needed
                    block = block - block.min()
                block = clip_range(block, 'uint16').astype(np.uint16, copy=False)
            else:  # float32
                block = block.astype(np.float32, copy=False)

            dset[start:stop] = np.ascontiguousarray(block)
            if (start // chunk_size) % 20 == 0 or stop == T:
                log_and_print(f"  Wrote frames {start}:{stop} (min={blk_min:.1f}, max={blk_max:.1f})")

    log_and_print(f"H5 written: {h5_path} (range min={running_min:.2f}, max={running_max:.2f})")

    # Quick verification (first frame only)
    try:
        with h5py.File(h5_path, 'r') as f:
            test = f['data'][0]
        if test.shape != (Ly, Lx):
            log_and_print("WARNING: First frame shape mismatch on H5 read-back", level='warning')
        else:
            log_and_print("H5 read-back first frame OK")
    except Exception as e:
        log_and_print(f"H5 verification failed: {e}", level='warning')

    # choose bin edges using running_min/running_max computed above
    # nbins = 100
    # bin_edges = np.linspace(running_min, running_max, nbins + 1)
    # hist_counts = np.zeros(nbins, dtype=np.int64)

    # # Compute histogram of pixel values on h5 file
    # with h5py.File(h5_path, 'r') as f:
    #     data = f['data'][:]
    #     hist_counts, _ = np.histogram(data, bins=bin_edges)

    # axs[1].bar(bin_edges[:-1], hist_counts, width=np.diff(bin_edges), color='gray')
    # axs[1].set_title('Histogram of Pixel Values (H5)')
    # axs[1].set_xlabel('Pixel Value')
    # axs[1].set_ylabel('Frequency')
    # plt.tight_layout()

    # # Save figure
    # histo_fig_path = h5_path.parent / "plots" / "pixel_value_histogram_h5.png"
    # plt.savefig(histo_fig_path)
    # plt.close(fig)

    adapter.close()
    return Path(h5_path)

def save_movie_as_bin(memmap_path, bin_path, parameters=None, chunk_size=512, scale=None):
    """
    Stream-save motion-corrected movie as Suite2p-compatible .bin file (int16 C-order).
    """
    log_and_print(f"Saving final movie to {bin_path} (chunk_size={chunk_size})")
    adapter = load_caiman_memmap(memmap_path)
    T, Ly, Lx = adapter.shape
    log_and_print(f"Memmap adapter: frames={T}, Ly={Ly}, Lx={Lx}, dtype={adapter.dtype}")

    running_min = np.inf
    running_max = -np.inf

    # Create a figure of pixel values histograms
    # fig, axs = plt.subplots(1, 2, figsize=(12, 6))
    # axs[0].hist(adapter.flatten(), bins=100, color='gray')
    # axs[0].set_title('Histogram of Pixel Values (Memmap)')
    # axs[0].set_xlabel('Pixel Value')
    # axs[0].set_ylabel('Frequency')

    with open(bin_path, 'wb') as f:
        for start in range(0, T, chunk_size):
            stop = min(T, start + chunk_size)
            block = adapter[start:stop].astype(np.float32, copy=False)
            if scale is not None:
                block *= scale
            blk_min = float(block.min()); blk_max = float(block.max())
            if blk_min < running_min: running_min = blk_min
            if blk_max > running_max: running_max = blk_max
            block = clip_range(block, 'int16').astype(np.int16, copy=False)
            f.write(np.ascontiguousarray(block).tobytes())
            if (start // chunk_size) % 20 == 0 or stop == T:
                log_and_print(f"  Wrote frames {start}:{stop} (min={blk_min:.1f}, max={blk_max:.1f})")

    # Verify size
    expected_size = T * Ly * Lx * 2
    actual_size = Path(bin_path).stat().st_size
    log_and_print(f"Binary written: {bin_path} bytes={actual_size} expected={expected_size}")
    if actual_size != expected_size:
        log_and_print("WARNING: Size mismatch in .bin export", level='warning')

    # Quick read-back of first frame
    try:
        first = np.fromfile(bin_path, dtype=np.int16, count=Ly*Lx).reshape(Ly, Lx)
        log_and_print(f"First frame read-back: min={first.min()} max={first.max()}")
    except Exception as e:
        log_and_print(f"Read-back failed: {e}", level='warning')

    # # Compute histogram of pixel values
    # hist, bin_edges = np.histogram(np.fromfile(bin_path, dtype=np.int16), bins=100)
    # axs[1].bar(bin_edges[:-1], hist, width=np.diff(bin_edges), color='gray')
    # axs[1].set_title('Histogram of Pixel Values (Bin)')
    # axs[1].set_xlabel('Pixel Value')
    # axs[1].set_ylabel('Frequency')
    # plt.tight_layout()

    # # Save figure
    # histo_fig_path = bin_path.parent / "plots" / "pixel_value_histogram_bin.png"
    # plt.savefig(histo_fig_path)
    # plt.close(fig)

    log_and_print(f"Range across stream: min={running_min:.2f}, max={running_max:.2f}")
    adapter.close()
    log_and_print(f"✓ Successfully saved .bin movie to {bin_path}")
    return Path(bin_path)

def save_movie_as_tiff(memmap_path, tiff_path, parameters=None, chunk_size=256, dtype_out='uint16', scale=None):
    """Stream-save motion-corrected movie as BigTIFF (multi-page).

    Frames are written sequentially to avoid loading the full movie. By default, scales/clips to uint16.
    """
    log_and_print(f"Saving final movie to {tiff_path} (dtype_out={dtype_out})")
    adapter = load_caiman_memmap(memmap_path)
    T, Ly, Lx = adapter.shape
    log_and_print(f"Memmap adapter: frames={T}, Ly={Ly}, Lx={Lx}, dtype={adapter.dtype}")

    running_min = np.inf
    running_max = -np.inf

    # # Create a figure of pixel values histograms
    # fig, axs = plt.subplots(1, 2, figsize=(12, 6))
    # axs[0].hist(adapter.flatten(), bins=100, color='gray')
    # axs[0].set_title('Histogram of Pixel Values (Memmap)')
    # axs[0].set_xlabel('Pixel Value')
    # axs[0].set_ylabel('Frequency')

    # choose converter
    def to_dtype(frames: np.ndarray) -> np.ndarray:
        arr = frames
        if scale is not None:
            arr = arr.astype(np.float32) * float(scale)
        if dtype_out == 'uint16':
            arr = clip_range(arr, 'uint16').astype(np.uint16)
        elif dtype_out == 'float32':
            arr = arr.astype(np.float32)
        else:
            raise ValueError("dtype_out must be 'uint16' or 'float32'")
        return arr

    with TiffWriter(str(tiff_path), bigtiff=True) as tif:
        for start in range(0, T, chunk_size):
            stop = min(T, start + chunk_size)
            chunk = adapter[start:stop]  # (chunk, Ly, Lx)
            running_min = min(running_min, float(np.min(chunk)))
            running_max = max(running_max, float(np.max(chunk)))
            out = to_dtype(chunk)
            for k in range(out.shape[0]):
                tif.write(out[k], contiguous=True, photometric='minisblack')

    log_and_print(f"TIFF written: {tiff_path} (range min={running_min:.2f}, max={running_max:.2f})")
    adapter.close()

    # # choose bin edges using running_min/running_max computed above
    # nbins = 100
    # bin_edges = np.linspace(running_min, running_max, nbins + 1)
    # hist_counts = np.zeros(nbins, dtype=np.int64)

    # with TiffFile(str(tiff_path)) as tif:
    #     for page in tif.pages:
    #         arr = page.asarray()
    #         c, _ = np.histogram(arr, bins=bin_edges)
    #         hist_counts += c

    # # plot as bar (centers and widths)
    # centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    # axs[1].bar(centers, hist_counts, width=np.diff(bin_edges), color='gray')
    # axs[1].set_title('Histogram of Pixel Values (TIFF)')
    # axs[1].set_xlabel('Pixel Value')
    # axs[1].set_ylabel('Frequency')
    # plt.tight_layout()

    # # Save figure
    # histo_fig_path = tiff_path.parent / "plots" / "pixel_value_histogram_tiff.png"
    # fig.savefig(histo_fig_path, dpi=300)
    # plt.close(fig)

    return Path(tiff_path)

def run_mcorr(data_path, export_path, parameters, regex_pattern, recompute=True, scale_range=False):
    """
    Run motion correction on a set of ome.tif files.
    Concatenate the ome.tif files into a single multi-page tiff file.
    Create a new batch.
    Add the motion correction item to the batch.
    Run the batch.

    Arguments:
    - data_path: Path to the folder containing the input ome.tif files.
    - export_path: Path to the folder where the output files will be saved.
    - parameters: Dictionary containing the parameters for motion correction.
    - regex_pattern: Regular expression pattern to match the input files.
    - recompute: Boolean indicating whether to recompute the motion correction.
    - scale_range: Boolean indicating whether to scale the output to uint16 range.

    Returns:
    - batch_path: Path to the created batch file.
    - index: Index of the movie in the batch.
    - movie_path: Path to the concatenated movie file.

    """
    # Set movie path
    movie_path = Path(export_path).joinpath('cat_tiff_bt.tiff')
    
    # Set the parent raw data path before any batch operations
    mc.set_parent_raw_data_path(Path(export_path))

    if not recompute and movie_path.exists():
        log_and_print(f"Concatenated movie already exists at {export_path}. Using existing file.")
    else:
        # Concatenate the ome.tif files into a single multi-page tiff file
        # Using the concat_tif.py script to concatenate the tif files. If needed, install libtiff with: pip install pylibtiff
        log_and_print(f"Loading and concatenating data from {data_path}.")
        try:
            # time0 = time.time()
            ##################
            ct.concatenate_files(
                input_paths=data_path, 
                output_path=export_path, 
                regex=regex_pattern,
                scale_range=scale_range
            )
            ##################
            # formatted_time = time.strftime("%H:%M:%S", time.gmtime(time.time() - time0))
            # print(f"Concatenation completed in {formatted_time}.")

            # Check the tiff file dtype and value range
            with TiffFile(movie_path) as tif:
                dtype = tif.pages[0].asarray().dtype
                min_val = tif.pages[0].asarray().min()
                max_val = tif.pages[0].asarray().max()
                mean_val = tif.pages[0].asarray().mean()
                print(f"Concatenated TIFF file \n\
                    dtype: {dtype}, \n\
                    min: {min_val}, \n\
                    max: {max_val}, \n\
                    mean: {mean_val}")
                
            # Verify that the concatenated movie is long enough for subsequent
            # correlation computations. If the movie is too short, CaImAn's
            # ``local_correlations_movie_parallel`` will fail silently.
            with TiffFile(movie_path) as tif:
                n_frames = len(tif.pages)
            if n_frames < 1000:
                raise ValueError(
                    f"Concatenated movie has {n_frames} frames which is below the safe "
                    "threshold (1000). Increase the '--max-frames' parameter when "
                    "creating test datasets or rerun with more data."
                )

        except Exception as e:
            log_and_print(f"An error occurred while concatenating files: {e}")

    # log_and_print(f"Concatenated movie path: {movie_path}.\n")    

    if not recompute:
        #  Check if a batch_*_pickle file exists in the export path
        batch_files = list(Path(export_path).glob(f"batch_*.pickle"))
        if len(batch_files) > 0:
            #  take the most recent batch file
            batch_path = batch_files[-1]
            log_and_print(f"Using existing batch file {batch_path}.")
            # load the batch
            df = mc.load_batch(batch_path)
            
            # rows_keep = [df.iloc[0].uuid]
            # for i, row in df.iterrows():
            #     if row.uuid not in rows_keep:
            #         df.caiman.remove_item(row.uuid)
        
    # if batch_path is not defined, create a new batch
    if 'batch_path' not in locals():
        # create a new batch path, appendind timestamp to avoid overwriting
        batch_path = Path.joinpath(export_path, f'batch_{time.strftime("%Y%m%d-%H%M%S")}.pickle')
        log_and_print(f"Creating batch {batch_path}.") 
        df = mc.create_batch(batch_path)

        # Add the input movie path to the batch
        df.caiman.add_item(
            algo='mcorr',
            item_name=movie_path.stem,
            input_movie_path=movie_path,
            params=parameters
        )
        
    time0 = time.time()
    mcorr_index = None
    # Run batch items that haven't been run yet
    for row_index, row in df.iterrows():
        
        # If algo is not mcorr, skip (this is a safety check, in case df was reloaded from disk)
        if row.algo != 'mcorr':
            continue
        
        # If already processed, skip
        if row["outputs"] is not None:
            log_and_print(f"Skipping batch item {row_index}, id {row.uuid}, algo {row.algo}. Already run.", level='warning')
            mcorr_index = row_index
            continue
        
        log_and_print(f"Running batch item {row_index}, id {row.uuid}, algo {row.algo}.")
        try:
            ##########################
            process = row.caiman.run()
            mcorr_index = row_index
            ##########################
        except Exception as e:
            log_and_print(f"An error occurred while running caiman for batch item {row_index}: {e}")
        
        # on Windows you MUST reload the batch dataframe after every iteration because it uses the `local` backend.
        # this is unnecessary on Linux & Mac
        # "DummyProcess" is used for local backend so this is automatic
        if process.__class__.__name__ == "DummyProcess":
            df = df.caiman.reload_from_disk()
            
    log_and_print(f"Batch completed for motion correction. Results saved to {batch_path}.")
    formatted_time = time.strftime("%H:%M:%S", time.gmtime(time.time() - time0))
    print(f"mcorr completed in {formatted_time}.")
    
    if mcorr_index is not None:
        df = df.caiman.reload_from_disk()
        # Get the path to the motion corrected movie
        movie_path = Path(df.iloc[mcorr_index].mcorr.get_output_path())
        # Get the motion corrected output as a memmaped numpy array
        # mcorr_movie = df.iloc[mcorr_index].mcorr.get_output()

        # Load motion corrected movie and check dtype, and mean pixel values
        mcorr_movie = load_mmap_movie(movie_path)
        if mcorr_movie is not None:
            shape = mcorr_movie.shape
            dtype = mcorr_movie.dtype
            first_frame = mcorr_movie[0]
            log_and_print(f"Motion corrected movie \n\
                        shape: {shape}, \n\
                        dtype: {dtype}, \n\
                        first frame min: {first_frame.min()}, \n\
                        first frame max: {first_frame.max()}, \n\
                        first frame mean: {first_frame.mean()}")
        else:
            log_and_print("Motion corrected movie could not be loaded.", level='error')


    return batch_path, 0, movie_path
  
def run_motion_correction_workflow(
    data_path,
    export_path,
    parameters,
    regex_pattern='*_Ch2_*.ome.tif',
    recompute=True,
    create_movies=True,
    output_format='memmap',
):
    """
    Complete motion correction workflow including z-motion correction.
    
    Args:
        data_path: List of paths containing input data
        export_path: Output directory path  
        parameters: Dictionary containing processing parameters
        regex_pattern: Pattern to match input files
        recompute: Whether to recompute existing results
        create_movies: Whether to create output movies
        output_format: 'memmap' (default), 'h5', 'tiff', or 'bin' for final motion-corrected movie storage

    Returns:
        dict: Results dictionary with paths and metadata
    """
    
    results = {
        'batch_path': None,
        'movie_path': None,
        'export_path': export_path,
        'success': False
    }
    
    try:
        # Get motion correction parameters
        parameters_mcorr = parameters['params_mcorr']

        # Run the motion correction
        scale_range_raw = parameters_mcorr.get('scale_range', False)
        # Handle string representations of booleans
        if isinstance(scale_range_raw, str):
            scale_range = scale_range_raw.lower() in ('true', '1', 'yes')
        else:
            scale_range = bool(scale_range_raw)

        batch_path, index, movie_path = run_mcorr(
            data_path, export_path, parameters_mcorr, regex_pattern, recompute, scale_range=scale_range
        )

        results['batch_path'] = batch_path
        results['movie_path'] = movie_path

        # Determine whether to clip to uint16 range
        clip_movie = output_format not in ('h5', 'bin', 'tiff')

        if not recompute and movie_path.exists():
            log_and_print(f"Motion corrected movie already exists at {movie_path}.")
        else:
            if clip_movie:
                log_and_print("Optimizing motion corrected movie bit depth (clipping memmap to uint16).")
                overwrite_movie_memmap(movie_path, movie_path, clip=True, movie_type='mcorr')
            else:
                log_and_print("Skipping memmap overwrite to preserve full dynamic range for downstream export.")
        
        # Z-motion correction (optional)
        if 'zstack_path' in parameters and 'z_motion_correction' in parameters.get('params_mcorr', {}):
            log_and_print("Starting z-motion correction...")
            time_z0 = time.time()
            
            zcorr_movie_path, _, _ = cz.z_motion(
                movie_path, parameters, scale_range=scale_range
            )
            
            # Save corrected movie, overwriting the original
            if zcorr_movie_path is not None:
                overwrite_movie_memmap(
                    zcorr_movie_path,
                    movie_path,
                    clip=clip_movie,
                    movie_type='zcorr',
                    save_original=False,
                    remove_input=True
                )
                results['z_corrected'] = True
            else:
                results['z_corrected'] = False
            
            formatted_time = time.strftime("%H:%M:%S", time.gmtime(time.time() - time_z0))
            if zcorr_movie_path is not None:
                log_and_print(f"Z-motion correction completed in {formatted_time}.")
            else:
                log_and_print(f"Z-motion computation completed in {formatted_time}.")
        
        # Create output movies (optional)
        if create_movies:
            log_and_print("Creating output movies...")
                            
            # Save as BigTIFF file  
            create_mcorr_movie(movie_path, export_path, None, None, 
                                        format='tiff', diff_corr=False)
            
            # Create comparison movie (first 240 frames)
            create_mcorr_movie(mcorr_movie_path=movie_path, export_path=export_path, 
                                        batch=batch_path, index=index, excerpt=240)
        
        results['success'] = True

        if output_format == 'h5':
            print("Saving motion corrected movie as .h5 file...")
            h5_path = export_path / 'mcorr_movie.h5'
            # Save movie as Suite2p, AIND and ImageJ-compatible .h5
            results['movie_path'] = save_movie_as_h5(
                memmap_path=movie_path,
                h5_path=h5_path,
                parameters=parameters
            )
        elif output_format == 'bin':
            log_and_print("Saving motion corrected movie as .bin file...")
            bin_path = export_path / 'mcorr_movie.bin'
            # Save movie as Suite2p-compatible .bin
            results['movie_path'] = save_movie_as_bin(
                memmap_path=movie_path,
                bin_path=bin_path,
                parameters=parameters
            )
        elif output_format == 'tiff':
            log_and_print("Saving motion corrected movie as BigTIFF file...")
            tiff_path = export_path / 'mcorr_movie.tiff'
            results['movie_path'] = save_movie_as_tiff(
                memmap_path=movie_path,
                tiff_path=tiff_path,
                parameters=parameters
            )

        log_and_print("Motion correction workflow completed successfully.")
        
    except Exception as e:
        log_and_print(f"Motion correction workflow failed: {e}", level='error')
        results['error'] = str(e)
        raise
    
    return results

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Motion Correction Module")
    parser.add_argument('input_paths', nargs='+', help='Input data paths')
    parser.add_argument('-o', '--output', required=True, help='Output directory')
    parser.add_argument('-p', '--params', type=str, help='Path to parameters JSON file')
    parser.add_argument('-t', '--pattern', default='*_Ch2_*.ome.tif', help='File pattern')
    parser.add_argument('-r', '--recompute', action='store_true', help='Recompute existing results')
    parser.add_argument('-c', '--create_movies', action='store_true', help='Create output movies')
    parser.add_argument('-f', '--format', choices=['memmap', 'h5', 'bin', 'tiff'], default='memmap', help='Output format for final movie')
    args = parser.parse_args()
    
    # Convert input paths to Path objects
    input_paths = [Path(p) for p in args.input_paths]
    output_path = Path(args.output)
    pattern = args.pattern
    recompute = args.recompute
    create_movies = args.create_movies
    save_mcorr_movie = args.format
    
    # Load parameters from JSON file if provided
    parameters = {}
    if args.params:
        import json
        with open(args.params, 'r') as f:
            parameters = json.load(f)
    else:
        raise ValueError("Parameters file must be provided with -p option.")

    # Run the motion correction workflow
    results = run_motion_correction_workflow(
        data_path=input_paths,
        export_path=output_path,
        parameters=parameters,
        regex_pattern=pattern,
        recompute=recompute,
        create_movies=create_movies,
        save_mcorr_movie=save_mcorr_movie
    )