# Synthetic z-motion dataset

Ground-truth functional movie for z-motion-correction validation. NAOMi-lite: real anatomy from `ZSeries-10022023-1300-004` (Ch2, 2x downsampled) as the volume, 60 somata detected near the focal plane, injected with spike->AR(1) GCaMP activity, sampled along a **known** 3D trajectory (rigid z + xy jitter + mild deformation). An axial-Gaussian gain models defocus, so z-motion attenuates cells (the artifact to correct).

The z-motion is **response-coupled**: downward (negative) displacement onsets cluster around 20 stimulus events, so brain motion co-occurs with responses (activity-z coupling r = -0.31), as in the real protocol.

## Files
- `synthetic_movie.tif` — the functional movie (T, Y, X), uint16, shared display scale.
- `synthetic_baseline.tif` — same motion, NO activity (the oracle F_anat predictor).
- `synthetic_anatomy.tif` — the real z-stack volume (Z, Y, X).
- `synthetic_ground_truth.npz` — trueC/trueS, cell_centers (z,y,x), responsive mask, z_true (per-frame focal plane), zoff, events, framerate.

The `.tif` is uint16-scaled for viewing; use the npz for exact ground truth.
