@echo off
setlocal enabledelayedexpansion
SET CONDA_ENV_NAME=analysis2p_ui
SET LOGFILE=install_log.txt

REM --- Check if the conda environment exists first, without logging ---
conda env list | findstr /I "%CONDA_ENV_NAME%" >nul
if not errorlevel 1 (
    REM Environment exists; delete any previous log and run the app without logging.
    if exist %LOGFILE% del %LOGFILE%
    echo Environment %CONDA_ENV_NAME% found.

    echo Checking if port 8502 is in use... >> %LOGFILE%

    for /f "tokens=5" %%a in ('netstat -aon ^| findstr "127.0.0.1:8502" ^| findstr "LISTENING"') do (
        set "PID=%%a"
        echo Port 8502 is in use by PID !PID!. Checking process details... >> %LOGFILE%

        if not "!PID!"=="0" (
            REM Retrieve process details using WMIC
            set "commandline="
            set "processname="
            
            for /f "tokens=2 delims=," %%b in ('wmic process where "ProcessId=!PID!" get CommandLine /format:csv 2^>nul') do (
                set "commandline=%%b"
            )

            for /f "tokens=1 delims=," %%c in ('wmic process where "ProcessId=!PID!" get Caption /format:csv 2^>nul') do (
                set "processname=%%c"
            )

            REM Log process details
            echo Process Name: !processname! Command Line: !commandline! >> %LOGFILE%

            REM If "streamlit" or "python" appears in the process, terminate it
            if defined commandline (
                echo Checking for Streamlit/Python process... >> %LOGFILE%
                echo !commandline! | findstr /I "streamlit python.exe" >nul
                if not errorlevel 1 (
                    echo Streamlit or Python process detected. Killing PID !PID! >> %LOGFILE%
                    taskkill /PID !PID! /F >> %LOGFILE% 2>&1
                    timeout /t 3 /nobreak >nul
                ) else (
                    echo PID !PID! does not seem to be Streamlit. Skipping termination. >> %LOGFILE%
                )
            ) else (
                echo Could not retrieve command line details for PID !PID!. Skipping... >> %LOGFILE%
            )
        ) else (
            echo No process found on port 8502. >> %LOGFILE%
        )
    )

    call conda activate %CONDA_ENV_NAME%
    echo Running the app on port 8502... 
    @REM streamlit run ui_app.py
    streamlit run ui_app.py --server.port 8502

    echo Press any key to exit.
    pause
    exit /b 0
)

REM --- Environment not found: log the output and prompt the user ---
echo Checking environment... > %LOGFILE%
echo Environment %CONDA_ENV_NAME% not found. >> %LOGFILE%
echo Environment %CONDA_ENV_NAME% not found.
echo Please choose an option:
echo 1. Install conda environment
echo 2. Download and extract the portable environment
echo 3. Exit
set /p choice="Enter your choice (1, 2, or 3): "
echo User selected option: %choice% >> %LOGFILE%

if "%choice%"=="1" (
    echo Installing conda environment... >> %LOGFILE%
    conda create -n %CONDA_ENV_NAME% python=3.9 -y >> %LOGFILE% 2>&1
    call conda activate %CONDA_ENV_NAME% >> %LOGFILE% 2>&1
    pip install streamlit python-dotenv >> %LOGFILE% 2>&1
    echo Installation complete. Restarting script... >> %LOGFILE%
    pause
    call "%~f0"
    exit /b 0
) else if "%choice%"=="2" (
    echo Downloading and extracting the portable environment... >> %LOGFILE%
    
    REM Create target directory if it doesn't exist
    if not exist "portable_env" (
        mkdir "portable_env" >> %LOGFILE% 2>&1
    )
    
    SET ARCHIVE_FILE=analysis2p_ui.tar.gz
    SET GITHUB_RELEASE_URL=https://github.com/pseudomanu/Analysis_2P/releases/download/0.3.5/%ARCHIVE_FILE%
    
    curl -L -o %ARCHIVE_FILE% %GITHUB_RELEASE_URL% >> %LOGFILE% 2>&1
    echo Extracting the portable environment... >> %LOGFILE%
    tar -xzf %ARCHIVE_FILE% -C portable_env >> %LOGFILE% 2>&1
    
    SET ENV_DIR=portable_env\%CONDA_ENV_NAME%
    
    echo Fixing paths inside the extracted environment... >> %LOGFILE%
    call "%ENV_DIR%\Scripts\conda-unpack.bat" >> %LOGFILE% 2>&1
    echo Activating the portable environment... >> %LOGFILE%
    call "%ENV_DIR%\Scripts\activate.bat" %CONDA_ENV_NAME% >> %LOGFILE% 2>&1
) else (
    echo Exiting... >> %LOGFILE%
    pause
    exit /b 0
)
