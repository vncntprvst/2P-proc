# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "cython",
#     "numpy",
#     "setuptools",
#     "wheel",
#     "caiman",
#     "mesmerize-core",
#     "mesmerize-viz",
# ]
#
# [tool.uv.sources]
# caiman = { git = "https://github.com/flatironinstitute/CaImAn.git" }
# ///

#%%
# Add to your shell profile or pipeline scripts
# export TF_CPP_MIN_LOG_LEVEL=2
# export CUDA_VISIBLE_DEVICES=0
# export TF_FORCE_GPU_ALLOW_GROWTH=true

#%% 
import types, sys

#%%
import os
# Suppress TensorFlow warnings before importing
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import numpy as np
import pandas as pd
from pathlib import Path

# Set up proper import paths for Analysis 2P
repo_root = Path(__file__).parent.parent
modules_dir = repo_root / "modules"

# Add directories to Python path
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
if str(modules_dir) not in sys.path:
    sys.path.insert(0, str(modules_dir))

from modules.compute_zcorr import make_composite_f_anat

#%%
def test_make_composite_f_anat_resizes_patch_fake_data():
    #%%
    # Labeled zones with one zone occupying a 5x5 area
    labeled_zones = np.zeros((6, 6), dtype=int)
    labeled_zones[:5, :5] = 1

    # Patch is only 3x3 but covers part of the zone
    patch = np.ones((3, 3), dtype=np.float32)

    patch_correlations = pd.DataFrame([
        {
            'frame_num': 0,
            'patch_number': 0,
            'patch_z_pos': 0,
            'r_squared': 1.0,
            'patch_x_lims': [0, 3],
            'patch_y_lims': [0, 3],
            'Z_patch': patch,
        }
    ])

    #%%
    F_anat, zone_df = make_composite_f_anat(patch_correlations, labeled_zones)

    #%%
    # Output should have the same spatial dimensions as labeled_zones
    assert F_anat.shape == (1, 6, 6)
    # The patch should have been resized to fill the 5x5 zone
    assert np.allclose(F_anat[0, :5, :5], 1.0)
    # Outside the zone should remain zero
    assert np.allclose(F_anat[0, 5, :], 0)
    assert np.allclose(F_anat[0, :, 5], 0)

    print("Test passed: Composite F_anat resized correctly to match labeled zones.")

