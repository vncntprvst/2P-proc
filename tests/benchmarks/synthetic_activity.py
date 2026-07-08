"""
Inject synthetic calcium activity into a real z-stack to build a ground-truth
functional movie for z-motion correction benchmarking.

Approach (grounded in established methods, not invented)
--------------------------------------------------------
The lightweight, community-standard way to synthesise calcium imaging data is:
a Poisson **spike train** convolved with a **GCaMP calcium kernel** (an AR(1)
exponential decay set by the indicator's decay time) to make each cell's ΔF/F,
multiplied by a spatial footprint. This is exactly what CaImAn's
``caiman.utils.utils.gen_data`` does (``gamma = exp(-1/(tau*framerate))``), and
what MLspike / the Suite2p benchmarks use.

The full-physics reference is NAOMi (Song et al., J. Neurosci. Methods 2021),
which simulates a *synthetic* cortical volume + PSF + scanning **including axial
sample motion**. We take a "NAOMi-lite" hybrid that is more faithful to this
microscope's tissue: use the **real ZSeries** as the anatomical volume, detect
real somata in it, inject standard spike→GCaMP activity into them, and sample
the volume along a known 3D trajectory. Because each cell's contribution is
gated by how close the focal plane is to its depth (an axial Gaussian ≈ the 2P
PSF), z-motion defocuses cells and thereby modulates their apparent activity —
reproducing the z-motion artifact we want to correct. The injected traces are
the ground truth to recover.

References
----------
- Song et al. 2021, "Neural Anatomy and Optical Microscopy (NAOMi) simulation",
  J. Neurosci. Methods (axial motion + ground-truth activity).
- CaImAn ``caiman.utils.utils.gen_data`` (spike→AR(1) calcium model).
- Deneux et al. 2016 (MLspike) — Ca–GECI generative model.
"""

import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.feature import peak_local_max

from tests.benchmarks.synthetic_zstack import make_functional_movie


def detect_somata(
    volume,
    n_cells=40,
    min_distance=6,
    dog_sigma=(1.5, 3.0),
    margin=6,
    z_center=None,
    z_band=None,
    seed=42,
):
    """Locate bright somata in a 3D volume via difference-of-Gaussians peaks.

    Parameters
    ----------
    volume : ndarray (Z, H, W)
    n_cells : int          Keep the N brightest detected peaks.
    min_distance : int     Minimum spacing (px) between peaks (lateral).
    dog_sigma : (float, float)  (small, large) Gaussian sigmas for the DoG
        soma enhancement, in (axial, lateral) units applied per axis.
    margin : int           Reject peaks within this many px of any border.
    z_center, z_band : float or None
        Restrict detected somata to ``|z - z_center| <= z_band``. A single-plane
        T-series only records cells near its focal depth, so the benchmark passes
        the nominal focal plane here; cells far from it never appear in-focus and
        would otherwise drag down the ground-truth recovery.

    Returns
    -------
    centers : ndarray (n, 3) int  — (z, y, x) soma centers, brightness-sorted.
    """
    vol = volume.astype(np.float32)
    s_small = (dog_sigma[0], dog_sigma[1], dog_sigma[1])
    s_large = (dog_sigma[0] * 2, dog_sigma[1] * 2, dog_sigma[1] * 2)
    dog = gaussian_filter(vol, s_small) - gaussian_filter(vol, s_large)

    peaks = peak_local_max(dog, min_distance=min_distance, exclude_border=margin, threshold_rel=0.2)
    if len(peaks) == 0:
        return np.empty((0, 3), dtype=int)
    if z_center is not None and z_band is not None:
        peaks = peaks[np.abs(peaks[:, 0] - z_center) <= z_band]
        if len(peaks) == 0:
            return np.empty((0, 3), dtype=int)
    # Sort by DoG response (brightest somata first) and keep the top N.
    order = np.argsort(dog[tuple(peaks.T)])[::-1]
    peaks = peaks[order[:n_cells]]
    return peaks.astype(int)


