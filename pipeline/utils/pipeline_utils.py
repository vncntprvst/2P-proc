"""
# -*- coding: utf-8 -*-

"""

from __future__ import annotations

import os, sys
from pathlib import Path

from tifffile import TiffFile

# Add project root to path (standardized approach)
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from caiman.mmapping import load_memmap
from caiman.paths import decode_mmap_filename_dict
import logging
import numpy as np
import time
import psutil
import contextlib
import mesmerize_core as mc
import gc
import shutil
from PIL import Image

def is_logger_configured():
    return len(logging.root.handlers) > 0

def log_and_print(message, level='info'):
    if is_logger_configured():
        if level == 'info':
            logging.info(message)
        elif level == 'warning':
            logging.warning(message)
        elif level == 'error':
            logging.error(message)
        elif level == 'critical':
            logging.critical(message)
    print(message)
@contextlib.contextmanager

def memory_manager(stage="operation"):
    process = psutil.Process()

    def print_memory_usage(stage_message):
        mem_info = process.memory_info()
        num_threads = process.num_threads()
        print()
        print("=" * 40)
        print(f"{stage_message} - Thread count: {num_threads}, Memory usage: {mem_info.rss / (1024 ** 2):.2f} MB")
        print("=" * 40)
        print()

    try:
        print_memory_usage(f"Process and memory usage before {stage}")
        yield
    finally:
        gc.collect()

# -----------------------------------------------------------------------------
# Adapter: expose a CaImAn memmap with a Suite2p BinaryFile-like API
# -----------------------------------------------------------------------------
class _FrameAccessor:
    """Internal helper to mimic Suite2p's BinaryFile .file slicing interface."""
    def __init__(self, parent: 'CaimanMemmapBinary'):
        self._parent = parent
    def __getitem__(self, indices):
        return self._parent._get_frames(indices)

class CaimanMemmapBinary:
    """
    BinaryFile-like wrapper for a CaImAn memmap (.mmap or .npy) without loading it fully.

    Provides minimal interface compatibility with Suite2p's BinaryFile:
      Attributes: Ly, Lx, filename, dtype, file, n_frames, shape, size
      Methods: __getitem__, data(), close(), sampled_mean() (approximate)

    Notes
    -----
    CaImAn stores data as a 2D memmap (pixels, T) where pixels = Ly*Lx*(d3).
    The filename encodes dimensions and order (C or F). We reshape lazily when
    frames are requested. This avoids allocating (T, Ly, Lx) in RAM.
    """
    def __init__(self, mmap_path: str | Path):
        self.filename = str(mmap_path)
        self._decoded = decode_mmap_filename_dict(self.filename)
        self.Ly = int(self._decoded['d1'])
        self.Lx = int(self._decoded['d2'])
        self._d3 = int(self._decoded['d3'])
        if self._d3 != 1:
            raise NotImplementedError("Adapter currently supports d3 == 1 (2D data)")
        self._T = int(self._decoded['T'])
        self._order = self._decoded['order']  # 'F' or 'C'
        self.dtype = np.float32  # CaImAn memmaps are float32 by convention
        pixels = self.Ly * self.Lx * self._d3
        # Open underlying memmap (pixels, T)
        self._mmap = np.memmap(self.filename, mode='r', dtype=self.dtype, shape=(pixels, self._T), order=self._order)
        # Provide .file accessor mimicking Suite2p BinaryFile.file slicing
        self.file = _FrameAccessor(self)
        self._closed = False

    # --- properties mirroring Suite2p BinaryFile ---
    @property
    def n_frames(self) -> int:
        return self._T

    @property
    def shape(self):
        return (self._T, self.Ly, self.Lx)

    @property
    def size(self):
        return self._mmap.size

    def _get_frames(self, indices):
        """Return frames (n, Ly, Lx) for given indices (slice/int/array)."""
        # Normalize indices to an array of frame indices
        if isinstance(indices, slice):
            frame_inds = np.arange(*indices.indices(self._T))
        elif isinstance(indices, (list, tuple, np.ndarray)):
            frame_inds = np.asarray(indices)
        else:  # single int
            frame_inds = np.asarray([indices])
        # Fetch columns corresponding to frames
        block = self._mmap[:, frame_inds]  # shape (pixels, n_frames)
        nF = block.shape[1]
        # Reshape (Ly, Lx, nF) with proper order then transpose to (nF, Ly, Lx)
        frames = block.reshape(self.Ly, self.Lx, nF, order=self._order).transpose(2, 0, 1)
        if frames.shape[0] == 1 and not isinstance(indices, slice) and not isinstance(indices, (list, tuple, np.ndarray)):
            return frames[0]
        return frames

    def __getitem__(self, indices):
        return self._get_frames(indices)

    def data(self):
        """Return entire movie (T, Ly, Lx). Beware of memory usage."""
        return self._get_frames(slice(0, self._T))

    def sampled_mean(self, nsamps: int = 1000):
        """Approximate mean by sampling up to nsamps frames evenly spaced."""
        nsamps = min(nsamps, self._T)
        inds = np.linspace(0, self._T - 1, nsamps, dtype=int)
        frames = self[inds].astype(np.float32)
        return frames.mean(axis=0)

    def close(self):
        if not self._closed:
            try:
                self._mmap._mmap.close()
            except Exception:
                pass
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def get_batch_ids(batch_path):
    df = mc.load_batch(batch_path)
    batch_ids = []
    for _, row in df.iterrows():
        batch_ids.append(row.uuid)
        try:
            df.caiman.remove_item(row.uuid)
        except Exception:
            pass
    del df
    return batch_ids


