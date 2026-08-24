# PostgreSQL backup for the CreditProbe Tool database.
# Writes a compressed custom-format dump and prunes to the newest 14.
# Schedule daily via Task Scheduler (see docs/deploy.md section 9):
#   schtasks /create /tn "CreditProbe PG Backup" /tr "powershell -ExecutionPolicy Bypass -File C:\QA\CreditProbe Tool\scripts\backup_db.ps1" /sc daily /st 02:00 /ru SYSTEM

$ErrorActionPreference = "Stop"

$BackupDir = "C:\QA\CreditProbe Tool\backups"
$PgDump    = "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"
$DbName    = "ipm"
$DbUser    = "ipm_app"
$DbHost    = "localhost"
$Retention = 14

# The role password must be available to pg_dump. Prefer a pgpass file
# (%APPDATA%\postgresql\pgpass.conf) so the secret is not embedded here. If you
# set $env:PGPASSWORD in the scheduled task instead, pg_dump will use it.

if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir | Out-Null }

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$outFile = Join-Path $BackupDir "ipm_$stamp.dump"

& $PgDump --format=custom --host=$DbHost --username=$DbUser --file=$outFile $DbName
Write-Output "Backup written: $outFile"

# Prune old dumps beyond the retention count.
Get-ChildItem $BackupDir -Filter "ipm_*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $Retention |
    Remove-Item -Force
Write-Output "Retention applied (keeping newest $Retention)."