def make_calcium_traces(
    n_cells, n_frames, framerate=20.0, decay_time=0.15, firerate=0.5, amp_range=(0.5, 1.5), seed=42
):
    """Poisson spikes → AR(1) GCaMP calcium traces (CaImAn gen_data model).

    Parameters
    ----------
    decay_time : float   Indicator decay τ in seconds (config's ``decay_time``).
    firerate : float     Mean spikes/second per cell.
    amp_range : (lo, hi) Per-cell transient amplitude multiplier (ΔF/F scale).

    Returns
    -------
    trueC : ndarray (n_cells, n_frames) float32  — calcium (ground-truth activity)
    trueS : ndarray (n_cells, n_frames) float32  — spikes
    """
    rng = np.random.default_rng(seed)
    gamma = np.exp(-1.0 / (decay_time * framerate))
    trueS = (rng.random((n_cells, n_frames)) < firerate / framerate).astype(np.float32)
    trueS[:, 0] = 0.0
    amps = rng.uniform(amp_range[0], amp_range[1], n_cells).astype(np.float32)
    trueC = trueS * amps[:, None]
    for t in range(1, n_frames):
        trueC[:, t] += gamma * trueC[:, t - 1]
    return trueC, trueS


def make_active_functional_movie(
    volume,
    z_nominal,
    z_offsets,
    cell_centers,
    trueC,
    xy_offsets=None,
    deform_amp=0.0,
    sigma_xy=4.0,
    sigma_z=2.0,
    activity_gain=800.0,
    noise_factor=0.02,
    seed=42,
):
    """Build a functional movie = real anatomy under z-motion + injected activity.

    The static anatomy (including somata baseline) is sampled from the volume at
    the imposed z-trajectory via ``make_functional_movie``. On top, each cell
    adds ``activity_gain * trueC[c, t] * footprint2D * axial_gain`` where
    ``axial_gain = exp(-0.5*((z(t) - z_cell)/sigma_z)^2)`` — so a transient is
    only fully visible when the focal plane sits on the cell, and z-motion both
    dims the baseline and attenuates the transient (the artifact).

    Parameters
    ----------
    volume : ndarray (Z, H, W)
    z_nominal : float           Nominal focal plane index.
    z_offsets : ndarray (T,)    Rigid per-frame z-offset (from make_rigid_z_trajectory).
    cell_centers : ndarray (n, 3)  (z, y, x) from detect_somata.
    trueC : ndarray (n, T)      Ground-truth calcium traces.
    sigma_xy, sigma_z : float   Lateral / axial footprint radii (px / planes).
    activity_gain : float       ΔF amplitude of activity in raw intensity units.

    Returns
    -------
    movie : ndarray (T, H, W) float32
    ground_truth : dict with 'trueC', 'cell_centers', 'z_true' (per-frame focal plane)
    """
    rng = np.random.default_rng(seed + 7)
    n_z, H, W = volume.shape
    T = z_offsets.shape[0]

    # Baseline anatomy under the imposed 3D motion (no activity, no noise yet).
    movie, _ = make_functional_movie(
        volume,
        z_nominal,
        z_offsets,
        xy_offsets=xy_offsets,
        deform_amp=deform_amp,
        noise_factor=0.0,
        seed=seed,
    )

    z_focal = z_nominal + z_offsets  # (T,) rigid focal plane per frame
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    for c, (zc, yc, xc) in enumerate(cell_centers):
        footprint = np.exp(-0.5 * (((yy - yc) / sigma_xy) ** 2 + ((xx - xc) / sigma_xy) ** 2))
        footprint = footprint.astype(np.float32)
        axial_gain = np.exp(-0.5 * ((z_focal - zc) / sigma_z) ** 2).astype(np.float32)  # (T,)
        # Outer product (T,) x (H,W) added frame-by-frame, activity-weighted.
        contrib = activity_gain * trueC[c] * axial_gain  # (T,)
        movie += contrib[:, None, None] * footprint[None]

    if noise_factor > 0:
        movie += rng.normal(0, noise_factor * movie.mean(), movie.shape).astype(np.float32)
        np.clip(movie, 0, None, out=movie)

    ground_truth = {
        "trueC": trueC.astype(np.float32),
        "cell_centers": np.asarray(cell_centers, dtype=int),
        "z_true": z_focal.astype(np.float32),
    }
    return movie.astype(np.float32), ground_truth


