@echo off
setlocal
cd /d "%~dp0"
set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"
set "PYTHON_BIN=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_BIN%" (
    echo Creating virtual environment in "%VENV_DIR%" ...
    where py >nul 2>nul && py -3 -m venv "%VENV_DIR%" || python -m venv "%VENV_DIR%"
)
if not exist "%PYTHON_BIN%" (
    echo Error: could not create the virtual environment. Install Python 3 from python.org first.
    exit /b 1
)

"%PYTHON_BIN%" -c "import cv2, cvzone, imutils, requests" >nul 2>nul || (
    echo Installing ball tracking dependencies from requirements.txt ...
    "%PYTHON_BIN%" -m pip install --upgrade pip
    "%PYTHON_BIN%" -m pip install -r "%ROOT_DIR%requirements.txt"
)

"%PYTHON_BIN%" "%ROOT_DIR%ball_tracking_setup.py" %*
