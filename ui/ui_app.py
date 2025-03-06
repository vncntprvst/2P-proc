import streamlit as st
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime 

root_dir = Path(__file__).resolve().parents[1]
params_dir = root_dir / "Mesmerize" / "parameters"
paths_dir = root_dir / "Mesmerize" / "paths"

# ------------------------------------------------------------------------------
# Load default templates 
# ------------------------------------------------------------------------------

with open(params_dir / "params_mcorr_cnmf_template.json", "r") as f:
    DEFAULT_MAIN_PARAM_TEMPLATE = json.load(f)
with open(params_dir / "params_zshift_template.json", "r") as f:
    DEFAULT_ZSHIFT_PARAM_TEMPLATE = json.load(f)
with open(paths_dir / "paths_template.json", "r") as f:
    DEFAULT_PATH_FILE_TEMPLATE = json.load(f)

# ------------------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------------------
def list_existing_param_files(param_dir: Path) -> list:
    """Return a list of existing JSON param files in param_dir."""
    if not param_dir.exists():
        return []
    return [str(p) for p in param_dir.glob("*.json")]

# -------------------------------------------------------------------------
# Main Streamlit App
# -------------------------------------------------------------------------
def main():
    st.title("Analysis_2P Pipeline Setup")
    st.write("This app guides you through setting up your JSON files and running the pipeline.")
    st.write("Set up your parameters file(s) one the left, then fill or edit the fields below and run the pipeline.")
    
    # List existing param files
    existing_param_files = list_existing_param_files(params_dir)
    
    # STEP 1: Create or re-use the main param file
    st.sidebar.header("Main Parameter File")
    param_mode = st.sidebar.radio(
        "Choose how to handle the main param file:",
        ("Create from Template", "Reuse Existing")
    )
    
    main_param_content = {}
    main_param_file_path = None
    
    if param_mode == "Create from Template":
        st.sidebar.write("You will be able to edit the JSON keys below if desired.")
        # Convert default template to a modifiable string
        main_param_text = st.sidebar.text_area(
            "Edit main param JSON if you wish:",
            value=json.dumps(DEFAULT_MAIN_PARAM_TEMPLATE, indent=4),
            height=300
        )
        
        # Let user specify the filename they want to save as
        main_param_filename = st.sidebar.text_input(
            "Main param filename (e.g. 'params_GC8m_25x_zoom1_610pi.json'):",
            "params_GC8m_25x_zoom1_610pi.json"
        )
        
        if st.sidebar.button("Save Main Param File"):
            try:
                main_param_content = json.loads(main_param_text)
                main_param_file_path = params_dir / main_param_filename
                params_dir.mkdir(parents=True, exist_ok=True)
                
                # Save to disk
                with open(main_param_file_path, "w") as f:
                    json.dump(main_param_content, f, indent=4)
                st.sidebar.success(f"Main param file saved to {main_param_file_path}")
            except Exception as e:
                st.sidebar.error(f"Error saving param file: {e}")
    
    else:  # Reuse existing
        if not existing_param_files:
            st.sidebar.warning("No existing param files found. Please create one first.")
        else:
            main_param_file_path = st.sidebar.selectbox(
                "Select an existing main param file:",
                existing_param_files
            )
            st.sidebar.write(f"Chosen: {main_param_file_path}")
            
    # STEP 2: Create or re-use Z-shift param file
    st.sidebar.header("(Optional) Z-motion Parameter File")
    use_zshift = st.sidebar.checkbox("Use Z-motion correction?", value=False)
    
    zshift_file_path = None
    if use_zshift:
        zshift_mode = st.sidebar.radio(
            "Choose how to handle the Z-shift param file:",
            ("Create from Template", "Reuse Existing")
        )
        if zshift_mode == "Create from Template":
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
                    zshift_file_path = params_dir / zshift_filename
                    params_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Save
                    with open(zshift_file_path, "w") as f:
                        json.dump(zshift_content, f, indent=4)
                    st.sidebar.success(f"Z-shift param file saved to {zshift_file_path}")
                except Exception as e:
                    st.sidebar.error(f"Error saving z-shift param file: {e}")
                    
        else:  # reuse
            # Filter existing param files by some naming convention if you like...
            # For simplicity, we re-use the same existing_param_files
            # Potentially could parse them for known keys, but this is simpler
            zshift_file_path = st.sidebar.selectbox(
                "Select an existing Z-shift param file:",
                existing_param_files
            )
            st.sidebar.write(f"Chosen: {zshift_file_path}")
    
    # STEP 3: Create path file with references to the above param files
    
    # Let user modify some fields from the template
    subject = st.text_input("Subject", value=DEFAULT_PATH_FILE_TEMPLATE["subject"])
    date_ = st.text_input("Date", value=datetime.now().strftime("%Y-%m-%d"))
    exp_type = st.text_input("Experiment type", value=DEFAULT_PATH_FILE_TEMPLATE["experiment_type"])
    
    concat_groups_str = st.text_input("Concatenation groups (comma-separated)", "1,2,3")
    if concat_groups_str.strip():
        try:
            concat_groups = [int(x.strip()) for x in concat_groups_str.split(",")]
        except:
            concat_groups = DEFAULT_PATH_FILE_TEMPLATE["concatenation_groups"]
    else:
        concat_groups = []
    
    data_paths_input = st.text_area(
        "Data paths (one per line)",
        value="\n".join(DEFAULT_PATH_FILE_TEMPLATE["data_paths"])
    )
    data_paths = [line.strip() for line in data_paths_input.split("\n") if line.strip()]
    
    export_paths_input = st.text_area(
        "Export paths (one per line)",
        value="\n".join(DEFAULT_PATH_FILE_TEMPLATE["export_paths"])
    )
    export_paths = [line.strip() for line in export_paths_input.split("\n") if line.strip()]
    
    zstack_paths_input = st.text_area(
        "Z-stack paths (one per line)",
        value="" if not use_zshift else "\n".join(DEFAULT_PATH_FILE_TEMPLATE["zstack_paths"])
    )
    zstack_paths = [line.strip() for line in zstack_paths_input.split("\n") if line.strip()]
    
    log_path = st.text_input(
        "Log path",
        value=DEFAULT_PATH_FILE_TEMPLATE["logging"]["log_path"]
    )
    log_level = st.selectbox(
        "Log level",
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        index=1  # default INFO
    )
    
    # Now build the final dictionary
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
    
    # If we have a main_param_file_path, let's insert it
    if main_param_file_path:
        path_file_dict["params_files"] = [str(main_param_file_path)]
    
    # If we have a zshift_file_path, let's insert it
    if use_zshift and zshift_file_path:
        path_file_dict["z_params_files"] = [str(zshift_file_path)]
    
    # Let user do final modifications
    st.subheader("Path JSON Preview")
    st.json(path_file_dict)
    
    # Provide a file name input & a "Download" button
    path_json_name = st.text_input("Path JSON filename:", "my_paths.json")
    if st.button("Download Path JSON"):
        data_to_download = json.dumps(path_file_dict, indent=4)
        st.download_button(
            "Download File",
            data_to_download,
            file_name=path_json_name,
            mime="application/json"
        )
    
    # Alternatively, let user save it to disk (if running locally)
    if st.button("Save Path JSON Locally"):
        try:
            path_file_path = paths_dir / path_json_name
            with open(path_file_path, "w") as f:
                json.dump(path_file_dict, f, indent=4)
            st.success(f"Saved {path_json_name} locally to {path_file_path}")
        except Exception as e:
            st.error(f"Error saving path JSON: {e}")
    
    # STEP 4: Trigger the Pipeline
    st.subheader("Run the Pipeline (Optional)")
    st.write("This will call `batch_mcorr_cnmf.py <path_file>` in your current environment.")
    if st.button("Run Pipeline Now"):
        cmd = ["python", "batch_mcorr_cnmf.py", path_json_name]
        st.write(f"Running command: {' '.join(cmd)}")
        try:
            # Execute the subprocess
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
