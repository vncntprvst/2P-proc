"""
This script contains functions to compute the movement in depth (z-correlation) and subtract the z-motion from the movie, either on a per-pixel or per-neuron basis.

All other functions are original.
Authors: Vincent Prevosto, Ting Lou, Manuel Levy
Date: 2024-02-21
License: CC-BY-SA 4.0
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set a consistent seed
random_seed = 42
import numpy as np
np.random.seed(random_seed)
import random
random.seed(random_seed)

import time
import os
import glob
import warnings

import numpy as np
import json
import pandas as pd
import gc

from caiman.mmapping import load_memmap

from PIL import Image
from matplotlib.colors import ListedColormap
from matplotlib import cm, patches
import matplotlib.pyplot as plt
from tifffile import TiffFile, TiffWriter, imread

from modules import bruker_concat_tif as ct

from scipy.ndimage import gaussian_filter, map_coordinates, shift, affine_transform, label, find_objects
from scipy.stats import mode, linregress
from scipy.io import savemat

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from tqdm import tqdm
from joblib import Parallel, delayed
import multiprocessing

from sklearn.linear_model import HuberRegressor
from skimage.transform import warp, AffineTransform
from skimage.registration import phase_cross_correlation

import cv2
import argparse

# Type checking imports (not loaded at runtime)
if TYPE_CHECKING:
    from suite2p.registration import rigid

def self_align_zstack(Zstack, method=cv2.MOTION_TRANSLATION):
    # Initialize storage for the aligned images
    aligned_images = np.zeros_like(Zstack)

    # Initialize storage for the shifts
    shifts = np.zeros((Zstack.shape[0], 2), dtype=np.float32)  # Store x, y shifts for each frame

    # Choose the reference frame (e.g., middle frame of the stack)
    reference_image = Zstack[Zstack.shape[0] // 2, :, :]

    # Specify the number of iterations and the termination threshold
    number_of_iterations = 5000
    termination_eps = 1e-10
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, number_of_iterations, termination_eps)

    # Run the registration
    for iz in range(Zstack.shape[0]):
        # Reset the warp matrix for each frame
        if method == cv2.MOTION_HOMOGRAPHY:
            warp_matrix = np.eye(3, 3, dtype=np.float32)
        else:
            warp_matrix = np.eye(2, 3, dtype=np.float32)

        # Perform alignment using the ECC algorithm
        (cc, warp_matrix) = cv2.findTransformECC(reference_image, Zstack[iz, :, :], warp_matrix, method, criteria)

        # Apply the transformation to align the images
        if method == cv2.MOTION_HOMOGRAPHY:
            aligned_images[iz, :, :] = cv2.warpPerspective(Zstack[iz, :, :], warp_matrix, (Zstack.shape[2], Zstack.shape[1]), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        else:
            aligned_images[iz, :, :] = cv2.warpAffine(Zstack[iz, :, :], warp_matrix, (Zstack.shape[2], Zstack.shape[1]), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        
        # Extract and store the shifts
        if method != cv2.MOTION_HOMOGRAPHY:  # Homography involves complex transformations
            dx, dy = warp_matrix[0, 2], warp_matrix[1, 2]
            shifts[iz] = [dx, dy]

    # Return both the aligned images and the shifts
    return aligned_images, shifts
        
def shift_zstack(zshift_params, zstack_in, z_shifted_file):

    """
    Shift images in zstack by dx and dy to compensate for drift due to objective angle.

    Parameters:
    - zshift_params: dictionary containing the parameters for z-shift.
        e.g. zshift_params = {
        "file_name": "zstack_shift.tif",
        "Ch": 2,
        "alpha": 25,
        "beta": 6.5,
        "step": 1,
        "micron_per_pixel": 1.46,
        "Nx": 765,
        "Ny": 765,
        "Nz": 41
        }
    - zstack_in: Path to the folder containing the z-stack images.
        e.g. zstack_in='D:/Analysis_2P/Data/C57_O1M2/10022023/ZSeries-10022023-1300-004'

    Returns:
    - zstack_out: Path to the folder containing the shifted z-stack images.

    """
    # Extract parameters
    Ch = zshift_params['Ch']
    alpha = zshift_params['alpha']
    beta = zshift_params['beta']
    step = zshift_params['step']
    micron_per_pixel = zshift_params['micron_per_pixel']
    Nx = zshift_params['Nx']
    Ny = zshift_params['Ny']
    Nz = zshift_params['Nz']

    # Compute shifts in microns
    dx = np.tan(np.radians(alpha)) * step
    dy = np.tan(np.radians(beta)) * step

    # Initialize empty array for shifted images
    shifted_Zstack = np.zeros((Nz, Ny, Nx))

    # Load and shift images
    # List files with {zstack_in.name}_Cycle00001_Ch{Ch}_{iz + 1:06d}.ome.tif pattern in zstack_in folder
    tif_list = glob.glob(f"{zstack_in}/{zstack_in.name}_Cycle00001_Ch{Ch}_*.ome.tif")
    if len(tif_list) == 1 and ct.is_multi_page_tiff(tif_list[0]):
        # Multi-page tiff format
        with TiffFile(tif_list[0]) as tif:
            for iz, page in enumerate(tif.pages):
                V = page.asarray()
                dxi = dx * (iz - Nz // 2)
                dyi = dy * (iz - Nz // 2)

                # Create a grid for the shifted image
                X, Y = np.meshgrid(np.arange(Nx) * micron_per_pixel - dxi, np.arange(Ny) * micron_per_pixel - dyi)

                # Interpolate the image on the new grid
                coordinates = np.array([Y.ravel() / micron_per_pixel, X.ravel() / micron_per_pixel])
                shifted_Zstack[iz] = map_coordinates(V, coordinates, order=1, mode='nearest').reshape(Ny, Nx)
    else:
        for iz in range(Nz):
            filename_temp = f"{zstack_in}/{zstack_in.name}_Cycle00001_Ch{Ch}_{iz + 1:06d}.ome.tif"
            V = imread(filename_temp)
            # For some images, the header contains information about the whole 41 image stack.
            # If so, imread will erroneously return dimensions as (41, Ny, Nx) instead of (Ny, Nx)
            if V.ndim == 3:
                V = V[0]

            dxi = dx * (iz - Nz // 2)
            dyi = dy * (iz - Nz // 2)

            # Create a grid for the shifted image
            X, Y = np.meshgrid(np.arange(Nx) * micron_per_pixel - dxi, np.arange(Ny) * micron_per_pixel - dyi)

            # Interpolate the image on the new grid
            coordinates = np.array([Y.ravel() / micron_per_pixel, X.ravel() / micron_per_pixel])
            shifted_Zstack[iz] = map_coordinates(V, coordinates, order=1, mode='nearest').reshape(Ny, Nx)
    
    # Normalize to uint16 range, from uint12 range (even though in float64 format at that point)    
    shifted_Zstack = (shifted_Zstack * ((2**16 - 1) / (2**12 - 1))).astype(np.float32)
    
    # print(f"Aligned zstack shape: {shifted_Zstack.shape}, data type: {shifted_Zstack.dtype}, min: {shifted_Zstack.min()}, max: {shifted_Zstack.max()}")
    
    # Refine alignment by registering the z-stack to iself
    registered_Zstack, shifts = self_align_zstack(shifted_Zstack)

    # Clip and convert to uint16
    registered_Zstack = np.clip(registered_Zstack, 0, 2**16-1).astype(np.uint16)
    
    # print(f"Aligned zstack shape: {registered_Zstack.shape}, data type: {registered_Zstack.dtype}, min: {registered_Zstack.min()}, max: {registered_Zstack.max()}")
        
    # # Concatenate the zstack and the aligned zstack horizontally
    # zstack_concat = np.concatenate((np.moveaxis(shifted_Zstack.astype(np.uint16), 0, -1), np.moveaxis(registered_Zstack.astype(np.uint16), 0, -1)), axis=1)
    # #  Save the concatenated zstacks as tiff
    # tiff_save_path = zstack_in / 'zstack_aligned.tif'
    # with TiffWriter(tiff_save_path, bigtiff=True) as tif:
    #     for iz in range(zstack_concat.shape[2]):
    #         tif.write(zstack_concat[:, :, iz].astype(np.uint16), photometric='minisblack') 
    
    zstack_out = zstack_in / z_shifted_file
    with TiffWriter(zstack_out, bigtiff=True) as writer:
        for iz in range(Nz):
            writer.write(registered_Zstack[iz])
            
    print("Shifted and self-registered z-stack saved.")
    
    return zstack_out            

def default_zcorr_params():
    return {
        "smooth_sigma": 1.15,                   
        "pre_smooth": 0,             
        "spatial_hp_reg": 42,       
        "spatial_taper": 40,        
        "maxregshift": 0.1,        
        "smooth_sigma_time": 0,      
        "nonrigid": False
    }
    
def compute_zcorr_for_frame(nfr, Treg, refAndMasks, ops):
    """
    Compute the z-correlation for a single frame, using phase correlation between the current frame and the cross-correlation reference image.
    
    Parameters:
    - nfr: int, the frame number
    - Treg: 3D numpy array, the registered movie
    - refAndMasks: list of tuples, each tuple containing the maskMul, maskOffset, and cfRefImg
    - ops: dictionary, the parameters for z-correlation-
    
    Returns:
    - yshift: float, the y-shift
    - xshift: float, the x-shift
    - zcorr: float, the z-correlation
    """
    data = Treg[nfr:nfr + 1]  # Get the current frame
    yshift = np.zeros((len(refAndMasks), 1), np.int32)
    xshift = np.zeros((len(refAndMasks), 1), np.int32)
    zcorr = np.zeros((len(refAndMasks), 1), np.float32)
    
    for z, ref in enumerate(refAndMasks):
        maskMul, maskOffset, cfRefImg = ref
        cfRefImg = cfRefImg.squeeze()
        
        # _, _, zcorr[z] = rigid.phasecorr(
        yshift[z], xshift[z], zcorr[z] = rigid.phasecorr(
            data=rigid.apply_masks(data=data, maskMul=maskMul, maskOffset=maskOffset),
            cfRefImg=cfRefImg,
            maxregshift=ops["maxregshift"],
            smooth_sigma_time=ops["smooth_sigma_time"],
        )

    # return zcorr
    return yshift, xshift, zcorr

def compute_zcorrel_for_frame(frame, Z_stack, compute_shifts=False):
    """
    Compute correlation between the current frame and each frame in the Z-stack
    """
    # Initialize arrays
    zcorr = np.zeros(Z_stack.shape[0], np.float32)
    if compute_shifts:
        yshift = np.zeros(Z_stack.shape[0], np.float32)
        xshift = np.zeros(Z_stack.shape[0], np.float32)
    
    for z_idx in range(Z_stack.shape[0]):
        if compute_shifts:
            shift_values, _, _ = phase_cross_correlation(frame,
                                                Z_stack[z_idx],
                                                upsample_factor=100)
            yshift[z_idx] = shift_values[0]
            xshift[z_idx] = shift_values[1]
            
            # Apply the computed shifts to align the z-stack frame with the current frame
            shifted_z_frame = shift(Z_stack[z_idx], shift=(shift_values[0], shift_values[1]), mode='constant', cval=0.0)

            # Compute correlation coefficient after alignment
            zcorr[z_idx] = np.corrcoef(frame.ravel(), shifted_z_frame.ravel())[0, 1]
            
        else:
            # Compute correlation coefficient without computing shifts
            zcorr[z_idx] = np.corrcoef(frame.ravel(), Z_stack[z_idx].ravel())[0, 1]
            
    if compute_shifts:
        return zcorr, yshift, xshift
    else: 
        return zcorr       
    

def compute_zcorrel(zstack_file, movie_mmap_path, smooth_sigma=3, return_shifts=False):
    """
    Computes correlation and x/y shifts in z for each frame in the movie, using the anatomical z-stack as reference.
    Computes z-position for each frame by finding the z-stack frame with the highest correlation.
    """
    #####################################
    ## 1. Load and prepare the z-stack ##
    #####################################
    
    # Load the z-stack and stack frames into a 3D array
    with TiffFile(zstack_file) as zstack_tiff_file:
        pages = [page.asarray() for page in zstack_tiff_file.pages]
    Z_stack = np.stack(pages, axis=0).astype(np.float32)
    
    # Flip Z_stack to match the orientation of the movie
    Z_stack = np.flip(Z_stack, axis=1)
    
    # Convert to float (not strictly necessary, but better be consistent with the movie data type)
    Z_stack = Z_stack.astype(np.float32)

    ###################################
    ## 2. Load and prepare the movie ##
    ################################### 
    
    # Load the movie
    movie_16bit, dims, T = load_memmap(movie_mmap_path)
    T_series = np.reshape(movie_16bit.T, [T] + list(dims), order='F')
    
    # Get the number of frames and the size of the movie
    nFrames, Ny, Nx = T_series.shape
    
    # Check that Z-stack matches the size of the movie
    if Z_stack.shape[1] != Ny or Z_stack.shape[2] != Nx:
        print("Z-stack dimensions do not match the movie dimensions.")
        return None
    
    ########################################################
    ## 3. Register the z-stack to the movie’s average FOV ##
    ########################################################
    
    # Zstack_0 is the frame in the z-stack with the best correlation with the mean of the T-series
    # To find it, we first realign each frame of the zstack to the mean of the T-series

    # Compute a mean image of the movie
    fov_image = np.mean(T_series, axis=0)

    # Find the best z-plane vs. the FOV

    #     For each plane z, compute the rigid shift needed to align Z_stack[z] with fov_image using phase_cross_correlation.
    #     Apply the shift, then compute the correlation coefficient.
    #     Select the plane with the highest correlation as the “best” reference plane Zstack_0.
    
    correlations = np.zeros(Z_stack.shape[0], np.float32)
    for z_idx in range(Z_stack.shape[0]):
        # Perform z-stack image registration
        shift, _ , _ = phase_cross_correlation(Z_stack[z_idx], fov_image, upsample_factor=100)
        print(f"Shift for z-stack frame {z_idx}: {shift}")
        # Create the transformation matrix (for translation only)
        tform = AffineTransform(translation=(shift[1], shift[0]))

        # Translate z-stack frames to minimize shift with mean of registered tseries frames (FOV)
        shifted_z_frame = warp(np.float32(Z_stack[z_idx, :, :]), tform)
        smoothed_shifted_z_frame = gaussian_filter(shifted_z_frame, sigma=1)

        # compute correlation coefficient after alignment
        correlations[z_idx] = np.corrcoef(fov_image.ravel(), smoothed_shifted_z_frame.ravel())[0, 1]
        print(f"Correlation for z-stack frame {z_idx}: {correlations[z_idx]}")

    best_z_index = np.argmax(correlations)
    Zstack_0 = Z_stack[best_z_index]

    # Print the index of the frame in the z-stack
    print(f'The frame in the z-stack with the best correlation is frame {best_z_index}')

    # Apply the best-plane alignment to the whole stack
    # We perform image registration again, but just between the best frame (reference) in the z-stack and the FOV
    shift, _ , _ = phase_cross_correlation(Zstack_0, fov_image, upsample_factor=100)

    # Create the transformation matrix (for translation only)
    tform = AffineTransform(translation=(shift[1], shift[0]))

    # Translate z-stack frames to minimize shift with mean of registered tseries frames (FOV)
    Zstack_reg = np.zeros_like(Z_stack)
    for iz in range(Z_stack.shape[0]):
        Zstack_reg[iz, :, :] = warp(np.float32(Z_stack[iz, :, :]), tform)
    
    ###################################################
    ## 4. Compute z-correlation for each movie frame ##
    ###################################################
    
    # For each frame in the movie:

    # Compare it to each plane z in the registered z-stack.
    # If return_shifts=True, use phase_cross_correlation to find sub-pixel x–y shifts and align that z-plane.
    # Compute the correlation coefficient of the aligned plane vs. the frame.
    # Store the correlation in zcorr[z, frame].
    
    # Initialize arrays
    zcorr = np.zeros((Z_stack.shape[0], nFrames), np.float32)
    if return_shifts:
        yshift = np.zeros((Z_stack.shape[0], nFrames), np.float32)
        xshift = np.zeros((Z_stack.shape[0], nFrames), np.float32)
    
    del Z_stack, Zstack_0, shift
    gc.collect()
    
    t0 = time.time()
     
    smoothed_f_func = gaussian_filter(T_series, sigma=[0, smooth_sigma, smooth_sigma])
    smoothed_z_stack = gaussian_filter(Zstack_reg, sigma=[0, smooth_sigma, smooth_sigma])
                   
    # Use Parallel 
    results = Parallel(n_jobs=-1)(
        delayed(compute_zcorrel_for_frame)(frame, smoothed_z_stack, compute_shifts=return_shifts)
        for frame in tqdm(smoothed_f_func, desc="Computing z-correlations")
    )
                
    if return_shifts:    
        for frameNum, result in enumerate(results):
            zcorr[:, frameNum], yshift[:, frameNum], xshift[:, frameNum]= result
    else:
        for frameNum, result in enumerate(results):
            zcorr[:, frameNum] = result
    
    # Kill all LokyProcess workers (Windows only)
    if os.name == 'nt':
        for p in multiprocessing.active_children():
            if 'LokyProcess' in p.name:
                p.terminate()
    
    print (f"Correlations for {nFrames} frames computed in {time.time() - t0:.2f} sec.")               

    # Get the optimal z position for each frame
    zpos = np.argmax(gaussian_filter(zcorr, sigma=3, axes=0), axis=0)
    zpos = zpos.astype(np.uint16)
    
    ###################################
    ## 5. Return correlation results ##
    ###################################
    
    # The function returns a dictionary containing:

    #     zcorr: A 2D array [z, frame] of correlation coefficients.
    #     zpos: The chosen best z-plane per frame.
    #     (Optional) yshift and xshift arrays if return_shifts=True.
    
    # Save z-correlation variables to a file
    if return_shifts:
        z_correlation = {
            'yshift': yshift.astype(np.float32),
            'xshift': xshift.astype(np.float32),
            'zcorr': zcorr.astype(np.float32),
            'zpos': zpos.astype(np.uint16)
        }
    else:
        z_correlation = {
            'zcorr': zcorr.astype(np.float32),
            'zpos': zpos.astype(np.uint16)
        }

    np.savez(movie_mmap_path.parents[1] / "z_correlation.npz", **z_correlation)

    del zcorr, zpos, smoothed_f_func, smoothed_z_stack, T_series, movie_16bit
    gc.collect()
    
    return z_correlation

def _get_suite2p_rigid():
    """Lazy import of Suite2p registration functions"""
    try:
        from suite2p.registration import rigid
        return rigid
    except ImportError:
        raise ImportError(
            "Suite2p required for this function. "
            "Install with: pip install suite2p"
        )

def compute_zcorrel_suite2p(zstack_file, movie_mmap_path, z_corr_params=None, smoothing=False, smooth_sigma=1, return_shifts=False):
    """
    Computes correlation and x/y shifts in z for each frame in the movie, using the anatomical z-stack as reference.
    Computes z-position for each frame by finding the z-stack frame with the highest correlation.
    
    The function is adapted from Suite2P's function `compute_zpos`:
    https://github.com/MouseLand/suite2p/blob/193e7f1f656bfbd1c100eb51411737c80f54ac3c/suite2p/registration/zalign.py#L125
    Copyright © 2023 Howard Hughes Medical Institute, Authored by Carsen Stringer and Marius Pachitariu.
    """
    rigid = _get_suite2p_rigid()
    
    # Load the z-stack and stack frames into a 3D array
    zstack_tiff_file = TiffFile(zstack_file)
    Z_stack = []
    for page in zstack_tiff_file.pages:
        Z_stack.append(page.asarray())
    Z_stack = np.stack(Z_stack, axis=0)
    zstack_tiff_file.close()
    
    # Flip Z_stack to match the orientation of the movie
    Z_stack = np.flip(Z_stack, axis=1)

    # Load the movie
    movie_16bit, dims, T = load_memmap(movie_mmap_path)
    T_series = np.reshape(movie_16bit.T, [T] + list(dims), order='F')
    
    # Get the size of the movie
    Ny, Nx = T_series.shape[1], T_series.shape[2]
    
    # Check that Z-stack matches the size of the movie
    if Z_stack.shape[1] != Ny or Z_stack.shape[2] != Nx:
        print("Z-stack dimensions do not match the movie dimensions.")
        return None
            
    # Get the number of frames in the movie
    nFrames, _, _ = T_series.shape
    
    # Initialize arrays
    # if return_shifts:
    yshift = np.zeros((Z_stack.shape[0], nFrames), np.float32)
    xshift = np.zeros((Z_stack.shape[0], nFrames), np.float32)
    zcorr = np.zeros((Z_stack.shape[0], nFrames), np.float32)
    
    t0 = time.time()
    
    # Set z_corr_params to default if not provided
    if z_corr_params is None:
        ops = default_zcorr_params()
    else:     
        ops = z_corr_params
    ops["nonrigid"] = False
    
    refAndMasks = []
    for Z in Z_stack:
        maskMul, maskOffset = rigid.compute_masks(
            refImg=Z,
            maskSlope=3 * ops["smooth_sigma"],
        )
        # Compute the cross-correlation reference image
        cfRefImag = rigid.phasecorr_reference(refImg=Z, smooth_sigma=ops["smooth_sigma"])
        # Add a new axis to cfRefImag
        cfRefImag = cfRefImag[np.newaxis, :, :]
        # Append the maskMul, maskOffset, and cfRefImag to refAndMasks
        refAndMasks.append((maskMul, maskOffset, cfRefImag))
  
    # # Compute zcorr for each frame
    # with concurrent.futures.ThreadPoolExecutor() as executor:
    #     # Submit the compute_zcorr_for_frame function to the executor
    #     futures = [executor.submit(compute_zcorr_for_frame, nfr, Treg, refAndMasks, ops) for nfr in range(nFrames)]
    #     # As the threads complete, store the results in the yshift, xshift, and zcorr arrays
    #     for i, future in enumerate(tqdm(concurrent.futures.as_completed(futures), total=nFrames, desc="Processing frames")):
    #         yshift_res, xshift_res, zcorr_res = future.result()
    #         yshift[:, i], xshift[:, i], zcorr[:, i] = (
    #             np.asarray(yshift_res, dtype=np.int32).squeeze(),
    #             np.asarray(xshift_res, dtype=np.int32).squeeze(),
    #             np.asarray(zcorr_res, dtype=np.float32).squeeze()
    #         )
    # print (f"{nFrames} frames processed in {time.time() - t0:.2f} sec.")
    
    # Use joblib.Parallel 
    results = Parallel(n_jobs=-1)(delayed(compute_zcorr_for_frame)(nfr, T_series, refAndMasks, ops) for nfr in tqdm(range(nFrames), desc="Processing frames"))

    # As the threads complete, store the results in the yshift, xshift, and zcorr arrays
    for i, result in enumerate(results):
        yshift_res, xshift_res, zcorr_res = result
        yshift[:, i], xshift[:, i], zcorr[:, i] = (
            np.asarray(yshift_res, dtype=np.int32).squeeze(),
            np.asarray(xshift_res, dtype=np.int32).squeeze(),
            np.asarray(zcorr_res, dtype=np.float32).squeeze()
        )

    # Kill all LokyProcess workers (Windows only)
    if os.name == 'nt':
        for p in multiprocessing.active_children():
            if 'LokyProcess' in p.name:
                p.terminate()
    
    print (f"{nFrames} frames processed in {time.time() - t0:.2f} sec.")
                    
    # # Without threading
    # for frameNum in range(nFrames):
    #     yshift_res, xshift_res, zcorr_res = compute_zcorr_for_frame(frameNum, T_series, refAndMasks, ops)
    #     zcorr[:, frameNum] = zcorr_res.squeeze()
    #     yshift[:, frameNum] = yshift_res.squeeze()
    #     xshift[:, frameNum] = xshift_res.squeeze()
    #     if frameNum % 10 == 0:
    #         print(f"{frameNum}/{nFrames} frames, {time.time() - t0:.2f} sec.")            
        
    # print(f"{frameNum}/{nFrames} frames, {time.time() - t0:.2f} sec.")

    # Get the optimal z position for each frame
    zpos = np.argmax(gaussian_filter(zcorr, sigma=3, axes=0), axis=0)
    zpos = zpos.astype(np.uint16)
    
    # import matplotlib.pyplot as plt
    # plt.figure()
    # plt.plot(zpos)
    # plt.xlabel('Frames')
    # plt.ylabel('Z Position')
    # plt.title('Z Position over Frames')
    # plt.grid(True)
    # plt.savefig(movie_mmap_path.parents[1] / "z_drift_s3.png")
    
    # Save z-correlation variables to a file in the mesmerize folder, preserving data types and accuracy
    if return_shifts:
        z_correlation = {
            'yshift': yshift.astype(np.int32),
            'xshift': xshift.astype(np.int32),
            'zcorr': zcorr.astype(np.float32),
            'zpos': zpos.astype(np.uint16)
        }
        warnings.warn("compute_zcorrel_suite2p returns x/y shifts as integers. Use compute_zcorrel for float x/y shifts.")
    else:
        z_correlation = {
            'zcorr': zcorr.astype(np.float32),
            'zpos': zpos.astype(np.uint16)
        }
                    
    np.savez(movie_mmap_path.parents[1] / "z_correlation.npz", **z_correlation)

    return z_correlation

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
    gc.collect()
    
    # Add the path to the memmap file to the memmap_paths.json file
    memmap_paths = {'zcorr_movie_path': str(movie_path)}
    with open(movie_path.parent / 'memmap_paths.json', 'w') as f:
        json.dump(memmap_paths, f)
        
    return movie_path


def patch_regress(frame_data, shift_patches=False):
    """
    Calculate the linear least-squares regression between the F_func movie and the z-stack 
    for each patch at several depths around zpos.
    
    Inputs: 
    - frame_data: tuple containing the frame number, the frame data, the z-stack, 
                    the dimensions of the movie, the patch size,
                    the step size, the current zpos, and the valid indices.
    
    Outputs:
    - results: list of dictionaries containing the r_squared, slope,
                intercept, frame number, patch number, patch x/y limits,
                patch z index, and patch z position. 
    """
    
    # np.seterr(over='raise')
        
    # fram_start_time = time.time()
    
    if shift_patches:
        print("Shifting patches option is not tested yet.")

    frameNum, frame_F_func, Zstack, Nx, Ny, patch_size, step_size, current_zpos, valid_indices = frame_data
        
    patch_regress_results = []
        
    # Clip Z_frame_shifted to uint16 range
    Z_frame_clipped = np.clip(Zstack, 0, 2**16-1)
        
    # Initialize patch number
    patch_num = -1
    
    # Loop over patches, moving vertically (along columns) first, then horizontally (along rows)    
    for i in range(0, Nx, step_size[1]):
        for j in range(0, Ny, step_size[0]):
            # Allow for a last partial patch on the right and bottom borders, but not more
            if i + patch_size[1] > Nx and patch_size_x < patch_size[1] and patch_size_y < patch_size[0]:
                continue 
            if j + patch_size[0] > Ny and patch_size_y < patch_size[0]:
                continue 
            # Adjust the patch size for patches on the bottom and right borders
            patch_size_x = patch_size[1] if i + patch_size[1] <= Nx else Nx - i
            patch_size_y = patch_size[0] if j + patch_size[0] <= Ny else Ny - j

            # Get the patch from the frame data
            T_patch = frame_F_func[j:j+patch_size_y, i:i+patch_size_x, ].ravel()
            # Increment patch number
            patch_num += 1
            
            # print(f"Frame {frameNum}, Patch {patch_num}, Patch Size: {patch_size_y}x{patch_size_x}")
            
            if shift_patches:
                # Define the maximum shift in pixels (both directions)
                max_shift = 3
                best_corr = -np.inf
                best_shift = (0, 0)
    
            # Initialize results list
            patch_results = []
            # Loop over valid depth indices
            for z_idx in valid_indices:
                Z_patch = Z_frame_clipped[j:j+patch_size_y, i:i+patch_size_x, z_idx].ravel()
                
                if T_patch.size == Z_patch.size:
                    # If shift_patches is True, find the best shift for T_patch
                    if shift_patches:
                        # Brute-force search for the best (dy, dx) shift that maximizes correlation
                        for dy in range(-max_shift, max_shift + 1):
                            for dx in range(-max_shift, max_shift + 1):
                                shifted_img = np.roll(T_patch, shift=(dy, dx), axis=(0, 1))
                                # Compute correlation coefficient between shifted T_patch and Z_patch
                                corr = np.corrcoef(shifted_img.ravel(), Z_patch.ravel())[0, 1]
                                if corr > best_corr:
                                    best_corr = corr
                                    best_shift = (dy, dx)
                        
                        # Apply the best shift to T_patch_img and flatten it for regression
                        T_patch = np.roll(T_patch, shift=best_shift, axis=(0, 1)).ravel()
    
                    _, _, r_value, _, _ = linregress(T_patch, Z_patch)
                    # try:
                    patch_results.append({
                    'r_squared': r_value**2, 'Z_patch': Z_patch, 
                    'frame_num': frameNum, 'patch_number': patch_num,
                    'patch_x_lims': [i, i+patch_size_x], 'patch_y_lims': [j, j+patch_size_y],
                    'patch_z_idx': int(z_idx) - int(current_zpos), 'patch_z_pos': z_idx
                    })
                    if shift_patches:
                        # Append the best shift to the results
                        patch_results[-1]['best_shift'] = best_shift
                        
                    # not needed: 'slope': slope, 'intercept': intercept,
                    
                    # except FloatingPointError:
                    #     print("Overflow Error")
                    #     # print(f"z_idx: {z_idx}, current_zpos: {current_zpos}")
                        
            # Smooth R^2 values over valid depth indices
            r_squares = [result['r_squared'] for result in patch_results]
            r_squares = gaussian_filter(r_squares, sigma=1)
            # Get the max R^2 value's index
            max_r_square_idx = np.argmax(r_squares)
            # Append the result corresponding to the max R^2 value to patch_regress_results
            patch_regress_results.append(patch_results[max_r_square_idx])                      
                        
    # frame_end_time = time.time()
    # print(f"Frame {frameNum} processed in {frame_end_time - fram_start_time:.2f} seconds")
            
    return patch_regress_results


def calculate_zones(patch_correlations, Ny, Nx):
    """
    Find zones (i.e., how patches overlap) in the patch_correlations table.
    
    Inputs:
    - patch_correlations: DataFrame containing the patch correlations.
    - Ny: int, the number of columns in the movie.
    - Nx: int, the number of rows in the movie.
    
    Outputs:
    - zone_pattern_contig: 2D numpy array containing the zone pattern with continuous zone IDs.
    - zone_pattern: 2D numpy array containing the zone pattern with non-contiguous unique zone IDs, for display purposes.   
    """
    start_time = time.time()
    
    # Initialize a mask for zone calculation
    mask = np.zeros((Ny, Nx), dtype=int)

    # Use the first frame's patches to define zones
    first_frame_patches = patch_correlations[patch_correlations['frame_num'] == patch_correlations['frame_num'].min()]
    for _, row in first_frame_patches.iterrows():
        x_start, x_end = row['patch_x_lims']
        y_start, y_end = row['patch_y_lims']
        mask[y_start:y_end, x_start:x_end] += 1
    
    # Label zones based on overlapping patches. Assign a unique number to each zone

    # Initialize the zone_pattern array to store zone identifiers
    zone_pattern = np.zeros((Ny, Nx), dtype=int)

    # Change the mask values from 4 to 3 (even to odd)
    mask = np.where(mask == 4, 3, mask)
    # Process for odd values (mask values that are odd become 1, others 0)
    binary_mask_odd = (mask % 2 == 1).astype(int)
    labeled_zones_odd, num_zones_odd = label(binary_mask_odd)

    # Assign unique labels to zone_pattern for odd zones
    zone_id_offset = 0  # Start zone IDs from 1 for odd zones
    for i in range(1, num_zones_odd + 1):
        zone_pattern[labeled_zones_odd == i] = zone_id_offset + i

    # Update the offset for even zones to continue unique labeling
    zone_id_offset += num_zones_odd

    # Process for even values (mask values that are even and non-zero become 1, others 0)
    binary_mask_even = ((mask % 2 == 0) & (mask != 0)).astype(int)
    labeled_zones_even, num_zones_even = label(binary_mask_even)

    # Assign unique labels to zone_pattern for even zones
    for i in range(1, num_zones_even + 1):
        zone_pattern[labeled_zones_even == i] = zone_id_offset + i

    # Flatten the array column-wise
    zone_pattern_col_flat = zone_pattern.flatten(order='F')

    # Get the unique zones and their unique indices
    _, inverse_indices = np.unique(zone_pattern_col_flat, return_inverse=True)
    unique_indices = pd.unique(inverse_indices) + 1
    
    # Re-label zones to have continuous IDs
    zone_pattern_contig = np.zeros_like(zone_pattern, dtype=np.uint16)
    for new_id, zone_id in enumerate(unique_indices):
        zone_pattern_contig[zone_pattern == zone_id] = new_id

    print(f"Patches divided into zones in {time.time() - start_time:.2f} seconds")
        
    return zone_pattern_contig, zone_pattern

def make_composite_f_anat(patch_correlations, labeled_zones):
    """
    Create a composite anatomical image from the patch correlations DataFrame.
    
    Inputs:
    - patch_correlations_df: DataFrame containing the patch correlations.
    - labeled_zones: 2D numpy array containing the labeled zones.
    
    Outputs:
    - F_anat_non_rigid: 3D numpy array containing the composite anatomical image.
    - zone_df: DataFrame containing the zone data.
    """
    
    fields = ['r_squared', 'patch_number', 'patch_z_pos', 'Z_patch'] #'patch_x_shift', 'patch_y_shift',
    
    # start_time = time.time()
    
    zone_data = []
    
    F_anat_non_rigid = np.zeros((len(np.unique(patch_correlations['frame_num'])), *labeled_zones.shape))

    # Iterate over frames
    for frame_idx, (frame_num, group) in enumerate(patch_correlations.groupby('frame_num')): 
        # `frame_num` is the current frame number
        # `group` is a DataFrame containing all rows for `frame_num`       

        sums = {field: np.zeros((np.max(labeled_zones)+1,)) for field in fields if field != 'Z_patch'}
        sums['Z_patch'] = {zone_id: [] for zone_id in np.unique(labeled_zones)}

        count = np.zeros((np.max(labeled_zones)+1,))
        
        composite_f_anat_frame = np.zeros(labeled_zones.shape)

        # Populate sums and counts per zone                
        for _, row in group.iterrows():
            # `index` is the index of the row in `patch_correlations_df`
            # `row` is a Series containing the data for the current row 
            
            x_start, x_end = row['patch_x_lims']
            y_start, y_end = row['patch_y_lims']
            
            # Extract the patch area from the labeled_zones
            patch_2D = row['Z_patch'].reshape(y_end - y_start, x_end - x_start)
            
            patch_zone_labels = labeled_zones[y_start:y_end, x_start:x_end]
            zone_ids = np.unique(patch_zone_labels)

            for zone_id in zone_ids:
                # Find coordinates of the current zone_id within the patch
                zone_mask = (patch_zone_labels == zone_id)
                # Get bounding box of the zone for 2d zone_specific_patch
                rows, cols = np.where(zone_mask)
                min_row, max_row = rows.min(), rows.max()
                min_col, max_col = cols.min(), cols.max()
                for field in fields:
                    if field == 'Z_patch':
                        # Extract the part of Z_patch that corresponds to the current zone_id.
                        # This returns a 1D array, ordered row-wise.
                        # zone_specific_patch = patch_2D[zone_mask]
                        #  in 2D for sanity check
                        zone_specific_patch = patch_2D[min_row:max_row+1, min_col:max_col+1]
                        sums[field][zone_id].append(zone_specific_patch)
                    else:
                        sums[field][zone_id] += row[field]
                count[zone_id] += 1

        # Calculate averages for each zone            
        averages = {field: np.zeros((np.max(labeled_zones)+1,)) for field in fields if field != 'Z_patch'}
        averages['Z_patch'] = {}

        for field in sums:
            if field == 'Z_patch':
                for zone_id, arrays in sums[field].items():
                    try:
                        if arrays:
                            averages[field][zone_id] = np.mean(arrays, axis=0)
                    except Exception as e:
                        # print(e)
                        print(f"Frame {frame_num}, Zone {zone_id}")
            else:
                averages[field] = np.divide(sums[field], count, where=(count > 0))

        # Collect data per zone
        unique_zones = np.unique(labeled_zones)
        for zone_id in unique_zones:
            zone_info = {'frame_num': frame_num, 'zone_id': zone_id}
            if count[zone_id] > 0:
                y_indices, x_indices = np.where(labeled_zones == zone_id)
                y_min, y_max = y_indices.min(), y_indices.max() + 1
                x_min, x_max = x_indices.min(), x_indices.max() + 1
                for field in fields[:-1]:
                    zone_info[field] = averages[field][zone_id]
                zone_data.append(zone_info)
                # reshape Zpatch to 2D and insert into composite_f_anat_frame               
                if 'Z_patch' in averages and zone_id in averages['Z_patch']:
                    # zone_2D = averages['Z_patch'][zone_id].reshape((y_max - y_min, x_max - x_min))
                    composite_f_anat_frame[y_min:y_max, x_min:x_max] = averages['Z_patch'][zone_id]

                # When this is the first zone in the first frame, print some info
                # if frame_idx == 0 and zone_id == unique_zones[0]:
                #     print(f"Frame {frame_num}, Zone {zone_id}:")
                #     print(f"  R^2: {averages['r_squared'][zone_id]:.4f}")
                #     print(f"  Patch number: {averages['patch_number'][zone_id]}")
                #     print(f"  Patch z position: {averages['patch_z_pos'][zone_id]}")
                #     print(f"  Patch x limits: {x_min}, {x_max}")
                #     print(f"  Patch y limits: {y_min}, {y_max}")
                #     print(f"  Range of values: {np.min(averages['Z_patch'][zone_id]):.2f} to {np.max(averages['Z_patch'][zone_id]):.2f}")
        
        F_anat_non_rigid[frame_idx, :, :] = composite_f_anat_frame
    
    # print(f"Zone data computed in {time.time() - start_time:.2f} seconds")   
    
    zone_df = pd.DataFrame(zone_data)  
    
    return F_anat_non_rigid, zone_df

def format_patch_correl_for_mat(zone_df):
    
    # Get fields from the dataframe
    fields = zone_df.columns[zone_df.columns != 'zone_id']
    
    # Pivot to create a 3D structure: zones * fields * frames
    data_3d = zone_df.set_index(['zone_id', 'frame_num']).unstack(fill_value=0).to_numpy()
    data_3d = data_3d.reshape((len(zone_df['zone_id'].unique()), len(fields), -1))
    
    # Create descriptors for each field
    field_descriptors = {field: 'Average ' + field for field in fields}
    
    # Prepare data for MAT file
    mat_data = {
        'zone_data': data_3d,
        'descriptors': field_descriptors
    }
    
    return mat_data

def compute_zone_mean_fluorescence(fov_image, labeled_zones, zone_data):
    """
    Loop over each zones' pixel region and get the average fluorescence value for each zone from the FOV image
    """
    zone_mean_fluorescence = []
    zone_rsquare = []

    for zone_id in range(np.max(labeled_zones) + 1):
        zone_indices = np.where(labeled_zones == zone_id)
        # Get the mean fluorescence value for that zone
        zone_mean_fluorescence.append(np.mean(fov_image[zone_indices]))
        # Get the R2 value for that zone
        zone_rsquare.append(zone_data[zone_data['zone_id'] == zone_id]['r_squared'].values[0])
        
    return zone_mean_fluorescence, zone_rsquare

def patch_correl_plots(patch_correlations_df, labeled_zones, zone_df, zone_pattern, fov_image, z_correlation, export_path):
    """
    Summary plots
    Plot the zone pattern, the R^2 heatmap, the distribution of patch z indices, 
    the distribution of R^2 values from compute_zcorrel, the R^2 histogram, 
    the curve of average R2 values as a function of fluorescence, and an example zone.
    """

    # Create subplots
    fig, ax = plt.subplots(2, 4, figsize=(20, 10))

    # Plot the zone pattern
    ax[0, 0].imshow(zone_pattern, cmap='plasma')
    ax[0, 0].set_xticks([])
    ax[0, 0].set_yticks([])
    ax[0, 0].set_title('Patch overlap zone pattern')
    
    # Plot the R^2 heatmap
    # plot zone_data's average r_squared values as a heatmap
    dim_num_zones = int(np.sqrt(np.max(labeled_zones) + 1))

    # Get zone_df data corresponding to the first frame
    frame_num = zone_df['frame_num'].min()
    zone_data = zone_df[zone_df['frame_num'] == frame_num]

    r_squared_values = zone_data['r_squared'].values.reshape((dim_num_zones, dim_num_zones), order='F')
    im = ax[1, 0].imshow(r_squared_values, cmap='viridis')
    fig.colorbar(im, ax=ax[1, 0])
    ax[1, 0].set_title(f"Average $R^2$ values per zone for frame {frame_num}")

    # Plot distribution of correlation for all patches across depth
    patch_z_idx = patch_correlations_df['patch_z_idx']
    bin_num = len(np.unique(patch_z_idx))
    bin_edges = np.arange(-bin_num/2, bin_num//2 + 1, 1)
    ax[0, 1].hist(patch_z_idx, bins=bin_edges, edgecolor='black')
    ax[0, 1].set_xlabel('Patch z index')
    ax[0, 1].set_ylabel('Frequency')
    ax[0, 1].set_title('Distribution of patch z indices, w/r to zpos')
    ax[0, 1].set_xticks(np.arange(-bin_num//2 + 1, bin_num//2 + 1, 1))

    # Plot the distribution of R^2 values from compute_zcorrel
    zcorrel = z_correlation['zcorr']
    max_vals = np.max(zcorrel, axis=0)
    rsquare_corr = np.square(max_vals)
    ax[1, 1].hist(rsquare_corr, bins=50, edgecolor='black')
    ax[1, 1].set_xlabel('$R^2$ value')
    ax[1, 1].set_ylabel('Frequency')
    ax[1, 1].set_title('Distribution of $R^2$ values from compute_zcorrel (whole frames)')

    # Plot the R2 histogram
    patch_rsquare_vals = patch_correlations_df['r_squared']
    ax[0, 2].hist(patch_rsquare_vals, bins=50, label='R-squared', edgecolor='black', color='blue') #alpha=0.5
    ax[0, 2].set_xlabel('$R^2$ value')
    ax[0, 2].set_ylabel('Frequency')
    ax[0, 2].set_title('Distribution of $R^2$ values for patches')

    # Plot the curve of average R2 values as a function of fluorescence
    zone_mean_fluorescence, zone_rsquare = compute_zone_mean_fluorescence(fov_image, labeled_zones, zone_df)
    ax[1, 2].scatter(zone_mean_fluorescence, zone_rsquare, alpha=0.5, edgecolor='black', s=10, facecolors='none', marker='o')
    ax[1, 2].set_xlabel('Average Fluorescence')
    ax[1, 2].set_ylabel('Average $R^2$')
    ax[1, 2].set_title('Average $R^2$ vs Average Fluorescence')

    # Plot an example zone
    zone_id = np.argmax(zone_mean_fluorescence)
    zone_indices = np.where(labeled_zones == zone_id)
    min_row, max_row = np.min(zone_indices[0]), np.max(zone_indices[0])
    min_col, max_col = np.min(zone_indices[1]), np.max(zone_indices[1])
    ax[0, 3].imshow(fov_image, cmap='gray')
    rect = patches.Rectangle((min_col, min_row), max_col-min_col+1, max_row-min_row+1, linewidth=1, edgecolor='r', facecolor='none')
    ax[0, 3].add_patch(rect)
    ax[0, 3].axis('off')
    ax[0, 3].set_title(f"FOV with Zone {zone_id} Highlighted")

    # Plot the zone fluorescence
    zone_fluorescence = fov_image[zone_indices]
    fluorescence_image = np.zeros((max_row - min_row + 1, max_col - min_col + 1))
    for i, row in enumerate(zone_indices[0]):
        col = zone_indices[1][i]
        fluorescence_image[row - min_row, col - min_col] = zone_fluorescence[i]
    ax[1, 3].imshow(fluorescence_image, cmap='gray')
    ax[1, 3].axis('off')
    ax[1, 3].set_title(f"Zone {zone_id} Fluorescence")
    
    # Save the figure
    plt.tight_layout()
    plot_export_path = export_path / 'plots'
    plot_export_path.mkdir(parents=True, exist_ok=True)
    plt.savefig(plot_export_path / 'patches_summary_plots.png') 
    
    # Close the figure
    plt.close(fig)
    
    # Plot the z-position over frames
    fig_zpos = plt.figure()
    zpos = z_correlation['zpos']
    plt.plot(zpos)
    plt.xlabel('Frames')
    plt.ylabel('Z Position')
    plt.title('Z Position over Frames')
    plt.grid(True)
    plt.savefig(plot_export_path / "z_drift.png")
    plt.close(fig_zpos)
    # plt.show()
    
    print(f"Summary plots saved to {plot_export_path}")


def fit_huber_regressor(i_pixel, F_anat, F_anat_mean, F_func, F_func_mean):
    """
    Fit a Huber regressor to find the scaling factor
    """
    huber = HuberRegressor(fit_intercept=False)
    try:
        huber.fit(F_anat[i_pixel, :].reshape(-1, 1) - F_anat_mean[i_pixel], F_func[i_pixel, :] - F_func_mean[i_pixel])
        b = huber.coef_[0]
    except ValueError as e:
        if "HuberRegressor convergence failed" in str(e):
            b = 0
            print(f"Convergence warning for pixel {i_pixel}. Setting b[i_pixel] to 0.")
        else:
            raise e
    return b

# def fit_huber_regressor(F_anat_pixel, F_func_pixel):
#     """
#     Fit a Huber regressor to find the scaling factor for a given pixel
#     """
#     huber = HuberRegressor(fit_intercept=False)
#     try:
#         huber.fit(F_anat_pixel.reshape(-1, 1), F_func_pixel)
#         b = huber.coef_[0]
#     except ValueError as e:
#         if "HuberRegressor convergence failed" in str(e):
#             b = 0
#             print(f"Convergence warning for pixel. Setting b to 0.")
#         else:
#             raise e
#     return b

