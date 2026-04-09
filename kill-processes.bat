@echo off
echo ============================================
echo   Killing Python, Electron, UV, Uvicorn Processes
echo ============================================
echo.

echo [1/4] Killing Python processes...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM pythonw.exe 2>nul
if %errorlevel% == 0 (
    echo       Python processes killed.
) else (
    echo       No Python processes found or already terminated.
)

echo.
echo [2/4] Killing Electron processes...
taskkill /F /IM electron.exe 2>nul
if %errorlevel% == 0 (
    echo       Electron processes killed.
) else (
    echo       No Electron processes found or already terminated.
)

echo.
echo [3/4] Killing UV processes...
taskkill /F /IM uv.exe 2>nul
if %errorlevel% == 0 (
    echo       UV processes killed.
) else (
    echo       No UV processes found or already terminated.
)

echo.
echo [4/4] Killing Uvicorn processes (via Python)...
REM Uvicorn runs as a Python process, so we check for any python processes running uvicorn
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%uvicorn%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%i 2>nul
    echo       Killed uvicorn process PID: %%i
)

echo.
echo ============================================
echo   All target processes have been terminated
echo ============================================
pause
