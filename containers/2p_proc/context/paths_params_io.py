import argparse
import json
import os
import logging
import sys
from pathlib import Path
from typing import Optional


def _detect_project_root() -> Optional[Path]:
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "pipeline").exists():
            return parent
    return None


PROJECT_ROOT = _detect_project_root()
if PROJECT_ROOT and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from pipeline.utils.config_loader import load_config as _load_config_impl
except ImportError:  # Fallback when running inside legacy containers without the loader
    _load_config_impl = None

def is_logger_configured():
    return len(logging.root.handlers) > 0

def log_and_print(message, level='info'):
    if is_logger_configured():
        if level == 'info':
            logging.info(message)
        elif level == 'warning':
            logging.warning(message)
        elif level == 'error':
            logging.error(message)
        elif level == 'critical':
            logging.critical(message)
    print(message)
    
def _raw_json(path_file):
    with open(path_file, "r") as f:
        return json.load(f)


def _load_config(path_file):
    """Load a configuration file, resolving includes and env variables when possible."""
    if _load_config_impl is not None:
        data = _load_config_impl(path_file)
    else:
        data = _raw_json(path_file)

    paths = data.get("paths", data)

    return data, paths


def read_path_file(path_file, field_name="None"):
    """Read paths and metadata from a configuration file.

    Parameters
    ----------
    path_file : str
        Path to the configuration JSON file.
    field_name : str, optional
        If provided, return only that field from the ``paths`` section.

    Returns
    -------
    tuple
        data_paths, export_paths, params_files, zstack_paths,
        subject, file_date
    """

    data, paths = _load_config(path_file)

    if field_name != "None":
        data_paths = paths.get(field_name, [])
        export_paths = []
    else:
        data_paths = paths.get("data_paths", [])
        export_paths = paths.get("export_paths", [])

    params_files = paths.get("params_files", [])
    zstack_paths = paths.get("zstack_paths", [])

    # Subject information may either be a simple string (legacy) or a
    # dictionary (new config template).
    subj = data.get("subject", {})
    if isinstance(subj, dict):
        subject = subj.get("name", "")
    else:
        subject = subj

    # Date can be stored under ``imaging`` or at the top level in legacy
    # files.
    file_date = data.get("imaging", {}).get("date", data.get("date", ""))

    return (
        data_paths,
        export_paths,
        params_files,
        zstack_paths,
        subject,
        file_date,
    )

def get_output_format(config_file):
    """Return the ``save_mcorr_movie`` setting from a configuration file."""

    try:
        data, _ = _load_config(config_file)
        return data.get("params_mcorr", {}).get("save_mcorr_movie", False)
    except Exception as e:
        raise ValueError(f"Error reading configuration file {config_file}: {e}")

def get_mcorr_method(config_file):
    """Return the motion correction method defined in ``params_mcorr``."""
    try:
        data, _ = _load_config(config_file)
        method = data.get("params_mcorr", {}).get("method", "")
        method = method.lower()
        if method in ["caiman"]:
            return method
        if method in ["none", ""]:
            return "none"
        print(
            f"Warning: Unknown motion correction method '{method}' in {config_file}. Defaulting to 'caiman'."
        )
        return "caiman"
    except Exception as e:
        raise ValueError(f"Error reading configuration file {config_file}: {e}")

def get_extraction_method(config_file):
    """Return the extraction method defined in ``params_extraction``."""

    try:
        data, _ = _load_config(config_file)
        method = data.get("params_extraction", {}).get("method", "")
        method = method.lower()
        # Accept legacy 'caiman' naming for CNMF too
        if method in ["cnmf", "suite2p", "aind", "caiman"]:
            # Normalize 'caiman' to 'cnmf' for downstream logic
            if method == "caiman":
                return "cnmf"
            return method
        if method in ["none", ""]:
            return "none"
        print(
            f"Warning: Unknown extraction method '{method}' in {config_file}. Defaulting to 'caiman'."
        )
        return "cnmf"
    except Exception as e:
        raise ValueError(f"Error reading configuration file {config_file}: {e}")