def fit_huber_regressor_on_region(F_anat, F_anat_mean, F_func, F_func_mean, pbar=None):
    """
    Fit a Huber regressor to find the scaling factor for a given zone
    """
    huber = HuberRegressor(fit_intercept=False)
    try:
        if np.isscalar(F_anat_mean) or len(F_anat_mean) == 1:
            X = F_anat.reshape(-1, 1) - F_anat_mean
            y = F_func - F_func_mean
        else:
            # Flatten the regions
            X = (F_anat - F_anat_mean[:, np.newaxis]).ravel().reshape(-1, 1)
            y = (F_func - F_func_mean[:, np.newaxis]).ravel()
        huber.fit(X, y)
        b = huber.coef_[0]
    except ValueError as e:
        if "HuberRegressor convergence failed" in str(e):
            b = 0
            print(f"Convergence warning. Setting b to 0.")
        else:
            raise e
    if pbar is not None:
        pbar.update()
    return b


def subtract_z_motion_lr_frames(F_func, F_anat):
    """
    Subtract the movement-induced changes from the functional movie using linear regression.
    """
    # Compute fit between F_anat_non_rigid and F_func using linear regression
    print("Computing fit between F_anat_non_rigid and F_func using linear regression")
    F_func_flattened = F_func.ravel()
    F_anat_non_rigid_flattened = F_anat.ravel()
    F_func_mean = np.mean(F_func_flattened)
    F_anat_non_rigid_mean = np.mean(F_anat_non_rigid_flattened)
    #  Use linregress to model F_func = slope * F_anat_non_rigid + intercept.
    slope, intercept, r_value, _, _ = linregress(F_anat_non_rigid_flattened - F_anat_non_rigid_mean, F_func_flattened - F_func_mean)
    z_motion_scaling_factors = {'slope': slope, 'intercept': intercept}
    print(f"R^2 value between F_func and F_anat_non_rigid: {r_value**2}")
    print(f"Slope: {slope}, Intercept: {intercept}")
    
    # Rescale and subtract the movement-induced changes from F_func
    print("Rescaling and subtracting the movement-induced changes from F_func")
    # We do not add intercept here, because that would bring the mean of F_corrected to 0, which is not desired when computing dF/F later. 
    # Instead, we subtract the mean of F_anat_non_rigid, which is a better approach.
    F_anat_non_rigid_adjusted = slope * (F_anat - np.mean(F_anat, axis=0))
    F_corrected = F_func - F_anat_non_rigid_adjusted
    print(f"F_corrected shape: {F_corrected.shape}, data type: {F_corrected.dtype}, min: {F_corrected.min()}, max: {F_corrected.max()}")
    # Clip F_corrected to uint16 range
    F_corrected = np.clip(F_corrected, 0, 2**16-1)

    return F_corrected, z_motion_scaling_factors

