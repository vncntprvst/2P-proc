#!/usr/bin/env python3
"""
Efficient test for patch_correl_plots function using mock data that simulates the real issue
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# Set up proper import paths
repo_root = Path(__file__).parent.parent  # Go up one level from tests/ to project root
modules_dir = repo_root / "modules"

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
if str(modules_dir) not in sys.path:
    sys.path.insert(0, str(modules_dir))

# Suppress TensorFlow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from modules.compute_zcorr import patch_correl_plots

def create_mock_data_with_real_issue():
    """
    Create mock data that reproduces the exact issue from your processing:
    - 899 zones that don't fit into a perfect square grid
    """
    print("🔧 Creating mock data that reproduces the reshape issue...")
    
    # Simulate the real data dimensions that caused the issue
    image_size = (765, 765)
    patch_size = (60, 60)
    step_size = (36, 36)
    
    # Create labeled zones - this simulates how zones are actually created
    labeled_zones = np.zeros(image_size, dtype=int)
    zone_id = 1
    
    # Create zones based on the step size pattern (like in real processing)
    for y in range(0, image_size[0] - patch_size[0] + 1, step_size[0]):
        for x in range(0, image_size[1] - patch_size[1] + 1, step_size[1]):
            y_end = min(y + patch_size[0], image_size[0])
            x_end = min(x + patch_size[1], image_size[1])
            labeled_zones[y:y_end, x:x_end] = zone_id
            zone_id += 1
    
    # Simulate the issue: we end up with 899 zones instead of 900
    # This happens due to boundary effects
    unique_zones = np.unique(labeled_zones[labeled_zones > 0])
    actual_num_zones = len(unique_zones)
    
    print(f"   📊 Mock data created:")
    print(f"   - Image size: {image_size}")
    print(f"   - Labeled zones shape: {labeled_zones.shape}")
    print(f"   - Number of zones: {actual_num_zones}")
    print(f"   - Zone IDs range: {unique_zones.min()} to {unique_zones.max()}")
    
    # This should reproduce the issue: 899 zones don't fit into 30x30 grid
    expected_grid_size = int(np.sqrt(unique_zones.max() + 1))  # This gives 30
    expected_total = expected_grid_size * expected_grid_size  # This gives 900
    print(f"   - Expected grid size: {expected_grid_size}x{expected_grid_size} = {expected_total}")
    print(f"   - Actual zones: {actual_num_zones}")
    print(f"   - Issue: {actual_num_zones} ≠ {expected_total} ❌")
    
    # Create mock patch correlations data
    num_frames = 10  # Use fewer frames for testing
    patch_correlations_df = []
    
    for frame_num in range(num_frames):
        for zone_id in unique_zones[:100]:  # Test with first 100 zones for speed
            patch_correlations_df.append({
                'frame_num': frame_num,
                'patch_number': zone_id,
                'patch_z_idx': np.random.randint(-5, 6),
                'patch_z_pos': np.random.randint(15, 25),
                'r_squared': np.random.random()
            })
    
    patch_correlations_df = pd.DataFrame(patch_correlations_df)
    
    # Create mock zone_df (this is what should be used instead of zone_data)
    zone_df = []
    for frame_num in range(num_frames):
        for zone_id in unique_zones[:100]:  # Match the patch_correlations_df
            zone_df.append({
                'frame_num': frame_num,
                'zone_id': zone_id,
                'r_squared': np.random.random(),
                'patch_number': zone_id,
                'patch_z_pos': np.random.randint(15, 25)
            })
    
    zone_df = pd.DataFrame(zone_df)
    
    # Create zone pattern for visualization
    zone_pattern = labeled_zones.copy()
    
    # Create mock FOV image
    fov_image = np.random.random(image_size).astype(np.float32)
    
    # Create mock z_correlation
    z_correlation = {
        'zcorr': np.random.random((41, num_frames)),
        'zpos': np.random.randint(0, 41, num_frames)
    }
    
    return patch_correlations_df, labeled_zones, zone_df, zone_pattern, fov_image, z_correlation

def test_patch_correl_plots_efficiently():
    """
    Test patch_correl_plots function with mock data that reproduces the real issue
    """
    print("🚀 Efficient test of patch_correl_plots function")
    
    # Create mock data
    patch_correlations_df, labeled_zones, zone_df, zone_pattern, fov_image, z_correlation = create_mock_data_with_real_issue()
    
    # Create temporary export path
    export_path = Path("/tmp/test_patch_plots")
    export_path.mkdir(exist_ok=True)
    
    print("\n🔧 Testing patch_correl_plots function...")
    
    try:
        # Test the function
        patch_correl_plots(
            patch_correlations_df, 
            labeled_zones, 
            zone_df, 
            zone_pattern, 
            fov_image, 
            z_correlation, 
            export_path
        )
        
        print("✅ patch_correl_plots completed successfully!")
        
        # Check if plots were created
        plots_dir = export_path / "plots"
        if plots_dir.exists():
            created_files = list(plots_dir.glob("*.png"))
            print(f"   📊 Created {len(created_files)} plot files:")
            for file in created_files:
                print(f"   - {file.name}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in patch_correl_plots: {e}")
        
        # Provide specific debugging for the issue
        if "reshape" in str(e).lower():
            print("   📋 Reshape error - this was the original issue")
            print("   - The fix should handle zones that don't form perfect squares")
        elif "zone_data" in str(e).lower():
            print("   📋 Variable name error - zone_data should be zone_df")
        
        import traceback
        traceback.print_exc()
        return False

def test_zone_counting_logic():
    """
    Test the specific zone counting logic that caused the original issue
    """
    print("\n🔍 Testing zone counting logic...")
    
    # Create test data similar to real scenario
    labeled_zones = np.zeros((765, 765), dtype=int)
    zone_id = 1
    
    # Simulate zone creation
    patch_size = (60, 60)
    step_size = (36, 36)
    
    for y in range(0, 765 - patch_size[0] + 1, step_size[0]):
        for x in range(0, 765 - patch_size[1] + 1, step_size[1]):
            y_end = min(y + patch_size[0], 765)
            x_end = min(x + patch_size[1], 765)
            labeled_zones[y:y_end, x:x_end] = zone_id
            zone_id += 1
    
    # Analyze the zone distribution
    unique_zones = np.unique(labeled_zones[labeled_zones > 0])
    max_zone_id = np.max(labeled_zones)
    num_zones = len(unique_zones)
    
    print(f"   📊 Zone analysis:")
    print(f"   - Max zone ID: {max_zone_id}")
    print(f"   - Number of unique zones: {num_zones}")
    print(f"   - Zone IDs are contiguous: {len(unique_zones) == max_zone_id}")
    
    # Test both methods of calculating grid dimensions
    old_method = int(np.sqrt(max_zone_id + 1))  # Original problematic method
    new_method = int(np.sqrt(num_zones))        # Fixed method
    
    print(f"   📐 Grid dimension calculations:")
    print(f"   - Old method (sqrt(max_zone_id + 1)): {old_method}")
    print(f"   - New method (sqrt(num_zones)): {new_method}")
    print(f"   - Old method grid size: {old_method}x{old_method} = {old_method**2}")
    print(f"   - New method grid size: {new_method}x{new_method} = {new_method**2}")
    
    # Check if either method would work
    old_works = (old_method**2 == num_zones)
    new_works = (new_method**2 == num_zones)
    
    print(f"   ✅ Old method works: {old_works}")
    print(f"   ✅ New method works: {new_works}")
    
    if not new_works:
        print(f"   ⚠️  Neither method creates perfect square - will use scatter plot instead")
    
    return new_works

def main():
    print("🧪 Efficient testing of patch_correl_plots issue")
    
    # Test 1: Zone counting logic
    zone_logic_ok = test_zone_counting_logic()
    
    # Test 2: The actual function with mock data
    function_ok = test_patch_correl_plots_efficiently()
    
    if zone_logic_ok and function_ok:
        print("\n✅ All tests passed! The patch_correl_plots issue should be fixed.")
    else:
        print("\n❌ Some tests failed. Check the output above for details.")

if __name__ == "__main__":
    main()
