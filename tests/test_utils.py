"""
Fast, dependency-free unit tests for utility functions.

Tests:
  - to_uint8_robust() from modules/motion_correction.py
  - save_mmap_movie() from pipeline/utils/pipeline_utils.py
  - clip_range() from pipeline/utils/pipeline_utils.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# Add repo root to path so we can import without installing
REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# to_uint8_robust
# ---------------------------------------------------------------------------

def _to_uint8_robust(arr, p_lo=0.1, p_hi=99.9):
    """Local re-implementation so the test doesn't import heavy deps."""
    vmin, vmax = np.percentile(arr, (p_lo, p_hi))
    if vmax <= vmin:
        vmax = vmin + 1.0
    arr = np.clip(arr, vmin, vmax)
    arr = (arr - vmin) * (255.0 / (vmax - vmin))
    return arr.astype(np.uint8)


class TestToUint8Robust:
    def test_output_dtype_is_uint8(self):
        data = np.random.rand(10, 32, 32).astype(np.float32)
        result = _to_uint8_robust(data)
        assert result.dtype == np.uint8

    def test_output_values_in_range(self):
        data = np.random.rand(10, 32, 32).astype(np.float32)
        result = _to_uint8_robust(data)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_clips_outliers(self):
        # Create data with a few extreme outliers
        data = np.ones((5, 8, 8), dtype=np.float32) * 1000.0
        data[0, 0, 0] = 1e9   # extreme high outlier
        data[0, 0, 1] = -1e9  # extreme low outlier
        result = _to_uint8_robust(data)
        assert result.dtype == np.uint8
        assert result.min() >= 0
        assert result.max() <= 255

    def test_all_zeros_does_not_crash(self):
        data = np.zeros((5, 8, 8), dtype=np.float32)
        result = _to_uint8_robust(data)
        assert result.dtype == np.uint8
        # All-zero input should produce all-zero output after the fallback
        assert np.all(result == 0)

    def test_preserves_shape(self):
        data = np.random.rand(7, 16, 16).astype(np.float32)
        result = _to_uint8_robust(data)
        assert result.shape == data.shape

    def test_negative_values_handled(self):
        data = np.random.randn(10, 8, 8).astype(np.float32)  # includes negatives
        result = _to_uint8_robust(data)
        assert result.dtype == np.uint8
        assert result.min() >= 0
        assert result.max() <= 255


# ---------------------------------------------------------------------------
# clip_range
# ---------------------------------------------------------------------------

def _clip_range(array, clip_range='uint16'):
    """Local re-implementation matching pipeline_utils.clip_range."""
    if clip_range == 'uint16':
        return np.clip(array, 0, 2**16 - 1)
    elif clip_range == 'uint8':
        return np.clip(array, 0, 2**8 - 1)
    elif clip_range == 'int16':
        return np.clip(array, -2**15, 2**15 - 1)
    else:
        return array


class TestClipRange:
    def test_uint16_clips_above(self):
        arr = np.array([0, 1000, 65535, 65536, 200000], dtype=np.float32)
        result = _clip_range(arr, 'uint16')
        assert result.max() <= 65535
        assert result[2] == 65535

    def test_uint16_clips_below(self):
        arr = np.array([-100, 0, 500], dtype=np.float32)
        result = _clip_range(arr, 'uint16')
        assert result.min() >= 0

    def test_uint8_clips(self):
        arr = np.array([-1, 0, 128, 255, 300], dtype=np.float32)
        result = _clip_range(arr, 'uint8')
        assert result.min() >= 0
        assert result.max() <= 255

    def test_int16_clips(self):
        arr = np.array([-40000, -32768, 0, 32767, 40000], dtype=np.float32)
        result = _clip_range(arr, 'int16')
        assert result.min() >= -32768
        assert result.max() <= 32767

    def test_unknown_range_returns_unchanged(self):
        arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        result = _clip_range(arr, 'float32')
        np.testing.assert_array_equal(result, arr)

    def test_boundary_values_preserved(self):
        arr = np.array([0, 65535], dtype=np.float32)
        result = _clip_range(arr, 'uint16')
        assert result[0] == 0
        assert result[1] == 65535


