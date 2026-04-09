@echo off
taskkill /F /IM python.exe 2>nul
echo Killing Electron processes...
taskkill /F /IM electron.exe 2>nul

echo Starting wecom-desktop...
cd /d "%~dp0wecom-desktop"
npm start
