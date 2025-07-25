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

import os
import sys
import time
from pathlib import Path
import numpy as np
import contextlib
import gc
import psutil
import logging
import h5py

# Import CaImAn and Mesmerize components
import mesmerize_core as mc
from caiman.mmapping import load_memmap

# Import local modules
try:
    # Try absolute imports first
    import modules.bruker_concat_tif as ct
    import modules.compute_zcorr as cz
except ImportError:
    try:
        # Try relative imports if absolute imports fail
        from . import bruker_concat_tif as ct
        from . import compute_zcorr as cz
    except ImportError:
        # Try importing from parent directory
        import sys
        from pathlib import Path
        parent_dir = Path(__file__).parent
        sys.path.insert(0, str(parent_dir))
        import bruker_concat_tif as ct
        import compute_zcorr as cz


def is_logger_configured():
    """Check if logging is configured."""
    return len(logging.root.handlers) > 0


def log_and_print(message, level='info'):
    """Log message and print to console."""
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
    """Context manager for memory tracking and cleanup."""
    process = psutil.Process()
    
    def print_memory_usage(stage_message):
        mem_info = process.memory_info()
        num_threads = process.num_threads()
        print(f"Memory Manager - {stage_message}")
        print(f"Thread count: {num_threads}, Memory usage: {mem_info.rss / (1024 ** 2):.2f} MB")
        
    try:
        print_memory_usage(f"Starting {stage}")
        yield
    finally:
        # Force garbage collection
        gc.collect()
        print_memory_usage(f"Completed {stage}")


def clip_range(array, clip_range='uint16'):
    """
    Clip the values of an array to a specific range.
    
    Args:
        array: Input numpy array
        clip_range: Range to clip to ('uint16' or 'uint8')
    
    Returns:
        Clipped array
    """
    if clip_range == 'uint16':
        return np.clip(array, 0, 2**16-1)
    elif clip_range == 'uint8':
        return np.clip(array, 0, 2**8-1)
    else:
        return array


def safe_rename(src, dst, max_attempts=5):
    """
    Attempt to rename a file with retries upon encountering access errors.
    
    Args:
        src: Source path
        dst: Destination path
        max_attempts: Maximum number of retry attempts
    
    Returns:
        bool: Success status
    """
    attempt = 0
    rename_success = False
    print(f"Renaming file {src} to {dst}.")
    
    while attempt < max_attempts:
        try:
            src.rename(dst)
            rename_success = True
            break
        except PermissionError:
            print(f"Attempt {attempt+1} failed, retrying in 5 seconds...")
            time.sleep(5)
            attempt += 1
    
    if attempt == max_attempts:
        print(f"Failed to rename file {src} to {dst} after {max_attempts} attempts.")
        
    return rename_success


def load_mmap_movie(movie_path):
    """
    Load a memmaped numpy array.
    
    Args:
        movie_path: Path to the .mmap file
    
    Returns:
        Loaded movie array with dimensions (T, y, x)
    """
    # Load the movie from the memmap file
    movie, dims, T = load_memmap(movie_path)
    # Reshape the array to the desired dimensions
    movie = np.reshape(movie.T, [T] + list(dims), order='F')
    
    return movie


def overwrite_movie_memmap(movie, original_mmap_path, clip=True, movie_type='mcorr', 
                          save_original=False, remove_input=False):
    """
    Overwrite the original memmap file with the new movie.
    
    Args:
        movie: Movie data (numpy array or Path to movie file)
        original_mmap_path: Path to original mmap file
        clip: Whether to clip values to uint16 range
        movie_type: Type of movie for logging ('mcorr', 'zcorr', etc.)
        save_original: Whether to keep a backup of the original file
        remove_input: Whether to remove the input file (if movie is a Path)
    
    Returns:
        tuple: (success_path, backup_path)
    """
    
    # Check if movie is a Path object or a numpy array
    if isinstance(movie, Path):
        movie_array = load_mmap_movie(movie)
    else:
        movie_array = movie

    if clip:
        # Clip values but keep as float32 (CaImAn expects 32-bit float)
        movie_array = clip_range(movie_array, 'uint16')
    
    # Original array with dimensions (T, y, x). Transpose to (y, x, T)
    transposed_array = movie_array.transpose(1, 2, 0)
    
    # Flatten in 'F' order (to align with CaImAn's expectations)
    flattened_array = transposed_array.flatten(order='F')
    
    # Create new memmap file
    log_and_print(f"{movie_type} movie path: {original_mmap_path}")
    flattened_movie_path = original_mmap_path.parent / f"flattened_{original_mmap_path.name}"
    
    # Save the flattened array as a memmap
    flattened_movie = np.memmap(flattened_movie_path, dtype='float32', mode='w+', 
                               shape=flattened_array.shape)
    np.copyto(flattened_movie, flattened_array)
    
    # Flush changes to disk and close the memmap
    flattened_movie.flush()
    del flattened_movie, flattened_array, transposed_array
    gc.collect()
    
    # Recompute the projections
    proj_paths = {}
    for proj_type in ["mean", "std", "max"]:
        p_img = getattr(np, f"nan{proj_type}")(movie_array, axis=0)
        proj_paths[proj_type] = original_mmap_path.parent.joinpath(
            f"{str(original_mmap_path.parent.stem)}_{proj_type}_projection.npy"
        )
        np.save(str(proj_paths[proj_type]), p_img)
        del p_img
        
    log_and_print(f"Projections recomputed and saved to {original_mmap_path.parent}.")
    
    del movie_array
    
    # Wait a moment for file system operations to complete
    time.sleep(5)
    
    # Create backup and rename files
    rename_success = safe_rename(original_mmap_path, 
                                original_mmap_path.parent / f"original_{original_mmap_path.name}")
    
    if rename_success:
        # Rename the clipped memmap file to the original name
        flattened_movie_path.rename(original_mmap_path)
        
        # Optionally remove the backup
        if not save_original:
            backup_path = original_mmap_path.parent / f"original_{original_mmap_path.name}"
            if backup_path.exists():
                backup_path.unlink()
            
        # Remove input file if requested
        if remove_input and isinstance(movie, Path):
            if movie.exists():
                movie.unlink()
    
        return original_mmap_path, None   
    
    else:
        return flattened_movie_path, None