def get_suite2p_ops(config_file, export_path=None):
    """Extract Suite2P ``ops`` parameters (fs, tau, dims, frames).

    Tries the following for ``nframes`` in order:
    - ``imaging.nframes`` from config
    - number of frames in ``z_correlation.npz`` (if present)
    - number of frames detected from exported movie in ``export_path``
      (TIFF/HDF5), if available
    """

    import json as json_module

    try:
        data, _ = _load_config(config_file)
        imaging_params = data.get("imaging", {})
        extraction_params = data.get("params_extraction", {}).get("main", {})

        # Frames/Hz
        if "fr" in imaging_params:
            fs = imaging_params["fr"]
        elif "fs" in imaging_params:
            fs = imaging_params["fs"]
        else:
            raise ValueError("No 'fr' or 'fs' found in imaging_params")

        # Dimensions
        Ly = imaging_params.get("Npixel_y", None)
        if Ly is None:
            raise ValueError("No 'Npixel_y' found in imaging_params")
        Lx = imaging_params.get("Npixel_x", None)
        if Lx is None:
            raise ValueError("No 'Npixel_x' found in imaging_params")

        # Calcium decay time
        if "decay_time" in extraction_params:
            tau = extraction_params["decay_time"]
        elif "tau" in extraction_params:
            tau = extraction_params["tau"]
        else:
            raise ValueError("No 'decay_time' or 'tau' found in params_extraction.main")

        # Optional z-corr file
        zcorr_file = None
        if export_path is not None:
            candidate = os.path.join(export_path, "z_correlation.npz")
            if os.path.exists(candidate):
                zcorr_file = candidate

        # Determine nframes
        nframes = imaging_params.get("nframes", None)

        # 0) Prefer sidecar JSON next to exported movies if available
        if (nframes is None or int(nframes) <= 0) and export_path is not None:
            sidecar_candidates = [
                os.path.join(export_path, "mcorr_movie.tiff.json"),
                os.path.join(export_path, "mcorr_u8.tiff.json"),
                os.path.join(export_path, "mcorr_movie.h5.json"),
                os.path.join(export_path, "mcorr_movie.bin.json"),
                os.path.join(export_path, "cat_tiff_bt.tiff.json"),
                os.path.join(export_path, "cat_tiff.h5.json"),
            ]
            for sc in sidecar_candidates:
                if os.path.exists(sc):
                    try:
                        with open(sc, "r") as f:
                            sc_data = json_module.load(f)
                        nframes_sc = int(sc_data.get("nframes", 0))
                        if nframes_sc > 0:
                            nframes = nframes_sc
                            break
                    except Exception:
                        pass
        if nframes is None:
            # 1) From z-corr if available
            if zcorr_file is not None:
                try:
                    import numpy as np
                    zcorr_data = np.load(zcorr_file)
                    nframes = int(zcorr_data["zcorr"].shape[1])
                except Exception:
                    nframes = None

        # 2) From exported movie if still unknown or zero
        if (nframes is None or int(nframes) <= 0) and export_path is not None:
            tiff_candidates = [
                os.path.join(export_path, "mcorr_movie.tiff"),
                os.path.join(export_path, "mcorr_u8.tiff"),
            ]
            h5_candidate = os.path.join(export_path, "mcorr_movie.h5")

            # Try TIFF first
            for tif_path in tiff_candidates:
                if os.path.exists(tif_path):
                    # Prefer tifffile if available; otherwise fall back to PIL
                    nframes_tif = None
                    try:
                        import tifffile  # type: ignore
                        with tifffile.TiffFile(tif_path) as tif:
                            # len(pages) is robust for multipage TIFF/BigTIFF
                            nframes_tif = int(len(tif.pages))
                    except Exception:
                        try:
                            from PIL import Image  # type: ignore
                            with Image.open(tif_path) as im:
                                count = 0
                                while True:
                                    try:
                                        im.seek(count)
                                        count += 1
                                    except EOFError:
                                        break
                            nframes_tif = int(count)
                        except Exception:
                            nframes_tif = None
                    if nframes_tif is not None and nframes_tif > 0:
                        nframes = nframes_tif
                        break

            # Try HDF5 if still unknown
            if (nframes is None or int(nframes) <= 0) and os.path.exists(h5_candidate):
                try:
                    import h5py  # type: ignore
                    with h5py.File(h5_candidate, "r") as f:
                        if "data" in f:
                            nframes = int(f["data"].shape[0])
                        else:
                            # Fallback: pick the first dataset we can find
                            def first_dataset(g):
                                for v in g.values():
                                    if isinstance(v, h5py.Dataset):
                                        return v
                                    if isinstance(v, h5py.Group):
                                        ds = first_dataset(v)
                                        if ds is not None:
                                            return ds
                                return None

                            ds = first_dataset(f)
                            if ds is not None and ds.shape:
                                nframes = int(ds.shape[0])
                except Exception:
                    pass

        # Final fallback
        if nframes is None:
            nframes = 0

        ops = {
            "nframes": int(nframes),
            "Ly": int(Ly),
            "Lx": int(Lx),
            "fs": float(fs),
            "tau": float(tau),
            "zcorr_file": zcorr_file,
        }
        return json_module.dumps(ops)
    except Exception as e:
        raise ValueError("Error reading configuration file {}: {}".format(config_file, e))

