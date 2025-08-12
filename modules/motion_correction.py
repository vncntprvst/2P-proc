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
from pathlib import Path
import numpy as np
import h5py
from tifffile import TiffWriter, TiffFile
import tifffile
import pandas as pd
from scipy.stats import mode
from sklearn.linear_model import HuberRegressor

# Import CaImAn and Mesmerize components
import mesmerize_core as mc
from caiman.mmapping import load_memmap

from modules import bruker_concat_tif as ct
from modules import compute_zcorr as cz

from Mesmerize.utils.pipeline_utils import (
    log_and_print, 
    create_mp4_movie,
    overwrite_movie_memmap, 
    load_mmap_movie, 
    clip_range, 
    cat_movies_to_mp4,
    memory_manager
)


def create_mcorr_movie(mcorr_path, export_path, batch, index=0, format='mp4', diff_corr=True, to_uint8=True, excerpt=None):
    """
    Save the motion corrected movie (memmaped array) as a BigTIFF file or a mp4 movie.
    If diff_corr is true (default), concatenate the original movie and the motion corrected movie horizontally.
    """
    # Load the movie from the memmap file
    mcorr_movie_16bit , dims, T = load_memmap(mcorr_path)
    # Reshape the array to the desired dimensions
    mcorr_movie_16bit = np.reshape(mcorr_movie_16bit.T, [T] + list(dims), order='F')
    # At this point the images should already be transposed
    # mcorr_movie_16bit = mcorr_movie_16bit.transpose(0, 2, 1)
    # image = mcorr_movie_16bit[0,:,:]  
    
    # If excerpt is not None, keep only the first x frames of the movie
    if excerpt is not None:
        mcorr_movie_16bit = mcorr_movie_16bit[:excerpt]
        
    # Convert values to uint8
    if to_uint8:
        mcorr_movie_ = (mcorr_movie_16bit / (2**16-1) * 255).astype('uint8')
    else:
        mcorr_movie_ = mcorr_movie_16bit
    
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
                original_movie_ = (original_movie / (2**16-1) * 255).astype('uint8')
            else:
                original_movie_ = original_movie
            # Set the path of the mp4 movie
            movie_path = Path.joinpath(export_path, f"compare_og_mcorr.mp4")
            # Concatenate the two movies horizontally
            cat_movies_to_mp4(original_movie_, mcorr_movie_, movie_path)
            log_and_print(f"Saved original vs motion corrected movie to {movie_path}.")

            return movie_path
        else:
            # Save the motion corrected movie as a mp4 movie
            # movie_path = Path.joinpath(export_path, f"mcorr.mp4")
            create_mp4_movie(mcorr_movie_16bit, export_path, 'mcorr.mp4')
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

def compute_movie_residuals(clipped_mcorr_path, zcorr_movie, export_path):
    """
    Compute the residuals between the motion corrected movie (x/y), and the z-motion corrected movie (z).
    """
    # Load the motion corrected movie
    mcorr_movie_16bit , dims, T = load_memmap(clipped_mcorr_path)
    mcorr_movie_16bit = np.reshape(mcorr_movie_16bit.T, [T] + list(dims), order='F')
    mcorr_movie_16bit = mcorr_movie_16bit.transpose(0, 2, 1)
    
    # Compute the difference between the motion corrected movie and the z-motion corrected movie (residuals for each frame)
    residual_movie = np.zeros_like(mcorr_movie_16bit)
    for i, frame in enumerate(mcorr_movie_16bit):
        residual_movie[i] = zcorr_movie[i] - frame
        
    # Convert all three movies' values to uint8, then concatenate them horizontally and save as a mp4 movie
    mcorr_movie_ = (mcorr_movie_16bit / (2**16-1) * 255).astype('uint8')
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
    s2p_files = [export_path / "F.npy", export_path / "stat.npy"]

    if not zcorr_file.exists() or not f_anat_files:
        log_and_print(
            "Required files for ROI z-motion correction missing. Skipping.",
            level="warning",
        )
        return None

    if cnmf_file.exists():
        extractor = "cnmf"
    elif all(f.exists() for f in s2p_files):
        extractor = "suite2p"
    else:
        log_and_print(
            "No supported extraction outputs found in export path. Skipping.",
            level="warning",
        )
        return None

    with memory_manager("roi z-motion correction"):
        zpos = np.load(zcorr_file)["zpos"]
        f_anat_movie = tifffile.imread(str(f_anat_files[0]))
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
            F = np.load(s2p_files[0])
            stat = np.load(s2p_files[1], allow_pickle=True)
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

        np.save(export_path / "F_roi_zcorrected.npy", Fcorrected)
        np.save(export_path / "F_roi_zbaseline.npy", Fz_rescaled)
        np.save(export_path / "roi_z_scaling.npy", b)

        try:
            import matplotlib.pyplot as plt

            plt.figure()
            plt.plot(zpos)
            plt.xlabel("Frame")
            plt.ylabel("Z position (µm)")
            plt.tight_layout()
            plt.savefig(export_path / "roi_z_drift.png")
            plt.close()

            plt.figure()
            plt.hist(b, bins=30)
            plt.xlabel("Scaling factor")
            plt.ylabel("Count")
            plt.tight_layout()
            plt.savefig(export_path / "roi_z_scaling_hist.png")
            plt.close()
        except Exception as e:
            log_and_print(f"Could not save diagnostic plots: {e}", level="warning")

    log_and_print("ROI z-motion correction completed.")
    return export_path
   
