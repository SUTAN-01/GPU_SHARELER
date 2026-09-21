param(
  [int]$Port = 4317
)

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  $process = Get-Process -Id $existing[0].OwningProcess -ErrorAction SilentlyContinue
  $processName = if ($process) { $process.ProcessName } else { "unknown" }
  Write-Host "Port $Port is already in use by: $processName (PID $($existing[0].OwningProcess))" -ForegroundColor Yellow
  Write-Host "The service may already be running. Open: http://localhost:$Port" -ForegroundColor Cyan
  Write-Host "To use another port, run: .\start.ps1 -Port 4318" -ForegroundColor DarkGray
  exit 0
}

$env:PORT = $Port
$python = $null
$pythonArgs = @()
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
  $python = "py.exe"
  $pythonArgs = @("-3")
} else {
  $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($pythonCommand) {
    & $pythonCommand.Source -c "import sys; raise SystemExit(sys.version_info < (3, 9))" 2>$null
    if ($LASTEXITCODE -eq 0) {
      $python = $pythonCommand.Source
    }
  }
}

if (-not $python) {
  Write-Host "Python 3.9+ not found. Please install Python and check 'Add Python to PATH'." -ForegroundColor Red
  exit 1
}

& $python @pythonArgs (Join-Path $PSScriptRoot "server.py")
