import numpy as np
from pathlib import Path
from tifffile import TiffWriter

from Mesmerize.compute_zcorr import save_mmap_movie, subtract_z_motion_patches

def download_test_data():
    # This function is a placeholder for downloading test data.
    # In practice, you would implement the logic to download or prepare the test data.
    raise NotImplementedError("Test data download not implemented.")

def create_test_data(tmp_path: Path):
    Ny, Nx, Nz = 8, 8, 4
    Nframe = 5
    # random zstack
    zstack = (np.random.rand(Ny, Nx, Nz) * 255).astype(np.uint16)
    zstack_file = tmp_path / "zstack.tiff"
    with TiffWriter(zstack_file) as t:
        for i in range(Nz):
            t.write(zstack[:, :, i])
    # create functional movie following a z drift trajectory
    zpos = np.random.randint(0, Nz, size=Nframe)
    movie = np.stack([zstack[:, :, zpos[f]] for f in range(Nframe)], axis=0).astype(np.float32)
    movie += np.random.normal(scale=5, size=movie.shape)
    movie_path = save_mmap_movie(movie, tmp_path / "func.mmap")
    z_correlation = {"zpos": zpos.astype(np.uint16), "zcorr": np.zeros((Nz, Nframe), dtype=np.float32)}
    mcorr_params = {"strides": (4, 4), "overlaps": (0, 0)}
    return movie_path, zstack_file, z_correlation, mcorr_params, movie, zstack, zpos


def test_subtract_z_motion_patches(tmp_path):
    (movie_path, zstack_file, zcorr, mcorr_params, movie, zstack, zpos) = create_test_data(tmp_path)
    corrected, _ = subtract_z_motion_patches(
        movie_path,
        zstack_file,
        zcorr,
        mcorr_params,
        subtract_method="huber_regression_pixels",
        save_tiffs=False,
        save_correl=False,
    )
    # compute mean correlation to anatomical plane before and after correction
    before = []
    after = []
    for i in range(len(zpos)):
        plane = zstack[:, :, zpos[i]].astype(np.float32)
        before.append(np.corrcoef(movie[i].ravel(), plane.ravel())[0, 1])
        after.append(np.corrcoef(corrected[i].ravel(), plane.ravel())[0, 1])
    assert np.mean(after) < np.mean(before)
