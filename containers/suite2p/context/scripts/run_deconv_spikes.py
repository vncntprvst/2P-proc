import argparse
import os
import numpy as np
import scipy.io as sio
from suite2p.extraction import dcnv

def deconv_spikes(dataFile, save_path, tau, fs, baseline, sig_baseline, win_baseline, batch_size, **kwargs):
    """    Deconvolve spikes from a given .mat file using OASIS method.
    Args:
        dataFile (str): Path to the input .mat file containing fluorescence data.
        save_path (str): Directory where the output spikes will be saved.
        tau (float): Tau parameter for deconvolution.
        fs (float): Sampling frequency of the data.
        baseline (str): Method for baseline correction.
        sig_baseline (float): Sigma value for baseline correction.
        win_baseline (float): Window size for baseline correction.
        batch_size (int): Batch size for OASIS deconvolution.
    """
    # Load the MATLAB .mat file
    F = sio.loadmat(dataFile)['Fdeconv']
    
    # Print basic data info
    print('The data size is:', F.shape)
    print('The data type is:', F.dtype)
    print('The first 5 rows and 5 columns are:', F[:5, :5])

    # Print model parameters
    print('The model parameters are:/n')
    if not kwargs.get('no_baseline', False):
        print('Baseline preprocessing is enabled.')
        print(f'tau={tau}, fs={fs}, baseline={baseline}, sig_baseline={sig_baseline}, win_baseline={win_baseline}, batch_size={batch_size}')
    else:
        print('Baseline preprocessing is disabled.')
        print(f'tau={tau}, fs={fs}, batch_size={batch_size}')

    # Preprocess and deconvolve
    # Check for no-baseline flag (argparse maps --no-baseline to no_baseline)
    if kwargs.get('no_baseline', False):
        print('Baseline preprocessing is disabled.')
        Fc = F
    else:
        print('Baseline preprocessing is enabled.')
        Fc = dcnv.preprocess(F=F, baseline=baseline, sig_baseline=sig_baseline, win_baseline=win_baseline, fs=fs)
    
    spks = dcnv.oasis(F=Fc, batch_size=batch_size, tau=tau, fs=fs)
    
    print('Finished deconvolving spikes')
    print('The first 10 values of spks are:')
    print(spks[:10])
        
    # Save output
    save_file = os.path.join(save_path, 'spks_deconv.mat')
    sio.savemat(save_file, {'spks': spks})
    print(f'Saved spks to {save_file}')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deconvolve Spikes")
    parser.add_argument('--dataFile', type=str, required=True, help="Path to input .mat file")
    parser.add_argument('--save_path', type=str, required=True, help="Directory to save the output")
    parser.add_argument('--tau', type=float, required=True, help="Tau parameter")
    parser.add_argument('--fs', type=float, required=True, help="Sampling frequency")
    parser.add_argument('--baseline', type=str, required=True, help="Baseline method")
    parser.add_argument('--sig_baseline', type=float, required=True, help="Sigma for baseline")
    parser.add_argument('--win_baseline', type=float, required=True, help="Window size for baseline")
    parser.add_argument('--batch_size', type=int, required=True, help="Batch size for OASIS")
    parser.add_argument('--no-baseline', action='store_true', help="Disable baseline preprocessing")
    
    args = parser.parse_args()
    
    # Run the deconvolution
    deconv_spikes(args.dataFile, args.save_path, args.tau, args.fs, args.baseline, args.sig_baseline, args.win_baseline, args.batch_size, no_baseline=args.no_baseline)
