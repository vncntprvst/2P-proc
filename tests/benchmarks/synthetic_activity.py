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
    deform_wave=False,
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

    # Baseline anatomy under the imposed 3D motion (no activity, no noise yet).
    # ``z_field`` is the per-pixel absolute focal plane (T, H, W) — for rigid
    # z_offsets it is uniform across the frame; for non-rigid (per-patch) z it
    # varies spatially, so each cell sees its own local focal plane.
    movie, z_field = make_functional_movie(
        volume,
        z_nominal,
        z_offsets,
        xy_offsets=xy_offsets,
        deform_amp=deform_amp,
        deform_wave=deform_wave,
        noise_factor=0.0,
        seed=seed,
    )

    T = movie.shape[0]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    z_local = np.zeros((len(cell_centers), T), np.float32)  # per-cell local focal plane

    for c, (zc, yc, xc) in enumerate(cell_centers):
        footprint = np.exp(-0.5 * (((yy - yc) / sigma_xy) ** 2 + ((xx - xc) / sigma_xy) ** 2))
        footprint = footprint.astype(np.float32)
        # Local focal plane at this cell's location (non-rigid aware).
        lz = z_field[:, int(yc), int(xc)]
        z_local[c] = lz
        axial_gain = np.exp(-0.5 * ((lz - zc) / sigma_z) ** 2).astype(np.float32)  # (T,)
        # Outer product (T,) x (H,W) added frame-by-frame, activity-weighted.
        contrib = activity_gain * trueC[c] * axial_gain  # (T,)
        movie += contrib[:, None, None] * footprint[None]

    if noise_factor > 0:
        # Shot noise (∝ √signal, the dominant 2P noise) + a read-noise floor, so
        # dim cells sit near the noise floor and bright ones are cleaner — as in
        # real recordings, rather than a uniform additive blur.
        scale = noise_factor * movie.mean()
        shot = rng.normal(0, 1, movie.shape).astype(np.float32) * np.sqrt(np.clip(movie, 0, None))
        movie += 3.0 * noise_factor * shot + rng.normal(0, scale, movie.shape).astype(np.float32)
        np.clip(movie, 0, None, out=movie)

    ground_truth = {
        "trueC": trueC.astype(np.float32),
        "cell_centers": np.asarray(cell_centers, dtype=int),
        # Global reference focal plane (mean over the FOV) for backward compatibility.
        "z_true": z_field.reshape(T, -1).mean(axis=1).astype(np.float32),
        # Per-cell local focal plane (T per cell) — the z-plane of each cell's patch.
        "z_local": z_local,
        # Full per-pixel focal-plane field (T, H, W).
        "z_field": z_field.astype(np.float32),
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
    resp_fraction=0.65,
    event_jitter=3,
    seed=42,
):
    """Heterogeneous population responses time-locked to stimulus events.

    Real calcium populations are not uniform "light bulbs": transient amplitudes
    are heavy-tailed (many small, few large), cells respond to the stimulus with
    very different reliabilities, and each cell has its own spontaneous rate. This
    models that gamut so the synthetic benchmark is discriminating rather than
    trivially high-SNR:

    - ``responsive`` : a subset of cells participate in the stimulus at all.
    - per-cell ``reliability`` ~ U(0.1, 0.9): fraction of events a cell responds to.
    - per-cell ``gain`` ~ log-normal (skewed): sets each cell's typical amplitude,
      so some cells are always dim and a few are strong.
    - per-event amplitude jitter (log-normal): the same cell varies event to event.
    - per-cell spontaneous ``bg_rate`` ~ U(0.02, 0.5) Hz of small background spikes.

    Returns
    -------
    trueC : (n_cells, n_frames) float32   ground-truth calcium
    trueS : (n_cells, n_frames) float32   spikes
    events : (n_events,) int              stimulus onset frames
    responsive : (n_cells,) bool          which cells respond to the stimulus
    event_weights : (n_events,) float32   population response strength per event
                                          (0-1), for response-coupled z-motion
    """
    rng = np.random.default_rng(seed)
    gamma = np.exp(-1.0 / (decay_time * framerate))
    margin = int(0.05 * n_frames) + 5
    events = np.linspace(margin, n_frames - margin, n_events).round().astype(int)

    responsive = rng.random(n_cells) < resp_fraction
    reliability = rng.uniform(0.1, 0.9, n_cells)
    gain = rng.lognormal(mean=-0.3, sigma=0.7, size=n_cells).astype(np.float32)  # skewed
    bg_rate = rng.uniform(0.02, 0.5, n_cells)

    trueS = np.zeros((n_cells, n_frames), np.float32)
    # Spontaneous background: small, sparse, per-cell rate.
    for c in range(n_cells):
        sp = np.where(rng.random(n_frames) < bg_rate[c] / framerate)[0]
        if len(sp):
            trueS[c, sp] += gain[c] * rng.lognormal(-0.7, 0.5, len(sp)).astype(np.float32)

    # Stimulus-evoked, per-cell reliability and per-event amplitude variability.
    event_amp = np.zeros(len(events), np.float32)
    for c in np.where(responsive)[0]:
        for ei, e in enumerate(events):
            if rng.random() < reliability[c]:
                t = int(np.clip(e + rng.integers(-event_jitter, event_jitter + 1), 0, n_frames - 1))
                amp = float(gain[c] * rng.lognormal(0.0, 0.5))
                trueS[c, t] += amp
                event_amp[ei] += amp

    trueC = trueS.copy()
    for t in range(1, n_frames):
        trueC[:, t] += gamma * trueC[:, t - 1]

    event_weights = (event_amp / (event_amp.max() + 1e-9)).astype(np.float32)
    return trueC.astype(np.float32), trueS, events, responsive, event_weights


