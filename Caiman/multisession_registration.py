"""
This script registers spatial components across multiple sessions using the CaImAn library.

Usage:
    Provide either a JSON file containing the paths or a list of result paths.

Examples:
    # Using a JSON file:
    python multisession_registration.py --json input_paths.json

    # Using a list of paths:
    python multisession_registration.py --paths path1 path2 path3
"""

import sys
import os
import json
import numpy as np
import scipy.io as sio
from scipy.sparse import csc_matrix, issparse, coo_matrix
import argparse
import matplotlib

# Only check for DISPLAY on non-Windows systems
if os.name != 'nt' and os.environ.get('DISPLAY', '') == '':
    print('No display found. Using non-interactive Agg backend.')
    matplotlib.use('Agg')

import matplotlib.pyplot as plt

from caiman.base.rois import register_multisession
from caiman.utils import visualization


def multi_session_reg(result_paths):
    """
    Registers spatial components across multiple sessions.

    Parameters:
        result_paths (list): A list of result paths.
    """
    # Construct file paths for .mat and .npy files.
    mat_file_paths = [os.path.join(path, 'results_caiman.mat') for path in result_paths]
    cn_paths = [os.path.join(path, 'mean_intensity_template.npy') for path in result_paths]

    spatial = []
    templates = []

    # Load spatial components from the .mat files.
    for path in mat_file_paths:
        try:
            mat_contents = sio.loadmat(path)
            spatial.append(mat_contents['spatial_components'])
        except Exception as e:
            print(f"Error loading {path}: {e}")
            sys.exit(1)

    # Attempt to load templates from .npy files.
    for path in cn_paths:
        if not os.path.exists(path):
            break
        try:
            templates.append(np.load(path, allow_pickle=True))
        except Exception as e:
            print(f"Error loading {path}: {e}")
            sys.exit(1)

    # If no templates were loaded, try to get them from the .mat files.
    if not templates:
        for path in mat_file_paths:
            try:
                mat_contents = sio.loadmat(path)
                templates.append(mat_contents['mean_map_motion_corrected'])
            except Exception as e:
                print(f"Error loading template from {path}: {e}")
                sys.exit(1)

    # Assume that the dimensions of the templates are all the same.
    dims = templates[0].shape

    print('Number of sessions: ', len(spatial))
    print('Number of components in each session: ', [spatial[i].shape[1] for i in range(len(spatial))])
    print('Type of spatial components: ', [type(spatial[i]) for i in range(len(spatial))])
    print('Dimensions of FOV: ', dims)
    print('Dimensions of each template images: ', [templates[i].shape for i in range(len(templates))])

    # Perform multisession registration.
    print("Registering spatial components across sessions")
    spatial_union, assignments, matchings = register_multisession(A=spatial, dims=dims, templates=templates)
    print(f"Registration completed, with {len(assignments)} components registered.")
    
    # Convert assignments to a dense array if it is returned as a sparse matrix.
    if issparse(assignments):
        print("Converting sparse assignments to dense array")
        assignments = assignments.toarray()

    n_reg = len(result_paths)
    # Filter assignments: keep rows with non-NaN values for all sessions.
    print("Filtering assignments")
    assignments_filtered = np.array(
        np.nan_to_num(assignments[np.sum(~np.isnan(assignments), axis=1) >= n_reg]),
        dtype=int
    )
    # Check if spatial[0] is a COO matrix and convert it if necessary.
    if isinstance(spatial[0], coo_matrix):
        print("Converting COO matrix to CSR format")
        spatial0 = spatial[0].tocsr()  # Convert to CSR format, which supports slicing.
    else:
        spatial0 = spatial[0]

    spatial_filtered = spatial0[:, assignments_filtered[:, 0]]

    # Plot the spatial contours on the last template.
    print("Plotting spatial contours on the last template")
    visualization.plot_contours(spatial_filtered, templates[-1])

    # Determine a common root directory to save the results.
    root_dir = os.path.commonpath(result_paths)
    spatial_union_sparse = csc_matrix(spatial_union)
    save_path = os.path.join(root_dir, 'register_multisession.mat')
    
    sio.savemat(save_path, mdict={
        'assignments': assignments,
        'matchings': matchings,
        'spatial_union': spatial_union_sparse,
        'assignments_filtered': assignments_filtered
    })
    print(f"Registration results saved to {save_path}")

    # Save the plot to a file.
    fig = plt.gcf()  # get the current figure 
    plot_save_path = os.path.join(root_dir, 'registered_spatial_components.png')
    fig.savefig(plot_save_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Register spatial components across multiple sessions using the CaImAn library."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--json",
        type=str,
        help="Path to a JSON file containing the 'export_paths' field."
    )
    group.add_argument(
        "--paths",
        nargs="+",
        help="List of result paths."
    )
    args = parser.parse_args()

    # Determine export paths based on input type.
    if args.paths:
        result_paths = args.paths
    elif args.json:
        with open(args.json, 'r') as file:
            data = json.load(file)
            if 'export_paths' in data:
                result_paths = data['export_paths']
            else:
                print("JSON file does not contain the 'export_paths' field.")
                sys.exit(1)
    else:
        print("Invalid input. Please provide either a list of result paths or a JSON file containing the paths.")
        sys.exit(1)

    print("Results paths:", result_paths)
    multi_session_reg(result_paths)