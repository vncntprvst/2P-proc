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
SSH_TRANSFER_NODE=your_transfer_node
SSH_LOGIN_NODE=your_login_node
```
The `SSH_TRANSFER_NODE` and `SSH_LOGIN_NODE` are the `.ssh/config` aliases for the nodes you use to transfer data and login to the cluster, respectively. It can be the same node.

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