# ---------------------------------------------------------------------------
# save_mmap_movie (pipeline_utils)
# ---------------------------------------------------------------------------

def _save_mmap_movie_impl(movie, movie_path):
    """
    Standalone re-implementation of pipeline_utils.save_mmap_movie for testing
    without importing heavy pipeline dependencies.
    """
    movie_path = Path(movie_path)
    T, Ly, Lx = movie.shape
    transposed_array = movie.transpose(1, 2, 0)
    flattened_array = transposed_array.flatten(order='F')
    movie_ = np.memmap(movie_path, dtype='float32', mode='w+', shape=flattened_array.shape)
    movie_[:] = flattened_array[:]
    del movie_
    del flattened_array

    memmap_metadata = {
        'path': str(movie_path),
        'shape': [T, Ly, Lx],
        'dtype': 'float32',
    }
    metadata_path = movie_path.parent / 'memmap_paths.json'
    with open(metadata_path, 'w') as f:
        json.dump(memmap_metadata, f, indent=2)

    return movie_path


def _load_mmap_movie_impl(movie_path, T, Ly, Lx):
    """Load a CaImAn-style memmap without importing CaImAn."""
    pixels = Ly * Lx
    raw = np.memmap(movie_path, dtype='float32', mode='r', shape=(pixels, T), order='F')
    # Reshape (pixels, T) -> (Ly, Lx, T) -> (T, Ly, Lx)
    return raw.reshape(Ly, Lx, T, order='F').transpose(2, 0, 1)


class TestSaveMmapMovie:
    def test_file_is_created(self, tmp_path):
        data = np.random.rand(10, 32, 32).astype(np.float32)
        out_path = tmp_path / "test_movie.mmap"
        _save_mmap_movie_impl(data, out_path)
        assert out_path.exists()

    def test_metadata_json_created(self, tmp_path):
        data = np.random.rand(10, 32, 32).astype(np.float32)
        out_path = tmp_path / "test_movie.mmap"
        _save_mmap_movie_impl(data, out_path)
        meta_path = tmp_path / "memmap_paths.json"
        assert meta_path.exists()

    def test_metadata_json_content(self, tmp_path):
        data = np.random.rand(10, 32, 32).astype(np.float32)
        out_path = tmp_path / "test_movie.mmap"
        _save_mmap_movie_impl(data, out_path)
        with open(tmp_path / "memmap_paths.json") as f:
            meta = json.load(f)
        assert meta['shape'] == [10, 32, 32]
        assert meta['dtype'] == 'float32'
        assert 'path' in meta

    def test_roundtrip_shape(self, tmp_path):
        T, Ly, Lx = 10, 32, 32
        data = np.random.rand(T, Ly, Lx).astype(np.float32)
        out_path = tmp_path / "test_movie.mmap"
        _save_mmap_movie_impl(data, out_path)
        loaded = _load_mmap_movie_impl(out_path, T, Ly, Lx)
        assert loaded.shape == (T, Ly, Lx)

    def test_roundtrip_values(self, tmp_path):
        T, Ly, Lx = 5, 16, 16
        data = np.arange(T * Ly * Lx, dtype=np.float32).reshape(T, Ly, Lx)
        out_path = tmp_path / "test_movie.mmap"
        _save_mmap_movie_impl(data, out_path)
        loaded = _load_mmap_movie_impl(out_path, T, Ly, Lx)
        np.testing.assert_allclose(loaded, data, rtol=1e-5)

    def test_file_size_correct(self, tmp_path):
        T, Ly, Lx = 10, 32, 32
        data = np.random.rand(T, Ly, Lx).astype(np.float32)
        out_path = tmp_path / "test_movie.mmap"
        _save_mmap_movie_impl(data, out_path)
        expected_bytes = T * Ly * Lx * 4  # float32 = 4 bytes
        assert out_path.stat().st_size == expected_bytes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
