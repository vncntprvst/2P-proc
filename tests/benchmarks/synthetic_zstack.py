"""
Synthetic 3D fluorescence data for z-motion correction benchmarks.

Conceptual model
----------------
Two-photon imaging acquires a 2D cross-section of a 3D tissue volume.
When the tissue moves in z, the imaged cross-section shifts to a different
depth, changing which neurons are in focus — not just translating the image.

Here we synthesise:
  1. A 3D fluorescence volume  (n_z_planes × H × W)
     Neurons are 3D Gaussians with a PSF-like shape: wide laterally,
     narrow axially (mimicking the 2P excitation PSF).

  2. A z-motion trajectory
     - Rigid: one z-offset per frame (same for all pixels)
     - Non-rigid: per-patch z-offsets, zero global mean per frame
       (different patches of the tissue drift in z independently)

  3. A synthetic functional movie
     Each frame is the 3D volume sampled at the z-position(s) dictated
     by the trajectory, via trilinear interpolation.
     Optionally add shot noise (Poisson).

The saved z-stack TIFF is pre-flipped along y so that compute_zcorrel's
internal y-flip leaves it correctly oriented relative to the movie.
"""

from pathlib import Path

import numpy as np
import tifffile
from scipy.ndimage import gaussian_filter, gaussian_filter1d, map_coordinates

# ──────────────────────────────────────────────────────────────────────────────
# Volume generation
# ──────────────────────────────────────────────────────────────────────────────


def make_3d_volume(
    n_z,
    height,
    width,
    n_cells=120,
    sigma_xy=6.0,
    sigma_z=1.5,
    bg_level=200.0,
    cell_brightness=2000.0,
    seed=42,
):
    """Generate a synthetic 3D fluorescence volume.

    Parameters
    ----------
    n_z : int
        Number of z-planes.
    height, width : int
        Spatial dimensions of each plane.
    n_cells : int
        Number of synthetic neurons.
    sigma_xy : float
        Lateral Gaussian radius in pixels.
    sigma_z : float
        Axial Gaussian radius in z-plane units. Should be < sigma_xy
        to reflect the narrower axial PSF of 2P microscopy.
    bg_level : float
        Constant background fluorescence added to every plane.
    cell_brightness : float
        Peak amplitude of each cell relative to background.
    seed : int

    Returns
    -------
    volume : ndarray, shape (n_z, height, width), float32
    cell_positions : ndarray, shape (n_cells, 3)  — (z, y, x) centers
    """
    rng = np.random.default_rng(seed)
    volume = np.full((n_z, height, width), bg_level, dtype=np.float32)

    margin_xy = int(3 * sigma_xy)
    margin_z = int(3 * sigma_z) + 1

    cz = rng.uniform(margin_z, n_z - margin_z, n_cells)
    cy = rng.uniform(margin_xy, height - margin_xy, n_cells)
    cx = rng.uniform(margin_xy, width - margin_xy, n_cells)
    amplitudes = rng.uniform(0.4, 1.0, n_cells) * cell_brightness

    zz, yy, xx = np.mgrid[0:n_z, 0:height, 0:width].astype(np.float32)

    for z0, y0, x0, amp in zip(cz, cy, cx, amplitudes):
        blob = amp * np.exp(
            -0.5
            * (
                ((zz - z0) / sigma_z) ** 2
                + ((yy - y0) / sigma_xy) ** 2
                + ((xx - x0) / sigma_xy) ** 2
            )
        )
        volume += blob.astype(np.float32)

    cell_positions = np.column_stack([cz, cy, cx])
    return volume, cell_positions


# ──────────────────────────────────────────────────────────────────────────────
# Z-motion trajectories
# ──────────────────────────────────────────────────────────────────────────────


