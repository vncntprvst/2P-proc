import streamlit as st
import json
import os
import platform
from pathlib import Path
import subprocess
from dotenv import load_dotenv
from datetime import datetime 
from streamlit.web.server.server import Server

st.set_page_config(layout="wide")

st.markdown("""
    <style>
    [data-testid="stSidebar"] {
        resize: horizontal;        /* Make it resizable */
        overflow: auto;           /* Needed for the resize handle to show */
        min-width: 30% !important;
        max-width: 50% !important;
    }
    /* Make text bigger on tab labels */
    [data-testid="stTab"] div[data-testid="stMarkdownContainer"] p {
        font-size: 24px !important;
    }
    .block-container {
        padding-top: 1rem !important;
        margin-top: 1rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------------
# Setup: directories
# -------------------------------------------------------------------------
root_dir = Path(__file__).resolve().parents[1]
caiman_pipeline_dir = root_dir / "Mesmerize"
params_dir = caiman_pipeline_dir / "parameters"
paths_dir = caiman_pipeline_dir / "paths"
scripts_dir = root_dir / "scripts"

# -------------------------------------------------------------------------
# Load default templates
# -------------------------------------------------------------------------
with open(params_dir / "params_mcorr_cnmf_template.json", "r") as f:
    DEFAULT_MAIN_PARAM_TEMPLATE = json.load(f)
with open(params_dir / "params_zshift_template.json", "r") as f:
    DEFAULT_ZSHIFT_PARAM_TEMPLATE = json.load(f)
with open(paths_dir / "paths_template.json", "r") as f:
    DEFAULT_PATH_FILE_TEMPLATE = json.load(f)

# -------------------------------------------------------------------------
# Create or filter list of existing param files
# -------------------------------------------------------------------------
def list_existing_param_files(param_dir: Path):
    """Return a dict with two lists: 'main' param files and 'zshift' param files."""
    result = {"main": [], "zshift": []}
    if not param_dir.exists():
        return result
    
    all_jsons = list(param_dir.glob("*.json"))
    for p in all_jsons:
        fname = p.name
        # main param: starts with 'params_' but NOT 'params_zshift'
        if fname.startswith("params_") and not fname.startswith("params_zshift"):
            result["main"].append(p)
        # zshift param: starts with 'params_zshift'
        elif fname.startswith("params_zshift"):
            result["zshift"].append(p)
    
    return result

# -------------------------------------------------------------------------
# Parse run numbers from data paths
# -------------------------------------------------------------------------
def parse_run_numbers(data_paths):
    """
    Given a list of paths like:
      "F:/Data2/2P/C57_N1M2/06012023/TSeries-06012023-1002-001"
    we extract the final dash-separated chunk (e.g. "001"),
    convert it to an int (1), and return a list like ["run1"].

    e.g. ["run1", "run2", "run3"]
    """
    runs = []
    for dp in data_paths:
        parts = dp.split("-")
        if not parts:
            continue

        last_part = parts[-1]  # e.g. "001"
        # If there's a trailing slash or extension, you might strip it:
        # last_part = last_part.rstrip("/").replace(".tif","")

        try:
            run_num = int(last_part)  # convert "001" -> 1
            runs.append(f"run{run_num}")
        except ValueError:
            # If it's not purely digits, skip or handle differently
            pass
    return runs

# -------------------------------------------------------------------------
# Initialize session state to store selected file paths
# -------------------------------------------------------------------------
def init_session_state():
    if "main_param_file_path" not in st.session_state:
        st.session_state["main_param_file_path"] = None
    if "zshift_file_path" not in st.session_state:
        st.session_state["zshift_file_path"] = None

# -------------------------------------------------------------------------
# List existing path files
# -------------------------------------------------------------------------
def list_existing_path_files(paths_dir: Path):
    """Return all .json files in the paths_dir directory."""
    if not paths_dir.exists():
        return []
    return list(paths_dir.glob("*.json"))
    
# -------------------------------------------------------------------------
# Get remote user
# -------------------------------------------------------------------------
def get_remote_user(host):
    try:
        result = subprocess.run(["ssh", host, "echo $USER"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            raise Exception(f"Failed to get remote user: {result.stderr}")
    except Exception as e:
        st.error(f"Error getting remote user: {e}")
        return None
    
# -------------------------------------------------------------------------
# Main Streamlit App
# -------------------------------------------------------------------------
def main():

    init_session_state()
    
    st.title("Analysis 2P: motion correction and CNMF")
    st.write("1. Create or re-use the parameter file(s) on the left sidebar.")
    st.write("2. Fill in the fields below to create a paths JSON file.")
    st.write("3. Run the pipeline.")

    # Gather existing param files from the folder
    existing_params = list_existing_param_files(params_dir)
    existing_main = existing_params["main"]   # list[Path]
    existing_zshift = existing_params["zshift"]
    
    # ---------------------------------------------------------------------
    # STEP 1: Create or reuse the MAIN param file
    # ---------------------------------------------------------------------
    st.sidebar.header("CaImAn Parameter File", help="[CaImAn Parameters](https://caiman.readthedocs.io/en/latest/Getting_Started.html#parameters)")
    param_mode = st.sidebar.radio(
        "CaImAn param file mode:",
        ("Reuse Existing", "Create from Existing")
    )

    if param_mode == "Reuse Existing":
        # User simply picks one of the existing param files (no editing)
        if not existing_main:
            st.sidebar.warning("No existing main param files found. Please create one first.")
        else:
            main_fnames = [p.name for p in existing_main]
            chosen_main_fname = st.sidebar.selectbox(
                "Select an existing main param file:",
                main_fnames
            )
            st.sidebar.write(f"Chosen file: {chosen_main_fname}")
            
            chosen_idx = main_fnames.index(chosen_main_fname)
            chosen_fullpath = existing_main[chosen_idx]
            
            # Store selection in session state for use in the path preview
            st.session_state["main_param_file_path"] = chosen_fullpath

    # elif param_mode == "Create from Template":
    #     # User starts with a default template (DEFAULT_MAIN_PARAM_TEMPLATE), can edit text
    #     main_param_text = st.sidebar.text_area(
    #         "Edit main param JSON if you wish:",
    #         value=json.dumps(DEFAULT_MAIN_PARAM_TEMPLATE, indent=4),
    #         height=300
    #     )
    #     main_param_filename = st.sidebar.text_input(
    #         "Filename (e.g. 'params_GC8m_25x_zoom1_610pi.json'):",
    #         "params_GC8m_25x_zoom1_610pi.json"
    #     )
        
    #     if st.sidebar.button("Save Main Param File"):
    #         try:
    #             main_param_content = json.loads(main_param_text)
    #             fullpath = params_dir / main_param_filename
    #             params_dir.mkdir(parents=True, exist_ok=True)
                
    #             # Write the new file
    #             with open(fullpath, "w") as f:
    #                 json.dump(main_param_content, f, indent=4)
                
    #             # Store path in session state
    #             st.session_state["main_param_file_path"] = fullpath
    #             st.sidebar.success(f"Saved main param file to {fullpath}")
    #         except Exception as e:
    #             st.sidebar.error(f"Error saving param file: {e}")

    else:  # param_mode == "Create from Existing"
        # User picks an existing file, can then edit it, and save as a new file
        if not existing_main:
            st.sidebar.warning("No existing parameter files found. Please create one first.")
        else:
            main_fnames = [p.name for p in existing_main]
            chosen_main_fname = st.sidebar.selectbox(
                "Select an existing main param file to copy/edit:",
                main_fnames
            )
            
            chosen_idx = main_fnames.index(chosen_main_fname)
            chosen_fullpath = existing_main[chosen_idx]
            
            # Load the chosen file’s contents for editing
            try:
                with open(chosen_fullpath, "r") as f:
                    chosen_file_content = json.load(f)
                default_text = json.dumps(chosen_file_content, indent=4)
            except Exception as e:
                default_text = f"Error reading file: {e}"
            
            main_param_text = st.sidebar.text_area(
                "Edit the JSON below as needed:",
                value=default_text,
                height=300
            )
            
            # Let the user specify a new filename
            main_param_filename = st.sidebar.text_input(
                "Save as new filename:",
                f"copy_of_{chosen_fullpath.name}"
            )
            
            if st.sidebar.button("Save Copy of Main Param File"):
                try:
                    new_content = json.loads(main_param_text)
                    new_path = params_dir / main_param_filename
                    params_dir.mkdir(parents=True, exist_ok=True)
                    
                    with open(new_path, "w") as f:
                        json.dump(new_content, f, indent=4)
                    
                    st.session_state["main_param_file_path"] = new_path
                    st.sidebar.success(f"Saved new main param file to {new_path}")
                except Exception as e:
                    st.sidebar.error(f"Error saving param file: {e}")

    
    # ---------------------------------------------------------------------
    # STEP 2: Create or reuse the Z-shift param file (optional)
    # ---------------------------------------------------------------------
    st.sidebar.header("(Optional) Z-motion Parameter File")
    use_zshift = st.sidebar.checkbox("Use Z-motion correction?", value=False, key="zshift_checkbox")

    if use_zshift:
        # Let user choose among 3 modes: Reuse, Create from Template, Create from Existing
        zshift_mode = st.sidebar.radio(
            "Z-shift parameter file mode:",
            ("Reuse Existing", "Create from Existing")
        )
        
        if zshift_mode == "Reuse Existing":
            # User picks a file from existing_zshift (no editing).
            if not existing_zshift:
                st.sidebar.warning("No existing z-shift param files found. Please create one first.")
            else:
                zshift_fnames = [p.name for p in existing_zshift]
                chosen_zshift_fname = st.sidebar.selectbox(
                    "Select an existing Z-shift param file:",
                    zshift_fnames
                )
                st.sidebar.write(f"Chosen file: {chosen_zshift_fname}")
                
                chosen_idx = zshift_fnames.index(chosen_zshift_fname)
                chosen_fullpath = existing_zshift[chosen_idx]
                st.session_state["zshift_file_path"] = chosen_fullpath
        
        # elif zshift_mode == "Create from Template":
        #     # Start from DEFAULT_ZSHIFT_PARAM_TEMPLATE
        #     zshift_text = st.sidebar.text_area(
        #         "Edit Z-shift param JSON if desired:",
        #         value=json.dumps(DEFAULT_ZSHIFT_PARAM_TEMPLATE, indent=4),
        #         height=300
        #     )
        #     zshift_filename = st.sidebar.text_input(
        #         "Z-shift param filename (e.g. 'params_zshift_C57_N1M2.json'):",
        #         "params_zshift_C57_N1M2.json"
        #     )
            
        #     if st.sidebar.button("Save Z-shift Param File"):
        #         try:
        #             zshift_content = json.loads(zshift_text)
        #             fullpath = params_dir / zshift_filename
        #             params_dir.mkdir(parents=True, exist_ok=True)
                    
        #             with open(fullpath, "w") as f:
        #                 json.dump(zshift_content, f, indent=4)
                    
        #             st.session_state["zshift_file_path"] = fullpath
        #             st.sidebar.success(f"Saved Z-shift param file to {fullpath}")
        #         except Exception as e:
        #             st.sidebar.error(f"Error saving z-shift param file: {e}")
        
        else:  # zshift_mode == "Create from Existing"
            # Let the user pick an existing Z-shift file, copy/edit it, then save under a new name
            if not existing_zshift:
                st.sidebar.warning("No existing z-shift param files found. Please create one first.")
            else:
                zshift_fnames = [p.name for p in existing_zshift]
                chosen_zshift_fname = st.sidebar.selectbox(
                    "Select an existing Z-shift param file to copy/edit:",
                    zshift_fnames
                )
                
                chosen_idx = zshift_fnames.index(chosen_zshift_fname)
                chosen_fullpath = existing_zshift[chosen_idx]
                
                # Load the chosen file contents
                try:
                    with open(chosen_fullpath, "r") as f:
                        chosen_file_content = json.load(f)
                    default_text = json.dumps(chosen_file_content, indent=4)
                except Exception as e:
                    default_text = f"Error reading file: {e}"
                
                zshift_text = st.sidebar.text_area(
                    "Edit the JSON below as needed:",
                    value=default_text,
                    height=300
                )
                
                # Let the user specify a new filename
                zshift_filename = st.sidebar.text_input(
                    "Save as new filename:",
                    f"copy_of_{chosen_fullpath.name}"
                )
                
                if st.sidebar.button("Save Copy of Z-shift Param File"):
                    try:
                        new_content = json.loads(zshift_text)
                        new_path = params_dir / zshift_filename
                        params_dir.mkdir(parents=True, exist_ok=True)
                        
                        with open(new_path, "w") as f:
                            json.dump(new_content, f, indent=4)
                        
                        st.session_state["zshift_file_path"] = new_path
                        st.sidebar.success(f"Saved new Z-shift param file to {new_path}")
                    except Exception as e:
                        st.sidebar.error(f"Error saving param file: {e}")

    else:
        # If the user unchecks "Use Z-motion correction?" 
        # clear any previously selected zshift path
        st.session_state["zshift_file_path"] = None

    # ---------------------------------------------------------------------

    tab1, tab2 = st.tabs(["Paths File", "Run the pipeline"])

    # ---------------------------------------------------------------------
    # STEP 3: Create or load the path JSON, referencing the selected files
    # ---------------------------------------------------------------------
    with tab1:
        # st.header("Path File Setup", divider=True)
        # Radio to pick path file mode
        path_file_mode = st.radio(
            "Fill the fields below, check the preview, and save the JSON file.",
            ("Load Existing", "Create from Template"),
            index=1  # default to "Create from Template"
        )

        # We'll store the loaded or template dictionary here
        if path_file_mode == "Load Existing":
            existing_paths_files = list_existing_path_files(paths_dir)
            if not existing_paths_files:
                st.warning("No existing path files found. Please create one first.")
                path_data = DEFAULT_PATH_FILE_TEMPLATE.copy()
            else:
                path_fnames = [p.name for p in existing_paths_files]
                chosen_path_fname = st.selectbox("Select an existing path file:", path_fnames)
                
                chosen_idx = path_fnames.index(chosen_path_fname)
                chosen_fullpath = existing_paths_files[chosen_idx]
                
                # Load the chosen path file into a dict
                try:
                    with open(chosen_fullpath, "r") as f:
                        loaded_paths = json.load(f)
                    st.info(f"Loaded existing path file: {chosen_fullpath}")
                    path_data = loaded_paths
                except Exception as e:
                    st.error(f"Error loading {chosen_fullpath}: {e}")
                    path_data = DEFAULT_PATH_FILE_TEMPLATE.copy()
        else:
            # Use the default path template
            path_data = DEFAULT_PATH_FILE_TEMPLATE.copy()

        # --- Now let the user edit each field in the usual text inputs:
        subject = st.text_input("Subject", value=path_data.get("subject", ""))
        date_ = st.text_input("Date", value=path_data.get("date", datetime.now().strftime("%Y%m%d")))
        exp_type = st.text_input("Experiment type", value=path_data.get("experiment_type", ""))

        # Concatenation groups
        concat_groups_str = st.text_input(
            "Concatenation groups (comma-separated)",
            ",".join(str(x) for x in path_data.get("concatenation_groups", []))
        )
        try:
            concat_groups = [int(x.strip()) for x in concat_groups_str.split(",") if x.strip()]
        except:
            concat_groups = path_data.get("concatenation_groups", [])

        # Data paths
        data_paths_input = st.text_area(
            "Data paths (one per line)",
            value="\n".join(path_data.get("data_paths", []))
        )
        data_paths = [line.strip() for line in data_paths_input.split("\n") if line.strip()]

        # Export paths
        export_paths_input = st.text_area(
            "Export paths (one per line)",
            value="\n".join(path_data.get("export_paths", []))
        )
        export_paths = [line.strip() for line in export_paths_input.split("\n") if line.strip()]

        # If user wants z-stack
        # use_zshift_for_paths = st.sidebar.checkbox("Use Z-motion correction?", value=False, key="zshift_paths_checkbox")
        zstack_paths_input = st.text_area(
            "Z-stack paths (one per line)",
            value="\n".join(path_data.get("zstack_paths", [])) if use_zshift else ""
        )
        zstack_paths = [line.strip() for line in zstack_paths_input.split("\n") if line.strip()]

        # Logging
        log_dict = path_data.get("logging", {})
        log_path = st.text_input("Log path", value=log_dict.get("log_path", ""))
        possible_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        default_level = log_dict.get("log_level", "INFO")
        if default_level not in possible_log_levels:
            default_level = "INFO"
        log_level = st.selectbox(
            "Log level",
            possible_log_levels,
            index=possible_log_levels.index(default_level)
        )

        # Build final path file dictionary
        path_file_dict = {
            "subject": subject,
            "date": date_,
            "experiment_type": exp_type,
            "concatenation_groups": concat_groups,
            "data_paths": data_paths,
            "export_paths": export_paths,
            "params_files": [],
            "zstack_paths": zstack_paths,
            "z_params_files": [],
            "logging": {
                "log_path": log_path,
                "log_level": log_level
            }
        }

        # Fill references to param files from session_state if available
        if st.session_state["main_param_file_path"]:
            path_file_dict["params_files"] = [str(st.session_state["main_param_file_path"])]
        if use_zshift and st.session_state["zshift_file_path"]:
            path_file_dict["z_params_files"] = [str(st.session_state["zshift_file_path"])]

        # Preview JSON
        st.subheader("Path JSON Preview", divider=True)
        st.json(path_file_dict)

        # --- Suggest a default filename based on subject, date and run numbers
        runs = parse_run_numbers(path_file_dict["data_paths"])
        if runs:
            # e.g. 'run1_run2_run3'
            runs_str = "_".join(runs)
            default_filename = f"paths_{subject}_{date_}_{runs_str}.json" if (subject and date_) else "my_paths.json"
        else:
            # fallback if no runs found
            default_filename = f"paths_{subject}_{date_}_run.json" if (subject and date_) else "my_paths.json"

        path_json_name = st.text_input("Path JSON filename:", default_filename)

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Save Path JSON"):
                try:
                    path_file_path = paths_dir / path_json_name
                    paths_dir.mkdir(parents=True, exist_ok=True)
                    with open(path_file_path, "w") as f:
                        json.dump(path_file_dict, f, indent=4)
                    st.success(f"Saved {path_json_name} locally to {path_file_path}")
                except Exception as e:
                    st.error(f"Error saving path JSON: {e}")
        with col2:
            st.download_button(
                label="Download Path JSON",
                data=json.dumps(path_file_dict, indent=4),
                file_name=path_json_name,
                mime="application/json"
            )
            
    # ---------------------------------------------------------------------
    # STEP 4: Run the pipeline
    # ---------------------------------------------------------------------
    with tab2:
        # st.header("Run the Pipeline", divider=True)

        # st.write("The pipeline can be run locally or on the Openmind cluster.")

        # 1) Button to run locally    
        if st.button(f"Run Pipeline Locally ({platform.node()})"):
            cmd = ["python", f"{caiman_pipeline_dir}/batch_mcorr_cnmf.py", path_json_name]
            st.write(f"Running command locally: {' '.join(cmd)}")
            try:
                completed_proc = subprocess.run(cmd, capture_output=True, text=True)
                if completed_proc.returncode == 0:
                    st.success("Pipeline finished successfully!")
                    st.text_area("Pipeline Output", completed_proc.stdout, height=200)
                else:
                    st.error(f"Pipeline exited with code {completed_proc.returncode}")
                    st.text_area("Pipeline Error Output", completed_proc.stderr, height=200)
            except Exception as e:
                st.error(f"Error running pipeline locally: {e}")

        # 2) Button to run on the cluster
        if st.button("Run Pipeline on Cluster (Openmind)"):
            # 2.1 Copy the path JSON to cluster
            # 2.2 Copy param files if needed
            # 2.3 SSH and run sbatch

            # We should have a local path to the paths JSON at this point, but check anyway:
            local_path_json = paths_dir / path_json_name
            if not local_path_json.exists():
                st.error(f"Path JSON does not exist locally: {local_path_json}")
            else:
                # Load environment variables from .env file
                load_dotenv(dotenv_path=root_dir / "scripts/utils/.env")
                # Get the SSH_LOGIN_NODE value
                remote_host = os.getenv("SSH_LOGIN_NODE")
                remote_user = get_remote_user(remote_host) 
                remote_pipeline_dir = f"{os.getenv('OM_USER_DIR_ALIAS')}/{remote_user}/code/Analysis_2P"
                remote_paths_dir = f"{remote_pipeline_dir}/Mesmerize/paths"
                remote_params_dir = f"{remote_pipeline_dir}/Mesmerize/parameters"
                
                # Create remote directories if they do not exist
                ssh_mkdir_cmd = [
                    "ssh",
                    remote_host,
                    f"mkdir -p {remote_paths_dir} {remote_params_dir}"
                ]
                st.write(f"Running: {' '.join(ssh_mkdir_cmd)}")
                try:
                    ssh_mkdir_proc = subprocess.run(ssh_mkdir_cmd, capture_output=True, text=True)
                    if ssh_mkdir_proc.returncode != 0:
                        st.error(f"Failed to create remote directories: {ssh_mkdir_proc.stderr}")
                        st.stop()
                    else:
                        st.info("Remote directories created or already exist.")
                except Exception as e:
                    st.error(f"Error creating remote directories: {e}")
                    st.stop()

                # 1. scp the paths JSON file to the cluster
                scp_cmd = [
                    "scp",
                    str(local_path_json),
                    f"{remote_host}:{remote_paths_dir}/{path_json_name}"
                ]
                st.write(f"Running: {' '.join(scp_cmd)}")
                try:
                    scp_proc = subprocess.run(scp_cmd, capture_output=True, text=True)
                    if scp_proc.returncode != 0:
                        st.error(f"SCP for path file failed: {scp_proc.stderr}")
                        st.stop()  # stop the Streamlit flow
                    else:
                        st.info("Path JSON copied to cluster.")
                except Exception as e:
                    st.error(f"Error copying path file to cluster: {e}")
                    st.stop()

                # 2. scp the param files similarly (only if these exist on the local machine)
                if st.session_state["main_param_file_path"]:
                    local_param = Path(st.session_state["main_param_file_path"])
                    if local_param.exists():
                        scp_params_cmd = [
                            "scp",
                            str(local_param),
                            f"{remote_host}:{remote_params_dir}/{local_param.name}"
                        ]
                        st.write(f"Running: {' '.join(scp_params_cmd)}")
                        scp_proc2 = subprocess.run(scp_params_cmd, capture_output=True, text=True)
                        if scp_proc2.returncode != 0:
                            st.error(f"SCP for main param failed: {scp_proc2.stderr}")
                            st.stop()
                        else:
                            st.info("Main param file copied to cluster.")
                    else:
                        st.warning(f"Local param file does not exist: {local_param}")

                if st.session_state["zshift_file_path"]:
                    local_zparam = Path(st.session_state["zshift_file_path"])
                    if local_zparam.exists():
                        scp_zparams_cmd = [
                            "scp",
                            str(local_zparam),
                            f"{remote_host}:{remote_params_dir}/{local_zparam.name}"
                        ]
                        st.write(f"Running: {' '.join(scp_zparams_cmd)}")
                        scp_proc3 = subprocess.run(scp_zparams_cmd, capture_output=True, text=True)
                        if scp_proc3.returncode != 0:
                            st.error(f"SCP for Z-shift param failed: {scp_proc3.stderr}")
                            st.stop()
                        else:
                            st.info("Z-shift param file copied to cluster.")
                    else:
                        st.warning(f"Local Z-shift param file does not exist: {local_zparam}")

                # 3. SSH to cluster, run sbatch
                remote_scripts_dir = f"{remote_pipeline_dir}/scripts"
                cluster_cmd = (
                    f"cd {remote_scripts_dir} && sbatch om_batch_mcorr_cnmf.sh "
                    f"{remote_paths_dir}/{path_json_name}"
                )
                ssh_cmd = ["ssh", remote_host, cluster_cmd]

                st.write(f"Running: {' '.join(ssh_cmd)}")
                try:
                    ssh_proc = subprocess.run(ssh_cmd, capture_output=True, text=True)
                    if ssh_proc.returncode == 0:
                        st.success("Submitted job to cluster via sbatch!")
                        st.text_area("Cluster Output", ssh_proc.stdout, height=200)
                    else:
                        st.error(f"Cluster sbatch command failed with code {ssh_proc.returncode}")
                        st.text_area("Cluster Error", ssh_proc.stderr, height=200)
                except Exception as e:
                    st.error(f"Error running sbatch on cluster: {e}")

    # ---------------------------------------------------------------------
    if st.button("Stop"):
        Server.get_current().stop()
        sys.exit(0)
    
if __name__ == "__main__":
    main()
