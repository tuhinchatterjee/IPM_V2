<#
Stop the CreditProbe Tool container started by scripts\app-start.ps1.

Usage (from the project root):
    powershell -ExecutionPolicy Bypass -File scripts\app-stop.ps1

The database, uploaded datasets, users and logs are untouched. They live in
PostgreSQL and in the ipm-logs / ipm-uploads Docker volumes, not in the
container, so app-start.ps1 picks up exactly where this left off.

NOTE: keep this file ASCII-only (see the note in app-start.ps1).
#>

[CmdletBinding()]
param(
    [string]$ContainerName = "CreditProbe"
)

$ErrorActionPreference = "Stop"

$exists = docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}"
if (-not $exists) {
    Write-Host "$ContainerName is not running. Nothing to stop."
    exit 0
}

# Removed, not just stopped, so --restart unless-stopped does not bring it back
# on the next reboot.
docker rm -f $ContainerName | Out-Null
Write-Host "Stopped and removed $ContainerName. Your data is unaffected."
