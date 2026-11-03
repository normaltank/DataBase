param(
    [Parameter(Mandatory=$true)][ValidateSet('Register','Start','Stop','Status','Unregister')][string]$Action,
    [Parameter(Mandatory=$true)][string]$Release,
    [Parameter(Mandatory=$true)][string]$Config
)
$ErrorActionPreference = 'Stop'
$Release = (Resolve-Path -LiteralPath $Release).Path
$Config = (Resolve-Path -LiteralPath $Config).Path
$Python = Join-Path $Release '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Create the release venv first.' }
$Names = @('ResearchCommons-Web','ResearchCommons-Worker')
switch ($Action) {
    'Register' {
        # Run as the dedicated deployment account. Interactive credential input stays out of arguments/files.
        $Credential = Get-Credential -Message 'Dedicated non-administrator service account'
        $Trigger = New-ScheduledTaskTrigger -AtStartup
        $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
        foreach ($Kind in @('web','worker')) {
            $Name = if ($Kind -eq 'web') { $Names[0] } else { $Names[1] }
            $TaskAction = New-ScheduledTaskAction -Execute $Python -WorkingDirectory $Release -Argument ('-B -m platform_app.deployment ' + $Kind + ' --config "' + $Config + '"')
            Register-ScheduledTask -TaskName $Name -Action $TaskAction -Trigger $Trigger -Settings $Settings -User $Credential.UserName -Password $Credential.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
        }
    }
    'Start' { foreach ($Name in $Names) { Start-ScheduledTask -TaskName $Name } }
    'Stop' {
        & $Python -B -m platform_app.deployment worker-stop --config $Config
        if ($LASTEXITCODE -ne 0) { throw 'Worker stop request failed.' }
        $Deadline = (Get-Date).AddSeconds(180)
        while ((Get-ScheduledTask -TaskName $Names[1]).State -eq 'Running') {
            if ((Get-Date) -ge $Deadline) { throw 'Worker is still finishing. Inspect status before retrying; no process was killed.' }
            Start-Sleep -Seconds 1
        }
        Stop-ScheduledTask -TaskName $Names[0]
    }
    'Status' {
        foreach ($Name in $Names) { Get-ScheduledTask -TaskName $Name; Get-ScheduledTaskInfo -TaskName $Name }
        & $Python -B -m platform_app.deployment worker-status --config $Config
    }
    'Unregister' {
        foreach ($Name in $Names) {
            if ((Get-ScheduledTask -TaskName $Name).State -eq 'Running') { throw 'Stop tasks before unregistering.' }
        }
        foreach ($Name in $Names) { Unregister-ScheduledTask -TaskName $Name -Confirm:$false }
    }
}
