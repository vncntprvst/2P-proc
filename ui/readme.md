User Interface
==============
### Quickstart
Navigate to the `ui` folder and double-click the file `run_A2P_ui.bat` (windows) or `run_A2P_ui.sh` (Linux - MacOS. Make sure the file is executable with `chmod +x run_A2P_ui.sh`).  
 
The terminal window will open and the UI will be launched in your default browser. If the app's environment is not installed, the script will prompt you to select the method, and install it.   

### Manual installation
```bash
pip install streamlit python-dotenv ansi2html
```
If you want to create a dedicated environment for the UI, you can use the following command:
```bash
conda create -n analysis2p_ui python=3.9
```

If running the pipeline on the cluster, make sure you have the `.env` file in the `<remote_code_directory>/scripts/utils` folder. See instructions in the main README.md file.

### Other ways to run the UI
Use one of the following methods to run the UI: 
* Run the Python script:
```bash
cd ui
conda activate analysis2p_ui
streamlit run ui_app.py
```
* Run the Batch/Script File:
Adjdust the name of the environment in `ui\run_A2P_ui.bat` as needed, then: 
```bash
cd ui
run_A2P_ui.bat
```
* Build an executable script:  
```bash
pip install pyinstaller
cd ui
pyinstaller --onefile run_ui.py --collect-all streamlit
```