@echo off
REM --- Configuration ---
SET CONDA_ENV_NAME=analysis2p_ui

REM --- Check if the conda environment exists ---
REM This uses "conda env list" and findstr to search for the environment name.
conda env list | findstr /I "%CONDA_ENV_NAME%" >nul
if errorlevel 1 (
    echo Environment %CONDA_ENV_NAME% not found.
    echo Downloading and extracting the portable environment...
    
    REM Create target directory if it doesn't exist
    if not exist "portable_env" (
        mkdir "portable_env"
    )
    
    SET ARCHIVE_FILE=analysis2p_ui.tar.gz
    SET GITHUB_RELEASE_URL=https://github.com/pseudomanu/Analysis_2P/releases/download/0.3.5/%ARCHIVE_FILE%
    
    REM Download the portable environment archive (Windows 10 includes curl)
    curl -L -o %ARCHIVE_FILE% %GITHUB_RELEASE_URL%
    
    echo Extracting the portable environment...
    REM Windows 10 includes tar; adjust options if needed
    tar -xzf %ARCHIVE_FILE% -C portable_env
    
    REM After extraction, the environment folder is inside portable_env
    SET ENV_DIR=portable_env\%CONDA_ENV_NAME%
    
    echo Fixing paths inside the extracted environment...
    REM Assumes a conda-unpack script exists in the Scripts folder.
    call "%ENV_DIR%\Scripts\conda-unpack.bat"
    
    echo Activating the portable environment...
    REM Use the activate script from the portable environment.
    call "%ENV_DIR%\Scripts\activate.bat" %CONDA_ENV_NAME%
) else (
    echo Environment %CONDA_ENV_NAME% found.
    echo Activating the environment...
    call conda activate %CONDA_ENV_NAME%
)

echo Running the app...
REM Launch the Streamlit application
streamlit run ui_app.py

REM Keep the window open so you can review any messages
pause
