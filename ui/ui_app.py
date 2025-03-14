import streamlit as st
import json
import os
import sys
import re
import time
import signal
import platform
from pathlib import Path
import subprocess
from dotenv import load_dotenv, dotenv_values, set_key
from datetime import datetime 
from streamlit.web.server.server import Server

st.set_page_config(layout="wide")

st.markdown(
    """
    <style>
    /* Set the main container margins */
    .block-container {
        padding-top: 1rem !important;
        margin-top: 2rem !important;
    }
    [data-testid="stSidebar"] {
        resize: horizontal;
        overflow: auto;
        min-width: 30% !important;
        max-width: 50% !important;
    }
    /* Make text bigger on tab labels */
    [data-testid="stTab"] div[data-testid="stMarkdownContainer"] p {
        font-size: 18px !important;
    }
    .st-key-intro {
        background-color: #3ab7824c !important;
        padding: 1rem !important;
        border-radius: 15px !important;
        border: 2px solid #ccc !important;
        box-shadow: 0 3px 6px rgba(0,0,0,0.3) !important;
    }
    .st-key-z-mcorr-methods {
        background-color: #ee82ee33 !important;
        padding: 1rem !important;
        border-radius: 15px !important;
        border: 1px solid #ccc !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.3) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------------
# Setup: directories
# -------------------------------------------------------------------------
code_dir = Path(__file__).resolve().parents[1]
caiman_pipeline_dir = code_dir / "Mesmerize"
params_dir = caiman_pipeline_dir / "parameters"
paths_dir = caiman_pipeline_dir / "paths"
scripts_dir = code_dir / "scripts"

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
    if "caiman_param_file_path" not in st.session_state:
        st.session_state["caiman_param_file_path"] = None
    if "zshift_file_path" not in st.session_state:
        st.session_state["zshift_file_path"] = None
    if "show_settings_modal" not in st.session_state:
        st.session_state["show_settings_modal"] = True
    # Load the .env file from ui/.env
    env_path = code_dir / "ui" / ".env"
    # If it doesn't exist, create it base on template.env
    if not env_path.exists():
        template_path = code_dir / "ui" / "template.env"
        with open(template_path, "r") as template_file:
            template_content = template_file.read()
        with open(env_path, "w") as env_file:
            env_file.write(template_content)
    load_dotenv(dotenv_path=env_path)
    # Save individual environment variables in session state so they can be updated
    st.session_state["remote_host"] = os.getenv("SSH_LOGIN_NODE")
    st.session_state["nese_user_dir"] = os.getenv("NESE_USER_DIR")
    st.session_state["remote_code_dir"] = os.getenv("OM_CODE_DIR")
    st.session_state["remote_scratch"] = os.getenv("OM_SCRATCH_DIR")
    
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
        st.error(f"⚠️ Error getting remote user: {e}")
        return None
    
# -------------------------------------------------------------------------
# Convert Windows-style line endings to Unix-style
# -------------------------------------------------------------------------    
def convert_to_unix(filepath):
    """Ensures file has UNIX line endings."""
    with open(filepath, "rb") as f:
        content = f.read()
    content = content.replace(b"\r\n", b"\n")  # Convert Windows CRLF to UNIX LF
    with open(filepath, "wb") as f:
        f.write(content)
        
# -------------------------------------------------------------------------
# Main Streamlit App
# -------------------------------------------------------------------------
def main():

    init_session_state()
    
    topcol1, topcol2 = st.columns([3, 1])
    with topcol1:
        st.header("Analysis 2P: motion correction and CNMF") #, divider="green")
    with topcol2:        
        experimenter = st.text_input("Experimenter", os.getenv("EXPERIMENTER"))
        if experimenter:
            os.environ["EXPERIMENTER"] = experimenter
            set_key(str(code_dir / "ui" / ".env"), "EXPERIMENTER", experimenter)
        
    # st.write("1. and 2. Create or re-use the parameter file(s).")
    # st.write("3. Create a paths JSON file.")
    # st.write("4. Run the pipeline.")
    with st.container(key="intro"):
        run_col1, run_col2 = st.columns(2, vertical_alignment="top")
        
        with run_col1:
            run_method = st.radio(
                "Select run method:",
                options=["Run on Openmind cluster", "Run on local workstation"],
                index=0  # default is "Run on Openmind cluster"
            )
            if run_method == "Run on Openmind cluster":
                paths_dir = caiman_pipeline_dir / "paths" / "openmind"
            else:
                paths_dir = caiman_pipeline_dir / "paths" 
            with open(paths_dir / "paths_template.json", "r") as f:
                DEFAULT_PATH_FILE_TEMPLATE = json.load(f)
                
            if run_method == "Run on Openmind cluster":
                with st.popover("Edit Openmind Settings", use_container_width=True):
                    # Read the current .env values (from ui/.env)
                    env_path = code_dir / "ui" / ".env"
                    env_values = dotenv_values(env_path)
                    
                    # Create input fields for each variable
                    new_remote_host = st.text_input("The SSH login alias (e.g., :grey-background[om7])", value=env_values.get("SSH_LOGIN_NODE", ""))
                    new_remote_code_dir = st.text_input("The remote code directory (e.g., :grey-background[<om_user_dir>/code/Analysis_2P], or :grey-background[/home/$USER/scripts])", value=env_values.get("OM_CODE_DIR", ""))
                    new_remote_scratch = st.text_input("[currently unused] The root data processing directory (e.g., :grey-background[<scratch space>/MyName])", value=env_values.get("OM_SCRATCH_DIR", ""))
                    new_nese_user_dir = st.text_input("[currently unused] Your data directory on NESE (e.g., :grey-background[<nese_lab_dir>/MyName])", value=env_values.get("NESE_USER_DIR", ""))
                    
                    # A button to save the updates
                    if st.button("Save Settings"):
                        set_key(str(env_path), "SSH_LOGIN_NODE", new_remote_host)
                        set_key(str(env_path), "NESE_USER_DIR", new_nese_user_dir)
                        set_key(str(env_path), "OM_CODE_DIR", new_remote_code_dir)
                        set_key(str(env_path), "OM_SCRATCH_DIR", new_remote_scratch)
                        # Update session state variables for immediate access
                        st.session_state["remote_host"] = new_remote_host
                        st.session_state["remote_code_dir"] = new_remote_code_dir
                        st.session_state["remote_scratch"] = new_remote_scratch
                        st.session_state["nese_user_dir"] = new_nese_user_dir
                        st.success("Settings updated!")
 
                    # Set the environment variables remote_paths_dir and remote_params_dir
                    remote_params_dir = Path(Path(new_remote_code_dir) / "Mesmerize" / "parameters").as_posix()
                    remote_paths_dir = Path(Path(new_remote_code_dir) / "Mesmerize" / "paths" / "openmind").as_posix()

            # else:
                # When "Run locally" is selected, show a disabled settings button
                # st.button("Edit Openmind Settings", use_container_width=True, disabled=True)
        
        with run_col2:
            if run_method == "Run on Openmind cluster":
                copy_files = st.checkbox("Do you want the script to transfer the data for you?")
                st.write('''>If selected, the script will transfer the data to the scratch space.  
                         Just provide the paths to the data (e.g., on NESE).''') 
        
    # Gather existing param files from the folder
    existing_params = list_existing_param_files(params_dir)
    existing_main = existing_params["main"]   # list[Path]
    existing_zshift = existing_params["zshift"]
        
    # ---------------------------------------------------------------------

    tab1, tab2, tab3, tab4 = st.tabs([":twisted_rightwards_arrows: Path file ", ":crocodile: Caiman parameters ", ":material/flex_direction: Correct z-motion", ":woman-running: Run the pipeline"])
    
    with tab2:
        # ---------------------------------------------------------------------
        # STEP 2: Create or reuse the CaImAn param file
        # ---------------------------------------------------------------------
        st.write("Enter the parameters for x/y motion correction (:blue-background[params_mcorr]) and CNMF (:blue-background[params_cnmf]).")
        
        if not existing_main:
            st.warning("No existing parameter files found. Please create one first.")
        else:
            main_fnames = [p.name for p in existing_main]

            # Compute default index from session state if available
            if "caiman_param_file_path" in st.session_state and st.session_state["caiman_param_file_path"]:
                current_main_name = Path(st.session_state["caiman_param_file_path"]).name
                if current_main_name in main_fnames:
                    default_index = main_fnames.index(current_main_name)
                else:
                    default_index = main_fnames.index("params_mcorr_cnmf_template.json") if "params_mcorr_cnmf_template.json" in main_fnames else 0
            else:
                default_index = main_fnames.index("params_mcorr_cnmf_template.json") if "params_mcorr_cnmf_template.json" in main_fnames else 0

            chosen_main_fname = st.selectbox(
                "Select an existing CaImAn parameter file:",
                main_fnames,
                index=default_index
            )
            
            chosen_idx = main_fnames.index(chosen_main_fname)
            chosen_fullpath = existing_main[chosen_idx]
            st.session_state["caiman_param_file_path"] = chosen_fullpath
            
            # Load the chosen file’s contents for editing
            try:
                with open(chosen_fullpath, "r") as f:
                    chosen_file_content = json.load(f)
                    
                # Ensure there's a "notes" section
                if "notes" not in chosen_file_content:
                    chosen_file_content["notes"] = {}
                
                # Update the notes section:
                if os.getenv("EXPERIMENTER"):
                    chosen_file_content["notes"]["author"] = experimenter  # experimenter set at the top of the page
                chosen_file_content["notes"]["date"] = datetime.now().strftime("%Y-%m-%d")
                
                default_text = json.dumps(chosen_file_content, indent=4)
            except Exception as e:
                default_text = f"⚠️ Error reading file: {e}"
                
            main_param_text = st.text_area(
                "Edit the parameters as needed, then save the file below if you made any change.",
                value=default_text,
                height=500
            )
            
            # Let the user specify a new filename
            main_param_filename = st.text_input(
                "Save the file parameter file (name must start with :blue-background[params_]):",
                f"{chosen_fullpath.name}"
            )
            
            # Validate the filename
            if not main_param_filename.startswith("params_"):
                st.error("Filename must start with 'params_'")
            
            if st.button("Save CaImAn Parameter File"):
                try:
                    new_content = json.loads(main_param_text)
                    new_path = params_dir / main_param_filename
                    
                    # Save content and path in session state so it persists
                    st.session_state.new_content = new_content
                    st.session_state.new_path = new_path
                    
                    if new_path.exists():
                        st.session_state.pending_overwrite = True
                        st.warning("File already exists. Click 'Confirm Overwrite' to proceed.")
                    else:
                        st.session_state.pending_overwrite = False
                        params_dir.mkdir(parents=True, exist_ok=True)
                        with open(new_path, "w") as f:
                            json.dump(new_content, f, indent=4)
                        st.session_state["caiman_param_file_path"] = new_path
                        st.success(f"Saved new CaImAn param file to {new_path}")
                except Exception as e:
                    st.error(f"⚠️ Error saving param file: {e}")

            if st.session_state.get("pending_overwrite", False):
                if st.button("Confirm Overwrite"):
                    try:
                        new_content = st.session_state.new_content
                        new_path = st.session_state.new_path
                        params_dir.mkdir(parents=True, exist_ok=True)
                        with open(new_path, "w") as f:
                            json.dump(new_content, f, indent=4)
                        st.session_state["caiman_param_file_path"] = new_path
                        st.success(f"Overwritten file at {new_path}")
                        st.session_state.pending_overwrite = False  # Reset the flag
                    except Exception as e:
                        st.error(f"⚠️ Error overwriting file: {e}")

    with tab3:
        # ---------------------------------------------------------------------
        # STEP 3: Create or reuse the Z-shift param file (optional)
        # ---------------------------------------------------------------------
        use_zshift = st.checkbox("Use Z-motion correction? (requires a z-stack)", value=False, key="zshift_checkbox")

        if use_zshift:            
            st.write('''
            Enter the settings for z-stack used for z-motion correction (:blue-background[zstack_shift]) and set the z-motion correction method (:blue-background[subtract_z_motion])''')
            # zmcorrcol1, zmcorrcol2, zmcorrcol3 = st.columns(3)
            # with zmcorrcol2:
            with st.container(key="z-mcorr-methods"):
                st.write('''
                    **"subtract_z_motion" options** (default: :grey-background[True])   
                    - :grey-background[False]: Only z-pos will be computed.  
                    - :grey-background[True]: Non-rigid F_anat will also be computed, but not subtracted, unless a :blue-background["subtract_method"] field is present.     
                    
                    **"subtract_method" options** (default: no method - do not include the field or set it to :grey-background[None])  
                    - :grey-background[linear_regression_frames]: Subtract z-motion using linear regression on frames.
                    - :grey-background[huber_regression_pixels]: Subtract z-motion using Huber regression on pixels.
                    - :grey-background[huber_regression_frames]: Subtract z-motion using Huber regression on frames.
                    ''')
                    
            if not existing_zshift:
                st.warning("No existing z-shift param files found. Please create one first.")
            else:
                zshift_fnames = [p.name for p in existing_zshift]

                # Compute default index based on session state if available
                if "zshift_file_path" in st.session_state and st.session_state["zshift_file_path"]:
                    current_zshift_name = Path(st.session_state["zshift_file_path"]).name
                    if current_zshift_name in zshift_fnames:
                        default_z_index = zshift_fnames.index(current_zshift_name)
                    else:
                        default_z_index = zshift_fnames.index("params_zshift_template.json") if "params_zshift_template.json" in zshift_fnames else 0
                else:
                    default_z_index = zshift_fnames.index("params_zshift_template.json") if "params_zshift_template.json" in zshift_fnames else 0

                chosen_zshift_fname = st.selectbox(
                    "Select an existing Z-shift parameter file",
                    zshift_fnames,
                    index=default_z_index
                )
                
                chosen_idx = zshift_fnames.index(chosen_zshift_fname)
                chosen_fullpath = existing_zshift[chosen_idx]
                st.session_state["zshift_file_path"] = chosen_fullpath
                
                # Load the chosen file contents
                try:
                    with open(chosen_fullpath, "r") as f:
                        chosen_file_content = json.load(f)
                    default_text = json.dumps(chosen_file_content, indent=4)
                except Exception as e:
                    default_text = f"⚠️ Error reading file: {e}"
                
                zshift_text = st.text_area(
                    "Edit the parameters as needed. A new file can be saved below.",
                    value=default_text,
                    height=350
                )
                
                # Let the user specify a new filename
                zshift_filename = st.text_input(
                    "Save as new file z-shift parameter file (name must start with params_zshift):",
                    f"{chosen_fullpath.name}"
                )
                # Validate the filename
                if not zshift_filename.startswith("params_zshift"):
                    st.error("Filename must start with 'params_zshift'")
                
                if st.button("Save New Z-shift Parameter File"):
                    try:
                        new_content = json.loads(zshift_text)
                        new_path = params_dir / zshift_filename
                        # Store the new content and file path in session state so they persist
                        st.session_state.new_zshift_content = new_content
                        st.session_state.new_zshift_path = new_path
                        
                        if new_path.exists():
                            st.session_state.pending_zshift_overwrite = True
                            st.warning("File already exists. Click 'Confirm Overwrite (Z-shift)' to proceed.")
                        else:
                            st.session_state.pending_zshift_overwrite = False
                            params_dir.mkdir(parents=True, exist_ok=True)
                            with open(new_path, "w") as f:
                                json.dump(new_content, f, indent=4)
                            st.session_state["zshift_file_path"] = new_path
                            st.success(f"Saved new Z-shift param file to {new_path}")
                    except Exception as e:
                        st.error(f"⚠️ Error saving param file: {e}")

                if st.session_state.get("pending_zshift_overwrite", False):
                    if st.button("Confirm Overwrite (Z-shift)"):
                        try:
                            new_content = st.session_state.new_zshift_content
                            new_path = st.session_state.new_zshift_path
                            params_dir.mkdir(parents=True, exist_ok=True)
                            with open(new_path, "w") as f:
                                json.dump(new_content, f, indent=4)
                            st.session_state["zshift_file_path"] = new_path
                            st.success(f"Overwritten file at {new_path}")
                            st.session_state.pending_zshift_overwrite = False  # Reset the flag
                        except Exception as e:
                            st.error(f"⚠️ Error overwriting file: {e}")


        else:
            # If the user unchecks "Use Z-motion correction?" 
            # clear any previously selected zshift path
            st.session_state["zshift_file_path"] = None

    # ---------------------------------------------------------------------
    # STEP 1: Create or load the path JSON, referencing the selected files
    # ---------------------------------------------------------------------
    with tab1:
        # st.header("Path File Setup", divider=True)
        st.write('''The Path JSON file contains the paths to the data, export directory, and parameter files.  
                 Edit the fields below as needed, check the preview in the left sidebar, and save the JSON file.''')
        # Radio to pick path file mode
        # path_file_mode = st.radio(
        #     "Fill the fields below, check the preview, and save the JSON file.",
        #     ("Load Existing", "Create from Template"),
        #     index=0  # default to "Load Existing"
        # )
        

        # We'll store the loaded or template dictionary here
        # if path_file_mode == "Load Existing":
        existing_paths_files = list_existing_path_files(paths_dir)
        if not existing_paths_files:
            st.warning("No existing path files found. Please create one first.")
            path_data = DEFAULT_PATH_FILE_TEMPLATE.copy()
        else:
            path_fnames = [p.name for p in existing_paths_files]
            chosen_path_fname = st.selectbox("Select an existing path file:", path_fnames, index=path_fnames.index("paths_template.json") if "paths_template.json" in path_fnames else 0)
            
            chosen_idx = path_fnames.index(chosen_path_fname)
            chosen_fullpath = existing_paths_files[chosen_idx]
            
            # Load the chosen path file into a dict
            try:
                with open(chosen_fullpath, "r") as f:
                    loaded_paths = json.load(f)
                st.info(f"Loaded existing path file: {chosen_fullpath}")
                path_data = loaded_paths
            except Exception as e:
                st.error(f"⚠️ Error loading {chosen_fullpath}: {e}")
                path_data = DEFAULT_PATH_FILE_TEMPLATE.copy()

            # --- Automatically select parameter files if they exist locally ---
            # Check for CaImAn parameter file(s)
            if "params_files" in path_data and path_data["params_files"]:
                param_candidates = [Path(p).name for p in path_data["params_files"]]
                existing_main_params = list_existing_param_files(params_dir)["main"]
                for candidate in param_candidates:
                    for p in existing_main_params:
                        if candidate == p.name:
                            st.session_state["caiman_param_file_path"] = p
                            st.info(f"Automatically selected CaImAn parameter file: :grey-background[{p.name}]")
                            break  # Select the first match

            # Check for z-shift parameter file(s)
            if "z_params_files" in path_data and path_data["z_params_files"]:
                zparam_candidates = [Path(p).name for p in path_data["z_params_files"]]
                existing_zshift_params = list_existing_param_files(params_dir)["zshift"]
                for candidate in zparam_candidates:
                    for p in existing_zshift_params:
                        if candidate == p.name:
                            st.session_state["zshift_file_path"] = p
                            st.info(f"Automatically selected Z-shift parameter file: :grey-background[{p.name}]")
                            break  # Select the first match

        # --- Now let the user edit each field in the usual text inputs:
        subject = st.text_input("Subject Name", value=path_data.get("subject", ""))
        date_ = st.text_input("Experiment Date", value=path_data.get("date", datetime.now().strftime("%Y%m%d")))
        exp_type = st.text_input("Experiment Type (e.g. :grey-background[GC8m_16x_zoom1_765pi] - typically matches the parameter file name.)", value=path_data.get("experiment_type", ""))

        # Concatenation groups
        concat_groups_str = st.text_input(
            "Concatenation groups (comma-separated). Use this to group runs together for processing. Default: empty field.",
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
        if st.session_state.get("caiman_param_file_path"):
            if run_method == "Run on Openmind cluster":
                file_name = Path(st.session_state["caiman_param_file_path"]).name
                remote_file_path = Path(remote_params_dir) / file_name
                remote_file_path_str = str(remote_file_path).replace("\\", "/")
                path_file_dict["params_files"] = [remote_file_path_str]
            else:
                path_file_dict["params_files"] = [str(st.session_state["caiman_param_file_path"])]

        if use_zshift and st.session_state.get("zshift_file_path"):
            if run_method == "Run on Openmind cluster":
                file_name = Path(st.session_state["zshift_file_path"]).name
                remote_file_path = Path(remote_params_dir) / file_name
                remote_file_path_str = str(remote_file_path).replace("\\", "/")
                path_file_dict["z_params_files"] = [remote_file_path_str]
            else:
                path_file_dict["z_params_files"] = [str(st.session_state["zshift_file_path"])]
        
        
    # --- Display the current state of the path file
    # Preview JSON
    st.sidebar.subheader("Path File Preview") #divider=True)
    st.sidebar.write('''Filling the forms to the right will automatically update the fields below.  
                     Save or download the File path below once ready.''')
    st.sidebar.write(''':material/info: The fields :grey-background[data_paths], :grey-background[export_paths], and :grey-background[params_files] must be filled.''')
    st.sidebar.json(path_file_dict)

    # --- Suggest a default filename based on subject, date and run numbers
    runs = parse_run_numbers(path_file_dict["data_paths"])
    if runs:
        # e.g. 'run1_run2_run3'
        runs_str = "_".join(runs)
        default_filename = f"paths_{subject}_{date_}_{runs_str}.json" if (subject and date_) else "my_paths.json"
    else:
        # fallback if no runs found
        default_filename = f"paths_{subject}_{date_}_run.json" if (subject and date_) else "my_paths.json"

    path_json_name = st.sidebar.text_input("Path JSON filename:", default_filename)

    col1, col2 = st.sidebar.columns(2)

    with col1:
        if st.sidebar.button("Save Path JSON"):
            try:
                path_file_path = paths_dir / path_json_name
                paths_dir.mkdir(parents=True, exist_ok=True)
                with open(path_file_path, "w") as f:
                    json.dump(path_file_dict, f, indent=4)
                st.sidebar.success(f"Saved {path_json_name} locally to {path_file_path}")
            except Exception as e:
                st.sidebar.error(f"⚠️ Error saving path JSON: {e}")
    with col2:
        st.sidebar.download_button(
            label="Download Path JSON",
            data=json.dumps(path_file_dict, indent=4),
            file_name=path_json_name,
            mime="application/json"
        )  
          
    # ---------------------------------------------------------------------
    # STEP 4: Run the pipeline
    # ---------------------------------------------------------------------
    with tab4:
        if run_method == "Run on Openmind cluster":
            # env_path = root_dir / "ui" / ".env"
            # env_values = dotenv_values(env_path)
            # remote_host = os.getenv("SSH_LOGIN_NODE")
            # remote_code_dir = os.getenv("OM_CODE_DIR", "")
            remote_host = st.session_state.get("remote_host", os.getenv("SSH_LOGIN_NODE"))
            remote_pipeline_dir = f"{st.session_state.get('remote_code_dir', os.getenv('OM_CODE_DIR', ''))}/Mesmerize"
            remote_scripts_dir = f"{st.session_state.get('remote_code_dir', os.getenv('OM_CODE_DIR', ''))}/scripts"
            if not remote_pipeline_dir:
                st.error("Please set the remote code directory in the settings.")
                st.stop()
            else:
                # Copy or create the batch script file 
                batch_script_filename = "om_batch_mcorr_cnmf.sh"
                
                # Check if it exists remotely, and if so download it
                remote_script_path = Path(Path(remote_scripts_dir) / batch_script_filename).as_posix()
                ssh_ls_cmd = ["ssh", remote_host, f"ls {remote_script_path}"]
                try:
                    ssh_ls_proc = subprocess.run(ssh_ls_cmd, capture_output=True, text=True)
                    if ssh_ls_proc.returncode == 0:
                        # st.info("Script file already exists on cluster.")
                        # Download the script file
                        scp_script_cmd = [
                            "scp",
                            f"{remote_host}:{remote_script_path}",
                            f"{scripts_dir}/{batch_script_filename}"
                        ]
                        scp_script_proc = subprocess.run(scp_script_cmd, capture_output=True, text=True)
                        if scp_script_proc.returncode != 0:
                            st.error(f"⚠️ SCP for script file failed: {scp_script_proc.stderr}")
                        # st.info(f"Script file {batch_script_filename} copied from {Path(remote_script_path).parent} to {scripts_dir}.")
                        st.info(f":green-background[{batch_script_filename}] retrieved from cluster.")
                        
                    else:
                        # st.warning(f"Script file not found on cluster: {ssh_ls_proc.stderr}")
                        # Create the script file locally
                        with open(scripts_dir / "om_batch_mcorr_cnmf_template.sh", "r") as f:
                                script_template = f.read()
                        with open(scripts_dir / batch_script_filename, "w") as f:
                            f.write(script_template)
                        st.info(f":grey-background[{batch_script_filename}] created from template.")
                        
                except Exception as e:
                    st.error(f"Error checking for script file on cluster: {e}")
                            
                # Get the SBATCH directives from om_batch_mcorr_cnmf_template.sh
                with open(scripts_dir / "om_batch_mcorr_cnmf.sh", "r") as f:
                    sbatch_lines = [line for line in f if line.startswith("#SBATCH")]

                # Parse the SBATCH directives using regular expressions with safety checks
                if len(sbatch_lines) >= 4:
                    walltime_match = re.search(r"-t\s+(\S+)", sbatch_lines[0])
                    nodes_match    = re.search(r"-N\s+(\S+)", sbatch_lines[1])
                    cores_match    = re.search(r"-n\s+(\S+)", sbatch_lines[2])
                    mem_match      = re.search(r"--mem=(\S+)", sbatch_lines[3])
                    batch_mcorr_cnmf_walltime = walltime_match.group(1) if walltime_match else "00:00:00"
                    batch_mcorr_cnmf_nodes    = nodes_match.group(1)    if nodes_match    else "1"
                    batch_mcorr_cnmf_cores    = cores_match.group(1)    if cores_match    else "5"
                    batch_mcorr_cnmf_mem      = mem_match.group(1)      if mem_match      else "120G"
                else:
                    st.error("Not enough SBATCH directives found in the template.")
                    
                # Now create fields to edit these values
                st.write("#### Cluster Job Parameters")
                batch_mcorr_cnmf_walltime = st.text_input("Walltime (HH:MM:SS)", value=batch_mcorr_cnmf_walltime)
                batch_mcorr_cnmf_nodes    = st.text_input("Number of nodes", value=batch_mcorr_cnmf_nodes)
                batch_mcorr_cnmf_cores    = st.text_input("Number of cores", value=batch_mcorr_cnmf_cores)
                batch_mcorr_cnmf_mem      = st.text_input("Memory per node (e.g., 120G)", value=batch_mcorr_cnmf_mem)
                
            # Always create a cluster_processing.sh file if it doesn't exist 
            if not (scripts_dir / "cluster_processing.sh").exists():
                # Create the script file locally
                with open(scripts_dir / "cluster_processing_template.sh", "r") as f:
                    script_template = f.read()
                with open(scripts_dir / "cluster_processing.sh", "w") as f:
                    f.write(script_template)                    
                st.info(f":grey-background[cluster_processing.sh] created from template.")
            
            # Replace Windows-style line endings with Unix-style
            with open(scripts_dir / "cluster_processing.sh", "r") as f:
                script_template = f.read()
                script_template = script_template.replace("\r\n", "\n")
            with open(scripts_dir / "cluster_processing.sh", "w") as f:
                f.write(script_template)
                                
        # 1) Button to run locally    
        if run_method == "Run locally":
            if st.button(f"Run Pipeline Locally ({platform.node()})"):
                cmd = ["python", f"{scripts_dir}/batch_mcorr_cnmf.py", path_json_name]
                st.write(f"Running command locally: {' '.join(cmd)}")
                try:
                    completed_proc = subprocess.run(cmd, capture_output=True, text=True)
                    if completed_proc.returncode == 0:
                        st.success("Pipeline finished successfully!")
                        st.text_area("Pipeline Output", completed_proc.stdout, height=200)
                    else:
                        st.error(f"⚠️ Pipeline exited with code {completed_proc.returncode}")
                        st.text_area("Pipeline Error Output", completed_proc.stderr, height=200)
                except Exception as e:
                    st.error(f"Error running pipeline locally: {e}")
        else:
            # 2) Button to run on the cluster
            if st.button("Run Pipeline on Cluster (Openmind)"):
                # Load environment variables
                load_dotenv(dotenv_path=code_dir / "ui" / ".env")
                remote_host = os.getenv("SSH_LOGIN_NODE")
                remote_code_dir = os.getenv("OM_CODE_DIR")
                remote_pipeline_dir = f"{remote_code_dir}/Mesmerize"
                remote_paths_dir = f"{remote_pipeline_dir}/paths/openmind"
                remote_params_dir = f"{remote_pipeline_dir}/parameters"
                remote_scripts_dir = f"{remote_code_dir}/scripts"
                remote_utils_dir = f"{remote_code_dir}/scripts/utils"

                local_path_json = paths_dir / path_json_name
                if not local_path_json.exists():
                    st.error(f"Path JSON does not exist locally: {local_path_json}")
                    st.stop()

                # Step 1: Ensure Remote Directories Exist (Single SSH Call)
                try:
                    subprocess.run(
                        ["ssh", remote_host, f"mkdir -p {remote_paths_dir} {remote_params_dir} {remote_scripts_dir} {remote_utils_dir}"],
                        check=True, capture_output=True, text=True
                    )
                    st.info("✅ Remote directories verified or created.")
                except subprocess.CalledProcessError as e:
                    st.error(f"⚠️ Failed to create remote directories: {e.stderr}")
                    st.stop()

                # Step 2: Collect Files to Transfer via SCP
                files_to_copy = {
                    str(local_path_json): f"{remote_paths_dir}/{path_json_name}",
                }

                # Add parameter files if they exist
                if st.session_state.get("caiman_param_file_path"):
                    local_param = Path(st.session_state["caiman_param_file_path"])
                    if local_param.exists():
                        files_to_copy[str(local_param)] = f"{remote_params_dir}/{local_param.name}"

                if st.session_state.get("zshift_file_path"):
                    local_zparam = Path(st.session_state["zshift_file_path"])
                    if local_zparam.exists():
                        files_to_copy[str(local_zparam)] = f"{remote_params_dir}/{local_zparam.name}"

                # Add batch scripts
                batch_script_path = scripts_dir / batch_script_filename
                convert_to_unix(batch_script_path)  # Ensure Unix line endings
                files_to_copy[str(batch_script_path)] = f"{remote_scripts_dir}/{batch_script_filename}"

                if copy_files:
                    cluster_processing_path = scripts_dir / "cluster_processing.sh"
                    convert_to_unix(cluster_processing_path)
                    files_to_copy[str(cluster_processing_path)] = f"{remote_scripts_dir}/cluster_processing.sh"

                # **Execute SCP Transfers in Batches**
                try:
                    for local_file, remote_path in files_to_copy.items():
                        scp_command = ["scp", local_file, f"{remote_host}:{remote_path}"]
                        subprocess.run(scp_command, check=True, capture_output=True, text=True)
                        st.success(f"✅ Successfully copied {Path(local_file).name} to {remote_host}:{remote_path}")
                except subprocess.CalledProcessError as e:
                    st.error(f"⚠️ SCP failed: {e.stderr}")
                    st.stop()

                # Step 3: Copy all missing utils/ scripts
                local_utils_dir = scripts_dir / "utils"
                try:
                    local_utils_files = [str(f) for f in local_utils_dir.glob("*") if f.is_file() and f.name != ".env"]
                    if local_utils_files:
                        scp_utils_cmd = ["scp"] + local_utils_files + [f"{remote_host}:{remote_utils_dir}/"]
                        subprocess.run(scp_utils_cmd, check=True, capture_output=True, text=True)
                        st.success(f"✅ Copied {len(local_utils_files)} utils scripts to cluster.")
                    else:
                        st.info("No missing utils scripts found.")
                except subprocess.CalledProcessError as e:
                    st.error(f"⚠️ SCP for utils scripts failed: {e.stderr}")
                    st.stop()

                # Step 4: Submit Cluster Job
                script_filename = "cluster_processing.sh" if copy_files else "om_batch_mcorr_cnmf.sh"
                cluster_cmd = f"cd {remote_scripts_dir} && sbatch {script_filename} {remote_paths_dir}/{path_json_name}"

                try:
                    ssh_proc = subprocess.run(["ssh", remote_host, cluster_cmd], capture_output=True, text=True)
                    if ssh_proc.returncode == 0:
                        st.success("✅ Submitted job to cluster via sbatch!")
                        job_id_match = re.search(r"Submitted batch job (\d+)", ssh_proc.stdout)
                        if job_id_match:
                            st.session_state["last_job_id"] = job_id_match.group(1)
                        st.text_area("Cluster Output", ssh_proc.stdout, height=200)
                    else:
                        st.error(f"⚠️ Cluster sbatch command failed: {ssh_proc.stderr}")
                        st.session_state["last_job_id"] = None
                except Exception as e:
                    st.error(f"⚠️ Error running sbatch on cluster: {e}")


        # Check if a job ID was submitted
        if "last_job_id" in st.session_state:
            job_id = st.session_state["last_job_id"]
            st.info(f"Latest submitted job ID: {job_id}")

            col1, col2 = st.columns(2)

            with col1:
                # Kill job button
                if st.button("Kill Job", key="kill_job_button", help="Cancel the last submitted job"):
                    remote_host = st.session_state.get("remote_host", os.getenv("SSH_LOGIN_NODE"))
                    cancel_cmd = f"ssh {remote_host} scancel {job_id}"
                    cancel_proc = subprocess.run(cancel_cmd, shell=True, capture_output=True, text=True)

                    if cancel_proc.returncode == 0:
                        st.success(f"Job {job_id} successfully canceled.")
                        del st.session_state["last_job_id"]
                    else:
                        st.error(f"Failed to cancel job {job_id}: {cancel_proc.stderr}")

            with col2:
                # Determine which script was used
                script_type = st.session_state.get("last_script", "cluster_processing.sh")  # Default to cluster_processing.sh
                log_filename = f"cluster_processing-{job_id}.ans" if "cluster_processing" in script_type else f"batch_mcorr_cnmf-{job_id}.ans"
                remote_log_path = f"{st.session_state.get('remote_code_dir')}/scripts/slurm_logs/{log_filename}"

                # Download log button
                if st.button("Show Logs", key="show_logs_button", help="Fetch job log file from cluster"):
                    remote_host = st.session_state.get("remote_host", os.getenv("SSH_LOGIN_NODE"))

                    scp_cmd = f"ssh {remote_host} cat {remote_log_path}"
                    scp_proc = subprocess.run(scp_cmd, shell=True, capture_output=True, text=True)

                    if scp_proc.returncode == 0:
                        log_content = scp_proc.stdout  # Read log content directly from SSH

                        st.success(f"Log file {log_filename} retrieved successfully.")
                        st.text_area("Log File Contents", log_content, height=300)

                        st.download_button(
                            label="Download Log File",
                            data=log_content,
                            file_name=log_filename,
                            mime="text/plain"
                        )
                    else:
                        st.error(f"Failed to retrieve log file {log_filename}: {scp_proc.stderr}")


    # ---------------------------------------------------------------------
    "---"
    endcol1, endcol2 = st.columns([3, 1])
    if endcol2.button("Stop and Exit", icon=":material/logout:"):
        endcol2.write("Shutting down the app...")

        # Immediately kill our own process
        os.kill(os.getpid(), signal.SIGTERM)
        
    
if __name__ == "__main__":
    main()
