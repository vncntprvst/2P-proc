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

import sys
import time
from pathlib import Path
import numpy as np
import h5py
from tifffile import TiffWriter, TiffFile

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
    
    # Load the memmap movie
    memmap_array = load_mmap_movie(memmap_path)
    
    # Suite2p expects uint16 data when reading from an h5 file
    # The memmap is float32, so clip and convert before export
    memmap_array = clip_range(memmap_array, 'uint16').astype(np.uint16)
    
    # Extract parameters
    frame_rate = parameters.get('imaging', {}).get('fr', 30.0) or parameters.get('imaging', {}).get('fs', 30.0)
    pixel_size_um = parameters.get('imaging', {}).get('microns_per_pixel', 1.0)

    # Get image dimensions
    T, Ly, Lx = memmap_array.shape
    
    # Create HDF5 file with data - following bergamo_stitcher pattern
    with h5py.File(h5_path, 'w') as f:
        # Create main dataset with chunking and compression
        dset = f.create_dataset(
            'data',
            data=memmap_array,
            chunks=True,  # Enable chunking like bergamo_stitcher
            compression='gzip',
            shuffle=True,
            dtype='uint16'
        )
        
        # Add spatial calibration metadata
        dset.attrs['element_size_um'] = [0, pixel_size_um, pixel_size_um]
        dset.attrs['pixel_size_um'] = pixel_size_um
        dset.attrs['spacing'] = pixel_size_um
        dset.attrs['unit'] = 'pixel'
        
        # Add acquisition metadata
        dset.attrs['time_unit'] = 'seconds'
        dset.attrs['frame_rate_hz'] = frame_rate
        dset.attrs['frame_interval'] = 1.0 / frame_rate
        dset.attrs['n_channels'] = 1  # Assuming single channel for calcium imaging
        dset.attrs['n_timepoints'] = T
        dset.attrs['fs'] = frame_rate  # Suite2p field
        dset.attrs['n_frames'] = T
        dset.attrs['height_pixels'] = Ly
        dset.attrs['width_pixels'] = Lx
        
        # Add physical dimensions
        physical_width_um = Lx * pixel_size_um
        physical_height_um = Ly * pixel_size_um
        dset.attrs['physical_width_um'] = physical_width_um
        dset.attrs['physical_height_um'] = physical_height_um
        
        # Add processing metadata as separate datasets (like bergamo_stitcher)
        f.create_dataset(
            'processing_pipeline',
            data='Analysis_2P',
            dtype=h5py.special_dtype(vlen=str)
        )
        
        f.create_dataset(
            'motion_corrected',
            data='true',
            dtype=h5py.special_dtype(vlen=str)
        )
        
        f.create_dataset(
            'data_type',
            data='calcium_imaging',
            dtype=h5py.special_dtype(vlen=str)
        )
        
        # Add extraction parameters as metadata string
        if 'params_extraction' in parameters:
            import json
            extraction_metadata = json.dumps(parameters['params_extraction'])
            f.create_dataset(
                'extraction_parameters',
                data=extraction_metadata,
                dtype=h5py.special_dtype(vlen=str)
            )
        
        log_and_print(f"HDF5 metadata:")
        log_and_print(f"  - Frame rate: {frame_rate} Hz")
        log_and_print(f"  - Pixel size: {pixel_size_um} μm")
        log_and_print(f"  - Dimensions: {T} frames × {Ly} × {Lx} pixels")
        log_and_print(f"  - Physical size: {physical_height_um:.1f} × {physical_width_um:.1f} μm")
        
    return Path(h5_path)

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
    
    if not recompute and movie_path.exists():
        log_and_print(f"Concatenated movie already exists at {export_path}. Using existing file.")
    else:
        # Concatenate the ome.tif files into a single multi-page tiff file
        # Using the concat_tif.py script to concatenate the tif files. If needed, install libtiff with: pip install pylibtiff
        log_and_print(f"Loading and concatenating data from {data_path}.")
        try:
            time0 = time.time()
            ##################
            ct.concatenate_files(data_path, export_path, regex_pattern)
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
                    movie_path, parameters
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
                                
                # Save as BigTIFF file  
                create_mcorr_movie(movie_path, export_path, None, None, 
                                          format='tiff', diff_corr=False)
                
                # Create comparison movie (first 240 frames)
                create_mcorr_movie(mcorr_path=movie_path, export_path=export_path, 
                                          batch=batch_path, index=index, excerpt=240)
            
            results['success'] = True

            if output_format == 'h5':
                h5_path = export_path / 'mcorr_movie.h5'
                                
                # Save movie with proper metadata
                results['movie_path'] = save_movie_as_h5(
                    memmap_path=movie_path,
                    h5_path=h5_path,
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
    parser.add_argument('-f', '--format', choices=['memmap', 'h5'], default='memmap', help='Output format for final movie')
    args = parser.parse_args()
    
    # Convert input paths to Path objects
    input_paths = [Path(p) for p in args.input_paths]
    output_path = Path(args.output)
    pattern = args.pattern
    recompute = args.recompute
    create_movies = args.create_movies
    output_format = args.format
    
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
        output_format=output_format
    )