def make_rigid_z_trajectory(n_frames, amplitude_planes, temporal_smoothness, seed=42):
    """Rigid per-frame z-offset (same across the whole FOV).

    Parameters
    ----------
    n_frames : int
    amplitude_planes : float
        RMS displacement in z-plane units.
    temporal_smoothness : float
        Gaussian sigma along the time axis. Larger = slower drift.

    Returns
    -------
    z_offsets : ndarray, shape (n_frames,), float32
        Ground-truth z-displacement for each frame (in z-plane units,
        centred on 0).
    """
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal(n_frames)
    smooth = gaussian_filter(raw, sigma=temporal_smoothness)
    smooth -= smooth.mean()
    smooth = smooth / smooth.std() * amplitude_planes
    return smooth.astype(np.float32)


def make_nonrigid_z_trajectory(
    n_frames,
    n_patches_y,
    n_patches_x,
    amplitude_planes,
    temporal_smoothness,
    spatial_smoothness=1.5,
    seed=42,
):
    """Non-rigid per-patch z-offsets with zero global mean per frame.

    The zero-mean constraint means a global (rigid) estimator should return
    near-zero, while a per-patch estimator should recover the local offsets.
    This is the key regime where non-rigid z-correction matters.

    Parameters
    ----------
    n_frames : int
    n_patches_y, n_patches_x : int
        Number of spatial patches in each dimension.
    amplitude_planes : float
        RMS displacement per patch in z-plane units.
    temporal_smoothness : float
        Gaussian sigma along the time axis.
    spatial_smoothness : float
        Gaussian sigma across patches (controls spatial correlation).

    Returns
    -------
    z_offsets : ndarray, shape (n_frames, n_patches_y, n_patches_x), float32
        Per-patch z-displacements, zero mean across patches at each frame.
    """
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal((n_frames, n_patches_y, n_patches_x))
    # Smooth in time and space
    smooth = gaussian_filter(
        raw, sigma=[temporal_smoothness, spatial_smoothness, spatial_smoothness]
    )
    # Remove global mean at each frame (enforce zero-mean non-rigid motion)
    smooth -= smooth.mean(axis=(1, 2), keepdims=True)
    # Normalise amplitude: mean std across patches
    std_per_frame = smooth.std(axis=(1, 2)).mean()
    if std_per_frame > 0:
        smooth = smooth / std_per_frame * amplitude_planes
    return smooth.astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# Lateral (x/y) motion and anisotropic deformation
# ──────────────────────────────────────────────────────────────────────────────


def make_xy_trajectory(n_frames, amplitude_px, temporal_smoothness, seed=42):
    """Rigid lateral (y, x) translation per frame, in pixels.

    Real z-motion is never purely axial: the sample also drifts laterally.
    compute_zcorrel registers each z-plane to the FOV before correlating, so a
    faithful benchmark must include this in-plane motion for the estimator to
    contend with.

    Returns
    -------
    xy_offsets : ndarray, shape (n_frames, 2), float32  — (dy, dx) per frame.
    """
    rng = np.random.default_rng(seed + 1)
    out = np.zeros((n_frames, 2), dtype=np.float32)
    for k in range(2):
        raw = rng.standard_normal(n_frames)
        s = gaussian_filter(raw, sigma=temporal_smoothness)
        s -= s.mean()
        if s.std() > 0:
            s = s / s.std() * amplitude_px
        out[:, k] = s
    return out


def _deformation_field(H, W, amplitude_px, scale_px, rng):
    """Smooth per-pixel (dy, dx) elastic displacement field.

    A low-spatial-frequency random field warps the frame anisotropically —
    modelling non-uniform in-plane tissue deformation that a rigid shift cannot
    capture.
    """
    dy = gaussian_filter(rng.standard_normal((H, W)), sigma=scale_px)
    dx = gaussian_filter(rng.standard_normal((H, W)), sigma=scale_px)
    for f in (dy, dx):
        if f.std() > 0:
            f *= amplitude_px / f.std()
    return dy.astype(np.float32), dx.astype(np.float32)


def _wave_deformation_field(yy, xx, amplitude_px, wavelength_px, direction, phase):
    """Traveling-wave (dy, dx) displacement field.

    Real tissue deformation during motion propagates as a wave rather than
    warping incoherently. This is a longitudinal plane wave: pixels are displaced
    along ``direction`` by ``amplitude_px * sin(k·r - phase)``; advancing ``phase``
    across frames makes the deformation travel across the FOV.
    """
    diry, dirx = direction
    proj = (yy * diry + xx * dirx) * (2.0 * np.pi / wavelength_px)
    disp = amplitude_px * np.sin(proj - phase)
    return (disp * diry).astype(np.float32), (disp * dirx).astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# Movie generation