def subtract_z_motion_hr_frames(F_func, F_anat, smoothing_factor=1):
    
    # Get the dimensions of the F_func and F_anat movies (must be the same)
    Nframe, Ny, Nx = F_func.shape
    
    if Nframe != F_anat.shape[0]:
        raise ValueError("The number of frames in the functional and anatomical movies must be the same.")
    
    # Smooth the F_func and F_anat movies in x and y but not T
    F_func = gaussian_filter(F_func, sigma=[0, smoothing_factor, smoothing_factor])
    F_anat = gaussian_filter(F_anat, sigma=[0, smoothing_factor, smoothing_factor])
    
    # # Reshape the "functional" fluorescence movie
    # F_func = F_func.reshape(Nframe, Ny * Nx).T
        
    # # Get the average image of the functional fluorescence movie
    # F_func_mean = np.mean(F_func, axis=1)
    
    # # Reshape the "anatomical" fluorescence movie
    # F_anat = F_anat.reshape(Nframe, Ny * Nx).T

    # # Get the average image of the z-stack movie
    # F_anat_mean = np.mean(F_anat, axis=1)
    
    F_func_flattened = F_func.ravel()
    F_anat_flattened = F_anat.ravel()
    F_func_mean = np.mean(F_func_flattened)
    F_anat_mean = np.mean(F_anat_flattened)
    
    # Fit a linear regression model between the non-rigid F_anat and the F_func movie, using fit_huber_regressor_on_region
    with tqdm(total=1, desc='Fitting regressors on frames to find z motion scaling factors') as pbar:
            z_motion_scaling_factors = fit_huber_regressor_on_region(F_anat_flattened, F_anat_mean, F_func_flattened, F_func_mean, pbar)  
    
    z_motion_scaling_factors = np.array(z_motion_scaling_factors).astype(np.float32)
    print(f"z_motion_scaling_factors: {z_motion_scaling_factors}")
    
    # Rescale and subtract the movement-induced changes from the original F matrix
    F_anat_rescaled = z_motion_scaling_factors * (F_anat - F_anat_mean)
    # F_anat_rescaled = z_motion_scaling_factors * (F_anat_flattened - F_anat_mean)   
    
    # Subtract the rescaled F_anat from the F_func movie
    print("Rescaling and subtracting the movement-induced changes from F_func")
    F_corrected = F_func - F_anat_rescaled
    # Fcorrected = F_func_flattened - F_anat_rescaled
    # Fcorrected = Fcorrected.reshape(F_func.shape)
    
    print(f"F_corrected shape: {F_corrected.shape}, data type: {F_corrected.dtype}, min: {F_corrected.min()}, max: {F_corrected.max()}")
    # Clip F_corrected to uint16 range
    F_corrected = np.clip(F_corrected, 0, 2**16-1)
    
    # # # Compute R^2 of the correction by frames
    # # # 1   –   ( sum(Vcorr2)    /   sum( (Vfunc - <Vfunc>)2 ))
    # # # Sum of squares of the residuals
    # # sum_resid = np.sum((F_func - F_func_mean) ** 2)
    # # # Sum of squares of the corrected values
    # # sum_corrected = np.sum(F_corrected ** 2)
    # # # Compute the R^2 value
    # # R2 = 1 - sum_corrected / sum_resid
    
    # # Compute the sum of squared residuals
    # sum_res = np.sum(((F_func - F_func_mean) - F_anat_rescaled) ** 2, axis=0)
    # # Compute the total sum of squares
    # sum_tot = np.sum((F_func - F_func_mean) ** 2, axis=0)
    # # Compute the R^2 map
    # r_square_map = 1 - sum_res / sum_tot

    return F_corrected, z_motion_scaling_factors


