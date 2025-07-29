#!/usr/bin/env python3
"""
Test script to run subtract_z_motion_patches with actual processing data
"""

import os
import sys
import numpy as np
from pathlib import Path

# Set up proper import paths for Analysis 2P
repo_root = Path(__file__).parent.parent  # Go up one level from tests/ to project root
modules_dir = repo_root / "modules"

# Add directories to Python path
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
if str(modules_dir) not in sys.path:
    sys.path.insert(0, str(modules_dir))

# Suppress TensorFlow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from modules.compute_zcorr import subtract_z_motion_patches

def main():
    print("🔧 Testing subtract_z_motion_patches with actual processing data...")
    
    # Set up paths based on your actual processing run
    export_base = Path("/home/wanglab/data/2P/Analysis/Scnn1aAi14_B2M0/04222024/run1run2/modules")
    
    # Check if the required files exist
    required_files = {
        'mcorr_movie': export_base / "0d2ed6e5-eee6-4132-a8f5-e83da455062a" / "0d2ed6e5-eee6-4132-a8f5-e83da455062a-cat_tiff_bt_els__d1_765_d2_765_d3_1_order_F_frames_3200.mmap",
        'z_correlation': export_base / "z_correlation.npz",
        'zstack': Path("/home/wanglab/data/2P/Scnn1aAi14_B2M0/04222024/ZSeries-04222024-1047-001/zstack_shifted.tif")
    }
    
    print("📁 Checking required files:")
    missing_files = []
    for name, path in required_files.items():
        if path.exists():
            file_size = path.stat().st_size / (1024**2)  # Size in MB
            print(f"   ✅ {name}: {path} ({file_size:.1f} MB)")
        else:
            print(f"   ❌ {name}: {path} (MISSING)")
            missing_files.append(name)
    
    if missing_files:
        print(f"\n❌ Cannot proceed - missing files: {missing_files}")
        return
    
    # Load z_correlation data
    print("\n📊 Loading z_correlation data...")
    z_correlation = np.load(required_files['z_correlation'])
    print(f"   Available keys: {list(z_correlation.keys())}")
    if 'zcorr' in z_correlation:
        print(f"   zcorr shape: {z_correlation['zcorr'].shape}")
    if 'zpos' in z_correlation:
        print(f"   zpos shape: {z_correlation['zpos'].shape}")
        print(f"   zpos range: {z_correlation['zpos'].min():.1f} to {z_correlation['zpos'].max():.1f}")
    
    # Set up motion correction parameters (from your actual pipeline)
    mcorr_params = {
        'pw_rigid': False,    # Non-rigid motion correction was used
        'max_shifts': (6, 6),
        'strides': (48, 48),
        'overlaps': (24, 24),
        'max_deviation_rigid': 3,
        'border_nan': 'copy'
    }
    
    print(f"\n🔧 Motion correction parameters:")
    for key, value in mcorr_params.items():
        print(f"   {key}: {value}")
    
    # Test different subtraction methods
    subtraction_methods = [
        None,  # Just compute F_anat without subtraction
        # 'huber_regression_pixels',  # Comment out the heavy method initially
    ]
    
    for method in subtraction_methods:
        print(f"\n🧪 Testing subtract_z_motion_patches with method: {method}")
        
        try:
            # Call the function
            zcorr_movie, z_motion_scaling_factors = subtract_z_motion_patches(
                required_files['mcorr_movie'],           # movie_mmap_path
                required_files['zstack'],                # zstack_filepath  
                z_correlation,                           # z_correlation
                mcorr_params,                           # mcorr_params
                method,                                 # subtract_method
                save_tiffs=True,                        # save_tiffs (save intermediate results)
                save_correl=True,                       # save_correl (save patch correlations)
                save_format='parquet'                   # save_format
            )
            
            print(f"   ✅ Function completed successfully!")
            
            if zcorr_movie is not None:
                print(f"   📊 zcorr_movie shape: {zcorr_movie.shape}")
                print(f"   📊 zcorr_movie dtype: {zcorr_movie.dtype}")
                print(f"   📊 zcorr_movie range: {zcorr_movie.min():.1f} to {zcorr_movie.max():.1f}")
            else:
                print(f"   ℹ️  zcorr_movie is None (method={method})")
                
            if z_motion_scaling_factors is not None:
                print(f"   📊 z_motion_scaling_factors shape: {z_motion_scaling_factors.shape}")
                print(f"   📊 scaling factors range: {z_motion_scaling_factors.min():.3f} to {z_motion_scaling_factors.max():.3f}")
            else:
                print(f"   ℹ️  z_motion_scaling_factors is None (method={method})")
                
        except Exception as e:
            print(f"   ❌ Error with method {method}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n✅ Testing completed!")

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
    assert np.mean(after) > np.mean(before)

if __name__ == "__main__":
    main()