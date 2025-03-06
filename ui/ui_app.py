import streamlit as st
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime 

st.set_page_config(layout="wide")

st.markdown("""
    <style>
    [data-testid="stSidebar"] {
        resize: horizontal;        /* Make it resizable */
        overflow: auto;           /* Needed for the resize handle to show */
        min-width: 30% !important;
        max-width: 50% !important;
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
params_dir = root_dir / "Mesmerize" / "parameters"
paths_dir = root_dir / "Mesmerize" / "paths"

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
# Initialize session state to store selected file paths
# -------------------------------------------------------------------------
def init_session_state():
    if "main_param_file_path" not in st.session_state:
        st.session_state["main_param_file_path"] = None
    if "zshift_file_path" not in st.session_state:
        st.session_state["zshift_file_path"] = None

# -------------------------------------------------------------------------
# Main Streamlit App
# -------------------------------------------------------------------------
def main():

    init_session_state()
    
    st.title("Analysis 2P: motion correction and CNMF")
    st.write("1. Create or re-use the parameter file(s) on the left sidebar.")
    st.write("2. Fill in the fields below to create a path JSON file.")
    st.write("3. Run the pipeline.")

    # Gather existing param files from the folder
    existing_params = list_existing_param_files(params_dir)
    existing_main = existing_params["main"]   # list[Path]
    existing_zshift = existing_params["zshift"]
    
    # ---------------------------------------------------------------------
    # STEP 1: Create or reuse the MAIN param file
    # ---------------------------------------------------------------------
    st.sidebar.header("Main Parameter File")
    param_mode = st.sidebar.radio(
        "Main param file mode:",
        ("Reuse Existing", "Create from Template", "Create from Existing")
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

    elif param_mode == "Create from Template":
        # User starts with a default template (DEFAULT_MAIN_PARAM_TEMPLATE), can edit text
        main_param_text = st.sidebar.text_area(
            "Edit main param JSON if you wish:",
            value=json.dumps(DEFAULT_MAIN_PARAM_TEMPLATE, indent=4),
            height=300
        )
        main_param_filename = st.sidebar.text_input(
            "Filename (e.g. 'params_GC8m_25x_zoom1_610pi.json'):",
            "params_GC8m_25x_zoom1_610pi.json"
        )
        
        if st.sidebar.button("Save Main Param File"):
            try:
                main_param_content = json.loads(main_param_text)
                fullpath = params_dir / main_param_filename
                params_dir.mkdir(parents=True, exist_ok=True)
                
                # Write the new file
                with open(fullpath, "w") as f:
                    json.dump(main_param_content, f, indent=4)
                
                # Store path in session state
                st.session_state["main_param_file_path"] = fullpath
                st.sidebar.success(f"Saved main param file to {fullpath}")
            except Exception as e:
                st.sidebar.error(f"Error saving param file: {e}")

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
    st.sidebar.header("(Optional) Z-motion Param File")
    use_zshift = st.sidebar.checkbox("Use Z-motion correction?", value=False)

    if use_zshift:
        # Let user choose among 3 modes: Reuse, Create from Template, Create from Existing
        zshift_mode = st.sidebar.radio(
            "Z-shift param file mode:",
            ("Reuse Existing", "Create from Template", "Create from Existing")
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
        
        elif zshift_mode == "Create from Template":
            # Start from DEFAULT_ZSHIFT_PARAM_TEMPLATE
            zshift_text = st.sidebar.text_area(
                "Edit Z-shift param JSON if desired:",
                value=json.dumps(DEFAULT_ZSHIFT_PARAM_TEMPLATE, indent=4),
                height=300
            )
            zshift_filename = st.sidebar.text_input(
                "Z-shift param filename (e.g. 'params_zshift_C57_N1M2.json'):",
                "params_zshift_C57_N1M2.json"
            )
            
            if st.sidebar.button("Save Z-shift Param File"):
                try:
                    zshift_content = json.loads(zshift_text)
                    fullpath = params_dir / zshift_filename
                    params_dir.mkdir(parents=True, exist_ok=True)
                    
                    with open(fullpath, "w") as f:
                        json.dump(zshift_content, f, indent=4)
                    
                    st.session_state["zshift_file_path"] = fullpath
                    st.sidebar.success(f"Saved Z-shift param file to {fullpath}")
                except Exception as e:
                    st.sidebar.error(f"Error saving z-shift param file: {e}")
        
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
    # STEP 3: Create the path JSON, referencing the selected files
    # ---------------------------------------------------------------------
    st.subheader("Path File Setup")
    
    subject = st.text_input("Subject", value=DEFAULT_PATH_FILE_TEMPLATE.get("subject", ""))
    date_ = st.text_input("Date", value=datetime.now().strftime("%Y-%m-%d"))
    exp_type = st.text_input("Experiment type", value=DEFAULT_PATH_FILE_TEMPLATE.get("experiment_type", ""))
    
    concat_groups_str = st.text_input("Concatenation groups (comma-separated)", "1,2,3")
    concat_groups = []
    if concat_groups_str.strip():
        try:
            concat_groups = [int(x.strip()) for x in concat_groups_str.split(",")]
        except:
            concat_groups = DEFAULT_PATH_FILE_TEMPLATE.get("concatenation_groups", [])
    
    # Data paths
    data_paths_input = st.text_area(
        "Data paths (one per line)",
        value="\n".join(DEFAULT_PATH_FILE_TEMPLATE.get("data_paths", []))
    )
    data_paths = [line.strip() for line in data_paths_input.split("\n") if line.strip()]
    
    # Export paths
    export_paths_input = st.text_area(
        "Export paths (one per line)",
        value="\n".join(DEFAULT_PATH_FILE_TEMPLATE.get("export_paths", []))
    )
    export_paths = [line.strip() for line in export_paths_input.split("\n") if line.strip()]
    
    # Z-stack paths
    zstack_paths_input = st.text_area(
        "Z-stack paths (one per line)",
        value="\n".join(DEFAULT_PATH_FILE_TEMPLATE.get("zstack_paths", [])) if use_zshift else ""
    )
    zstack_paths = [line.strip() for line in zstack_paths_input.split("\n") if line.strip()]
    
    # Logging
    default_log_dict = DEFAULT_PATH_FILE_TEMPLATE.get("logging", {"log_path": "", "log_level": "INFO"})
    log_path = st.text_input("Log path", value=default_log_dict.get("log_path", ""))
    log_level = st.selectbox(
        "Log level",
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        index=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].index(default_log_dict.get("log_level", "INFO"))
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
    
    # Insert the selected param file (if any)
    if st.session_state["main_param_file_path"]:
        path_file_dict["params_files"] = [str(st.session_state["main_param_file_path"])]
    
    # Insert the selected zshift file (if any)
    if use_zshift and st.session_state["zshift_file_path"]:
        path_file_dict["z_params_files"] = [str(st.session_state["zshift_file_path"])]
    
    st.subheader("Path JSON Preview")
    st.json(path_file_dict)
    
    # ---------------------------------------------------------------------
    # Save or download the path file
    # ---------------------------------------------------------------------
    path_json_name = st.text_input("Path JSON filename:", "my_paths.json")
    
    if st.button("Download Path JSON"):
        data_to_download = json.dumps(path_file_dict, indent=4)
        st.download_button("Download File", data_to_download, file_name=path_json_name, mime="application/json")
    
    if st.button("Save Path JSON Locally"):
        try:
            path_file_path = paths_dir / path_json_name
            paths_dir.mkdir(parents=True, exist_ok=True)
            with open(path_file_path, "w") as f:
                json.dump(path_file_dict, f, indent=4)
            st.success(f"Saved {path_json_name} locally to {path_file_path}")
        except Exception as e:
            st.error(f"Error saving path JSON: {e}")
    
    # ---------------------------------------------------------------------
    # STEP 4: Run the pipeline
    # ---------------------------------------------------------------------
    st.subheader("Run the Pipeline (Optional)")
    st.write("This will call `batch_mcorr_cnmf.py <path_file>` in your current environment.")
    
    if st.button("Run Pipeline Now"):
        cmd = ["python", "batch_mcorr_cnmf.py", path_json_name]
        st.write(f"Running command: {' '.join(cmd)}")
        try:
            completed_proc = subprocess.run(cmd, capture_output=True, text=True)
            if completed_proc.returncode == 0:
                st.success("Pipeline finished successfully!")
                st.text_area("Pipeline Output", completed_proc.stdout, height=200)
            else:
                st.error(f"Pipeline exited with code {completed_proc.returncode}")
                st.text_area("Pipeline Error Output", completed_proc.stderr, height=200)
        except Exception as e:
            st.error(f"Error running pipeline: {e}")

if __name__ == "__main__":
    main()