def subtract_z_motion_hr_pixels(F_func, F_anat):
    """
    Subtract the movement-induced changes from the functional movie using pixel-wise subtraction.
    """
    # Get the dimensions of the F_func and F_anat movies (must be the same)
    Nframe, Ny, Nx = F_func.shape

    # Reshape the "functional" fluorescence movie
    F_func = F_func.reshape(Nframe, Ny * Nx).T
        
    # Get the average image of the functional fluorescence movie
    F_func_mean = np.mean(F_func, axis=1)
    
    # Reshape the "anatomical" fluorescence movie
    F_anat = F_anat.reshape(Nframe, Ny * Nx).T

    # Get the average image of the z-stack movie
    F_anat_mean = np.mean(F_anat, axis=1)

    # Fit a linear regression model between the non-rigid F_anat and the F_func movie
    z_motion_scaling_factors = Parallel(n_jobs=-1)(delayed(fit_huber_regressor)
                                                    (i_pixel, F_anat, F_anat_mean, F_func, F_func_mean)
                                                    for i_pixel in tqdm(range(Ny * Nx),
                                                    desc='Fitting regressors to find z motion scaling factors'))
        
    # # Subtract mean values before passing to the regressor
    # F_anat_adjusted = [F_anat[i_pixel, :] - F_anat_mean[i_pixel] for i_pixel in range(Ny * Nx)]
    # F_func_adjusted = [F_func[i_pixel, :] - F_func_mean[i_pixel] for i_pixel in range(Ny * Nx)]

    # # Fit a linear regression model between the non-rigid F_anat and the F_func movie
    # z_motion_scaling_factors = Parallel(n_jobs=-1)(delayed(fit_huber_regressor)
    #                                                 (F_anat_adjusted[i], F_func_adjusted[i])
    #                                                 for i in tqdm(range(Ny * Nx),
    #                                                 desc='Fitting regressors to find z motion scaling factors'))
    # Run as regular loop for debugging purposes: 
    # z_motion_scaling_factors = [fit_huber_regressor(F_anat_adjusted[i], F_func_adjusted[i]) for i in range(Ny * Nx)]

    # Change the list to a numpy array and cast to float32
    z_motion_scaling_factors = np.array(z_motion_scaling_factors).astype(np.float32)
    # np.save(export_dir / 'z_motion_scaling_factors_hr_pixels.npy', z_motion_scaling_factors)
    # Kill all LokyProcess workers (Windows only)
    if os.name == 'nt':
        for p in multiprocessing.active_children():
            if 'LokyProcess' in p.name:
                p.terminate()

    # Rescale and subtract the movement-induced changes from the original F matrix
    F_anat_rescaled = z_motion_scaling_factors[:, np.newaxis] * (F_anat - F_anat_mean[:, np.newaxis])
    Fcorrected = F_func - F_anat_rescaled

    # Reshape the corrected F matrix to the original shape
    Fcorrected = Fcorrected.T.reshape(Nframe, Ny, Nx)
    Fcorrected = np.clip(Fcorrected, 0, 2**16-1)
    
    # print(f"F_corrected shape: {F_corrected.shape}, data type: {F_corrected.dtype}, min: {F_corrected.min()}, max: {F_corrected.max()}")
       
    # # Compute R^2 of the correction for each pixel
    # # # 1   –   ( sum(Fxycorr(t)2)xyt    /   sum( (Fxyfunc(t) - <Fxyfunc(t)>t)2 )xyt )
    # # # Total sum of squares, proportional to the variance of the data. We use the residuals of F_func when we remove the mean of F_func)
    # # sum_tot = np.sum((F_func - F_func_mean[:, np.newaxis]) ** 2)
    # # # Sum of squares of the corrected values residuals (meaning residuals of F_func when we remove the corrected F_anat)
    # # sum_res = np.sum(Fcorrected ** 2)
    # # # sum_res = np.sum((F_func - Fcorrected.T.reshape(Nframe, Ny * Nx).T) ** 2)
    # # # Compute the R^2 value
    # # R2 = 1 - sum_res / sum_tot
    
    # #     R2 = 1 – sum((Fxyfunc(t) - <Fxyfunc(t)>t) - bxy * (Fxyanat(t) - <Fxyanat(t)>t))^2)
    # # / sum((Fxyfunc(t) - <Fxyfunc(t)>t)^2)

    # # Compute the sum of squared residuals
    # sum_res = np.sum(((F_func - F_func_mean[:, np.newaxis] ) - F_anat_rescaled) ** 2, axis=1)
    # # Compute the total sum of squares
    # sum_tot = np.sum((F_func - F_func_mean[:, np.newaxis]) ** 2, axis=1)
    # # Compute the R^2 map
    # r_square_map = 1 - sum_res / sum_tot
    # # re-shape r_square_map to the original shape
    # r_square_map = r_square_map.reshape(Ny, Nx)
    
    # # print("sum_res shape:", sum_res.shape)
    # # print("sum_tot shape:", sum_tot.shape)
    # # print("r_square_map shape:", r_square_map.shape)
    
    # # Print the formulas
    # # print("Sum of squared residuals: sum_res = ∑ [ (F_func - F_func_mean) - z_motion_scaling_factors * (F_anat - F_anat_mean) ]^2")
    # # print("Total sum of squares: sum_tot = ∑ (F_func - F_func_mean)^2")
    # # print(f"R² map: r_square_map = 1 - sum_res / sum_tot")
    
    # # # Compute correlation coefficient between F_func and F_anat
    # # # Compute the correlation coefficient for each pixel over time
    # # corr_coef = np.array([np.corrcoef(F_func[i_pix], F_anat[i_pix])[0, 1] for i_pix in range(Ny * Nx)])
    # # # Reshape the correlation coefficients back to the original 2D shape (y, x)
    # # corr_coef_map = corr_coef.reshape(Ny, Nx)
    
    # #   Save corr_coef_map as a png image
    # #  Reshape z_motion_scaling_factors
    # z_motion_scaling_factors_map = z_motion_scaling_factors.reshape(Ny, Nx)
    
    # fov_image = np.mean(F_func.T.reshape(Nframe, Ny, Nx), axis=0)

    return Fcorrected, z_motion_scaling_factors


