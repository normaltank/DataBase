$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $PSScriptRoot 'data\server-process.json'
if (-not (Test-Path -LiteralPath $stateFile)) { Write-Host 'No background platform process is recorded.'; exit 0 }
$serverInfo = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$expectedApp = Join-Path $PSScriptRoot 'app.py'
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$serverInfo.pid)"
if (-not $serverProcess) { Write-Host 'Platform is already stopped.'; exit 0 }
if ($serverInfo.appPath -ne $expectedApp -or -not $serverProcess.CommandLine.Contains($expectedApp)) {
    Write-Host 'The recorded process does not match this project. No process was stopped.'
    exit 1
}
Stop-Process -Id $serverProcess.ProcessId
Write-Host 'Local platform stopped. Your data is preserved.'
