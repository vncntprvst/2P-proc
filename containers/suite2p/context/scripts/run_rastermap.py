import argparse
from rastermap import Rastermap
import os
import numpy as np
import scipy.io as sio

def run_rastermap(analysis_filename, analysis_dir, n_clusters, n_PCs, locality, time_lag_window, mean_time):
    # Load the MATLAB .mat file
    data = sio.loadmat(analysis_filename)['resp_rastermap'] 
    
    # Print basic data info
    print('The data size is:')
    print(data.shape)
    print('The data type is:')
    print(data.dtype)
    print('The first 5 rows and 5 columns are:')
    print(data[0:5, 0:5])
    
    # Print model parameters
    print(' The model parameters are:')
    print(f'n_clusters={n_clusters}, n_PCs={n_PCs}, locality={locality}, time_lag_window={time_lag_window}, mean_time={mean_time}')
    
    # Fit the Rastermap model
    model = Rastermap(
        n_clusters=n_clusters, 
        n_PCs=n_PCs, 
        locality=locality, 
        time_lag_window=time_lag_window, 
        mean_time=mean_time
    ).fit(data)
    print('Rastermap model fitted successfully')
    
    # Sort indices
    isort = np.argsort(model.embedding[:, 0])
    print('The first 10 sorted indices are:')
    print(isort[:10])
    
    # Save output to a MATLAB .mat file
    save_path = os.path.join(analysis_dir, 'isort_rastermap.mat')
    print('Saving isort to path:')
    print(save_path)
    sio.savemat(save_path, {'isort': isort})
    print('Saved successfully!')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Rastermap Analysis")
    parser.add_argument('--analysis_filename', type=str, required=True, help="Path to the .mat file containing resp_rastermap")
    parser.add_argument('--analysis_dir', type=str, required=True, help="Directory to save the output")
    parser.add_argument('--n_clusters', type=int, required=True, help="Number of clusters")
    parser.add_argument('--n_PCs', type=int, required=True, help="Number of principal components")
    parser.add_argument('--locality', type=float, required=True, help="Locality parameter for Rastermap")
    parser.add_argument('--time_lag_window', type=int, required=True, help="Time lag window")
    parser.add_argument('--mean_time', type=int, required=True, help="Mean time parameter")

    args = parser.parse_args()
    
    # Run the Rastermap analysis
    run_rastermap(
        args.analysis_filename, 
        args.analysis_dir, 
        args.n_clusters, 
        args.n_PCs, 
        args.locality, 
        args.time_lag_window, 
        args.mean_time
    )
