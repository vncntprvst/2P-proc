"""bruker_concat_tif.py
Script to concatenate Bruker 2P ome.tif files into a single BigTIFF file.

Example usage, from a python console or notebook:
import bruker_concat_tif as ct
ct.concatenate_files(['/path/to/folder1'], '/path/to/output')
ct.concatenate_files(['/path/to/folder1', '/path/to/folder2'], '/path/to/output', regex='*_Ch1_*.ome.tif')

Example usage, from the command line:
python bruker_concat_tif.py /path/to/folder1 /path/to/output
""" 
# Written by Vincent Prevosto <prevosto at mit dot edu>
# CC BY-SA 4.0

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os, glob, argparse, time
# from tifftools import tiff_concat
from tifffile import imread, imwrite, TiffWriter, TiffFile
from libtiff import TIFF, libtiff_ctypes
import numpy as np
import warnings, contextlib
import psutil
# import dask.array as da

# Couldn't suppress tiffffile warnings with warnings.filterwarnings('ignore'), so used this instead
@contextlib.contextmanager
def suppress_stdout_stderr():
    """A context manager that redirects stdout and stderr to devnull"""
    with open(os.devnull, 'w') as fnull:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = fnull, fnull
        try:
            yield
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            
@contextlib.contextmanager
def suppress_c_stderr():
    """A context manager that redirects C level stderr to devnull"""
    original_stderr_fd = sys.stderr.fileno()
    original_stderr = os.dup(original_stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)

    try:
        os.dup2(devnull, original_stderr_fd)
        yield
    finally:
        os.dup2(original_stderr, original_stderr_fd)
        os.close(devnull)
        os.close(original_stderr)

def is_multi_page_tiff(file_path):
    """
    Check if the TIFF file at file_path is a multi-page TIFF.
    
    Args:
    - file_path: Path to the TIFF file.
    
    Returns:
    - True if the file is a multi-page TIFF, False otherwise.
    """
    with TiffFile(file_path) as tif:
        # Check if the TIFF file has more than one page
        return len(tif.pages) > 1

                    
def concat_tiff_files(file_list, output_file, compression=None):
    """ Concatenate a list of tiff files into a multi-page TIFF""" 
    # with suppress_c_stderr():
    libtiff_ctypes.suppress_warnings()

    tif = TIFF.open(file_list[0], 'r')
    first_img = tif.read_image()
    tif.close()
    
    # Get the shape of the first image
    # img_shape = first_img.shape
    # print(f"First image shape: {first_img.shape}")
    # Get the data type of the first image
    img_dtype = first_img.dtype
    # Get the range of the first image
    img_range = (first_img.min(), first_img.max())    
    
    if img_dtype == np.uint16 and img_range[1] <= 4095:
        # Convert range to uint16 by multiplying by 16
        print(f"Images are {img_dtype} with range {img_range}.")
                
    # Open the output file as biggiff
    out_tif = TIFF.open(output_file, mode='w8')
    # Write all the images to the output file
    # tiff_concat(file_list, output_file, overwrite=True)
    for i in range(len(file_list)):
        tif = TIFF.open(file_list[i], 'r')
        img = tif.read_image()
        # Flip the image vertically (Original Bruker frames are flipped upside down)
        img = np.flipud(img)
        tif.close()
        out_tif.write_image(img, compression=compression)
    out_tif.close()
    
    # # Load all the images first with then save as a multi-page tiff
    # for i in range(len(file_list)):
    #     tif = TIFF.open(file_list[i], 'r')
    #     img = tif.read_image()
    #     tif.close()
    #     if i == 0:
    #         m = img
    #     else:
    #         m = np.dstack((m, img))
    
    # bigtiff_file = output_file.replace('.tiff', '_bt.tiff')
    # imwrite(bigtiff_file, m, imagej=False, bigtiff=True, metadata=None, dtype=np.uint16, compressionargs={'compression': compression})
    
    print(f"Concatenated {len(file_list)} files to multi-page TIFF {output_file}.")


