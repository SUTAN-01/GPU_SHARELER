param(
  [int]$Port = 4317
)

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
  Write-Host "端口 $Port 当前没有监听服务。"
  exit 0
}

$pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $pids) {
  $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
  if ($process) {
    Write-Host "正在停止 $($process.ProcessName) (PID $processId)..."
    Stop-Process -Id $processId -Force
  }
}
Write-Host "端口 $Port 已释放。"