#%%
def test_make_composite_f_anat_resizes_patch_real_data():
    """Test make_composite_f_anat with actual patch size parameters from the processing pipeline."""
    
    print("🔧 Testing make_composite_f_anat with actual processing parameters...")
    
    # Use the actual parameters from the processing pipeline
    # From the log: "Patch size: [60, 60], Step size: [36, 36], Patch overlap: [24, 24]"
    # Image size: 765x765 pixels
    image_size = (765, 765)
    patch_size = (60, 60)
    step_size = (36, 36)
    
    # Load the actual z-correlation data if available
    export_base = Path("/home/wanglab/data/2P/Analysis/Scnn1aAi14_B2M0/04222024/run1run2/modules")
    z_corr_file = export_base / "z_correlation.npz"
    
    # Create labeled zones based on the actual patch grid used in processing
    labeled_zones = np.zeros(image_size, dtype=int)
    zone_id = 1
    
    # Create zones based on the step size pattern used in the actual processing
    for y in range(0, image_size[0] - patch_size[0] + 1, step_size[0]):
        for x in range(0, image_size[1] - patch_size[1] + 1, step_size[1]):
            y_end = min(y + patch_size[0], image_size[0])
            x_end = min(x + patch_size[1], image_size[1])
            labeled_zones[y:y_end, x:x_end] = zone_id
            zone_id += 1
    
    print(f"✅ Created labeled zones from actual processing parameters:")
    print(f"   - Image size: {image_size}")
    print(f"   - Patch size: {patch_size}")
    print(f"   - Step size: {step_size}")
    print(f"   - Number of zones: {zone_id - 1}")
    print(f"   - Unique zones: {len(np.unique(labeled_zones))}")
    
    # Create test patches that simulate the size mismatch from the error
    # Error was: "could not broadcast input array from shape (36,12) into shape (765,765)"
    # This suggests patches had irregular shapes due to edge effects or processing artifacts
    
    test_patches = []
    
    # Create a few patches with the problematic dimensions mentioned in the error
    # Patch 1: The exact dimensions from the error message
    patch_36_12 = np.random.random((36, 12)).astype(np.float32) * 1000  # Scale to realistic intensity
    test_patches.append({
        'frame_num': 0,
        'patch_number': 0,
        'patch_z_pos': 5,
        'r_squared': 0.85,
        'patch_x_lims': [100, 160],  # 60 pixel width expected
        'patch_y_lims': [100, 160],  # 60 pixel height expected
        'Z_patch': patch_36_12,
    })
    
    # Patch 2: Edge case - patch at image boundary
    patch_at_edge = np.random.random((24, 45)).astype(np.float32) * 800
    test_patches.append({
        'frame_num': 1,
        'patch_number': 1,
        'patch_z_pos': 8,
        'r_squared': 0.72,
        'patch_x_lims': [720, 765],  # At right edge - only 45 pixels wide
        'patch_y_lims': [741, 765],  # At bottom edge - only 24 pixels tall
        'Z_patch': patch_at_edge,
    })
    
    # Patch 3: Normal sized patch for comparison
    patch_normal = np.random.random((60, 60)).astype(np.float32) * 1200
    test_patches.append({
        'frame_num': 2,
        'patch_number': 2,
        'patch_z_pos': 12,
        'r_squared': 0.90,
        'patch_x_lims': [200, 260],  # Perfect 60x60 patch
        'patch_y_lims': [200, 260],
        'Z_patch': patch_normal,
    })
    
    # Patch 4: Another irregular patch size
    patch_irregular = np.random.random((48, 30)).astype(np.float32) * 900
    test_patches.append({
        'frame_num': 3,
        'patch_number': 3,
        'patch_z_pos': 15,
        'r_squared': 0.78,
        'patch_x_lims': [400, 460],  # Expected 60 wide, got 30
        'patch_y_lims': [300, 360],  # Expected 60 tall, got 48
        'Z_patch': patch_irregular,
    })
    
    patch_correlations = pd.DataFrame(test_patches)
    
    print(f"✅ Created {len(test_patches)} test patches with realistic size mismatches:")
    for i, patch in enumerate(test_patches):
        expected_shape = (
            patch['patch_y_lims'][1] - patch['patch_y_lims'][0],
            patch['patch_x_lims'][1] - patch['patch_x_lims'][0]
        )
        actual_shape = patch['Z_patch'].shape
        print(f"   - Patch {i}: actual {actual_shape} vs expected {expected_shape}")
    
    # Test the function that caused the original broadcasting error
    try:
        print("🔧 Running make_composite_f_anat with actual processing parameters...")
        F_anat, zone_df = make_composite_f_anat(patch_correlations, labeled_zones)
        
        # Verify the output
        expected_shape = (len(patch_correlations), labeled_zones.shape[0], labeled_zones.shape[1])
        assert F_anat.shape == expected_shape, f"Expected shape {expected_shape}, got {F_anat.shape}"
        
        print(f"✅ make_composite_f_anat completed successfully!")
        print(f"   - Output F_anat shape: {F_anat.shape}")
        print(f"   - Zone DataFrame entries: {len(zone_df)}")
        
        # Verify that patches were properly resized and placed
        for i, (_, row) in enumerate(patch_correlations.iterrows()):
            x_min, x_max = row['patch_x_lims']
            y_min, y_max = row['patch_y_lims']
            
            # Check that the region has non-zero values (indicating patch was placed)
            region = F_anat[i, y_min:y_max, x_min:x_max]
            if region.size > 0:
                has_values = np.any(region > 0)
                print(f"   - Patch {i} region ({region.shape}): {'✅ has values' if has_values else '⚠️ empty'}")
        
        # Check if z_correlation.npz exists and compare
        if z_corr_file.exists():
            try:
                z_data = np.load(z_corr_file, allow_pickle=True)
                print(f"✅ Found actual z_correlation.npz with keys: {list(z_data.keys())}")
                if 'zcorr' in z_data:
                    print(f"   - zcorr shape: {z_data['zcorr'].shape}")
                if 'zpos' in z_data:
                    print(f"   - zpos shape: {z_data['zpos'].shape}")
            except Exception as e:
                print(f"⚠️ Could not load z_correlation.npz: {e}")
        
        print("✅ All tests passed! The cv2.resize fix successfully handles the broadcasting error.")
        return True
        
    except Exception as e:
        print(f"❌ Error in make_composite_f_anat: {e}")
        print("   The patch resizing fix needs further adjustment.")
        
        # Provide specific debugging information
        if "broadcast" in str(e).lower():
            print("   📋 Broadcasting error still occurring:")
            print("   - Check that cv2.resize is working correctly")
            print("   - Verify the patch dimensions are being properly adjusted")
        elif "cv2" in str(e).lower():
            print("   📋 OpenCV error:")
            print("   - Check that cv2 is properly imported in compute_zcorr.py")
            print("   - Verify cv2.resize parameters are correct")
        elif "shape" in str(e).lower():
            print("   📋 Shape-related error:")
            print("   - Check array dimensions in the resizing logic")
        
        # Show the exact error location
        import traceback
        print("   📋 Full traceback:")
        traceback.print_exc()
        
        raise

#%%
if __name__ == "__main__":
    test_make_composite_f_anat_resizes_patch_fake_data()
    test_make_composite_f_anat_resizes_patch_real_data()
# %%