def cleanup_files(batch_path, export_path):
    try:
        batch_ids = get_batch_ids(batch_path)
    except Exception:
        log_and_print(f"Could not get batch ids from {batch_path}.")
        return
    for batch_id in batch_ids:
        batch_runfile = Path(export_path) / f"{batch_id}.runfile"
        if batch_runfile.exists():
            batch_runfile.unlink()
        batch_dir = Path(export_path) / batch_id
        if batch_dir.exists():
            time.sleep(1)
            try:
                shutil.rmtree(batch_dir)
            except Exception as e:
                log_and_print(f"Could not delete {batch_dir}: {e}")
    for pickle_file in Path(export_path).glob("batch_*.pickle"):
        pickle_file.unlink()
    # Remove concatenated tiff if present
    cat_tiff_path = Path(export_path) / 'cat_tiff_bt.tiff'
    if cat_tiff_path.exists():
        cat_tiff_path.unlink()
    # NOTE: Do not remove the final motion-corrected movie here.
    # Downstream steps (ops creation and extraction) may rely on
    # `mcorr_movie.*` being present in the export directory.
    # A separate cleanup step is run by the batch script during wrapping.
    
    # Remove concatenation sidecar JSONs if present
    cat_sidecars = [
        Path(export_path) / 'cat_tiff_bt.tiff.json',
        Path(export_path) / 'cat_tiff.h5.json',
    ]
    for sc in cat_sidecars:
        if sc.exists():
            try:
                sc.unlink()
            except Exception:
                pass
    log_and_print("Batch files deleted.\n")


