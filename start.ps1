param([ValidateRange(1024,65535)][int]$Port = 8848, [switch]$NoBrowser,
      [string]$DataDir = (Join-Path $PSScriptRoot 'data'), [switch]$NoImport)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$platformData = [IO.Path]::GetFullPath($DataDir)
$pythonCandidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    'C:\Python312\python.exe',
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
)
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
$platformPython = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        & $candidate -c 'import flask,werkzeug' 2>$null
        if ($LASTEXITCODE -eq 0) { $platformPython = $candidate; break }
    }
}
if (-not $platformPython) {
    Write-Host 'Python with Flask was not found. Follow README.md to install requirements.'
    exit 1
}
$existing = $null
try { $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2 } catch { }
if ($existing) {
    if ($existing.app -eq 'research-commons') {
        $existingState = Join-Path $platformData 'server-process.json'
        if (-not (Test-Path -LiteralPath $existingState)) { throw 'Port is occupied by an unregistered platform. Choose a different port.' }
        $existingInfo = Get-Content -LiteralPath $existingState -Raw | ConvertFrom-Json
        if ($existingInfo.dataDir -ne $platformData -or $existingInfo.appPath -ne (Join-Path $PSScriptRoot 'app.py') -or $existingInfo.port -ne $Port) { throw 'Port is occupied by another checkout or data directory.' }
        & (Join-Path $PSScriptRoot 'start-ingestion.ps1') -DataDir $platformData -PythonPath $platformPython
        Write-Host "Already running: http://127.0.0.1:$Port"
        if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
        exit 0
    }
    throw 'The port is occupied by another service.'
}
$appPath = Join-Path $PSScriptRoot 'app.py'
$logPath = Join-Path $platformData 'logs'
$dataPath = $platformData
New-Item -ItemType Directory -Path $logPath -Force | Out-Null
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$serverArguments = @("`"$appPath`"", '--port', "$Port", '--data-dir', "`"$platformData`"")
if ($NoImport) { $serverArguments += '--no-import' }
$server = Start-Process -FilePath $platformPython -ArgumentList $serverArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logPath 'platform.stdout.log') -RedirectStandardError (Join-Path $logPath 'platform.stderr.log') -PassThru
@{pid=$server.Id;port=$Port;appPath=$appPath;dataDir=$platformData} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataPath 'server-process.json') -Encoding UTF8
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
        if ($health.app -eq 'research-commons') {
            & (Join-Path $PSScriptRoot 'start-ingestion.ps1') -DataDir $platformData -PythonPath $platformPython
            Write-Host "Local platform ready: http://127.0.0.1:$Port"
            if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
            exit 0
        }
    } catch { }
    if ($server.HasExited) { break }
    Start-Sleep -Milliseconds 500
}
Write-Host 'The platform could not start. See logs/platform.stderr.log. Try another port with: .\start.ps1 -Port 8080'
exit 1