def concat_multi_tiff_files(file_list, output_file, compression=None):
    # with suppress_c_stderr():
    libtiff_ctypes.suppress_warnings()
        
    with TiffWriter(output_file, bigtiff=True) as out_tif:
        for file_path in file_list:
            # print(f"Processing {file_path}")
            with TiffFile(file_path) as tif:
                for page in tif.pages:
                    img = page.asarray()
                    # Flip the image vertically if needed
                    img_flipped = np.flipud(img)
                    out_tif.write(img_flipped, compression=compression)
    print(f"Concatenated {len(file_list)} files to multi-page TIFF {output_file}.")


def load_multi_page_tiff(input_file):
    """
    Load a multi-page TIFF file into a NumPy array.

    Args:
    - input_file: Path to the multi-page TIFF file.

    Returns:
    - loaded_movie: A NumPy array containing the image data from all pages.
    """
    with TiffFile(input_file) as tif:
        # Allocate a NumPy array to hold the image data
        # Assumes that all pages have the same shape and data type
        num_pages = len(tif.pages)
        if num_pages == 0:
            raise ValueError("The TIFF file contains no pages.")
        
        # Read the first page to determine the shape and dtype
        sample_page = tif.pages[0].asarray()
        image_shape = sample_page.shape
        dtype = sample_page.dtype
        
        # Create an empty array to store all images
        loaded_movie = np.empty((num_pages,) + image_shape, dtype=dtype)
        
        # Load each page into the array
        for i, page in enumerate(tif.pages):
            loaded_movie[i] = page.asarray()
    
    return loaded_movie


def convert_to_bigtiff(input_file, output_file, compression='lzw', scale_range=False, remove_temp=True):
    """ 
    Convert a multi-page TIFF to a BigTIFF. 
    BigTIFF is required for files larger than 4GB. 
    LazyTIFF will read these multi-page TIFFs as 4D
    """
    try:
        # Check how much memory will be needed to load the file
        file_size_gb = os.path.getsize(input_file) / 1024**3
        print(f"Memory needed to load file: {file_size_gb:.2f} GB")

        # Check how much memory is available
        available_memory_gb = psutil.virtual_memory().available / 1024**3
        print(f"Memory available: {available_memory_gb:.2f} GB")

        if file_size_gb > available_memory_gb:
            raise MemoryError(f"Memory needed to load file ({file_size_gb:.2f} GB) is greater than available memory ({available_memory_gb:.2f} GB).")
            # Create a Dask array that lazily represents the TIFF file
            loaded_movie = da.from_array(imread(input_file), chunks=(1, -1, -1))
        else:
            # loaded_movie = imread(input_file) #, outtype=np.uint16)

            loaded_movie = load_multi_page_tiff(input_file)

    except Exception as e:
        print(f"Error loading multi-page TIFF file: {e}")
        return
    
    # Check data type and data range
    # At this point it is likely uint16 datatype, but with a uint12 range (original data from Bruker is uint12)
    if loaded_movie.dtype == np.uint16 and loaded_movie.max() <= 4095 and scale_range:
        # Convert range to uint16
        print(f"Images are {loaded_movie.dtype} with range {loaded_movie.min()} - {loaded_movie.max()}.")
        print(f"Set -r flag to False to disable conversion from uint12 to uint16.")
        
        # loaded_movie = loaded_movie * 16 # Replaced with slightly more accurate method below
        scale_factor = (2**16 - 1) / (2**12 - 1)
        # Check how much memory the scaled array will need, in addition to the original array
        scaled_size_gb = loaded_movie.nbytes * scale_factor / 1024**3
        print(f"Memory needed to scale array, to convert to uint16: {scaled_size_gb:.2f} GB")
        print(f"Total memory needed: {file_size_gb + scaled_size_gb:.2f} GB")
        available_memory_gb = psutil.virtual_memory().available / 1024**3
        # print(f"Memory available: {available_memory_gb:.2f} GB")

        if file_size_gb + scaled_size_gb > available_memory_gb/2:
        #     # Cancel the conversion if there is not enough memory
        #     # raise MemoryError(f"Memory needed to scale array ({scaled_size_gb:.2f} GB) is greater than available memory ({available_memory_gb:.2f} GB).")
        #     print(f"Memory needed to scale array ({file_size_gb + scaled_size_gb:.2f} GB) is greater than half available memory ({available_memory_gb/2:.2f} GB).")
        #     # print(f"Set -r flag to False to disable conversion from uint12 to uint16, or increase available memory.")
            print(f"Scaling by chunks out of caution.")
            
            # Define chunk size
            chunk_size = 1000  # TODO: Adjust this value based on the system's memory capacity

            # Calculate the number of chunks
            num_chunks = (len(loaded_movie) - 1) // chunk_size + 1

            # Process each chunk
            print(f"Scaling by chunks: {num_chunks} chunks of {chunk_size} frames.")
            # scaled_movie = np.zeros_like(loaded_movie)
            for i in range(num_chunks):
                start = i * chunk_size
                end = start + chunk_size
                print(f"Processing chunk {i+1}/{num_chunks}")
                print(f"Memory needed to scale array: {loaded_movie[start:end].nbytes * scale_factor / 1024**3:.2f} GB")
                loaded_movie[start:end] = (loaded_movie[start:end] * scale_factor).astype(np.uint16)
                    
        else:
            loaded_movie = (loaded_movie * scale_factor).astype(np.uint16)
        
        print(f"Converted data range: {loaded_movie.min()} - {loaded_movie.max()}")

    else:
        print(f"Images are {loaded_movie.dtype} with range {loaded_movie.min()} - {loaded_movie.max()}.")
        print(f"No scaling of data range requested. \n")

    # Flip each frame of the movie individually (this is done earlier in concat_tiff_files)
    # flipped_movie = np.array([np.flipud(frame) for frame in loaded_movie])
    
    if remove_temp:
        # Remove the original file
        os.remove(input_file)
        print(f"Removed {input_file}")
    
    # Save the movie as a bigtiff      
    imwrite(output_file, loaded_movie, imagej=False, bigtiff=True, metadata=None, dtype=np.uint16, compressionargs={'compression': compression})

    # print(f"BigTIFF file saved as {output_file}")
        