def make_response_coupled_zmotion(
    n_frames,
    events,
    base_zoff=None,
    framerate=20.0,
    kick_amp=1.8,
    kick_prob=0.85,
    kick_dwell=0.5,
    kick_settle=0.4,
    kick_lead=2,
    event_jitter=2,
    step_rate=0.015,
    max_excursion=3.0,
    event_weights=None,
    quantize=True,
    seed=42,
):
    """Response-coupled z-trajectory shaped like a real z-position estimate.

    Real brain z-motion during behaviour is not a smooth ramp: the sample dwells
    near a plane and makes discrete transitions, so an estimated z-position reads
    as a **staircase**. This builds that shape:

    1. A dwell-and-step background random walk (occasional ±1-plane transitions at
       rate ``step_rate``, bounded to ``±max_excursion``).
    2. Response kicks: at each event, with probability ``kick_prob``, a **downward**
       displacement of ~``kick_amp`` planes that onsets near the event, **holds**
       for ``kick_dwell`` s, then steps back over ``kick_settle`` s — the animal
       reacts, the brain displaces and settles (not an exponential spike).
    3. Optional ``base_zoff`` (e.g. a real estimated zpos) added as extra drift.

    The result is quantized to integer planes (``quantize=True``) so it looks like
    a real staircase z-trace, then centred on 0.

    Returns z_offsets : (n_frames,) float32.
    """
    rng = np.random.default_rng(seed + 2)
    zoff = np.zeros(n_frames, np.float32)

    # 1. Dwell-and-step background (staircase random walk).
    cur = 0.0
    for t in range(1, n_frames):
        if rng.random() < step_rate:
            cur = float(np.clip(cur + rng.choice([-1.0, 1.0]), -max_excursion, max_excursion))
        zoff[t] = cur

    # 2. Response kicks: downward hold-and-return pulses whose onset is at or just
    #    BEFORE the response (kick_lead frames early) — the animal reacts, the brain
    #    displaces as the cells fire. Stronger population responses (event_weights)
    #    are more likely to trigger a kick and kick a little harder.
    dwell = max(1, int(round(kick_dwell * framerate)))
    settle = max(1, int(round(kick_settle * framerate)))
    for ei, e in enumerate(events):
        w = 1.0 if event_weights is None else float(event_weights[ei])
        if rng.random() < kick_prob * (0.4 + 0.6 * w):
            t0 = int(
                np.clip(
                    e - kick_lead + rng.integers(-event_jitter, event_jitter + 1), 0, n_frames - 1
                )
            )
            amp = -abs(kick_amp) * (0.6 + 0.5 * w) * rng.uniform(0.8, 1.1)  # downward, weighted
            hi = min(t0 + dwell, n_frames)
            zoff[t0:hi] += amp
            for k, t in enumerate(range(hi, min(hi + settle, n_frames))):
                zoff[t] += amp * (1.0 - (k + 1) / settle)  # step back to baseline

    # 3. Optional real-zpos background drift.
    if base_zoff is not None:
        b = np.asarray(base_zoff, np.float32)[:n_frames]
        zoff[: len(b)] += b - b.mean()

    # 4. Quantize to integer planes for the staircase look, then centre.
    if quantize:
        zoff = np.round(zoff)
    return (zoff - zoff.mean()).astype(np.float32)
