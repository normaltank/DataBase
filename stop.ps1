param([string]$DataDir = (Join-Path $PSScriptRoot 'data'))
$ErrorActionPreference = 'Stop'
$platformData = [IO.Path]::GetFullPath($DataDir)
& (Join-Path $PSScriptRoot 'stop-ingestion.ps1') -DataDir $platformData
$stateFile = Join-Path $platformData 'server-process.json'
if (-not (Test-Path -LiteralPath $stateFile)) { Write-Host 'No background platform process is recorded.'; exit 0 }
$serverInfo = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$expectedApp = Join-Path $PSScriptRoot 'app.py'
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$serverInfo.pid)"
if (-not $serverProcess) { Write-Host 'Platform is already stopped.'; exit 0 }
if ($serverInfo.appPath -ne $expectedApp -or $serverInfo.dataDir -ne $platformData -or -not $serverProcess.CommandLine.Contains($expectedApp) -or -not $serverProcess.CommandLine.Contains($platformData)) {
    Write-Host 'The recorded process does not match this project. No process was stopped.'
    exit 1
}
Stop-Process -Id $serverProcess.ProcessId
Remove-Item -LiteralPath $stateFile
Write-Host 'Local platform stopped. Your data is preserved.'
