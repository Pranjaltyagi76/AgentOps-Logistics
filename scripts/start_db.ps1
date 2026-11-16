<#
.SYNOPSIS
    Starts the local portable Postgres 16 used for development, if it is not already running.

.DESCRIPTION
    Uses the layout from context/deployment.md §2.1:
      binaries: %LOCALAPPDATA%\Programs\pgsql-16\bin
      data:     %LOCALAPPDATA%\agentops-pg\data
      log:      %LOCALAPPDATA%\agentops-pg\server.log
    Listens on 127.0.0.1:5432 only. Safe to run repeatedly.

    To start it automatically when you sign in to Windows, register it once yourself
    (a per-user task, no admin rights needed):

      $script = Join-Path (Get-Location) 'scripts\start_db.ps1'
      Register-ScheduledTask -TaskName 'AgentOps Postgres' -User $env:USERNAME `
        -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) `
        -Action (New-ScheduledTaskAction -Execute 'powershell.exe' `
          -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"")

    Remove it with: Unregister-ScheduledTask -TaskName 'AgentOps Postgres'

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_db.ps1
#>
param(
    [string]$BinDir = (Join-Path $env:LOCALAPPDATA 'Programs\pgsql-16\bin'),
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'agentops-pg\data'),
    [int]$Port = 5432
)

$ErrorActionPreference = 'Stop'
$pgCtl = Join-Path $BinDir 'pg_ctl.exe'
if (-not (Test-Path $pgCtl)) {
    Write-Error "pg_ctl.exe not found in $BinDir (see context/deployment.md §2.1)"
    exit 1
}
if (-not (Test-Path (Join-Path $DataDir 'PG_VERSION'))) {
    Write-Error "No Postgres data directory at $DataDir (see context/deployment.md §2.1)"
    exit 1
}

& $pgCtl -D $DataDir status *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Output "Postgres is already running ($DataDir)."
    exit 0
}

$log = Join-Path (Split-Path $DataDir -Parent) 'server.log'
& $pgCtl -D $DataDir -l $log -o "-p $Port -c listen_addresses=127.0.0.1" -w start
if ($LASTEXITCODE -ne 0) {
    Write-Error "Postgres did not start; see $log"
    exit $LASTEXITCODE
}
Write-Output "Postgres started on 127.0.0.1:$Port (log: $log)."
