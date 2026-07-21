# Synthetic z-motion dataset

Ground-truth functional movie for z-motion-correction validation. NAOMi-lite: real anatomy from `ZSeries-10022023-1300-004` (Ch2, 2x downsampled) as the volume, 60 somata detected near the focal plane, injected with **heterogeneous** spike->AR(1) GCaMP activity (skewed per-cell amplitudes, variable response reliability, spontaneous background + shot noise — not uniform 'light bulbs'), sampled along a **known** 3D trajectory. An axial-Gaussian gain models defocus, so z-motion attenuates cells (the artifact to correct).

The z-motion is a **staircase** (discrete plane dwells + transitions, like a real z-position estimate) that is **response-coupled**: downward steps onset at or just before the 20 stimulus responses (probability weighted by population response strength), so brain motion co-occurs with responses (activity-z coupling r = -0.39), as in the real protocol. In-plane tissue deformation is a propagating wave riding on the motion.

## Files
- `synthetic_movie.tif` — the functional movie (T, Y, X), uint16, shared display scale.
- `synthetic_baseline.tif` — same motion, NO activity (the oracle F_anat predictor).
- `synthetic_anatomy.tif` — the real z-stack volume (Z, Y, X).
- `synthetic_ground_truth.npz` — trueC/trueS, cell_centers (z,y,x), responsive mask, z_true (per-frame focal plane), zoff, events, framerate.

The `.tif` is uint16-scaled for viewing; use the npz for exact ground truth.
