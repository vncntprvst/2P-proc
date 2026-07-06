"""
Load Bruker PrairieView 2P recordings into memory for z-motion benchmarks.

Bruker stores each frame as a separate OME-TIFF alongside a per-acquisition XML
sidecar.  A ``ZSeries`` folder is an axial stack (one TIFF per z-plane, per
channel); a ``TSeries`` folder is a functional recording (one TIFF per frame,
often split into cycles).  This module assembles those per-file TIFFs into the
``(Z, H, W)`` reference volume and ``(T, H, W)`` movie that the benchmark and the
z-correction pipeline consume.

The filename convention matches the glob already used by
``modules.compute_zcorr.shift_zstack``:

    {folder.name}_Cycle{cycle:05d}_Ch{channel}_{index:06d}.ome.tif

Channel 2 is the functional channel used for both the z-stack and the movie
(``shift_zstack`` defaults to ``Ch: 2``), so the correlation in
``compute_zcorrel`` compares like-for-like contrast.
"""

import glob
import re
from pathlib import Path

import numpy as np
import tifffile
from skimage.measure import block_reduce


def _read_frame(path):
    """Read a single Bruker OME-TIFF frame as a 2-D array.

    The first file of each cycle carries the OME metadata for the whole series,
    so a plain ``imread`` on it returns every frame in the acquisition.
    ``is_ome=False`` restricts the read to the file's own page(s); we then
    squeeze to the last 2-D image if a stray page axis remains.
    """
    arr = tifffile.imread(path, is_ome=False)
    if arr.ndim > 2:
        arr = arr[0] if arr.shape[0] < arr.shape[-1] else arr.reshape(-1, *arr.shape[-2:])[0]
    return arr


def _downscale(img, factor):
    """Mean-pool an image (or last two axes of a stack) by an integer factor."""
    if factor == 1:
        return img
    if img.ndim == 2:
        block = (factor, factor)
    else:
        block = (1,) * (img.ndim - 2) + (factor, factor)
    return block_reduce(img, block_size=block, func=np.mean).astype(np.float32)


def parse_z_focus_um(xml_path):
    """Return the per-frame 'Z Focus' positions (microns) from a Bruker XML.

    Bruker writes one ``<SubindexedValue ... description="Z Focus">`` per frame
    (plus one in the acquisition header).  For a ZSeries these are the true
    axial positions of each plane; for a TSeries they are all identical.
    """
    text = Path(xml_path).read_text(errors="ignore")
    vals = re.findall(r'value="([-0-9.]+)"\s+description="Z Focus"', text)
    return np.array([float(v) for v in vals], dtype=np.float64)


def _list_channel_tifs(folder, channel, cycle=None):
    """Sorted list of OME-TIFFs for one channel in a Bruker folder."""
    folder = Path(folder)
    cyc = "*" if cycle is None else f"{cycle:05d}"
    pattern = f"{folder}/{folder.name}_Cycle{cyc}_Ch{channel}_*.ome.tif"
    files = sorted(glob.glob(pattern))
    return files


def load_bruker_zstack(folder, channel=2, downsample=1, max_planes=None):
    """Load a Bruker ZSeries folder into a reference volume.

    Parameters
    ----------
    folder : str or Path
        Path to the ``ZSeries-...`` directory.
    channel : int
        Acquisition channel (2 = functional, matches the TSeries and the
        ``shift_zstack`` default).
    downsample : int
        Integer spatial mean-pooling factor applied to each plane.
    max_planes : int or None
        If set, subsample the stack to at most this many evenly spaced planes
        (keeps the full axial range while shrinking the volume).

    Returns
    -------
    volume : ndarray, shape (Z, H, W), float32
    z_um : ndarray, shape (Z,), float64
        The 'Z Focus' micron position of each retained plane (may be empty if
        no XML sidecar is present).
    """
    folder = Path(folder)
    files = _list_channel_tifs(folder, channel, cycle=1)
    if not files:
        # Fall back to any cycle if Cycle00001 naming differs.
        files = _list_channel_tifs(folder, channel)
    if not files:
        raise FileNotFoundError(f"No Ch{channel} OME-TIFFs found in {folder}")

    xml_path = folder / f"{folder.name}.xml"
    z_um = parse_z_focus_um(xml_path) if xml_path.exists() else np.array([])
    # The header contributes one extra Z Focus entry; drop it if lengths differ.
    if len(z_um) == len(files) + 1:
        z_um = z_um[1:]

    idx = np.arange(len(files))
    if max_planes is not None and max_planes < len(files):
        idx = np.linspace(0, len(files) - 1, max_planes).round().astype(int)

    planes = [_downscale(_read_frame(files[i]).astype(np.float32), downsample) for i in idx]
    volume = np.stack(planes, axis=0)
    z_um = z_um[idx] if len(z_um) == len(files) else z_um
    return volume, z_um


def load_bruker_tseries(folder, channel=2, n_frames=None, downsample=1):
    """Load a Bruker TSeries folder into a functional movie.

    Frames are ordered by cycle then by within-cycle index (filename sort order,
    which matches acquisition order for zero-padded Bruker names).

    Parameters
    ----------
    folder : str or Path
    channel : int
    n_frames : int or None
        Keep only the first ``n_frames`` frames (handy for small runs).
    downsample : int
        Integer spatial mean-pooling factor.

    Returns
    -------
    movie : ndarray, shape (T, H, W), float32
    """
    folder = Path(folder)
    files = _list_channel_tifs(folder, channel)
    if not files:
        raise FileNotFoundError(f"No Ch{channel} OME-TIFFs found in {folder}")
    if n_frames is not None:
        files = files[:n_frames]
    frames = [_downscale(_read_frame(f).astype(np.float32), downsample) for f in files]
    return np.stack(frames, axis=0)