def run_mcorr(data_path, export_path, parameters, regex_pattern, recompute=True):
    """
    Run motion correction on a set of ome.tif files.
    
    This function:
    1. Concatenates ome.tif files into a single multi-page TIFF
    2. Creates a new Mesmerize batch
    3. Adds motion correction item to the batch
    4. Runs the batch processing
    
    Args:
        data_path: List of paths containing ome.tif files
        export_path: Path where results will be saved
        parameters: Motion correction parameters
        regex_pattern: Pattern to match input files
        recompute: Whether to recompute if results exist
    
    Returns:
        tuple: (batch_path, mcorr_index, movie_path)
    """
    # Set movie path
    movie_path = Path(export_path).joinpath('cat_tiff_bt.tiff')
    
    if not recompute and movie_path.exists():
        log_and_print(f"Concatenated movie already exists at {export_path}. Using existing file.")
    else:
        # Concatenate the ome.tif files into a single multi-page tiff file
        ct.concatenate_files(data_path, export_path, regex_pattern, method='bigtiff')

    log_and_print(f"Concatenated movie path: {movie_path}.")    

    # Check for existing batch or create new one
    batch_path = None
    existing_batches = list(Path(export_path).glob("batch_*.pickle"))
    
    if not recompute and existing_batches:
        batch_path = existing_batches[0]
        log_and_print(f"Using existing batch: {batch_path}")
        df = mc.load_batch(batch_path)
    else:
        # Create new batch file path
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_file_path = Path(export_path) / f"batch_{timestamp}.pickle"
        
        # Create new batch
        df = mc.create_batch(batch_file_path)
        batch_path = batch_file_path
        log_and_print(f"Created new batch: {batch_path}")
        
        # Add motion correction item to batch
        df.caiman.add_item(
            algo='mcorr',
            input_movie_path=movie_path,
            params=parameters,
            item_name=f"mcorr_{movie_path.stem}"
        )
    
    time0 = time.time()
    mcorr_index = None
    
    # Run batch items that haven't been run yet
    for row_index, row in df.iterrows():
        if row.algo == 'mcorr' and row["outputs"] is None:
            log_and_print(f"Running motion correction for batch item {row.name}")
            process = row.caiman.run()
            mcorr_index = row_index
            
            # Reload batch on Windows (required for local backend)
            if process.__class__.__name__ == "DummyProcess":
                df = df.caiman.reload_from_disk()
            break
            
    log_and_print(f"Batch completed for motion correction. Results saved to {batch_path}.")
    formatted_time = time.strftime("%H:%M:%S", time.gmtime(time.time() - time0))
    print(f"Motion correction completed in {formatted_time}.")
    
    # Get the motion corrected movie path
    if mcorr_index is not None:
        # Reload batch from disk to get updated results
        df = df.caiman.reload_from_disk()
        mcorr_movie_path = Path(df.iloc[mcorr_index].mcorr.get_output_path())
        return batch_path, mcorr_index, mcorr_movie_path
    else:
        # Find existing motion correction result
        for idx, row in df.iterrows():
            if row.algo == 'mcorr' and row["outputs"] is not None:
                mcorr_movie_path = Path(row.mcorr.get_output_path())
                return batch_path, idx, mcorr_movie_path
                
        raise RuntimeError("No motion correction results found")


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
        output_format: 'memmap' (default) or 'h5' for final movie storage
    
    Returns:
        dict: Results dictionary with paths and metadata
    """
    
    results = {
        'batch_path': None,
        'movie_path': None,
        'export_path': export_path,
        'success': False
    }
    
    with memory_manager("motion_correction"):
        try:
            # Get motion correction parameters
            parameters_mcorr = parameters['params_mcorr']
            
            # Run the motion correction 
            batch_path, index, movie_path = run_mcorr(
                data_path, export_path, parameters_mcorr, regex_pattern, recompute
            )
            
            results['batch_path'] = batch_path
            results['movie_path'] = movie_path
            
            # Clip the motion corrected movie to uint16 range
            if not recompute and movie_path.exists():
                log_and_print(f"Clipped motion corrected movie already exists at {movie_path}.")
            else:
                log_and_print("Optimizing motion corrected movie bit depth...")
                overwrite_movie_memmap(movie_path, movie_path, clip=True, movie_type='mcorr')
            
            # Z-motion correction (optional)
            if 'zstack_path' in parameters and 'z_params' in parameters:
                log_and_print("Starting z-motion correction...")
                time_z0 = time.time()
                
                zcorr_movie_path, _, _ = cz.z_motion(
                    movie_path, parameters, output_format=output_format
                )
                
                # Save corrected movie, overwriting the original
                if zcorr_movie_path is not None:
                    overwrite_movie_memmap(zcorr_movie_path, movie_path, clip=True, 
                                         movie_type='zcorr', save_original=False, remove_input=True)
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
                
                # Import movie creation functions
                try:
                    from . import pipeline_mcorr_cnmf as pipeline
                except ImportError:
                    import sys
                    sys.path.append(str(Path(__file__).parent.parent / "Mesmerize"))
                    import pipeline_mcorr_cnmf as pipeline
                
                # Save as BigTIFF file  
                pipeline.create_mcorr_movie(movie_path, export_path, None, None, 
                                          format='tiff', diff_corr=False)
                
                # Create comparison movie (first 240 frames)
                pipeline.create_mcorr_movie(mcorr_path=movie_path, export_path=export_path, 
                                          batch=batch_path, index=index, excerpt=240)
            
            results['success'] = True

            if output_format == 'h5':
                h5_path = movie_path.with_suffix('.h5')
                log_and_print(f"Saving final movie to {h5_path}")
                memmap_array = load_mmap_movie(movie_path)
                # Suite2p expects uint16 data when reading from an h5 file.
                # The memmap is float32, so clip and convert before export.
                memmap_array = clip_range(memmap_array, 'uint16').astype(np.uint16)
                # Save the memmap array to HDF5 with gzip compression
                with h5py.File(h5_path, 'w') as f:
                    f.create_dataset(
                        'data',             # Default dataset field name in Suite2p
                        data=memmap_array,
                        compression='gzip',
                        chunks=(1, memmap_array.shape[1], memmap_array.shape[2])
                    )
                results['movie_path'] = h5_path

            log_and_print("Motion correction workflow completed successfully.")
            
        except Exception as e:
            log_and_print(f"Motion correction workflow failed: {e}", level='error')
            results['error'] = str(e)
            raise
    
    return results


def get_default_mcorr_parameters():
    """
    Get default motion correction parameters.
    
    Returns:
        dict: Default parameters for motion correction
    """
    return {
        'main': {
            'strides': [36, 36],
            'overlaps': [24, 24],
            'max_shifts': [12, 12],
            'max_deviation_rigid': 6,
            'border_nan': 'copy',
            'pw_rigid': True,
            'gSig_filt': None
        }
    }


if __name__ == "__main__":
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description="Motion Correction Module")
    parser.add_argument('input_paths', nargs='+', help='Input data paths')
    parser.add_argument('-o', '--output', required=True, help='Output directory')
    parser.add_argument('-p', '--pattern', default='*_Ch2_*.ome.tif', help='File pattern')
    parser.add_argument('--recompute', action='store_true', help='Recompute existing results')
    parser.add_argument('--no-movies', action='store_true', help='Skip movie creation')
    parser.add_argument('--save-h5', action='store_true', help='Save final movie as HDF5')
    
    args = parser.parse_args()
    
    # Set up basic parameters
    parameters = {
        'params_mcorr': get_default_mcorr_parameters()
    }
    
    # Run workflow
    results = run_motion_correction_workflow(
        data_path=args.input_paths,
        export_path=Path(args.output),
        parameters=parameters,
        regex_pattern=args.pattern,
        recompute=args.recompute,
        create_movies=not args.no_movies,
        output_format='h5' if args.save_h5 else 'memmap'
    )
    
    print(f"Motion correction completed: {results['success']}")
    if results['success']:
        print(f"Results saved to: {results['export_path']}")
        print(f"Movie path: {results['movie_path']}")