def check_filesystem(data_path):
    # if it's a json file, open it and read the data paths
    if data_path.endswith('.json'):
        data_path = read_path_file(data_path)[0]
        
    # if data_path is a dictionary or a list, get the first data_path
    if isinstance(data_path, dict) or isinstance(data_path, list):
        data_path = data_path[0]
    # print('Data path: ' + data_path)
        
    if not os.path.exists(data_path):
        print('Data path not found. Check the path.')
        return
        
    # check if data files are on /nese (i.e., path starts with /nese)
    if data_path.startswith('/nese'):
        filesystem = 'nese'
    elif data_path.startswith('/om') | data_path.startswith('/om2'):
        filesystem = 'om'
    elif data_path.startswith('/mnt'):
        filesystem = 'raid_storage'
    else:
        filesystem = 'local'
    
    return filesystem

def read_data_paths(file_path, field_name, shell_type="python"):
    """Return a list of paths from the configuration file."""
    data, paths = _load_config(file_path)
    if field_name in paths:
        data_paths = paths[field_name]
    else:
        data_paths = data.get(field_name, [])

    if shell_type == "bash" and isinstance(data_paths, list):
        return "\n".join(data_paths)

    return data_paths
          
def get_common_dir(file_path, field_name):
    data_paths = read_data_paths(file_path, field_name)

    if isinstance(data_paths, list) and len(data_paths) > 1:
        common_dir = os.path.commonpath(data_paths)
    elif isinstance(data_paths, list) and len(data_paths) == 1:
        common_dir = os.path.dirname(data_paths[0])
    elif isinstance(data_paths, dict) and "log_path" in data_paths:
        common_dir = data_paths["log_path"]
    else:
        common_dir = None

    return common_dir

def update_remote_paths(path_file, old_paths, new_paths, overwrite=True):
    # Ensure old_paths and new_paths are lists
    if not isinstance(old_paths, list):
        old_paths = [old_paths]
    if not isinstance(new_paths, list):
        new_paths = [new_paths]

    if len(old_paths) != len(new_paths):
        raise ValueError("old_paths and new_paths must have the same length")

    with open(path_file, "r") as f:
        data = json.load(f)

    json_str = json.dumps(data)
    for old, new in zip(old_paths, new_paths):
        json_str = json_str.replace(old, new)
        if old in path_file:
            path_file = path_file.replace(old, new)

    data = json.loads(json_str)

    if overwrite:
        with open(path_file, "w") as f:
            json.dump(data, f, indent=4)

    return path_file