def concatenate_tiff_to_bigtiff(tiff_files, export_path, conversion_step='one-step', compression='lzw', scale_range=False):
    """ Concatenate a list of tiff files into a multi-page BigTIFF""" 
    if os.path.isdir(export_path):
        # Define output file path
        cattiff_file = os.path.join(export_path, 'cat_tiff.tiff')
    elif os.path.isfile(export_path):
        cattiff_file = export_path
        export_path = os.path.dirname(export_path)
    
    multipagetiff_file = cattiff_file.replace('.tiff', '_mpt.tiff')
    bigtiff_file = cattiff_file.replace('.tiff', '_bt.tiff')
    
    # ignore warnings for this operation
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # with suppress_stdout_stderr():
            # with suppress_c_stderr():
            
        # # if two-step conversion is not needed, write to bigtiff directly
        # First concatenate the ome.tif files into a multipage tiff
        try:
            if(is_multi_page_tiff(tiff_files[0])):
                # input files are multitiff 
                print("Input files are multitiff")
                concat_multi_tiff_files(tiff_files, multipagetiff_file)
            else:
                print("Input files are single tiff")
                concat_tiff_files(tiff_files, multipagetiff_file)
            
        except Exception as e:
            print(f"Error concatenating files: {e}")
        else:
            print(f"Done with concatenation.")
            
        # Then convert the multipage tiff to bigtiff
        try: 
            convert_to_bigtiff(multipagetiff_file, bigtiff_file, compression, scale_range)
        except Exception as e:
            print(f"Error converting to BigTIFF: {e}")
            raise
        else:
            print(f"Done with conversion.")
        finally:
            # set warnings back to default
            warnings.resetwarnings()

    print(f"Concatenated {len(tiff_files)} files to BigTIFF {bigtiff_file}.")

    # Double check the output
    reloaded_movie = load_multi_page_tiff(bigtiff_file)

    print(f"Checking BigTIFF file: {bigtiff_file}")
    print(f"Number of pages: {len(reloaded_movie)}")
    print(f"Image shape: {reloaded_movie.shape[1:]}, \n\
        dtype: {reloaded_movie.dtype}, \n\
        range: {reloaded_movie.min()} - {reloaded_movie.max()}\n")
    