def save_movie_as_h5(memmap_path, h5_path, parameters):
    """
    Save motion-corrected movie as HDF5 with proper metadata for Suite2p and ImageJ.

    Args:
        memmap_path: Path to the memmap movie file
        h5_path: Output path for HDF5 file
        parameters: Parameter dictionary containing extraction settings

    Returns:
        Path: Path to saved HDF5 file
    """
    log_and_print(f"Saving final movie to {h5_path}")

    # Load the memmap movie as (frames, Ly, Lx)
    memmap_array = load_mmap_movie(memmap_path)

    # Convert to int16 for Suite2p compatibility
    memmap_array = clip_range(memmap_array, 'int16').astype(np.int16)

    # Log initial data state
    log_and_print(f"Loaded memmap array: shape={memmap_array.shape}, dtype={memmap_array.dtype}")
    log_and_print(f"Data range: min={memmap_array.min():.3f}, max={memmap_array.max():.3f}, mean={memmap_array.mean():.3f}")

    # Optional: Check shape
    if memmap_array.ndim != 3:
        raise ValueError(f"Expected shape (frames, Ly, Lx), got {memmap_array.shape}")

    # Extract parameters
    try:
        imaging = parameters.get('imaging', {})
        frame_rate = imaging.get('fr') or imaging.get('fs')
        if frame_rate is None:
            frame_rate = 30.0
            print("Warning: Using default frame rate of 30.0 Hz as 'fr' or 'fs' not found in parameters.")
        pixel_size_um = imaging.get('microns_per_pixel')
        if pixel_size_um is None:
            pixel_size_um = 1.0
            print("Warning: Using default pixel size of 1.0 μm as 'microns_per_pixel' not found in parameters.")

    except Exception as e:
        log_and_print(f"Missing key in parameters: {e}", level="error")
        return None

    # Get image dimensions
    T, Ly, Lx = memmap_array.shape

    # Ensure C-contiguous memory layout (same as .bin export)
    if not memmap_array.flags['C_CONTIGUOUS']:
        log_and_print("Converting to C-contiguous array...")
        memmap_array = np.ascontiguousarray(memmap_array)

    # Create debugging plots
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    
    # Plot original first frame
    axes[0,0].imshow(memmap_array[0], cmap='gray')
    axes[0,0].set_title(f'H5 Export: First Frame (min={memmap_array[0].min()}, max={memmap_array[0].max()})')
    axes[0,0].axis('off')
    
    # Plot after C-ordering
    axes[0,1].imshow(memmap_array[0], cmap='gray')
    axes[0,1].set_title(f'After C-ordering (C_CONTIGUOUS={memmap_array.flags["C_CONTIGUOUS"]})')
    axes[0,1].axis('off')

    with h5py.File(h5_path, 'w') as f:
        # Create dataset compatible with Suite2p - simple, no compression, int16
        dset = f.create_dataset(
            'data',
            data=memmap_array,
            dtype='int16'
        )

        # Minimal metadata - don't overdo it like the original version
        dset.attrs['fs'] = frame_rate
        dset.attrs['n_frames'] = T
        dset.attrs['Ly'] = Ly
        dset.attrs['Lx'] = Lx

        log_and_print(f"HDF5 metadata:")
        log_and_print(f"  - Frame rate: {frame_rate} Hz")
        log_and_print(f"  - Pixel size: {pixel_size_um} μm")
        log_and_print(f"  - Dimensions: {T} frames × {Ly} × {Lx} pixels")
        log_and_print(f"  - Physical size: {Ly * pixel_size_um:.1f} × {Lx * pixel_size_um:.1f} μm")

    # Immediate read-back test
    log_and_print("Performing HDF5 read-back verification...")
    try:
        with h5py.File(h5_path, 'r') as f:
            test_array = f['data'][:]
        log_and_print(f"Read-back success: shape={test_array.shape}, dtype={test_array.dtype}")
        log_and_print(f"Read-back data: min={test_array.min()}, max={test_array.max()}, mean={test_array.mean():.3f}")
        
        # Plot read-back comparison
        axes[1,0].imshow(test_array[0], cmap='gray')
        axes[1,0].set_title(f'H5 Read-back Test (min={test_array[0].min()}, max={test_array[0].max()})')
        axes[1,0].axis('off')
        
        # Plot difference (should be all zeros)
        diff = memmap_array[0].astype(np.int32) - test_array[0].astype(np.int32)
        axes[1,1].imshow(diff, cmap='RdBu', vmin=-10, vmax=10)
        axes[1,1].set_title(f'Difference (max_abs_diff={np.abs(diff).max()})')
        axes[1,1].axis('off')
        
        if np.all(test_array == 0):
            log_and_print("ERROR: H5 read-back data is all zeros!", level='error')
        elif not np.array_equal(memmap_array, test_array):
            log_and_print("WARNING: H5 read-back data doesn't match original!", level='warning')
        else:
            log_and_print("✓ H5 read-back verification passed")
            
    except Exception as e:
        log_and_print(f"H5 read-back test failed: {e}", level='error')

    # Save debugging figure
    plt.tight_layout()
    debug_png_path = Path(h5_path).with_suffix('.debug.png')
    # plt.savefig(debug_png_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    # log_and_print(f"Saved H5 debugging plots to {debug_png_path}")

    return Path(h5_path)

