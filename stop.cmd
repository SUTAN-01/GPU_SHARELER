@echo off
set "PORT=%~1"
if "%PORT%"=="" set "PORT=4317"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr LISTENING ^| findstr ":%PORT% "') do (
  echo Stopping PID %%P on port %PORT%...
  taskkill /PID %%P /F
  exit /b 0
)

echo Port %PORT% is not listening.
