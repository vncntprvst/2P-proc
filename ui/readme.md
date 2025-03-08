User Interface
==============

### Installation
```bash
pip install streamlit python-dotenv
```
If you want to create a dedicated environment for the UI, you can use the following command:
```bash
conda create -n analysis2p_ui python=3.9
```
If running the pipeline on the cluster, make sure you have the `.env` file in the `/scripts/utils` directory, with the following content:
```
SSH_LOGIN_NODE=your_login_node
OM_USER_DIR_ALIAS=your_user_dir_alias
```
The `SSH_LOGIN_NODE` is the `.ssh/config` alias for the node you use to the cluster. 
The `OM_USER_DIR_ALIAS` is the alias for the user directory on the cluster.

### Run the UI
Use one of the following methods to run the UI: 
* Run the Python script:
```bash
cd ui
streamlit run ui_app.py
```
* Run the Batch/Script File:
Adjdust the name of the environment in `run_ui.bat` as needed, then: 
```bash
cd ui
run_ui.bat
```
* Build an executable script:  
```bash
pip install pyinstaller
cd ui
pyinstaller --onefile run_ui.py --collect-all streamlit
```