def subtract_z_motion_patches(movie_mmap_path, zstack_filepath, z_correlation, mcorr_params, 
                              subtract_method='huber_regression_pixels', 
                              save_tiffs=False,
                              save_correl=False, save_format='parquet'):
    """
    Find the correlation between patches in the F_func movie and the anat z-stack.
    Create a composite anatomical image, using patch correlations to identify the best depth for each zone.
    Fit a linear regression between the non-rigid F_anat and the F_func movie.
    Subtract the scaled F_anat from the F_func movie to correct for z-motion.    
    """
    print("Starting z-motion correction with patch correlations...")
    # Load the motion-corrected functional movie
    movie_16bit, dims, T = load_memmap(movie_mmap_path)
    F_func = np.reshape(movie_16bit.T, [T] + list(dims), order='F')
    # Get dimensions    
    Nframe, Ny, Nx = F_func.shape
    # Clip the movie range to uint16
    F_func = np.clip(F_func, 0, 2**16-1)
    
    # Load the shifted z-stack    
    with TiffFile(zstack_filepath) as info_zstack:
        Nz = len(info_zstack.pages)
        Zstack = np.zeros((Ny, Nx, Nz), dtype=np.float32)
        for iz, page in enumerate(info_zstack.pages):
            Zstack[:, :, iz] = page.asarray()
      
    # TODO: check why on Windows F_anat bit depth is 8 and not 16. Use other method to load z-stack (append to list)?
    
    # Clip the z-stack range to uint16
    Zstack = np.clip(Zstack, 0, 2**16-1)
    
    # Flip Zstack upside-down to match the orientation of the movie
    Zstack = np.flip(Zstack, axis=0)
    
    # Get dimensions 
    Zstack_shape = Zstack.shape
    
    # Print F_func and Zstack shapes, data type and min/max range
    print(f"F_func shape: {F_func.shape}, data type: {F_func.dtype}, min: {F_func.min()}, max: {F_func.max()}")
    print(f"Zstack shape: {Zstack.shape}, data type: {Zstack.dtype}, min: {Zstack.min()}, max: {Zstack.max()}")

    export_path = movie_mmap_path.parent.parent
    
    # TODO: Update options to reload patch correlations: 
    if (export_path / 'patch_correlations.parquet').exists(): 
        print(f"Loading patch correlations from {export_path / 'patch_correlations.parquet'}")
        patch_correlations_df = pd.read_parquet(export_path / 'patch_correlations.parquet') 
        patch_correlations_df['Z_patch'] = patch_correlations_df['Z_patch'].apply(lambda x: np.frombuffer(x, dtype=np.uint16))
    else:
        # Define patch size based on Caiman's parameters. Width of patch = strides+overlaps.
        step_size = mcorr_params['strides'] 
        patch_overlap = mcorr_params['overlaps']
        # Calculate patch size for both x and y dimensions 
        patch_size = [step + overlap for step, overlap in zip(step_size, patch_overlap)]
        print()
        print("Calling patch_regress to find the correlation between patches in the F_func movie and the anat z-stack over frames")
        print(f"Patch size: {patch_size}, Step size: {step_size}, Patch overlap: {patch_overlap}")

        # Get zpos, x and y shifts
        zpos = z_correlation['zpos']
        
        # Time the execution
        start_time = time.time()

        # Prepare data for parallel processing
        frame_data_list = []
        for frameNum in range(Nframe):
            current_zpos = zpos[frameNum]
            # The number of z-stack frames to consider is 11 (+/- 5 frames around the current zpos)
            indices = [current_zpos + i for i in range(-5, 6)]
            # Check for valid z indices
            valid_indices = [index for index in indices if 0 <= index < Zstack_shape[2]]
            # Append the frame data to the list
            frame_data_list.append((frameNum, F_func[frameNum, :, :],
                            Zstack, Nx, Ny, patch_size, step_size,
                            zpos[frameNum], valid_indices))
            
            if frameNum == 0:
                print(f"Displaying values for frame {frameNum}")
                print(f"Current zpos is: {current_zpos}")
                print(f"F_func shape: {F_func[frameNum, :, :].shape}, Zstack shape: {Zstack.shape}")
                print(f"Number of frames: {Nframe}, Number of z-stack frames: {Zstack_shape[2]}")
                print(f"Patch size: {patch_size}, Step size: {step_size}, Patch overlap: {patch_overlap}")
                print(f"Number of valid z indices per frame: {len(valid_indices)}")
                
        # Call patch_regress in parallel
        patch_regress_results = Parallel(n_jobs=-1)(delayed(patch_regress)(frame_data) for frame_data in tqdm(frame_data_list, desc="Find the correlation between patches in the F_func movie and the anat z-stack over frames"))
                    
        # Flatten list of lists returned by map
        patch_correlations = [item for sublist in patch_regress_results for item in sublist]

        # Kill all LokyProcess workers (Windows only)
        if os.name == 'nt':
            for p in multiprocessing.active_children():
                if 'LokyProcess' in p.name:
                    p.terminate()

        # Convert to DataFrame
        patch_correlations_df = pd.DataFrame(patch_correlations)
        
        # Display execution time in mn and seconds
        exect_time = time.time() - start_time

        print("Patch correlation computation took ", exect_time // 60, "mn and ", exect_time % 60, "seconds")
    
    # Calculate patch overlap zones
    labeled_zones, zone_pattern= calculate_zones(patch_correlations_df, Ny, Nx)

    print("Calculated labeled zones and zone pattern")
    print(f"Number of zones: {len(labeled_zones)}")
    print(f"Zone pattern shape: {zone_pattern.shape}, data type: {zone_pattern.dtype}, min: {zone_pattern.min()}, max: {zone_pattern.max()}")
        
    # Create non-rigid F_anat, using ProcessPoolExecutor to parallelize
    groups = list(patch_correlations_df.groupby('frame_num'))
    with ProcessPoolExecutor() as executor:
        # Submit frames to make_composite_f_anat
        futures = {executor.submit(make_composite_f_anat, group, labeled_zones): frame_num for frame_num, group in groups}

        # Collect results as they complete
        results = []
        frame_arrays = []
        frame_nums = [] 
        for future in tqdm(as_completed(futures), total=len(futures), desc="Generating composite F_anat"):
            frame_num = futures[future]  # Retrieve frame number from the dictionary
            image_data, zone_data = future.result()
            results.append(zone_data)
            frame_arrays.append(image_data)
            frame_nums.append(frame_num) 
            
    # Concatenate all DataFrame results
    zone_df = pd.concat(results)

    # F_anat_non_rigid = np.concatenate(frame_arrays, axis=0)
    # Just in case the frames are not in order, sort frames and arrays according to the frame number
    sorted_indices = np.argsort(frame_nums)
    F_anat_non_rigid = np.concatenate([frame_arrays[idx] for idx in sorted_indices], axis=0)
    # Clip to uint16 range
    F_anat_non_rigid = np.clip(F_anat_non_rigid, 0, 2**16-1).astype(np.float32)

    # Plot the first frame of mcorr movie, the first frame of the z-stack, and the first frame of the composite F_anat side by side
    fig, ax = plt.subplots(1, 3, figsize=(15, 5))
    ax[0].imshow(F_func[0, :, :], cmap='gray')
    ax[0].set_title('First frame of F_func movie')
    ax[1].imshow(Zstack[:, :, 0], cmap='gray')
    ax[1].set_title('First frame of Zstack movie')
    ax[2].imshow(F_anat_non_rigid[0, :, :], cmap='gray')
    ax[2].set_title('First frame of composite F_anat movie')
    plt.tight_layout()
    # save the figure
    plot_dir = movie_mmap_path.parent.parent / 'plots'
    plot_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(plot_dir / 'first_frames_comparison.png')
    plt.close(fig)
    
    ###################################################
    ### Subtract z motion from the functional movie ###
    ###################################################
    
    if subtract_method == 'linear_regression_frames':
        F_corrected, z_motion_scaling_factors = subtract_z_motion_lr_frames(F_func, F_anat_non_rigid)
    elif subtract_method == 'huber_regression_pixels':
        F_corrected, z_motion_scaling_factors = subtract_z_motion_hr_pixels(F_func, F_anat_non_rigid)
    elif subtract_method == 'huber_regression_frames':
        F_corrected, z_motion_scaling_factors = subtract_z_motion_hr_frames(F_func, F_anat_non_rigid)
    else:
        F_corrected = None
        z_motion_scaling_factors = None
        
    # Make summary plots 
    patch_correl_plots(patch_correlations_df, labeled_zones, zone_df, zone_pattern, np.mean(F_func, axis=0), z_correlation, export_path)
    
    print("Saving labeled_zones")
    labeled_zones_df = pd.DataFrame(labeled_zones)
    labeled_zones_filepath = export_path / 'labeled_zones.csv'
    labeled_zones_df.to_csv(labeled_zones_filepath, index=False, header=False)
    
    #  Save r_square_map as heatmap figure
    # if subtract_method == 'huber_regression_pixels' or subtract_method == 'huber_regression_frames':
    #     print("Saving R^2 heatmap")
    #     fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    #     im = ax.imshow(r_square_map, cmap='viridis')
    #     fig.colorbar(im, ax=ax)
    #     ax.set_title("R^2 values for each pixel")
    #     plt.tight_layout()
    #     r_square_map_filepath = export_path / 'r_square_map.png'
    #     plt.savefig(r_square_map_filepath)
    
    # Save videos
    if save_tiffs:
        if F_corrected is not None:
            print("Saving F_corrected")
            # Save to tiff 
            f_corrected_filepath = export_path / f"F_func_corrected_T_{Nframe}_Y_{Ny}_X_{Nx}.tiff"
            with TiffWriter(f_corrected_filepath, bigtiff=True) as tif:
                tif.write(F_corrected.astype(np.uint16), photometric='minisblack')
                
        if F_anat_non_rigid is not None:
            print("Saving composite F_anat")
            # Save F_anat_non_rigid
            composite_f_anat_filepath = export_path / f"F_anat_non_rigid_T_{Nframe}_Y_{Ny}_X_{Nx}.tiff"
            # Save movie to a tiff file
            with TiffWriter(composite_f_anat_filepath, bigtiff=True) as tif:
                tif.write(F_anat_non_rigid.astype(np.uint16), photometric='minisblack') 
    
    if save_correl:
        print("Saving patch correlations")
        start_time = time.time()
        if save_format == 'mat':
        # # Save to a .mat file

            patch_correlations_filepath = export_path / 'patch_correlations.mat'
            # zone_df_mat = format_patch_correl_for_mat(zone_df)
            # savemat(patch_correlations_filepath, zone_df_mat)
        
            # Specifying the exact dtype
            dtype = [
                ('frame_num', 'uint32'),
                ('zone_id', 'int16'),
                ('r_squared', 'float32'),
                ('patch_number', 'uint16'),
                ('patch_z_pos', 'int16'),
            ]

            # Convert zone_df to structured NumPy array
            structured_array = np.array(list(zone_df.itertuples(index=False, name=None)), dtype=dtype)

            # Prepare data to save
            mat_dict = {
                'patch_data_averaged_by_zone': structured_array,
                'zone_index': labeled_zones
            }

            # Save to .mat file, displaying a counter for progress
            savemat(patch_correlations_filepath, mat_dict)
        
        elif save_format == 'parquet':
            # Save to a Parquet file            
            patch_correlations_filepath = export_path / 'patch_correlations.parquet' 
            # Saving / loading the Z_patch column is tricky, as its quite large. 
            # One option is to convert it to binary before saving
            patch_correlations_df['Z_patch'] = patch_correlations_df['Z_patch'].apply(lambda x: x.tobytes())  
            patch_correlations_df.to_parquet(patch_correlations_filepath, index=False)
            # Another option would be to save it separately.
                
        elif save_format == 'csv':
            # Save to a csv file
            patch_correlations_filepath = export_path / 'patch_correlations.csv'
            zone_df.to_csv(patch_correlations_filepath, index=False, header=True)
                
        print(f"Patch correlations saved in {time.time() - start_time:.2f} seconds")
            
    # clean up            
    del F_func, movie_16bit, Zstack, F_anat_non_rigid, patch_regress_results, patch_correlations_df, labeled_zones_df, patch_correlations
    gc.collect()

    return F_corrected, z_motion_scaling_factors

def subtract_z_motion_neurons(components, fov_image, zpos, shifted_zstack_filename, zparams_path):
    """
    Subtract z motion from the fluorescence traces of neurons.
    """
    
    F=components.C
    spatial_components=components.A
    Nneuron, Nframe = F.shape

    if not isinstance(zparams_path, dict):
        with open(zparams_path, 'r') as file:
            params = json.load(file)

    # Assuming spatial_components is a sparse matrix
    spatial_components_dense = spatial_components.toarray()
    ROI = [{} for _ in range(Nneuron)]
    for i_neuron in range(Nneuron):
        ind = np.where(spatial_components_dense[:, i_neuron] > 0)[0]
        pix_y, pix_x = np.unravel_index(ind, (params['zstack_shift']['Nx'], params['zstack_shift']['Ny']))
        ROI[i_neuron]['pix_x'] = pix_x
        ROI[i_neuron]['pix_y'] = pix_y
        ROI[i_neuron]['pix_w'] = np.full(len(ROI[i_neuron]['pix_x']), 1 / len(ROI[i_neuron]['pix_x']))

    F0 = np.zeros(Nneuron)
    Fz0 = np.zeros(Nneuron)
    b = np.zeros(Nneuron)
    Fz = np.zeros((Nneuron, Nframe))
    Fz_rescaled = np.zeros((Nneuron, Nframe))
    Fcorrected = np.zeros((Nneuron, Nframe))

    info_zstack = Image.open(shifted_zstack_filename)
    Nz = info_zstack.n_frames
    Nx = info_zstack.width
    Ny = info_zstack.height
    Zstack = np.zeros((Ny, Nx, Nz), dtype=np.float32)
    info_zstack.close()

    # Translate z-stack frames to minimize shift with mean of registered tseries frames
    zpos_0 = mode(zpos).mode
    Zstack_0 = Zstack[ :, :,zpos_0]
    # Perform image registration
    shift, error, _ = phase_cross_correlation(Zstack_0, fov_image, upsample_factor=10)

    # Create the transformation matrix (for translation only)
    tform = np.eye(3)
    tform[0, 2] = -shift[1]  # x translation
    tform[1, 2] = -shift[0]  # y translation

    for iz in range(Nz):
        Zstack[:, :, iz] = warp(Zstack[:, :, iz], tform)

        # Make a movie of the z-stack frames that best fit the registered tseries frames
    F810_t = Zstack[:, :, zpos]

    # Apply the cell masks on this movie and find the movement-induced changes
    # in fluorescence of each cell predicted from z changes, then rescale and
    # subtract them from the original F matrix
    for i_neuron in range(Nneuron):
        F0[i_neuron] = np.mean(F[i_neuron, :])
        for i_pix in range(len(ROI[i_neuron]['pix_x'])):
            Fz[i_neuron, :] += ROI[i_neuron]['pix_w'][i_pix] * F810_t[ROI[i_neuron]['pix_y'][i_pix], ROI[i_neuron]['pix_x'][i_pix], :]
        Fz0[i_neuron] = np.mean(Fz[i_neuron, :])

        huber = HuberRegressor(fit_intercept=False)
        huber.fit(Fz[i_neuron, :].reshape(-1, 1) - Fz0[i_neuron], F[i_neuron, :] - F0[i_neuron])
        b[i_neuron] = huber.coef_[0]

        Fz_rescaled[i_neuron, :] = b[i_neuron] * (Fz[i_neuron, :] - Fz0[i_neuron])
        Fcorrected[i_neuron, :] = F[i_neuron, :] - Fz_rescaled[i_neuron, :]

    # If z is >+5um or <-5um away from mode, then replace F by NaN and interpolate linearly from non missing values
    missing_F = np.abs(zpos - zpos_0) > 5
    if np.any(missing_F):
        Fcorrected[:, missing_F] = np.nan
        Fcorrected = pd.DataFrame(Fcorrected).interpolate(method='linear', axis=1, limit_direction='both').values

    Fz_scale_factor = np.mean(b)

    # Plotting and visualization
    # fig_z_drift = plt.figure()
    # plt.plot(zpos)
    # plt.xlabel('frames')
    # plt.ylabel('z')

    # x,y,t  
    return  Fcorrected, Fz_scale_factor

def subtract_z_motion_pixels(movie_mmap_path, zpos, zstack_filepath, n_jobs=-1):
    """
    Fit a Huber regressor to find the scaling factor for each pixel. 
    Subtract the movement-induced changes from the original F matrix per pixel.
    """
    # Load the movie
    movie_16bit, dims, T = load_memmap(movie_mmap_path)
    pixels = np.reshape(movie_16bit.T, [T] + list(dims), order='F')
    Nframe, Ny, Nx = pixels.shape
    
    # Load the FOV file
    mcorr_batch_dir = movie_mmap_path.parent
    fov_file_path = Path.joinpath(mcorr_batch_dir, f"{mcorr_batch_dir.stem}_mean_projection.npy")
    fov_image = np.load(fov_file_path)
    
    # Load the z-stack
    info_zstack = Image.open(zstack_filepath)
    Nz = info_zstack.n_frames
    Zstack = np.zeros((Ny, Nx, Nz), dtype=np.float32)
    for iz in range(Nz):
        info_zstack.seek(iz)
        Zstack[:, :, iz] = np.array(info_zstack)
    info_zstack.close()        
    # TODO: check why on Windows F_anat bit depth is 8 and not 16

    # Flip Zstack up-down to match the orientation of the movie
    Zstack = np.flip(Zstack, axis=0)

    # Reshape the "functional" fluorescence movie
    F_func = pixels.reshape(Nframe, Ny * Nx).T
        
    # Get the average image of the functional fluorescence movie
    F_func_mean = np.mean(F_func, axis=1)
    
    # Translate zstack frames to minimize shift with mean of registered tseries frames
    zpos_0 = mode(zpos).mode
    Zstack_0 = Zstack[:, :, zpos_0]
    
    # Perform image registration
    shift, _ , _ = phase_cross_correlation(Zstack_0, fov_image, upsample_factor=10)
    
    # Create the transformation matrix (for translation only)
    tform = np.eye(3)
    tform[0, 2] = -shift[1]
    tform[1, 2] = -shift[0]

    # Translate z-stack frames to minimize shift with mean of registered tseries frames (FOV)
    for iz in range(Nz):
        Zstack[:, :, iz] = warp(Zstack[:, :, iz], tform)

    # Make a movie of the z-stack frames that follows zcorr (movement in depth)
    F_anat = Zstack[:, :, zpos]

    # Reshape the "anatomical" fluorescence movie
    F_anat = F_anat.reshape(Ny * Nx, Nframe)

    # Get the average image of the z-stack movie
    F_anat_mean = np.mean(F_anat, axis=1)
        
    # Fit a Huber regressor to find the scaling factor
    # with Parallel(n_jobs=n_jobs) as parallel:
    #     z_motion_scaling_factors = parallel(
    #         delayed(fit_huber_regressor)(
    #             i_pixel, 
    #             F_anat, 
    #             F_anat_mean, 
    #             F_func, 
    #             F_func_mean
    #         ) 
    #         for i_pixel in tqdm(
    #             range(Nx * Ny), 
    #             desc='Fitting regressors to find z motion scaling factors'
    #         )
    #     )
    # # Close and join workers
    # parallel._backend.terminate()

    z_motion_scaling_factors = Parallel(n_jobs=n_jobs)(delayed(fit_huber_regressor)(i_pixel, F_anat, F_anat_mean, F_func, F_func_mean) for i_pixel in tqdm(range(Ny * Nx), desc='Fitting regressors to find z motion scaling factors'))
                   
    # Change the list to a numpy array and cast to float32
    z_motion_scaling_factors = np.array(z_motion_scaling_factors)
    z_motion_scaling_factors = z_motion_scaling_factors.astype(np.float32)

    # Kill all LokyProcess workers (Windows only)
    if os.name == 'nt':
        for p in multiprocessing.active_children():
            if 'LokyProcess' in p.name:
                p.terminate()

    # Rescale and subtract the movement-induced changes from the original F matrix
    F_anat_rescaled = z_motion_scaling_factors[:, np.newaxis] * (F_anat - F_anat_mean[:, np.newaxis])
    Fcorrected = F_func - F_anat_rescaled
    Fcorrected = np.clip(Fcorrected, 0, 2**16-1)

    # If z is >+5um or <-5um away from mode, then replace F by NaN and interpolate linearly from non missing values
    missing_F = np.abs(zpos - zpos_0) > 5
    if np.any(missing_F):
        Fcorrected[:, missing_F] = np.nan
        Fcorrected = pd.DataFrame(Fcorrected).interpolate(method='linear', axis=1, limit_direction='both').values
        # TODO: check that it only interpolates NaNs
        
    # Reshape Fcorrected to the original shape
    F_func_reshaped = F_func.T.reshape(Nframe, Ny, Nx)
    F_anat_rescaled_reshaped = F_anat_rescaled.T.reshape(Nframe, Ny, Nx)
    min_Fars = np.min(F_anat_rescaled_reshaped)
    max_Fars = np.max(F_anat_rescaled_reshaped)
    F_anat_rescaled_reshaped = (F_anat_rescaled_reshaped - min_Fars) / (max_Fars - min_Fars) * (2**16-1)
    Fcorrected_reshaped = Fcorrected.T.reshape(Nframe, Ny, Nx)
    Fcorrected_reshaped = np.clip(Fcorrected_reshaped, 0, 2**16-1)
    F_anat_reshaped = F_anat.T.reshape(Nframe, Ny, Nx)

    # Save an excerpt of the corrected F matrix to a video file
    # Take only the first 80 frames
    F_anat_reshaped_excerpt = F_anat_reshaped[:80]
    Fcorrected_reshaped_excerpt = Fcorrected_reshaped[:80]
    F_anat_rescaled_reshaped_excerpt = F_anat_rescaled_reshaped[:80]
    F_func_reshaped_excerpt = F_func_reshaped[:80]
    
    # Assign data type to uint16
    F_func_reshaped_excerpt = F_func_reshaped_excerpt.astype(np.uint16)
    F_anat_rescaled_reshaped_excerpt = F_anat_rescaled_reshaped_excerpt.astype(np.uint16)
    Fcorrected_reshaped_excerpt = Fcorrected_reshaped_excerpt.astype(np.uint16)
    F_anat_reshaped_excerpt = F_anat_reshaped_excerpt.astype(np.uint16)
    
    # Concatenate horizontally
    top = np.concatenate((F_func_reshaped_excerpt, F_anat_reshaped_excerpt), axis=2)
    bottom = np.concatenate((F_anat_rescaled_reshaped_excerpt, Fcorrected_reshaped_excerpt), axis=2)
    
    # Concatenate vertically
    F_concat = np.concatenate((top, bottom), axis=1)
    
    # Save the concatenated array to a video file
    F_concat_img = Image.fromarray(F_concat[0])
    F_concat_img.save(movie_mmap_path.parent.parent / "F_concat.tif", save_all=True, append_images=[Image.fromarray(F_concat[i]) for i in range(1, 80)])
    
    # clean up            
    del pixels, movie_16bit
    gc.collect()

    # Return the corrected F matrix and the scaling factor
    return Fcorrected_reshaped, z_motion_scaling_factors

def z_motion(mcorr_movie_path, parameters, recompute=True):
    """
    Shifts the z-stack and performs z-motion correlation.

    This function:
      1. Sets up and loads necessary parameters.
      2. Ensures the z-stack path is correctly formatted.
      3. Generates a shifted z-stack file if one does not already exist.
      4. Computes the z-correlation between the shifted z-stack and the movie.
      5. Optionally subtracts z-motion using various methods (patches, pixels, etc.).
      6. Saves the corrected movie as a memmap file if z-motion subtraction is performed.

    Returns:
      movie_path:  Path to the saved corrected movie (or None if not generated).
      z_motion_scaling_factors:  The scaling factors used during z-motion subtraction (or None).
      z_correlation:  The computed z-correlation data.
    """
    
    # --- Parameter Setup ---
    # Extract z-stack parameters and the z-stack file path from the input parameters.
    z_parameters = parameters['z_params']
    zstack_path = parameters['zstack_path']
    
    # If z_parameters is not already a dict, assume it is a path to a JSON file and load it.
    if not isinstance(z_parameters, dict):
        with open(z_parameters, 'r') as file:
            z_parameters = json.load(file)
    
    # Retrieve the expected file name for the shifted z-stack.
    z_shifted_file = z_parameters['zstack_shift']['file_name']
    
    # Ensure zstack_path is a Path object.
    if isinstance(zstack_path, str):
        zstack_path = Path(zstack_path)
        
    # --- Generate Shifted Z-stack ---
    try:
        # If the shifted z-stack file doesn't exist, generate it using the shift_zstack function.
        if not os.path.exists(zstack_path / z_shifted_file) or recompute:
            shift_zstack_path = shift_zstack(z_parameters['zstack_shift'], zstack_path, z_shifted_file)
        else:
            shift_zstack_path = zstack_path / z_shifted_file
    except Exception as e:
        print(f"Error in compute_zcorr - generate zstack_shifted: {e}")
        return None, None, None
    
    # --- Compute Z-correlation ---
    try:
        # Determine the directory where the z_correlation file should be saved.
        mesmerize_path = mcorr_movie_path.parents[1]
        # Compute z-correlation if the file doesn't already exist; otherwise, load it.
        if not os.path.exists(mesmerize_path / "z_correlation.npz") or recompute:
            z_correlation = compute_zcorrel(zstack_path / z_shifted_file, mcorr_movie_path)
        else:
            z_correlation = np.load(mesmerize_path / "z_correlation.npz")
    except Exception as e:
        print(f"Error in compute_zcorr - compute z-correlation: {e}")
        return None, None, None
    
    # --- Perform Z-motion Subtraction (if specified) ---
    try:
        if 'subtract_z_motion' in z_parameters:
            subtract_z_motion = z_parameters['subtract_z_motion']
            
            # Initialize variables for the z-motion subtraction results.
            zcorr_movie = None
            z_motion_scaling_factors = None
            movie_path = None      
    
            # Check if the subtraction flag is a boolean.
            if isinstance(subtract_z_motion, bool):
                if subtract_z_motion:
                    # Use the specified subtraction method if provided.
                    if 'subtract_method' in z_parameters:
                        subtract_method = z_parameters['subtract_method']
                        print(f"Z-motion subtraction method: {subtract_method}")
                    else:
                        subtract_method = None
                        print("No subtraction method selected. Computing non-rigid F_anat but not F_func corrected.")
                    
                    # Perform z-motion subtraction on patches (default method)
                    if not os.path.exists(mesmerize_path / "non_rigid_z_motion_scaling_factors.npy"):
                        zcorr_movie, z_motion_scaling_factors = subtract_z_motion_patches(
                            mcorr_movie_path,
                            zstack_path / z_shifted_file, 
                            z_correlation, 
                            parameters['params_mcorr']['main'],
                            subtract_method,
                            True
                        )
                        # Save the scaling factors if they have been computed.
                        if z_motion_scaling_factors is not None:
                            np.save(mesmerize_path / "non_rigid_z_motion_scaling_factors.npy", z_motion_scaling_factors)
                    else:
                        print("Z-motion subtraction already performed.")
                else:
                    print("No z-motion subtraction requested.")
                    
            # If the subtraction parameter is provided as a string, select the appropriate method.
            elif isinstance(subtract_z_motion, str):
                if subtract_z_motion == 'pixels':
                    # Perform pixel-based z-motion subtraction.
                    if not os.path.exists(mesmerize_path / "pixels_z_motion_scaling_factors.npy"):
                        zcorr_movie, z_motion_scaling_factors = subtract_z_motion_pixels(
                            mcorr_movie_path, 
                            z_correlation, 
                            shift_zstack_path
                        )
                        # Save the scaling factors.
                        np.save(mesmerize_path / "pixels_z_motion_scaling_factors.npy", z_motion_scaling_factors)
                    else:
                        print("Z-motion subtraction already performed.")
                
                elif subtract_z_motion == 'neurons':
                    print("Subtracting z motion from neurons is no longer supported.")
                           
            else:
                print("No z-motion subtraction method specified.")

            # --- Save Corrected Movie ---
            # If a corrected movie has been generated, save it to a memmap file.
            if zcorr_movie is not None:
                movie_path = save_mmap_movie(
                    zcorr_movie, 
                    mcorr_movie_path.parent / f"zcorr_movie_{mcorr_movie_path.name}"
                )
                    
            return movie_path, z_motion_scaling_factors, z_correlation
    
        else:
            # If no subtraction is specified, return the computed z_correlation only.
            return None, None, z_correlation
    
    except Exception as e:
        print(f"Error in compute_zcorr - computing non-rigid F_anat: {e}")
        return None, None, None
     
if __name__ == "__main__":
    # Get arguements from command line
    parser = argparse.ArgumentParser(description="Compute z-motion correction for a movie")
    parser.add_argument("mcorr_movie_path", type=str, help="Path to the motion-corrected movie")
    parser.add_argument("parameters", type=str, help="Path to the parameters file")
    args = parser.parse_args()
    mcorr_movie_path = Path(args.mcorr_movie_path)
    parameters = Path(args.parameters)
    # Call the function
    z_motion(mcorr_movie_path, parameters)