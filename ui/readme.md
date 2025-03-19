User Interface
==============
### Quickstart
Navigate to the `ui` folder and double-click the file `run_A2P_ui.bat` (windows) or `run_A2P_ui.sh` (Linux - MacOS. Make sure the file is executable with `chmod +x run_A2P_ui.sh`).  
 
The terminal window will open and the UI will be launched in your default browser. If the app's environment is not installed, the script will prompt you to select the method, and install it.   

Create a shortcut to the file for easy access (e.g. on the desktop).

### Manual installation
```bash
pip install streamlit python-dotenv ansi2html
```
If you want to create a dedicated environment for the UI, you can use the following command:
```bash
conda create -n analysis2p_ui python=3.9
```

If running the pipeline on the cluster, make sure you have the `.env` file in the `<remote_code_directory>/scripts/utils` folder. See instructions in the main README.md file.

### Adding an icon
If you want to add an icon to the UI's shortcut, you can use the existing files (`icon/a2p_icon.ico` or `icon/a2p_icon.png`) or create your own.   
To generate an icon, create a square `png` image, install [ImageMagick](https://imagemagick.org/script/download.php), and use the following command: 
```bash
magick a2p_icon.png -define icon:auto-resize=256,48,32,16 a2p_icon.ico
```
Then, right-click the shortcut, select "Properties", and click the "Change Icon" button. Browse to the location of the icon file and select it.

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