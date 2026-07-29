@echo off
setlocal
title Installation native de LYS IRM

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-LYS-IRM.ps1"
set "LYS_SETUP_EXIT=%ERRORLEVEL%"

if not "%LYS_SETUP_EXIT%"=="0" (
  echo.
  echo L'installation ne s'est pas terminee correctement.
  echo Consultez le message ci-dessus ou transmettez une capture d'ecran.
)

echo.
pause
exit /b %LYS_SETUP_EXIT%
