@echo off
setlocal
cd /d "%~dp0"
set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"
set "PYTHON_BIN=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_BIN%" call :make_venv
if not exist "%PYTHON_BIN%" (
    echo Error: could not create the virtual environment.
    echo Install Python 3.13 from python.org and run this launcher again.
    exit /b 1
)

"%PYTHON_BIN%" -c "import cv2, cvzone, imutils, requests" >nul 2>nul || (
    echo Installing ball tracking dependencies from requirements.txt ...
    "%PYTHON_BIN%" -m pip install --upgrade pip
    "%PYTHON_BIN%" -m pip install -r "%ROOT_DIR%requirements.txt"
)

"%PYTHON_BIN%" "%ROOT_DIR%ball_tracking_setup.py" %*
exit /b %errorlevel%

:make_venv
echo Creating virtual environment in "%VENV_DIR%" ...
where py >nul 2>nul || goto make_venv_plain
rem Prefer a Python with prebuilt pygame/opencv wheels - the newest release
rem (e.g. 3.14) often has none yet and pip then fails building from source
py -3.13 -c "exit()" >nul 2>nul && py -3.13 -m venv "%VENV_DIR%" && goto :eof
py -3.12 -c "exit()" >nul 2>nul && py -3.12 -m venv "%VENV_DIR%" && goto :eof
py -3.11 -c "exit()" >nul 2>nul && py -3.11 -m venv "%VENV_DIR%" && goto :eof
py -3 -m venv "%VENV_DIR%"
goto :eof
:make_venv_plain
python -m venv "%VENV_DIR%"
goto :eof