# ──────────────────────────────────────────────────────────────────────────────


def _sample_fields(volume, z_field, y_field, x_field):
    """Trilinear interpolation of volume at per-pixel (z, y, x) coordinates.

    Parameters
    ----------
    volume : ndarray, shape (n_z, H, W)
    z_field, y_field, x_field : ndarray, shape (H, W)
        Sampling coordinate for every pixel.

    Returns
    -------
    frame : ndarray, shape (H, W), float32
    """
    H, W = z_field.shape
    coords = np.array([z_field.ravel(), y_field.ravel(), x_field.ravel()])
    frame = map_coordinates(volume, coords, order=1, mode="nearest", prefilter=False)
    return frame.reshape(H, W).astype(np.float32)


def _sample_at_z_field(volume, z_field):
    """Trilinear interpolation at spatially varying z (no lateral warp)."""
    n_z, H, W = volume.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    return _sample_fields(volume, z_field, yy, xx)


def make_functional_movie(
    volume,
    z_nominal,
    z_offsets,
    patch_size_y=None,
    patch_size_x=None,
    xy_offsets=None,
    deform_amp=0.0,
    deform_scale=None,
    deform_wave=False,
    wave_wavelength=None,
    wave_period=12.0,
    noise_factor=0.02,
    seed=42,
):
    """Generate a synthetic functional movie from a 3D volume.

    Supports rigid and non-rigid z-motion, optional rigid lateral (x/y)
    translation, and optional anisotropic in-plane deformation.

    Parameters
    ----------
    volume : ndarray, shape (n_z, H, W)
    z_nominal : float
        Nominal focal plane index (centre of the z-stack range).
    z_offsets : ndarray
        Shape (T,) for rigid motion, or
        shape (T, n_patches_y, n_patches_x) for non-rigid motion.
    patch_size_y, patch_size_x : int or None
        When z_offsets is non-rigid, defines the pixel size of each
        spatial patch. If None, inferred from volume shape / n_patches.
    xy_offsets : ndarray, shape (T, 2) or None
        Per-frame rigid lateral (dy, dx) translation in pixels.
    deform_amp : float
        RMS amplitude (pixels) of a per-frame anisotropic elastic warp.
        0 disables deformation.
    deform_scale : float or None
        Spatial correlation length (pixels) of the deformation field.
        Defaults to H / 8.
    noise_factor : float
        Gaussian noise amplitude as a fraction of mean signal.
    seed : int

    Returns
    -------
    movie : ndarray, shape (T, H, W), float32
    z_field_per_frame : ndarray, shape (T, H, W), float32
        The exact z-position for every pixel in every frame (ground truth).
    """
    rng = np.random.default_rng(seed)
    n_z, H, W = volume.shape
    rigid = z_offsets.ndim == 1
    T = z_offsets.shape[0]
    if deform_scale is None:
        deform_scale = H / 8.0
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    # Traveling-wave deformation set-up: a fixed random propagation direction and
    # wavelength; amplitude is modulated by the instantaneous motion (deformation
    # rides on movement) with a small always-on floor.
    if deform_wave:
        if wave_wavelength is None:
            wave_wavelength = H / 1.5
        ang = rng.uniform(0, 2 * np.pi)
        wave_dir = (np.sin(ang), np.cos(ang))
        motion = z_offsets if rigid else z_offsets.reshape(T, -1).mean(axis=1)
        vel = np.abs(np.gradient(motion.astype(np.float32)))
        vel = gaussian_filter1d(vel, sigma=2.0)
        wave_env = 0.3 + 0.7 * (vel / (vel.max() + 1e-9))  # (T,) in [0.3, 1]

    if not rigid:
        n_py, n_px = z_offsets.shape[1], z_offsets.shape[2]
        if patch_size_y is None:
            patch_size_y = H // n_py
        if patch_size_x is None:
            patch_size_x = W // n_px

    movie = np.empty((T, H, W), dtype=np.float32)
    z_field_per_frame = np.empty((T, H, W), dtype=np.float32)

    for t in range(T):
        if rigid:
            z_field = np.full((H, W), z_nominal + z_offsets[t], dtype=np.float32)
        else:
            # Build a per-pixel z-field by upsampling patch offsets
            patch_map = np.zeros((H, W), dtype=np.float32)
            for py in range(n_py):
                for px in range(n_px):
                    y0 = py * patch_size_y
                    y1 = min(y0 + patch_size_y, H)
                    x0 = px * patch_size_x
                    x1 = min(x0 + patch_size_x, W)
                    patch_map[y0:y1, x0:x1] = z_offsets[t, py, px]
            # Smooth the patch boundaries for a physically realistic field
            patch_map = gaussian_filter(patch_map, sigma=patch_size_y / 4)
            z_field = (z_nominal + patch_map).astype(np.float32)

        # Clip to valid z-range (with half-plane margin for interpolation)
        np.clip(z_field, 0.5, n_z - 1.5, out=z_field)

        # Lateral sampling coordinates: base grid + rigid shift + elastic warp
        y_field, x_field = yy, xx
        if xy_offsets is not None:
            y_field = yy + xy_offsets[t, 0]
            x_field = xx + xy_offsets[t, 1]
        if deform_amp > 0:
            if deform_wave:
                phase = 2.0 * np.pi * t / wave_period
                dy, dx = _wave_deformation_field(
                    yy, xx, deform_amp * wave_env[t], wave_wavelength, wave_dir, phase
                )
            else:
                dy, dx = _deformation_field(H, W, deform_amp, deform_scale, rng)
            y_field = y_field + dy
            x_field = x_field + dx
        if xy_offsets is not None or deform_amp > 0:
            y_field = np.clip(y_field, 0, H - 1)
            x_field = np.clip(x_field, 0, W - 1)

        z_field_per_frame[t] = z_field
        frame = _sample_fields(volume, z_field, y_field, x_field)

        if noise_factor > 0:
            noise = rng.normal(0, noise_factor * frame.mean(), frame.shape)
            frame = np.clip(frame + noise, 0, None).astype(np.float32)

        movie[t] = frame

    return movie, z_field_per_frame


