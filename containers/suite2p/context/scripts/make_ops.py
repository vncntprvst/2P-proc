import argparse
import os
import logging
import numpy as np
import h5py
from tifffile import TiffFile
import suite2p

from scipy.ndimage import median_filter

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

def compute_suite2p_images(movie, filter_size=3):
    """
    Compute Suite2p-style mean, enhanced mean, and max projection images.

    Parameters:
        movie: np.ndarray or array-like (nframes, Ly, Lx) fully in memory
        filter_size: int
            Size for median filter (for enhanced mean image)

    Returns:
        meanImg, meanImgE, max_proj
    """
    # If object has no .mean attribute (e.g. h5py Dataset) caller should use chunked helper.
    meanImg = np.asarray(movie).mean(axis=0).astype(np.float32)
    meanImgE = median_filter(meanImg, size=filter_size)
    max_proj = np.asarray(movie).max(axis=0).astype(np.float32)
    return meanImg, meanImgE, max_proj

def compute_suite2p_images_h5(dset, filter_size=3, chunk_size=256):
    """Chunked summary image computation for an h5py Dataset to avoid loading all frames.

    Parameters
    ----------
    dset : h5py.Dataset
        Dataset with shape (nframes, Ly, Lx)
    filter_size : int
        Median filter size for enhanced mean image.
    chunk_size : int
        Number of frames per chunk.
    """
    nframes, Ly, Lx = dset.shape
    acc = np.zeros((Ly, Lx), dtype=np.float64)
    max_proj = np.full((Ly, Lx), -np.inf, dtype=np.float32)
    for start in range(0, nframes, chunk_size):
        stop = min(nframes, start + chunk_size)
        chunk = dset[start:stop]  # (chunk, Ly, Lx)
        # accumulate sum (float64 for precision), and running max
        acc += chunk.sum(axis=0, dtype=np.float64)
        chunk_max = chunk.max(axis=0)
        max_proj = np.maximum(max_proj, chunk_max)
    meanImg = (acc / nframes).astype(np.float32)
    meanImgE = median_filter(meanImg, size=filter_size)
    return meanImg, meanImgE, max_proj

def compute_bin_frames(fs: float, tau: float) -> int:
    """Compute frames per bin consistent with Suite2p GUI: round(tau * fs)."""
    try:
        return max(1, int(round(float(tau) * float(fs))))
    except Exception:
        # Fallback to at least 1 frame per bin
        return 1