def generate_target_paths(source_paths, target_fs, shell_type='python', field_name='None'):
    if source_paths.endswith('.json'):
        source_paths = read_path_file(source_paths, field_name)[0]

    if isinstance(source_paths, str):
        source_paths = source_paths.replace('[', '').replace(' ', ',').replace(']', '').split(',')

    if not source_paths:
        raise ValueError("No valid source paths found.")

    target_paths = []
    for source_path in source_paths:
        path_parts = source_path.strip("/").split("/")
        
        # Extract components dynamically
        # Construct the target path
        if field_name == 'export_paths':
            subject = path_parts[-4]  # Subject (e.g., 2P13)
            session_date = path_parts[-3]  # Session date (e.g., 20240903)
            run_name = path_parts[-2]  # Run name (e.g., TSeries-09032024-0952-001)
            method = path_parts[-1]  # Method (e.g., mesmerize)
            target_path = "{}/{}/{}/{}/{}".format(target_fs, subject, session_date, run_name, method)
        else:
            subject = path_parts[-3]  # Subject (e.g., 2P13)
            session_date = path_parts[-2]  # Session date (e.g., 20240903)
            run_name = path_parts[-1]  # Run name (e.g., TSeries-09032024-0952-001)
            target_path = "{}/{}/{}/{}".format(target_fs, subject, session_date, run_name)
        os.makedirs(target_path, exist_ok=True)  # Ensure directory exists

        target_paths.append(target_path)

    if shell_type == 'bash':
        target_paths = '\n'.join(target_paths) # Ensure newline-separated output for Bash

    return target_paths

import json

def update_path_file(
    path_file,
    target_path_file,
    data_paths,
    export_paths=None,
    params_files=None,
    zstack_paths=None,
):
    """Update the ``paths`` section of a configuration file."""

    with open(path_file, "r") as f:
        data = json.load(f)

    paths = data.get("paths", data)

    export_paths = None if export_paths == "__NONE__" else export_paths
    params_files = None if params_files == "__NONE__" else params_files
    zstack_paths = None if zstack_paths == "__NONE__" else zstack_paths
    export_paths = export_paths if export_paths is not None else paths.get("export_paths", [])
    params_files = params_files if params_files is not None else paths.get("params_files", [])
    zstack_paths = zstack_paths if zstack_paths is not None else paths.get("zstack_paths", [])

    def parse_list(value):
        if isinstance(value, str):
            return value.replace("[", "").replace("]", "").splitlines()
        return value

    data_paths = parse_list(data_paths)
    export_paths = parse_list(export_paths)
    zstack_paths = parse_list(zstack_paths)

    paths.update(
        {
            "data_paths": data_paths,
            "export_paths": export_paths,
            "params_files": params_files,
            "zstack_paths": zstack_paths,
        }
    )
    data["paths"] = paths

    if target_path_file is None:
        print("Overwriting original path file")
        target_path_file = path_file

    with open(target_path_file, "w") as f:
        json.dump(data, f, indent=4)

    print("Updated path file saved to {}".format(target_path_file))

def transfer_data(source_paths, target_paths):
    if isinstance(source_paths, str):
        source_paths = source_paths.replace('[', '').replace(' ', ',').replace(']', '').split(',')
        # print('Source paths now: ' + str(source_paths))
    if isinstance(target_paths, str):
        target_paths = target_paths.replace('[', '').replace(' ', ',').replace(']', '').split(',')
        # print('Target paths now: ' + str(target_paths))
        
    for source_path, target_path in zip(source_paths, target_paths):        
        # copy data from source to target
        if os.path.exists(source_path):
            print('Copying data from ' + source_path + ' to ' + target_path)
            os.system('rsync -azP ' + source_path + ' ' + target_path)
        else:
            print('Source path does not exist')
        
    return
          
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file", nargs="+", help="Configuration JSON file")
    parser.add_argument(
        "--get-mcorr-method",
        action="store_true",
        help="Extract the motion correction method from the configuration file",
    )
    parser.add_argument(
        "--get-extraction-method",
        action="store_true",
        help="Extract the extraction method from the configuration file",
    )
    parser.add_argument(
        "--get-suite2p-ops",
        action="store_true",
        help="Extract Suite2P ops parameters (fs and tau) from the configuration file",
    )
    parser.add_argument(
        "--get-output-format",
        dest="get_output_format",
        action="store_true",
        help="Extract the output format parameter from the configuration file",
    )
    parser.add_argument(
        "--export-path",
        default=None,
        help="Path to the export directory",
    )
    args = parser.parse_args()

    config_file = args.config_file[0]

    if args.get_mcorr_method:
        print(get_mcorr_method(config_file))
    elif args.get_extraction_method:
        print(get_extraction_method(config_file))
    elif args.get_suite2p_ops:
        print(get_suite2p_ops(config_file, args.export_path))
    elif args.get_output_format:
        print(get_output_format(config_file))
    else:
        read_path_file(config_file)
      
if __name__ == '__main__':
    main()