def save_movie_as_bin(memmap_path, bin_path, parameters=None):
    """
    Save motion-corrected movie as Suite2p-compatible .bin file.
    
    Args:
        memmap_path: Path to the memmap movie file
        bin_path: Output path for the .bin file
        parameters: Parameter dictionary (optional, for metadata)
    
    Returns:
        Path: Path to saved .bin file
    """
    log_and_print(f"Saving final movie to {bin_path}")

    # Load the memmap movie as (frames, Ly, Lx)
    memmap_array = load_mmap_movie(memmap_path)
    
    # Log initial data state
    log_and_print(f"Loaded memmap array: shape={memmap_array.shape}, dtype={memmap_array.dtype}")
    log_and_print(f"Data range: min={memmap_array.min():.3f}, max={memmap_array.max():.3f}, mean={memmap_array.mean():.3f}")
    
    # Check for empty data
    if np.all(memmap_array == 0):
        log_and_print("ERROR: Input memmap data is all zeros!", level='error')
        return None

    # Clip and convert to int16 for Suite2p compatibility
    memmap_array = clip_range(memmap_array, 'int16').astype(np.int16)

    log_and_print(f"After int16 conversion: min={memmap_array.min()}, max={memmap_array.max()}, mean={memmap_array.mean():.3f}")
    
    # Validate shape
    if memmap_array.ndim != 3:
        raise ValueError(f"Expected memmap array shape (frames, Ly, Lx), got: {memmap_array.shape}")
    
    nframes, Ly, Lx = memmap_array.shape

    # Create debugging plots
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    
    # Plot original first frame
    axes[0,0].imshow(memmap_array[0], cmap='gray')
    axes[0,0].set_title(f'First Frame (min={memmap_array[0].min()}, max={memmap_array[0].max()})')
    axes[0,0].axis('off')
    
    # Ensure C-contiguous memory layout (required for Suite2p)
    if not memmap_array.flags['C_CONTIGUOUS']:
        log_and_print("Converting to C-contiguous array...")
        memmap_array = np.ascontiguousarray(memmap_array)
    
    # Plot after C-ordering
    axes[0,1].imshow(memmap_array[0], cmap='gray')
    axes[0,1].set_title(f'After C-ordering (C_CONTIGUOUS={memmap_array.flags["C_CONTIGUOUS"]})')
    axes[0,1].axis('off')
    
    # Log final array properties
    log_and_print(f"Final array properties:")
    log_and_print(f"  Shape: {memmap_array.shape}")
    log_and_print(f"  Dtype: {memmap_array.dtype}")
    log_and_print(f"  C-contiguous: {memmap_array.flags['C_CONTIGUOUS']}")
    log_and_print(f"  Memory usage: {memmap_array.nbytes / (1024**3):.2f} GB")

    # Save binary file
    log_and_print(f"Writing {memmap_array.nbytes} bytes to {bin_path}...")
    with open(bin_path, 'wb') as f:
        memmap_array.tofile(f)

    # Verify file size
    file_size = Path(bin_path).stat().st_size
    expected_size = nframes * Ly * Lx * 2  # 2 bytes per int16
    log_and_print(f"File verification: written={file_size} bytes, expected={expected_size} bytes")
    
    if file_size != expected_size:
        log_and_print(f"ERROR: File size mismatch!", level='error')
        return None

    # Immediate read-back test
    log_and_print("Performing read-back verification...")
    try:
        test_array = np.fromfile(bin_path, dtype=np.int16).reshape(nframes, Ly, Lx)
        log_and_print(f"Read-back success: shape={test_array.shape}, dtype={test_array.dtype}")
        log_and_print(f"Read-back data: min={test_array.min()}, max={test_array.max()}, mean={test_array.mean():.3f}")
        
        # Plot read-back comparison
        axes[1,0].imshow(test_array[0], cmap='gray')
        axes[1,0].set_title(f'Read-back Test (min={test_array[0].min()}, max={test_array[0].max()})')
        axes[1,0].axis('off')
        
        # Plot difference (should be all zeros)
        diff = memmap_array[0].astype(np.int32) - test_array[0].astype(np.int32)
        axes[1,1].imshow(diff, cmap='RdBu', vmin=-10, vmax=10)
        axes[1,1].set_title(f'Difference (max_abs_diff={np.abs(diff).max()})')
        axes[1,1].axis('off')
        
        if np.all(test_array == 0):
            log_and_print("ERROR: Read-back data is all zeros!", level='error')
        elif not np.array_equal(memmap_array, test_array):
            log_and_print("WARNING: Read-back data doesn't match original!", level='warning')
        else:
            log_and_print("✓ Read-back verification passed")
            
    except Exception as e:
        log_and_print(f"Read-back test failed: {e}", level='error')

    # Save debugging figure
    plt.tight_layout()
    debug_png_path = Path(bin_path).with_suffix('.debug.png')
    # plt.savefig(debug_png_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    # log_and_print(f"Saved debugging plots to {debug_png_path}")

    log_and_print(f"✓ Successfully saved .bin movie to {bin_path}")
    return Path(bin_path)

