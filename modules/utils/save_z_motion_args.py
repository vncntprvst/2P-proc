# To run before call 
# zcorr_movie, z_motion_scaling_factors = subtract_z_motion_patches(
#     mcorr_movie_path,
#     zstack_path / z_shifted_file, 
#     z_correlation, 
#     parameters['params_mcorr']['main'],
#     subtract_method,
#     True
# )

import datetime
from pathlib import Path

def save_z_motion_args(mesmerize_path, args_dict):
    """
    Save z-motion correction arguments to JSON for reproducibility.
    
    This function serializes both the paths and parameters used for z-motion 
    correction, as well as summary information about array shapes and key 
    statistics from z_correlation data.
    
    Parameters:
    -----------
    mesmerize_path : pathlib.Path
        Directory where arguments should be saved
    args_dict : dict
        Dictionary containing the z-motion arguments
        
    Returns:
    --------
    pathlib.Path
        Path to the saved arguments file
    """
    import json
    import datetime
    import numpy as np
    
    # Create output directory if it doesn't exist
    mesmerize_path.mkdir(parents=True, exist_ok=True)
    
    # Generate a timestamp for the filename
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    args_path = mesmerize_path / f"z_motion_args_{timestamp}.json"
    
    # Process z_correlation data to make it serializable
    if 'z_correlation' in args_dict:
        z_corr_info = {}
        for key in args_dict['z_correlation'].keys():
            array = args_dict['z_correlation'][key]
            z_corr_info[key] = {
                'shape': list(array.shape),
                'dtype': str(array.dtype),
                'min': float(array.min()),
                'max': float(array.max()),
                'mean': float(array.mean()),
                'std': float(array.std()),
                # Include 10 sample values (safely serializable)
                'samples': array.flat[:10].tolist()
            }
        # Replace z_correlation with its info
        args_dict['z_correlation'] = z_corr_info
    
    # Convert paths to strings and handle other non-serializable objects
    serializable_args = {}
    for key, value in args_dict.items():
        if hasattr(value, 'resolve'):  # Path object
            serializable_args[key] = str(value)
        elif isinstance(value, np.ndarray):
            serializable_args[key] = f"Array with shape {value.shape}, dtype {value.dtype}"
        else:
            serializable_args[key] = value
    
    # Save the serializable args to JSON file
    with open(args_path, 'w') as f:
        json.dump(serializable_args, f, indent=4)
        
    print(f"Z-motion arguments saved to: {args_path}")
    return args_path

# Prepare the arguments dictionary for saving
z_motion_args = {
    'mcorr_movie_path': mcorr_movie_path,
    'zstack_file': zstack_path / z_shifted_file,
    'z_correlation_keys': list(z_correlation.keys()),
    'z_correlation': {k: z_correlation[k] for k in ['zcorr', 'zpos']},
    'mcorr_params': parameters['params_mcorr']['main'],
    'subtract_method': subtract_method,
    'save_tiffs': True,
    'timestamp': datetime.datetime.now().isoformat()
}

# Save the arguments
save_z_motion_args(mesmerize_path, z_motion_args)