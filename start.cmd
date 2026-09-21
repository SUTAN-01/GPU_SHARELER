@echo off
set "PORT=%~1"
if "%PORT%"=="" set "PORT=4317"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr LISTENING ^| findstr ":%PORT% "') do (
  echo 端口 %PORT% 已被占用，PID: %%P
  echo 服务可能已经运行，请打开: http://localhost:%PORT%
  echo 如需使用其他端口，请执行: start.cmd 4318
  exit /b 0
)

where py.exe >nul 2>nul
if %errorlevel%==0 (
  py.exe -3 -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul
  if not errorlevel 1 (
    py.exe -3 "%~dp0server.py"
    exit /b %errorlevel%
  )
)

where python.exe >nul 2>nul
if %errorlevel%==0 (
  python.exe -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul
  if not errorlevel 1 (
    python.exe "%~dp0server.py"
    exit /b %errorlevel%
  )
)

echo 未找到可用的 Python 3.9+，请先安装 Python 并勾选 Add Python to PATH。
exit /b 1
