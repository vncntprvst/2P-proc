"""Non-rigid deformation between two sessions' mean images (run inside the track2p venv).

Elastix affine registration of image 2 onto image 1, then B-spline registration starting
from the affine result; the B-spline deformation field (displacement beyond affine) is
summarised as RMS / 95th-percentile magnitude inside the brain mask (mean image above its
20th percentile).

Usage: python deformation_between_days.py <img1.npy> <img2.npy> <um_per_px> <out.npz>
"""

import sys

import itk
import numpy as np


def main():
    f1, f2, um, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    a, b = np.load(f1).astype(np.float32), np.load(f2).astype(np.float32)
    fixed, moving = itk.GetImageFromArray(a), itk.GetImageFromArray(b)
    po = itk.ParameterObject.New()
    po.AddParameterMap(po.GetDefaultParameterMap("affine"))
    aff_img, aff_params = itk.elastix_registration_method(fixed, moving, parameter_object=po)
    po2 = itk.ParameterObject.New()
    po2.AddParameterMap(po2.GetDefaultParameterMap("bspline"))
    nr_img, nr_params = itk.elastix_registration_method(fixed, aff_img, parameter_object=po2)
    field = itk.GetArrayFromImage(itk.transformix_deformation_field(aff_img, nr_params))  # (Ly, Lx, 2) px
    mag = np.linalg.norm(field, axis=2) * um
    mask = a > np.percentile(a, 20)
    aff = np.array(aff_params.GetParameter(0, "TransformParameters"), float)
    corr = lambda x, y: float(np.corrcoef(x[mask], y[mask])[0, 1])  # noqa: E731
    np.savez(out, field=field, mag_um=mag, affine=aff,
             rms_um=float(np.sqrt((mag[mask] ** 2).mean())), p95_um=float(np.percentile(mag[mask], 95)),
             corr_raw=corr(a, b), corr_affine=corr(a, itk.GetArrayFromImage(aff_img)),
             corr_nonrigid=corr(a, itk.GetArrayFromImage(nr_img)))


if __name__ == "__main__":
    main()
