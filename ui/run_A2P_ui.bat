@echo off
SET CONDA_ENV_NAME=analysis2p_ui
SET LOGFILE=install_log.txt

REM --- Check if the conda environment exists first, without logging ---
conda env list | findstr /I "%CONDA_ENV_NAME%" >nul
if not errorlevel 1 (
    REM Environment exists; delete any previous log and run the app without logging.
    if exist %LOGFILE% del %LOGFILE%
    echo Environment %CONDA_ENV_NAME% found.
    REM Check if port 8501 is in use on localhost (127.0.0.1)
    netstat -ano | findstr "127.0.0.1:8501" >nul
    if not errorlevel 1 (
        echo Port 8501 on localhost is in use.
        REM Iterate through each line that matches exactly the local address
        for /f "tokens=5" %%a in ('netstat -aon ^| findstr "127.0.0.1:8501"') do (
            if not "%%a"=="0" (
                echo Killing process with PID %%a
                taskkill /PID %%a /F
            ) else (
                echo Skipping critical system process with PID 0.
            )
        )
    )      
    call conda activate %CONDA_ENV_NAME%
    echo Running the app...
    streamlit run ui_app.py
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