def concatenate_tiff_to_hdf5(tiff_files, export_path):
    import caiman as cm
    
    # Check if the export path is a directory
    if os.path.isdir(export_path):
        # Define output file path
        cat_h5_file = os.path.join(export_path, 'cat_tiff.h5')
    elif os.path.isfile(export_path):
        cat_h5_file = export_path
        export_path = os.path.dirname(export_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with suppress_stdout_stderr():
            m = cm.load_movie_chain(tiff_files,outtype=np.ushort)
        # set warnings back to default
        warnings.resetwarnings()
        
    m.save(cat_h5_file,to32=False)
    print(f"Concatenated Tiff saved to {cat_h5_file}")
        
def concatenate_files(input_paths, output_path, regex='*_Ch2_*.ome.tif', method='bigtiff', keep=False, compression='lzw', scale_range=True):
    """ Concatenate a list of tiff files into a multi-page TIFF"""
    if os.path.isdir(input_paths[0]):
        # If the input is a directory, we use the default regex pattern.
        if regex is None:
            print('Default regex pattern is: ' f'{regex}')
            print('Use -p to specify a different pattern.')
            
        # If the input is a single directory, get all the tiff files
        if len(input_paths) == 1:
            tiff_files = sorted(glob.glob(os.path.join(input_paths[0],regex)))
        else:
        # For multiple folders:
            tiff_files = []
            for folder in input_paths:
                tiff_files += sorted(glob.glob(os.path.join(folder,regex)))
            tiff_files.sort()

    else:
        # The input is file list
        tiff_files = input_paths

    # Count the files
    file_count = len(tiff_files)
    print(f"Found {file_count} files to concatenate.")
    
    if output_path is None:
        # Default directory is the input directory
        export_path = os.path.dirname(input_paths[0])
    elif os.path.isfile(output_path) and os.path.exists(output_path) and keep:
        raise FileExistsError('Output file already exists. Aborting.')
    else:
        export_path = output_path
        
    print(f"Saving concatenated file to directory: {export_path}")
    
    # Start the timer
    start_time = time.time()
    
    # Concatenate the tiff files, according to the method
    if method == 'bigtiff':
        concatenate_tiff_to_bigtiff(tiff_files, export_path, compression=compression, scale_range=scale_range)
    elif method == 'hdf5':
        concatenate_tiff_to_hdf5(tiff_files, export_path)

    # Calculate the elapsed time
    elapsed_time = time.time() - start_time

    print(f"Concatenation completed in {elapsed_time:.2f} seconds.\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', nargs='+', help='Input files')
    # Optional arguments
    parser.add_argument('-p', '--pattern', default='*_Ch2_*.ome.tif', help='Regex pattern to match files')
    parser.add_argument('-o', '--output', default=None, help='Output directory or file')
    parser.add_argument('-m', '--method', choices=['bigtiff', 'hdf5'], default='bigtiff', help='Output format')
    parser.add_argument('-c', '--compression', choices=['lzw', 'none'], default='lzw', help='Compression method for BigTIFF')
    parser.add_argument('-s', '--step', choices=['one-step', 'two-step'], default='one-step', help='Conversion steps for BigTIFF')
    parser.add_argument('-r', '--scale_range', action='store_true', default=True, help='Scale range from uint12 to uint16')
    parser.add_argument('-t', '--temp_delete', action='store_true', default=True, help='Delete temporary files')
    parser.add_argument('-k', '--keep', action='store_true', help='Don\'t force overwrite if file exists')
    args = parser.parse_args()
    
    concatenate_files(args.input, args.output, args.pattern, args.method, args.keep, args.compression, args.scale_range)

if __name__ == '__main__':
    main()