def enforce_nbinned(ops: dict) -> None:
    """Ensure bin_frames=round(tau*fs) and nbinned = nframes // bin_frames; log summary."""
    nframes = int(ops.get('nframes', 0))
    fs = float(ops.get('fs', 1.0))
    tau = float(ops.get('tau', 1.0))
    desired_bin = compute_bin_frames(fs, tau)
    # Always enforce bin_frames to match GUI logic
    prev = int(ops.get('bin_frames', 0) or 0)
    if prev != desired_bin:
        print(f"[bin_frames] Setting bin_frames from {prev} to {desired_bin} (tau*fs)")
    ops['bin_frames'] = desired_bin
    # Derive nbinned from bin_frames
    nb = max(1, (nframes // desired_bin) if nframes > 0 else 1)
    ops['nbinned'] = nb
    print(f"Binning summary: nframes={nframes} fs={fs} tau={tau} nbinned={ops['nbinned']} bin_frames={ops['bin_frames']}")

def compute_suite2p_images_bin_mmap(bin_path: str, nframes: int, Ly: int, Lx: int,
                                    nsamps: int = 2048, chunk_size: int = 256,
                                    filter_size: int = 3):
    """Compute mean/max images from a binary int16 movie by sampling evenly across time.

    This avoids biasing summaries to the first frames and matches the h5 chunked path.
    """
    # memory-map as a 1D view, then reshape to (nframes, Ly, Lx) on the fly per chunk
    mm = np.memmap(bin_path, mode='r', dtype=np.int16)
    expected = nframes * Ly * Lx
    if mm.size < expected:
        raise ValueError(f"Binary size smaller than expected: {mm.size} < {expected}")
    # build evenly spaced indices
    nsamps = min(nsamps, nframes)
    inds = np.linspace(0, nframes - 1, nsamps, dtype=np.int64)
    acc = np.zeros((Ly, Lx), dtype=np.float64)
    max_proj = np.full((Ly, Lx), -np.inf, dtype=np.float32)
    # process in chunks of indices to limit reshaping cost
    for start in range(0, inds.size, chunk_size):
        stop = min(inds.size, start + chunk_size)
        i_chunk = inds[start:stop]
        # gather frames
        # For each frame i, slice mm[i*Ly*Lx : (i+1)*Ly*Lx]
        buf = np.zeros((i_chunk.size, Ly, Lx), dtype=np.int16)
        for j, i in enumerate(i_chunk):
            s = int(i) * Ly * Lx
            e = s + Ly * Lx
            buf[j] = np.asarray(mm[s:e], dtype=np.int16).reshape(Ly, Lx)
        acc += buf.sum(axis=0, dtype=np.float64)
        max_proj = np.maximum(max_proj, buf.max(axis=0))
    meanImg = (acc / inds.size).astype(np.float32)
    meanImgE = median_filter(meanImg, size=filter_size)
    return meanImg, meanImgE, max_proj

def main():
    parser = argparse.ArgumentParser(description="Generate Suite2p ops file from command line arguments.")

    parser.add_argument('--export_path', required=True, help="Path where outputs and ops.npy will be saved")
    parser.add_argument('--movie', required=True, help="Path to HDF5, BIN or TIFF movie file")
    parser.add_argument('--h5py_key', default='data', help="HDF5 dataset key - if .h5 movie (default: 'data')")
    parser.add_argument('--fs', type=float, required=True, help="Acquisition rate (Hz)")
    parser.add_argument('--tau', type=float, required=True, help="Decay time constant")
    parser.add_argument('--save_mat', type=int, default=0, help="Export results as MATLAB .mat (1=True, 0=False)")
    parser.add_argument('--do_registration', type=int, default=0, help="Perform registration (0=skip, 1=do)")
    parser.add_argument('--nonrigid', type=int, default=0, help="Perform nonrigid registration (0=skip, 1=do)")
    parser.add_argument('--reg_file', default=None, help="Path to the motion-corrected HDF5 movie file, if different from --movie")
    parser.add_argument('--zcorr_file', default=None, help="Path to the z-motion estimates file")

    # Detection parameters
    parser.add_argument('--diameter', type=int, default=0, help="Expected diameter of neurons in pixels")
    parser.add_argument('--spatial_scale', type=int, default=0, help="Spatial scale for detection (0=auto)")
    parser.add_argument('--threshold_scaling', type=float, default=1.0, help="Scaling factor for detection threshold")
    parser.add_argument('--max_overlap', type=float, default=0.75, help="Maximum allowed overlap between ROIs")
    parser.add_argument('--anatomical_only', type=int, default=0, help="Anatomical detection mode")

    # For .bin files, these are required!
    parser.add_argument('--nframes', type=int, help="Number of frames (required if using .bin)")
    parser.add_argument('--Ly', type=int, help="Frame height (required if using .bin)")
    parser.add_argument('--Lx', type=int, help="Frame width (required if using .bin)")

    args = parser.parse_args()

    # Normalize optional path-like args that may come in as the literal string 'null'/'None'
    def _normalize_optional_path(v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in {"", "none", "null", "false"}:
            return None
        return v

    args.reg_file = _normalize_optional_path(args.reg_file)
    args.zcorr_file = _normalize_optional_path(args.zcorr_file)

    ops = suite2p.default_ops()

    extraction_only = (args.do_registration == 0)

    if args.movie.endswith('.h5'):
        with h5py.File(args.movie, 'r') as f:
            dset = f[args.h5py_key]
            nframes, Ly, Lx = dset.shape
            meanImg, meanImgE, max_proj = compute_suite2p_images_h5(dset)
            data_dtype = str(dset.dtype)
        ops.update({
            'h5py': [args.movie],
            'h5py_key': args.h5py_key,
            'data_dtype': data_dtype,
            'nframes': nframes,
            'Ly': Ly,
            'Lx': Lx,
        })
        if extraction_only:
            # In extraction-only mode Suite2p expects a binary reg_file; we mimic AIND allowing h5 directly.
            ops['reg_file'] = args.movie
    elif args.movie.endswith('.bin'):
        if args.nframes is None or args.Ly is None or args.Lx is None:
            raise ValueError("For .bin movies, specify --nframes, --Ly, --Lx")
        # Compute summaries from evenly sampled frames across the whole movie
        meanImg, meanImgE, max_proj = compute_suite2p_images_bin_mmap(
            args.movie, args.nframes, args.Ly, args.Lx
        )
        ops.update({
            'data_path': [args.movie],
            'input_format': 'binary',
            'data_dtype': 'int16',
            'nframes': args.nframes,
            'Ly': args.Ly,
            'Lx': args.Lx,
            'reg_file': args.movie if extraction_only else (args.reg_file or args.movie),
        })
    elif args.movie.endswith('.tif') or args.movie.endswith('.tiff'):
        # Read TIFF metadata and sample frames to compute summaries
        with TiffFile(args.movie) as tf:
            nframes = len(tf.pages)
            first = tf.pages[0].asarray()
            Ly, Lx = first.shape[-2], first.shape[-1]
            # sample evenly spaced frames to build mean/max
            nsamps = min(2048, nframes)
            inds = np.linspace(0, nframes - 1, nsamps, dtype=int)
            acc = np.zeros((Ly, Lx), dtype=np.float64)
            max_proj = np.full((Ly, Lx), -np.inf, dtype=np.float32)
            for i in inds:
                fr = tf.pages[int(i)].asarray()
                if fr.ndim == 3:  # handle (channels, y, x)
                    fr = fr[0]
                acc += fr.astype(np.float64)
                max_proj = np.maximum(max_proj, fr.astype(np.float32))
            meanImg = (acc / inds.size).astype(np.float32)
            meanImgE = median_filter(meanImg, size=3)
        ops.update({
            'data_path': [os.path.dirname(args.movie)],
            'tiff_list': [os.path.basename(args.movie)],
            'data_dtype': 'uint16',
            'nframes': nframes,
            'Ly': Ly,
            'Lx': Lx,
        })
    else:
        raise ValueError("Unsupported movie format. Use .h5, .bin, or .tif/.tiff files.")

    # Summary images
    ops['meanImg'] = meanImg
    ops['meanImgE'] = meanImgE
    ops['max_proj'] = max_proj

    # Generic fields
    ops['first_tiffs'] = []
    ops['nframes_per_folder'] = [ops['nframes']]
    ops['h5list'] = [args.movie] if args.movie.endswith('.h5') else []
    ops['xrange'] = [0, ops['Lx']]
    ops['yrange'] = [0, ops['Ly']]
    ops['filelist'] = [args.movie]

    # Parameter overrides
    ops.update({
        'save_path0': args.export_path,
        'save_folder': '.',
        'save_mat': args.save_mat,
        'do_registration': args.do_registration,
        'nonrigid': args.nonrigid,
        'fs': args.fs,
        'tau': args.tau,
        'diameter': args.diameter,
        'spatial_scale': args.spatial_scale,
        'threshold_scaling': args.threshold_scaling,
        'max_overlap': args.max_overlap,
        'anatomical_only': args.anatomical_only,
        'max_iterations': 20,
        'high_pass': 100,
        'soma_crop': 1,
        'allow_overlap': 0,
        'inner_neuropil_radius': 2,
        'min_neuropil_pixels': 350,
    })

    # Binning consistent with GUI: bin_frames = round(tau*fs), nbinned derived from nframes
    enforce_nbinned(ops)

    # Validate z-motion estimates file
    if args.zcorr_file is not None:
        if os.path.exists(args.zcorr_file):
            try:
                zcorr_data = np.load(args.zcorr_file)
                ops['zpos'] = zcorr_data['zpos']
            except Exception as e:
                log_and_print(f"Warning: failed to read zcorr_file '{args.zcorr_file}': {e}", level='warning')
        else:
            log_and_print(f"Warning: zcorr_file not found: '{args.zcorr_file}'. Proceeding without z-motion estimates.", level='warning')

    # Validate extraction-only configuration
    if extraction_only:
        print("NOTE: Extraction-only mode is un-tested")
        if args.movie.endswith('.h5') and 'reg_file' not in ops:
            ops['reg_file'] = args.movie
        if args.movie.endswith('.h5') and ops['nbinned'] > ops['nframes']:
            ops['nbinned'] = max(1, ops['nframes']//10)

    # Print ops for debugging
    print("Generated ops dictionary:")
    for key, value in ops.items():
        print(f"  {key}: {value}")

    os.makedirs(args.export_path, exist_ok=True)
    ops_path = os.path.join(args.export_path, 'ops.npy')
    np.save(ops_path, ops)
    print(f"Saved ops file to: {ops_path}")
    
if __name__ == '__main__':
    main()
