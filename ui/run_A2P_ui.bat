@echo off
setlocal enabledelayedexpansion
SET CONDA_ENV_NAME=analysis2p_ui
SET LOGFILE=a2p_ui_log.txt

REM --- Check if the conda environment exists first, without logging ---
conda env list | findstr /I "%CONDA_ENV_NAME%" >nul
if not errorlevel 1 (
    if exist %LOGFILE% del %LOGFILE%
    echo Environment %CONDA_ENV_NAME% found.

    @REM echo Finding a free port... >> %LOGFILE%

    REM Start looking for a free port at 8502
    set PORT=8502

    :CHECK_PORT
    netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul
    if not errorlevel 1 (
        set /a PORT+=1
        goto CHECK_PORT
    )

    @REM echo Using port !PORT! for Streamlit. >> %LOGFILE%

    call conda activate %CONDA_ENV_NAME%
    echo Running the app on port !PORT!...
    streamlit run ui_app.py --server.port !PORT!

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
    pip install streamlit python-dotenv ansi2html >> %LOGFILE% 2>&1
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