# ──────────────────────────────────────────────────────────────────────────────
# Stimulus/response-locked activity and motion (realistic coupling)
# ──────────────────────────────────────────────────────────────────────────────


def make_stimulus_locked_traces(
    n_cells,
    n_frames,
    framerate=20.0,
    decay_time=0.15,
    n_events=12,
    resp_fraction=0.6,
    resp_prob=0.8,
    event_jitter=3,
    amp_range=(0.8, 2.0),
    background_rate=0.2,
    seed=42,
):
    """Population responses time-locked to stimulus events + background firing.

    Mimics a stimulus protocol: at each event a responsive subset of cells fires
    (near the event, with jitter), on top of low background Poisson activity.

    Returns
    -------
    trueC : (n_cells, n_frames) float32   ground-truth calcium
    trueS : (n_cells, n_frames) float32   spikes
    events : (n_events,) int              stimulus/response onset frames
    responsive : (n_cells,) bool          which cells respond to the stimulus
    """
    rng = np.random.default_rng(seed)
    gamma = np.exp(-1.0 / (decay_time * framerate))
    margin = int(0.05 * n_frames) + 5
    events = np.linspace(margin, n_frames - margin, n_events).round().astype(int)
    trueS = (rng.random((n_cells, n_frames)) < background_rate / framerate).astype(np.float32)
    responsive = rng.random(n_cells) < resp_fraction
    for c in np.where(responsive)[0]:
        for e in events:
            if rng.random() < resp_prob:
                t = int(np.clip(e + rng.integers(-event_jitter, event_jitter + 1), 0, n_frames - 1))
                trueS[c, t] += rng.uniform(*amp_range)
    trueC = trueS.copy()
    for t in range(1, n_frames):
        trueC[:, t] += gamma * trueC[:, t - 1]
    return trueC.astype(np.float32), trueS, events, responsive


def make_response_coupled_zmotion(
    n_frames,
    events,
    base_zoff=None,
    framerate=20.0,
    kick_amp=3.0,
    kick_prob=0.8,
    kick_tau=0.4,
    kick_delay=1,
    event_jitter=2,
    seed=42,
):
    """z-trajectory whose (downward) movement onsets cluster around response events.

    Real brain motion is not random: the animal reacts to the stimulus, so z tends
    to move (downward) around response onset. Each event triggers, with probability
    `kick_prob`, a downward (negative) displacement that onsets near the event and
    decays with `kick_tau`. An optional `base_zoff` (e.g. a real estimated zpos) is
    added as the ongoing background fluctuation.

    Returns z_offsets : (n_frames,) float32  (centred on 0).
    """
    rng = np.random.default_rng(seed + 2)
    zoff = np.zeros(n_frames, np.float32)
    if base_zoff is not None:
        b = np.asarray(base_zoff, np.float32)[:n_frames]
        zoff[: len(b)] = b - b.mean()
    gamma = np.exp(-1.0 / (kick_tau * framerate))
    for e in events:
        if rng.random() < kick_prob:
            t0 = int(
                np.clip(
                    e + kick_delay + rng.integers(-event_jitter, event_jitter + 1), 0, n_frames - 1
                )
            )
            amp = -abs(kick_amp) * rng.uniform(0.6, 1.2)  # downward = negative
            kick = np.zeros(n_frames, np.float32)
            kick[t0] = amp
            for t in range(t0 + 1, n_frames):
                kick[t] = gamma * kick[t - 1]
            zoff += kick
    return (zoff - zoff.mean()).astype(np.float32)
