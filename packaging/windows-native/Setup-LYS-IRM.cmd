@echo off
setlocal
title Installation de LYS IRM

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-LYS-IRM.ps1"
set "LYS_SETUP_EXIT=%ERRORLEVEL%"

echo.
echo Appuyez sur une touche pour fermer.
pause >nul
exit /b %LYS_SETUP_EXIT%
