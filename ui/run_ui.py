import sys
import os
from pathlib import Path

# Import the private CLI API (works in Streamlit 1.x to 1.40+)
import streamlit.web.cli as stcli

def main():
    # Figure out where `ui_app.py` is located when bundled
    if getattr(sys, 'frozen', False):
        # Running inside PyInstaller bundle
        bundle_dir = Path(sys._MEIPASS)
    else:
        # Running in normal Python
        bundle_dir = Path(__file__).parent

    # If you placed ui_app.py in the same folder, refer to it here.
    ui_app_path = bundle_dir / "ui_app.py"

    # Fake the command-line call "streamlit run ui_app.py"
    sys.argv = ["streamlit", "run", str(ui_app_path)]
    stcli._main_run_clExplicit()

if __name__ == "__main__":
    main()
