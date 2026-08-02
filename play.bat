@echo off
rem One-click Putt Quest launcher.
rem Opens two windows: the ball tracker (camera) and the game.
rem Both scripts share the project virtual environment (.venv) and will
rem auto-install any missing dependencies the first time they run.

setlocal
cd /d "%~dp0"

echo Starting ball tracker (camera window)...
start "Putt Quest - Ball Tracker" cmd /k "%~dp0run_ball_tracking.bat"

rem Give the tracker a head start so the camera is open by the time the
rem game asks for its first status ping. Tune if your camera is slow.
timeout /t 4 /nobreak >nul

echo Starting Putt Quest game...
start "Putt Quest - Game" cmd /k "%~dp0run_putt_quest.bat"

echo.
echo Both windows launched. Close them with Q (or the window X) when done.
echo This launcher window can be closed at any time.
endlocal