# ──────────────────────────────────────────────────────────────────────────────
# File I/O helpers
# ──────────────────────────────────────────────────────────────────────────────


def save_zstack_tiff(volume, path):
    """Save 3D volume as a multi-page TIFF.

    Pre-flips along the y-axis so that compute_zcorrel's internal y-flip
    restores the correct orientation relative to the functional movie.

    Parameters
    ----------
    volume : ndarray, shape (n_z, H, W)
    path : str or Path
    """
    # compute_zcorrel does: Z_stack = np.flip(Z_stack, axis=1)
    # Pre-flip so that after compute_zcorrel's flip the stack is correct.
    to_save = np.flip(volume.astype(np.uint16), axis=1)
    tifffile.imwrite(str(path), to_save, photometric="minisblack")


def save_caiman_memmap(movie, out_dir, base_name="Yr"):
    """Save a movie as a CaImAn-format memmap file.

    The filename encodes shape in the CaImAn convention so that
    caiman.mmapping.load_memmap can read it back.

    Parameters
    ----------
    movie : ndarray, shape (T, H, W), float32
    out_dir : str or Path
    base_name : str

    Returns
    -------
    fpath : Path
    """
    T, H, W = movie.shape
    fname = f"{base_name}_d1_{H}_d2_{W}_d3_1_order_F_frames_{T}_.mmap"
    fpath = Path(out_dir) / fname
    # CaImAn layout: float32, shape (H*W, T), Fortran column-major pixel order
    mmap = np.memmap(fpath, dtype=np.float32, mode="w+", shape=(H * W, T), order="F")
    for t in range(T):
        mmap[:, t] = movie[t].ravel(order="F")
    mmap.flush()
    del mmap
    return fpath
