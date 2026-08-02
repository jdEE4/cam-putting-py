@echo off
setlocal
cd /d "%~dp0"
set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"
set "PYTHON_BIN=%VENV_DIR%\Scripts\python.exe"

echo ============================================
echo   Building the one-click Putt Quest .exe
echo ============================================

if not exist "%PYTHON_BIN%" call :make_venv
if not exist "%PYTHON_BIN%" (
    echo Error: could not create the virtual environment.
    echo Install Python 3.13 from python.org and run this again.
    exit /b 1
)

echo Installing build + runtime dependencies ...
"%PYTHON_BIN%" -m pip install --upgrade pip
"%PYTHON_BIN%" -m pip install -r "%ROOT_DIR%requirements.txt"
"%PYTHON_BIN%" -m pip install -r "%ROOT_DIR%requirements-game.txt"
rem NOTE: the version spec MUST be quoted - unquoted, cmd reads the ">" in
rem "pyinstaller>=6.0" as a redirect and silently writes a file named "6.0"
"%PYTHON_BIN%" -m pip install -r "%ROOT_DIR%requirements-build.txt"

echo Cleaning previous build ...
if exist "%ROOT_DIR%build\PuttQuest" rmdir /s /q "%ROOT_DIR%build\PuttQuest"
if exist "%ROOT_DIR%dist\PuttQuest.exe" del /q "%ROOT_DIR%dist\PuttQuest.exe"

echo Running PyInstaller (this takes a few minutes) ...
"%PYTHON_BIN%" -m PyInstaller "%ROOT_DIR%PuttQuest.spec" --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED - see the PyInstaller output above.
    exit /b 1
)

if not exist "%ROOT_DIR%dist\PuttQuest.exe" (
    echo.
    echo BUILD FAILED - dist\PuttQuest.exe was not produced.
    exit /b 1
)

echo.
echo ============================================
echo   Done:  dist\PuttQuest.exe
echo   Share that single file - no Python needed.
echo ============================================
echo.
echo First launch unpacks the bundle and can take 10-30 seconds.
echo Leave the console window open - the tracker prints ball speed there.
echo.
choice /C YN /M "Launch it now"
if errorlevel 2 goto :eof
start "" "%ROOT_DIR%dist\PuttQuest.exe"
exit /b 0

:make_venv
echo Creating virtual environment in "%VENV_DIR%" ...
where py >nul 2>nul || goto make_venv_plain
py -3.13 -c "exit()" >nul 2>nul && py -3.13 -m venv "%VENV_DIR%" && goto :eof
py -3.12 -c "exit()" >nul 2>nul && py -3.12 -m venv "%VENV_DIR%" && goto :eof
py -3.11 -c "exit()" >nul 2>nul && py -3.11 -m venv "%VENV_DIR%" && goto :eof
py -3 -m venv "%VENV_DIR%"
goto :eof
:make_venv_plain
python -m venv "%VENV_DIR%"
goto :eof
