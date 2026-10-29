param([string]$DataDir = (Join-Path $PSScriptRoot 'data'), [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$ingestionData = [IO.Path]::GetFullPath($DataDir)
$workerPath = Join-Path $PSScriptRoot 'scripts\ingestion_worker.py'
$workerState = Join-Path $ingestionData 'ingestion-process.json'
New-Item -ItemType Directory -Path $ingestionData -Force | Out-Null
if (Test-Path -LiteralPath $workerState) {
    $recorded = Get-Content -LiteralPath $workerState -Raw | ConvertFrom-Json
    $running = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$recorded.pid)"
    if ($running) {
        if ($recorded.workerPath -ne $workerPath -or $recorded.dataDir -ne $ingestionData -or -not $running.CommandLine.Contains($workerPath) -or -not $running.CommandLine.Contains($ingestionData)) { throw 'Recorded worker PID belongs to another process. No process was changed.' }
        Write-Host 'Public ingestion worker is already running.'
        exit 0
    }
}
if (-not $PythonPath) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Python is unavailable. Start through start.ps1 or specify -PythonPath.' }
    $PythonPath = $pythonCommand.Source
}
$workerLogs = Join-Path $ingestionData 'logs'
New-Item -ItemType Directory -Path $workerLogs -Force | Out-Null
$worker = Start-Process -FilePath $PythonPath -ArgumentList @("`"$workerPath`"",'--data-dir',"`"$ingestionData`"") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $workerLogs 'ingestion.stdout.log') -RedirectStandardError (Join-Path $workerLogs 'ingestion.stderr.log') -PassThru
@{pid=$worker.Id;workerPath=$workerPath;dataDir=$ingestionData} | ConvertTo-Json | Set-Content -LiteralPath $workerState -Encoding UTF8
Start-Sleep -Milliseconds 800
if ($worker.HasExited) { throw 'Public ingestion worker exited. See the data directory logs/ingestion.stderr.log.' }
Write-Host "Public ingestion worker started for: $ingestionData"
