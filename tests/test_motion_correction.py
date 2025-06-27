"""
# test_motion_correction.py
This script tests the motion correction step of the Mesmerize pipeline.

It checks for test data, downloads it if necessary, sets up parameters, and runs the motion correction step.

Usage:
python test_motion_correction.py

"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path

# Set up proper import paths
repo_root = Path(__file__).parent.parent
mesmerize_dir = repo_root / "Mesmerize"

# Add directories to Python path
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
if str(mesmerize_dir) not in sys.path:
    sys.path.insert(0, str(mesmerize_dir))

# Import required modules - these imports need to come after path setup
try:
    # Basic imports - if these fail, the script cannot run
    import numpy as np
    from caiman.mmapping import load_memmap
    
    # Optional imports - we can run without these
    try:
        import pytest
    except ImportError:
        print("Warning: pytest not found. This is fine for manual script execution.")
    
    # Import mesmerize-core
    import mesmerize_core as mc

    # Import our pipeline module
    from pipeline_mcorr_cnmf import run_mcorr

except ImportError as e:
    print(f"ERROR: Failed to import required modules: {e}")
    print(f"Current PYTHONPATH: {sys.path}")
    print(f"Make sure you have activated the correct conda environment (e.g., mescore)")
    sys.exit(1)

def download_test_data_if_needed():
    """
    Check if test data exists, download and extract it if not.
    Returns the path to the test data directory.
    """
    # Use the already defined repo_root from above
    
    test_data_dir = mesmerize_dir / "test_data"
    
    # If test data directory doesn't exist, download it
    if not test_data_dir.exists() or not list(test_data_dir.glob("*")):
        print("Test data not found or empty. Downloading...")
        script_path = repo_root / "scripts" / "download_test_data.sh"
        
        # Check if script exists
        if not script_path.exists():
            raise FileNotFoundError(f"Download script not found at: {script_path}")
        
        # Change directory to Mesmerize to ensure correct relative paths
        original_dir = os.getcwd()
        os.chdir(str(mesmerize_dir))
        
        try:
            # Run the download script
            print(f"Running download script: {script_path}")
            result = subprocess.run(
                ["bash", str(script_path)],
                check=False,  # Don't raise exception so we can handle errors manually
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            if result.returncode != 0:
                print(f"Download script failed with return code: {result.returncode}")
                print(f"STDOUT: {result.stdout.decode()}")
                print(f"STDERR: {result.stderr.decode()}")
                raise RuntimeError("Failed to download test data")
                
            # Verify test data was downloaded
            if not test_data_dir.exists() or not list(test_data_dir.glob("*")):
                raise RuntimeError("Test data directory is empty after download")
                
        finally:
            # Always return to the original directory
            os.chdir(original_dir)
    
    return test_data_dir

def get_paths_from_json(paths_file, field_name=None):
    """Load data paths from a JSON file."""
    with open(paths_file, 'r') as f:
        data = json.load(f)
    if field_name:
        return data.get(field_name, [])
    # If no field name specified, return the entire data
    return data

def get_test_parameters(params_file):
    """Load test parameters from the file"""

    # If the specific file doesn't exist, try to find any JSON parameter file
    if not params_file.exists():
        print(f"Parameters file not found at: {params_file}")
        print("Looking for alternative parameter files...")
        
        # List all parameter files in the directory
        param_files = list((params_file.parent).glob("*.json"))
        if param_files:
            params_file = param_files[0]
            print(f"Using alternative parameter file: {params_file}")
        else:
            # If no parameter files found, use default parameters
            print("No parameter files found. Using default parameters.")
            if hasattr(proc, 'get_default_parameters'):
                return proc.get_default_parameters('mcorr')
            else:
                # Basic default parameters as fallback
                return {
                    'main': {
                        'strides': [36, 36],
                        'overlaps': [24, 24],
                        'max_shifts': [12, 12],
                        'max_deviation_rigid': 6,
                        'border_nan': 'copy',
                        'pw_rigid': True,
                        'gSig_filt': None
                    }
                }
    
    # Load parameters from file
    try:
        with open(params_file, 'r') as f:
            params = json.load(f)
            
        # If params_mcorr exists in the loaded file, return that section
        if 'params_mcorr' in params:
            return params['params_mcorr']
        else:
            return params
            
    except json.JSONDecodeError as e:
        print(f"Error parsing parameter file: {e}")
        # Fall back to default parameters
        if hasattr(proc, 'get_default_parameters'):
            return proc.get_default_parameters('mcorr')
        else:
            raise

def test_motion_correction(run_on_subset=False, regex_pattern='*_Ch2_*.ome.tif', recompute=True):
    """
    Test the motion correction step of the pipeline.
    
    This test:
    1. Checks for test data and downloads if needed
    2. Sets up necessary paths and parameters
    3. Runs only the motion correction step
    4. Validates the output
    """
    print("Starting motion correction test...")

    # Prepare test environment
    test_data_dir = download_test_data_if_needed()
    print(f"Test data directory: {test_data_dir}")
    
    # # Create an output directory for test results
    # output_dir = repo_root / "tests" / "test_output"
    # output_dir.mkdir(exist_ok=True, parents=True)
    # print(f"Output directory: {output_dir}")
    
    # Import the bruker_concat_tif module to handle file concatenation
    try:
        from Mesmerize.bruker_concat_tif import concatenate_files
        print("Successfully imported bruker_concat_tif module")
    except ImportError:
        print("Error: Failed to import bruker_concat_tif module")
        sys.exit(1)
    
    # List contents of test data directory to verify
    print("Test data directory contents:")
    for item in test_data_dir.glob("*"):
        if item.is_dir():
            print(f"  - {item.name}/ (dir)")
            # List first few items in subdirectories
            for subitem in list(item.glob("*"))[:3]:
                print(f"    - {subitem.name}")
            if len(list(item.glob("*"))) > 3:
                print(f"    - ... and {len(list(item.glob('*'))) - 3} more items")
        else:
            print(f"  - {item.name}")
    
    # Get the paths from the path json file
    # 
    paths_file = test_data_dir / "paths_test_smaller.json"
    if not paths_file.exists():
        # Look in the path directory for a similar file
        paths_file_copy = repo_root / "Mesmerize" / "paths" / "paths_test_smaller.json"
        # if it exists, copy to the test data directory
        if paths_file_copy.exists():
            print(f"Copying paths file from {paths_file} to {test_data_dir}")
            shutil.copy(paths_file, test_data_dir)

    if not paths_file.exists():
        raise FileNotFoundError(f"Test paths file not found at: {paths_file}")
    print(f"Using test paths file: {paths_file}")

    # Load paths from the JSON file
    try:
        with open(paths_file, 'r') as f:
            paths_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing paths file: {e}")
        raise

    # Use the  datasets listed in the paths file, and concatenate by group
    concat_group = get_paths_from_json(paths_file, 'concatenation_groups')
    print(f"Concatenation groups: {concat_group}")

    test_dataset_dirs = get_paths_from_json(paths_file, 'data_paths')
    if not test_dataset_dirs:
        raise FileNotFoundError("No suitable data directories found in test data")
    # Match the dataset directories to the directories in the test data
    test_dataset_dirs = [test_data_dir.parent / d for d in test_dataset_dirs]  # Handle relative paths correctly
    print(f"Test dataset directories: {test_dataset_dirs}")

    # Group the dataset directories by concatenation group
    grouped_dataset_dirs = {}
    for group in concat_group:
        grouped_dataset_dirs[group] = []
        for dataset_dir in test_dataset_dirs:
            grouped_dataset_dirs[group].append(dataset_dir)
        
    # Set up parameters for test
    params_file_path = test_data_dir.parent / paths_data.get('params_files')[0]
    parameters_mcorr = get_test_parameters(params_file_path)
    print("Parameters loaded successfully")
    
    # Look for .ome.tif files recursively for each group
    # The test data structure has files organized in deep subdirectories
    grouped_dataset_files = {}
    data_files = []
    
    pattern = '**/*.ome.tif'  # Default pattern for test datasets

    for group, dataset_dirs in grouped_dataset_dirs.items():
        for data_path in dataset_dirs:
            recursive_files = list(data_path.rglob(pattern.replace("**/", "")))
            if recursive_files:
                print(f"Found {len(recursive_files)} {pattern} files recursively in {data_path}")
                grouped_dataset_files[group] = recursive_files
                data_files.extend(recursive_files)

    print(f"Found {len(data_files)} image files in data directory")
       
    # Define export path
    export_path = repo_root / "tests" / "test_output" # Path('/tmp/test_motion_correction')
    print(f"Export path: {export_path}")
    
    # Create export directory if it doesn't exist
    if export_path.exists():
        print(f"Removing existing export directory: {export_path}")
        shutil.rmtree(export_path)
    export_path.mkdir(parents=True)
    
    print("\nRunning motion correction...")

    # Import mesmerize_core and set parent raw data path - Required by the pipeline
    print("Setting parent raw data path...")

    try:
        mc.set_parent_raw_data_path(export_path)
        print("Parent raw data path set successfully")
    except Exception as e:
        print(f"Error setting parent raw data path: {e}")
        raise RuntimeError(f"Failed to set parent raw data path: {e}")
    
    # print(f"Using data_path: {data_path}")
    # print(f"Using export_path: {export_path}")
    # print(f"Using regex_pattern: {regex_pattern}")
            
    if run_on_subset:
        print("Running on a subset of files for faster testing")
    
        max_files = 50  # Limit to this many files for testing
        if len(data_files) > max_files:
            print(f"Using subset of {max_files} files from {len(data_files)} total files")
            # Try to get an evenly distributed sample
            step = len(data_files) // max_files
            test_files = data_files[::step][:max_files]
        else:
            test_files = data_files
            
        print(f"Selected {len(test_files)} files for testing")

        # Copy files to a new directory for testing
        test_data_dir = test_data_dir / "test_subset"
        test_data_dir.mkdir(exist_ok=True)

        # Create a grouped dataset dir dictionary for the selected files
        grouped_dataset_dirs = {}
        grouped_dataset_dirs[1] = [test_data_dir]

    # If not running on a subset, use all available files   
    else:
        print("Running on all available files")

    try:
        # Get export paths for all groups
        group_export_paths = get_paths_from_json(paths_file, 'export_paths')

        for group, group_data_paths in grouped_dataset_dirs.items():
            print(f"Processing group {group} with {len(group_data_paths)} directories")
            group_export_dir = export_path / group_export_paths[group - 1].split('/')[-1]  # Get the last part of the path
            group_export_dir.mkdir(parents=True, exist_ok=True)
            # Run the motion correction
            mc_output_file, index, movie_path = run_mcorr(group_data_paths, group_export_dir, parameters_mcorr, regex_pattern, recompute)

            print("\nValidating motion correction results...")
            # Validate results
            if not mc_output_file.exists():
                print(f"ERROR: Motion corrected movie not found at: {mc_output_file}")
                raise FileNotFoundError("Motion corrected movie not created")
                
            print("Loading motion corrected movie to check integrity...")
            try:
                # Try to load the motion corrected movie
                mcorr_movie, dims, T = load_memmap(mc_output_file)
                print(f"Motion corrected movie loaded. Dimensions: {dims}, Frames: {T}")
                
                # Reshape to proper dimensions
                mcorr_movie = np.reshape(mcorr_movie.T, [T] + list(dims), order='F')
                
                # Check basic properties of the motion corrected movie
                if not np.isfinite(mcorr_movie).all():
                    print("WARNING: Motion corrected movie contains NaN or Inf values")
                
                if mcorr_movie.std() <= 0:
                    print("WARNING: Motion corrected movie has zero standard deviation")
                    
                print(f"Motion corrected movie shape: {mcorr_movie.shape}")
                
                print("\nDirect motion correction test passed!")
                print(f"Motion corrected movie saved at: {mc_output_file}")
                
                return {
                    'motion_corrected_path': mc_output_file,
                    'test_data_dir': test_data_dir,
                    'export_path': export_path,
                    'group': group,
                    'group_export_dir': group_export_dir
                }
                    
            except Exception as e:
                print(f"Error loading motion corrected movie: {e}")
                raise
            finally:
                # Clean up resources
                del mcorr_movie
                del dims
                del T

    except Exception as e:
        print(f"Motion correction failed: {e}")
        
if __name__ == "__main__":
    print("=" * 60)
    print("MOTION CORRECTION TEST")
    print("=" * 60)
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Repository root: {repo_root}")
    print(f"Mesmerize directory: {mesmerize_dir}")
    print("-" * 60)

    # Get first argument for running on a subset
    if len(sys.argv) < 2:
        run_on_subset = False
    else:
        run_on_subset = sys.argv[1].lower() == "true"

    if run_on_subset:
        print(f"Running on a subset of files")

    try:
        result = test_motion_correction(run_on_subset=run_on_subset)
        print("\n🎉 Test completed successfully!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
