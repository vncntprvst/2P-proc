@echo off
REM --- Configuration ---
SET CONDA_ENV_NAME=analysis2p_ui
SET LOGFILE=install_log.txt

REM Redirect all output to the log file
(
    REM --- Check if the conda environment exists ---
    REM This uses "conda env list" and findstr to search for the environment name.
    conda env list | findstr /I "%CONDA_ENV_NAME%" >nul
    if errorlevel 1 (
        echo Environment %CONDA_ENV_NAME% not found.
        echo Please choose an option:
        echo 1. Install conda environment
        echo 2. Download and extract the portable environment
        echo 3. Exit
    ) else (
        echo Environment %CONDA_ENV_NAME% found.
        echo Activating the environment...
        call conda activate %CONDA_ENV_NAME%
        echo Running the app...
        REM Launch the Streamlit application
        streamlit run ui_app.py
        REM Keep the window open so you can review any messages
        pause
        exit /b 0
    )
) > %LOGFILE% 2>&1

REM Capture user input outside the redirection block
set /p choice="Enter your choice (1, 2, or 3): "

REM Log the user input
echo User selected option: %choice% >> %LOGFILE%

REM Process the user input
if "%choice%"=="1" (
    echo Installing conda environment... >> %LOGFILE%
    conda create -n %CONDA_ENV_NAME% python=3.9 -y >> %LOGFILE% 2>&1
    call conda activate %CONDA_ENV_NAME% >> %LOGFILE% 2>&1
    pip install streamlit python-dotenv >> %LOGFILE% 2>&1
    REM Re-run the script after installation
    call "%~f0" >> %LOGFILE% 2>&1
    exit /b 0
) else if "%choice%"=="2" (
    echo Downloading and extracting the portable environment... >> %LOGFILE%
    
    REM Create target directory if it doesn't exist
    if not exist "portable_env" (
        mkdir "portable_env" >> %LOGFILE% 2>&1
    )
    
    SET ARCHIVE_FILE=analysis2p_ui.tar.gz
    SET GITHUB_RELEASE_URL=https://github.com/pseudomanu/Analysis_2P/releases/download/0.3.5/%ARCHIVE_FILE%
    
    REM Download the portable environment archive (Windows 10 includes curl)
    curl -L -o %ARCHIVE_FILE% %GITHUB_RELEASE_URL% >> %LOGFILE% 2>&1
    
    echo Extracting the portable environment... >> %LOGFILE%
    REM Windows 10 includes tar; adjust options if needed
    tar -xzf %ARCHIVE_FILE% -C portable_env >> %LOGFILE% 2>&1
    
    REM After extraction, the environment folder is inside portable_env
    SET ENV_DIR=portable_env\%CONDA_ENV_NAME%
    
    echo Fixing paths inside the extracted environment... >> %LOGFILE%
    REM Assumes a conda-unpack script exists in the Scripts folder.
    call "%ENV_DIR%\Scripts\conda-unpack.bat" >> %LOGFILE% 2>&1
    
    echo Activating the portable environment... >> %LOGFILE%
    REM Use the activate script from the portable environment.
    call "%ENV_DIR%\Scripts\activate.bat" %CONDA_ENV_NAME% >> %LOGFILE% 2>&1
) else (
    echo Exiting... >> %LOGFILE%
    exit /b 0
)