def run_mcorr(data_path, export_path, parameters, regex_pattern, recompute=True):
    """
    Run motion correction on a set of ome.tif files.
    Concatenate the ome.tif files into a single multi-page tiff file.
    Create a new batch.
    Add the motion correction item to the batch.
    Run the batch.
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
            time0 = time.time()
            ##################
            ct.concatenate_files(
                input_paths=data_path, 
                output_path=export_path, 
                regex=regex_pattern,
                scale_range=False
            )
            ##################
            formatted_time = time.strftime("%H:%M:%S", time.gmtime(time.time() - time0))
            print(f"Concatenation completed in {formatted_time}.")

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

    log_and_print(f"Concatenated movie path: {movie_path}.")    

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
        output_format: 'memmap' (default), 'h5', or 'bin' for final motion-corrected movie storage

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
        batch_path, index, movie_path = run_mcorr(
            data_path, export_path, parameters_mcorr, regex_pattern, recompute
        )

        results['batch_path'] = batch_path
        results['movie_path'] = movie_path

        # Determine whether to clip to uint16 range
        clip_movie = output_format not in ('h5', 'bin')

        if not recompute and movie_path.exists():
            log_and_print(f"Motion corrected movie already exists at {movie_path}.")
        else:
            log_and_print("Optimizing motion corrected movie bit depth...")
            overwrite_movie_memmap(movie_path, movie_path, clip=clip_movie, movie_type='mcorr')
        
        # Z-motion correction (optional)
        if 'zstack_path' in parameters and 'z_motion_correction' in parameters.get('params_mcorr', {}):
            log_and_print("Starting z-motion correction...")
            time_z0 = time.time()
            
            zcorr_movie_path, _, _ = cz.z_motion(
                movie_path, parameters
            )
            
            # Save corrected movie, overwriting the original
            if zcorr_movie_path is not None:
                overwrite_movie_memmap(
                    zcorr_movie_path,
                    movie_path,
                    clip=clip_movie,
                    movie_type='zcorr',
                    save_original=False,
                    remove_input=True,
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
            create_mcorr_movie(mcorr_path=movie_path, export_path=export_path, 
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
    parser.add_argument('-f', '--format', choices=['memmap', 'h5', 'bin'], default='memmap', help='Output format for final movie')
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