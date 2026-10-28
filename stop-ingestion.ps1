param([string]$DataDir = (Join-Path $PSScriptRoot 'data'))
$ErrorActionPreference = 'Stop'
$ingestionData = [IO.Path]::GetFullPath($DataDir)
$workerPath = Join-Path $PSScriptRoot 'scripts\ingestion_worker.py'
$workerState = Join-Path $ingestionData 'ingestion-process.json'
if (-not (Test-Path -LiteralPath $workerState)) { Write-Host 'No public ingestion worker is recorded.'; exit 0 }
$recorded = Get-Content -LiteralPath $workerState -Raw | ConvertFrom-Json
$running = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$recorded.pid)"
if ($running) {
    if ($recorded.workerPath -ne $workerPath -or $recorded.dataDir -ne $ingestionData -or -not $running.CommandLine.Contains($workerPath) -or -not $running.CommandLine.Contains($ingestionData)) { throw 'Recorded worker PID does not match this checkout and data directory. No process was stopped.' }
    Stop-Process -Id $running.ProcessId
}
Remove-Item -LiteralPath $workerState
Write-Host 'Public ingestion worker stopped. Durable tasks remain available for restart.'
