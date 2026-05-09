@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found on PATH. Install Python 3.10+ and retry.
  exit /b 1
)

python -m pip install ".[exe]"
if errorlevel 1 exit /b 1

python -m PyInstaller packaging\uav_simplify_mission.spec --clean --noconfirm
if errorlevel 1 exit /b 1

echo.
echo Built: %cd%\dist\uav-simplify-mission.exe
endlocal