def find_latest_batch(export_path):
    runfiles = sorted(Path(export_path).glob('*.runfile'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runfiles:
        raise FileNotFoundError(f"No runfile found in {export_path}")
    return Path(export_path) / runfiles[0].stem


def get_default_parameters(proc_step):
    """
    Get the default parameters for motion correction or CNMF.
    """
    if proc_step == 'mcorr':
        default_params = \
            {
            'main':
                {
                    'strides': [36, 36],
                    'overlaps': [24, 24],
                    'max_shifts': [12, 12],
                    'max_deviation_rigid': 6,
                    'border_nan': 'copy',
                    'pw_rigid': True,
                    'gSig_filt': None
                },
            }
            
    elif proc_step == 'cnmf':
        default_params = \
            {
            'main':
                {
                    'fr': 20, # framerate, very important!
                    'p': 1,
                    'nb': 2,
                    'merge_thr': 0.85,
                    'rf': 20,
                    'stride': 10, # "stride" for cnmf, "strides" for mcorr
                    'K': 10,
                    'gSig': [5, 5],
                    'ssub': 1,
                    'tsub': 1,
                    'method_init': 'greedy_roi',
                    'min_SNR': 3.0,
                    'SNR_lowest':  1.0,
                    'rval_thr': 0.8,
                    'rval_lowest': 0.2,
                    'use_cnn': True,
                    'min_cnn_thr': 0.9,
                    'cnn_lowest': 0.2,
                    'decay_time': 0.15,
                },
            'refit': True, # If `True`, run a second iteration of CNMF
            }
            
    return default_params

def clip_range(array, clip_range='uint16'):
    """
    Clip the values of an array to a specific range.
    """
    if clip_range == 'uint16':
        return np.clip(array, 0, 2**16 - 1)
    elif clip_range == 'uint8':
        return np.clip(array, 0, 2**8 - 1)
    elif clip_range == 'int16':
        return np.clip(array, -2**15, 2**15 - 1)
    else:
        return array

def safe_rename(src, dst):
    """Attempt to rename the file with retries upon encountering an access error."""
    max_attempts = 5
    attempt = 0
    rename_succes = False
    print(f"Renaming file {src} to {dst}.")
    while attempt < max_attempts:
        try:
            src.rename(dst)
            rename_succes = True
            break
        except PermissionError:
            print(f"Attempt {attempt+1} failed, retrying in 5 seconds...")
            time.sleep(5)
            attempt += 1
    if attempt == max_attempts:
        print(f"Failed to rename file {src} to {dst} after {max_attempts} attempts.")
        
    return rename_succes
        
def overwrite_movie_memmap(movie, original_mmap_path, clip=True, movie_type='mcorr', save_original=False, remove_input=False):
    """
    Overwrite the original memmap file with the new movie.
    """
    # Check if movie is a Path object or a numpy array
    if isinstance(movie, Path):
        #  Load the movie from the memmap file
        movie_array = load_mmap_movie(movie)
    else:
        movie_array = movie
    print(f"Movie type: {type(movie_array)}, with shape: {movie_array.shape}")
    first_frame = movie_array[0]
    print(f"First frame dtype: {first_frame.dtype}, shape: {first_frame.shape}, min_val: {first_frame.min()}, max_val: {first_frame.max()}")
    print(f"Movie median: {np.median(movie_array)}")

    # # Compare original movie median
    # with TiffFile(movie.parent.parent / "cat_tiff_bt.tiff") as tif:
    #     og_tiff = tif.asarray()
    #     print(f"Z-stack shape: {og_tiff.shape}")
    #     print(f"Z-stack median: {np.median(og_tiff)}")

    if clip:
        print(f"Clipping movie array to uint16 range.")
        # Clip, but don't convert to uint16 yet (caiman expects 32 bit float) image
        movie_array = clip_range(movie_array, 'uint16')
    
    # Original array with dimensions (T, y, x). Transpose the array to (y, x, T)
    transposed_array = movie_array.transpose(1, 2, 0)

    # Flatten the transposed array in 'F' order (to align with the loading code's expectations, based on caiman demo notebook)
    flattened_array = transposed_array.flatten(order='F')

    # Create a new memmap file with write access
    log_and_print(f"{movie_type} movie path: {original_mmap_path}")
    flattened_movie_path = original_mmap_path.parent / f"flattened_{original_mmap_path.name}"

    # Save the flattened array as a memmap
    flattened_movie = np.memmap(flattened_movie_path, dtype='float32', mode='w+', shape=flattened_array.shape)
    np.copyto(flattened_movie, flattened_array) # equivalent to flattened_movie[:] = flattened_array[:] 
    
    # Flush changes to disk and close the memmap and the original memmap
    flattened_movie.flush()
    del flattened_movie, flattened_array, transposed_array  # Delete variables explicitly
    gc.collect()  # Force garbage collection

    # Recompute the projections
    proj_paths = dict()
    for proj_type in ["mean", "std", "max"]:
        p_img = getattr(np, f"nan{proj_type}")(movie_array, axis=0)
        proj_paths[proj_type] = original_mmap_path.parent.joinpath(
            f"{str(original_mmap_path.parent.stem)}_{proj_type}_projection.npy"
        )
        np.save(str(proj_paths[proj_type]), p_img)
        del p_img  # Delete projection images after saving
        
    log_and_print(f"Projections recomputed and saved to {original_mmap_path.parent}.")

    del movie_array

    # The code below does not work on Windows while memmap is open
    time.sleep(5)

    # Create a backup copy of the original memmap file then delete the original
    rename_success = safe_rename(original_mmap_path, original_mmap_path.parent / f"original_{original_mmap_path.name}")
    # original_mmap_path.rename(original_mmap_path.parent / f"original_{original_mmap_path.name}")
    # print(f"Original motion corrected movie saved to {original_mmap_path.parent / f'original_{original_mmap_path.name}'}")

    if rename_success:
        # Finally, rename the clipped memmap file to the original name
        flattened_movie_path.rename(original_mmap_path)
        # Delete the backup copy
        if not save_original:
            (original_mmap_path.parent / f"original_{original_mmap_path.name}").unlink()
            
        if remove_input and isinstance(movie, Path):
            movie.unlink()
    
        return original_mmap_path, flattened_movie_path   
    
    else:
        return flattened_movie_path, None  

def save_mmap_movie(movie, movie_path):
    """
    Save an array as a memmaped numpy array.
    Original array must have dimensions T, y, x
    """
    # Save the movie as a memmaped numpy array
    movie_path = Path(movie_path)
    # Transpose the array to (y, x, T)
    transposed_array = movie.transpose(1, 2, 0)
    # Flatten the transposed array in 'F' order (to align with the loading code)
    flattened_array = transposed_array.flatten(order='F')
    # Create a new memmap file with write access
    movie_ = np.memmap(movie_path, dtype='float32', mode='w+', shape=flattened_array.shape)
    movie_[:] = flattened_array[:]
    # Flush changes to disk and close the memmap
    del movie_
    del flattened_array    
    
def load_mmap_movie(movie_path):
    """
    Load a memmaped numpy array.
    Returns a fully materialized 3D numpy array (T, Ly, Lx).
    For large datasets prefer using `load_caiman_memmap` to avoid loading all frames.
    """
    # Load the movie from the memmap file
    movie , dims, T = load_memmap(movie_path)
    # Reshape the array to the desired dimensions
    movie = np.reshape(movie.T, [T] + list(dims), order='F')
    return movie

def load_caiman_memmap(movie_path: str | Path) -> CaimanMemmapBinary:
    """Convenience loader returning a BinaryFile-like adapter for a CaImAn memmap."""
    return CaimanMemmapBinary(movie_path)

def create_mp4_movie(input_movie, export_path, filename=None):
    """
    Create a mp4 movie from a numpy array, using ffmpeg.
    """   
    # Create a directory for temporary frame storage
    temp_frame_dir = export_path / 'temp_frames'
    os.makedirs(temp_frame_dir, exist_ok=True)

    # Save each frame as an image 
    for i, frame in enumerate(input_movie):
        # If height not divisible by 2, add padding, to avoid [libx264 @ 0x563ae05f8b40] height not divisible by 2 error
        if frame.shape[0] % 2 != 0:
            # Add a row of black pixels at the bottom
            frame = np.pad(frame, ((0, 1), (0, 0)), 'constant')
        frame_image = Image.fromarray(frame)
        frame_image.save(temp_frame_dir / f"frame_{i:04d}.png")
        
    # Get the size of the frames post-padding
    frame_size = frame_image.size
    
    if filename is None:
        filename = 'movie.mp4'
        
    # Construct the FFmpeg command to make an MP4 movie with the adjusted size
    ffmpeg_command = f"ffmpeg -y -r 30 -f image2 -s {frame_size[0]}x{frame_size[1]} -i {temp_frame_dir}/frame_%04d.png -vcodec libx264 -crf 25 -pix_fmt yuv420p {Path(export_path, filename)}"
    os.system(ffmpeg_command)

    # Delete the temporary frame images after creating the video
    # for file in os.listdir(temp_frame_dir):
    #     os.remove(temp_frame_dir / file)
    # os.rmdir(temp_frame_dir)
    shutil.rmtree(temp_frame_dir)

def cat_movies_to_mp4(movie1, movie2, movie_path):
    """
    Concatenate two movies horizontally and save as a mp4 movie.
    """
    # For visualization purposes only: 
    # If ranges are significantly different, consider rescaling
    
    # Store the original data type
    movie1_dtype = movie1.dtype
    movie2_dtype = movie2.dtype
    
    movie1_min, movie1_max = np.min(movie1), np.max(movie1)
    movie2_min, movie2_max = np.min(movie2), np.max(movie2)
        
    if movie1_min != movie2_min or movie1_max != movie2_max:
        # Check if the movies are either uint16 or uint8
        if movie1.dtype in (np.uint16, np.uint8) or movie2.dtype in (np.uint16, np.uint8):
            # convert to float32
            movie1 = movie1.astype(np.float32)
            movie2 = movie2.astype(np.float32)
        normalized_movie1 = (movie1 - movie1_min) / (movie1_max - movie1_min) * 65535
        normalized_movie2 = (movie2 - movie2_min) / (movie2_max - movie2_min) * 65535
    else:
        normalized_movie1 = movie1
        normalized_movie2 = movie2

    # Convert to uint16 (or uint8 if that was the original datatype), after normalization
    if movie1_dtype not in (np.uint16, np.uint8):
        normalized_movie1 = normalized_movie1.astype(np.uint16)
    else:
        normalized_movie1 = normalized_movie1.astype(movie1_dtype)
    if movie2_dtype not in (np.uint16, np.uint8):
        normalized_movie2 = normalized_movie2.astype(np.uint16)
    else:
        normalized_movie2 = normalized_movie2.astype(movie2_dtype)

    # first_frame_1 = normalized_movie1[0,:,:]
    # first_frame_2 = normalized_movie2[0,:,:]
    
    # Concatenate the two movies horizontally
    cat_movie = np.concatenate((normalized_movie1, normalized_movie2), axis=2)
    
    # Split the movie path into path and filename
    export_path = movie_path.parent
    filename = movie_path.name
    
    # Create the mp4 movie
    create_mp4_movie(cat_movie, export_path, filename)
