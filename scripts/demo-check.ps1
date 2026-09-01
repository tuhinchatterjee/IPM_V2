<#
.SYNOPSIS
    Pre-flight for a CreditProbe client demonstration. Spends nothing.

.DESCRIPTION
    One command that answers one question: can this machine give the
    demonstration right now?

    It makes NO live provider call. It reads the key's PRESENCE and never its
    value, never prints it, and never writes it anywhere.

    Every check reports PASS, WARNING or FAIL, and the script ends with

        DEMO CHECK: GO
    or
        DEMO CHECK: NO-GO

    and nothing in between. A pre-flight that says "mostly fine" is a
    pre-flight nobody can act on at eight in the morning.

    WARNING never blocks GO on its own. A FAIL always does.

.PARAMETER Quiet
    Print only the section headings and the verdict.

.PARAMETER Json
    Emit the whole result as JSON instead of the readable report.

.EXAMPLE
    .\scripts\demo-check.ps1

.EXAMPLE
    .\scripts\demo-check.ps1 -Json

.NOTES
    Windows PowerShell 5.1 and PowerShell 7. Docker Desktop. No local Python
    or Node is needed: everything that needs them runs inside the containers.

    Exit codes
        0   GO
        1   NO-GO
#>
[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

$Script:Results = New-Object System.Collections.ArrayList

function Add-Result {
    param(
        [string]$Section,
        [string]$Name,
        [ValidateSet('PASS', 'WARNING', 'FAIL')][string]$State,
        [string]$Detail = ''
    )
    $null = $Script:Results.Add([pscustomobject]@{
            Section = $Section
            Name    = $Name
            State   = $State
            Detail  = $Detail
        })
    if ($Quiet) { return }
    $colour = switch ($State) {
        'PASS' { 'Green' }
        'WARNING' { 'Yellow' }
        'FAIL' { 'Red' }
    }
    $mark = switch ($State) {
        'PASS' { '  OK  ' }
        'WARNING' { ' WARN ' }
        'FAIL' { ' FAIL ' }
    }
    Write-Host $mark -ForegroundColor $colour -NoNewline
    Write-Host (' {0}' -f $Name) -NoNewline
    if ($Detail) { Write-Host ('  - {0}' -f $Detail) -ForegroundColor DarkGray }
    else { Write-Host '' }
}

function Write-Section {
    param([string]$Title)
    if ($Quiet) { return }
    Write-Host ''
    Write-Host ('== {0} ' -f $Title).PadRight(64, '=') -ForegroundColor Cyan
}

function Invoke-Silently {
    param([string]$File, [string[]]$Arguments)
    try {
        $output = & $File @Arguments 2>&1
        return [pscustomobject]@{ Code = $LASTEXITCODE; Output = ($output -join "`n") }
    }
    catch {
        return [pscustomobject]@{ Code = 1; Output = $_.Exception.Message }
    }
}

function Test-Port {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $open = $async.AsyncWaitHandle.WaitOne(700)
        if ($open) { $client.EndConnect($async) }
        $client.Close()
        return $open
    }
    catch { return $false }
}

function Get-Json {
    param([string]$Url, [int]$TimeoutSec = 12)
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec -Method Get
    }
    catch { return $null }
}

if (-not $Quiet) {
    Write-Host ''
    Write-Host 'CreditProbe demonstration pre-flight' -ForegroundColor White
    Write-Host 'No live provider call is made. Nothing is spent.' -ForegroundColor DarkGray
}

# ------------------------------------------------------------------ 1. source
Write-Section 'Source'

$branch = (Invoke-Silently 'git' @('rev-parse', '--abbrev-ref', 'HEAD')).Output.Trim()
$sha = (Invoke-Silently 'git' @('rev-parse', 'HEAD')).Output.Trim()
$short = if ($sha.Length -ge 12) { $sha.Substring(0, 12) } else { $sha }
Add-Result 'Source' 'git branch' 'PASS' $branch
Add-Result 'Source' 'commit' 'PASS' $short

$dirty = (Invoke-Silently 'git' @('status', '--porcelain')).Output.Trim()
if ($dirty) {
    Add-Result 'Source' 'working tree' 'WARNING' 'uncommitted changes are present'
}
else {
    Add-Result 'Source' 'working tree' 'PASS' 'clean'
}

# ------------------------------------------------------------------ 2. docker
Write-Section 'Docker'

$docker = Invoke-Silently 'docker' @('version', '--format', '{{.Server.Version}}')
if ($docker.Code -ne 0) {
    Add-Result 'Docker' 'Docker Desktop' 'FAIL' 'not installed, or the engine is not running'
}
else {
    Add-Result 'Docker' 'Docker Desktop' 'PASS' ('engine {0}' -f $docker.Output.Trim())
}

$compose = Invoke-Silently 'docker' @('compose', 'config', '-q')
if ($compose.Code -ne 0) {
    Add-Result 'Docker' 'compose file' 'FAIL' 'docker-compose.yml is not valid'
}
else {
    Add-Result 'Docker' 'compose file' 'PASS' 'valid'
}

$psOut = Invoke-Silently 'docker' @('compose', 'ps', '--format', '{{.Service}} {{.State}}')
foreach ($service in @('db', 'backend', 'frontend', 'agent-worker')) {
    $line = ($psOut.Output -split "`n") | Where-Object { $_ -match ('^{0}\s' -f [regex]::Escape($service)) }
    if (-not $line) {
        Add-Result 'Docker' ('service {0}' -f $service) 'FAIL' 'not running - run .\scripts\demo-start.ps1'
    }
    elseif ($line -match 'running') {
        Add-Result 'Docker' ('service {0}' -f $service) 'PASS' 'running'
    }
    else {
        Add-Result 'Docker' ('service {0}' -f $service) 'FAIL' $line.Trim()
    }
}

# ------------------------------------------------------------ 3. configuration
Write-Section 'Configuration'

$envPath = Join-Path $RepoRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    Add-Result 'Configuration' '.env' 'FAIL' 'missing - copy .env.example and fill it in'
}
else {
    Add-Result 'Configuration' '.env' 'PASS' 'present'
    # PRESENCE only. The value is never read into a variable, never printed,
    # never logged. A pre-flight that echoes a key is a pre-flight that puts
    # the key in a screenshot.
    $hasKey = (Select-String -LiteralPath $envPath -Pattern '^\s*ANTHROPIC_API_KEY\s*=\s*\S' -Quiet)
    if ($hasKey) {
        Add-Result 'Configuration' 'API key' 'PASS' 'present (value not read)'
    }
    else {
        Add-Result 'Configuration' 'API key' 'WARNING' 'not set - deterministic flows still demonstrate'
    }
}

foreach ($port in @(3000, 8000)) {
    if (Test-Port -Port $port) {
        Add-Result 'Configuration' ('port {0}' -f $port) 'PASS' 'answering'
    }
    else {
        Add-Result 'Configuration' ('port {0}' -f $port) 'FAIL' 'nothing is listening'
    }
}

try {
    $drive = Get-PSDrive -Name ($RepoRoot.Substring(0, 1)) -ErrorAction Stop
    $freeGb = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGb -lt 5) {
        Add-Result 'Configuration' 'disk space' 'WARNING' ('{0} GB free' -f $freeGb)
    }
    else {
        Add-Result 'Configuration' 'disk space' 'PASS' ('{0} GB free' -f $freeGb)
    }
}
catch {
    Add-Result 'Configuration' 'disk space' 'WARNING' 'could not be read'
}

# ------------------------------------------------------------------ 4. backend
Write-Section 'Backend'

$health = Get-Json 'http://localhost:8000/api/v1/health'
if ($null -eq $health) {
    Add-Result 'Backend' 'health' 'FAIL' 'the API did not answer on port 8000'
}
else {
    $state = [string]$health.status
    if ($state -eq 'ok') { Add-Result 'Backend' 'health' 'PASS' $state }
    elseif ($state -eq 'degraded') { Add-Result 'Backend' 'health' 'WARNING' $state }
    else { Add-Result 'Backend' 'health' 'FAIL' $state }
}

$build = Get-Json 'http://localhost:8000/api/v1/build'
if ($null -eq $build) {
    Add-Result 'Backend' 'source/image SHA' 'FAIL' 'the build endpoint did not answer'
}
else {
    $imageSha = ''
    if ($build.PSObject.Properties.Name -contains 'build' -and $build.build) {
        if ($build.build.PSObject.Properties.Name -contains 'source_sha') {
            $imageSha = [string]$build.build.source_sha
        }
    }
    if (-not $imageSha) {
        Add-Result 'Backend' 'source/image SHA' 'WARNING' 'the image does not report a source SHA'
    }
    elseif ($imageSha -eq $sha) {
        Add-Result 'Backend' 'source/image SHA' 'PASS' 'the running image is this commit'
    }
    else {
        Add-Result 'Backend' 'source/image SHA' 'FAIL' ('image {0} but source {1} - rebuild' -f $imageSha.Substring(0, [Math]::Min(12, $imageSha.Length)), $short)
    }
}

$frontendProxy = Get-Json 'http://localhost:3000/api/v1/health'
if ($null -eq $frontendProxy) {
    Add-Result 'Backend' 'front-end proxy' 'FAIL' 'the browser cannot reach the API through port 3000'
}
else {
    Add-Result 'Backend' 'front-end proxy' 'PASS' 'the browser can reach the API'
}

# --------------------------------------------------------------------- 5. demo
Write-Section 'Demonstration state'

$demo = Get-Json 'http://localhost:8000/api/v1/demo'
if ($null -eq $demo) {
    Add-Result 'Demo' 'Demo Mode' 'WARNING' 'the demo endpoint did not answer'
}
elseif ($demo.demo_mode) {
    Add-Result 'Demo' 'Demo Mode' 'PASS' ('ON, pinned to {0}' -f $demo.data_release)
}
else {
    Add-Result 'Demo' 'Demo Mode' 'FAIL' 'OFF - set CREDITPROBE_DEMO_MODE=true in .env and restart'
}

if ($null -ne $demo -and $demo.demo_safe_mode) {
    Add-Result 'Demo' 'Demo Safe Mode' 'PASS' 'ON'
}
else {
    Add-Result 'Demo' 'Demo Safe Mode' 'WARNING' 'OFF - set AI_DEMO_SAFE_MODE=true to refuse an unvalidated answer'
}

$catalog = Get-Json 'http://localhost:8000/api/v1/catalog'
if ($null -eq $catalog) {
    Add-Result 'Demo' 'data catalogue' 'FAIL' 'the catalogue did not answer'
}
elseif ([int]$catalog.dataset_count -lt 20) {
    Add-Result 'Demo' 'data catalogue' 'FAIL' ('{0} datasets, expected at least 20' -f $catalog.dataset_count)
}
else {
    Add-Result 'Demo' 'data catalogue' 'PASS' ('{0} governed datasets' -f $catalog.dataset_count)
}

$users = Get-Json 'http://localhost:8000/api/v1/users'
if ($null -eq $users) {
    Add-Result 'Demo' 'seeded users' 'FAIL' 'the users endpoint did not answer'
}
else {
    $names = @($users.users | ForEach-Object { $_.username })
    $wanted = @('alex.rahman', 'sara.qahtani', 'omar.nasser', 'layla.haddad')
    $missing = @($wanted | Where-Object { $names -notcontains $_ })
    if ($missing.Count -gt 0) {
        Add-Result 'Demo' 'seeded users' 'FAIL' ('missing: {0}' -f ($missing -join ', '))
    }
    else {
        Add-Result 'Demo' 'seeded users' 'PASS' ('{0} account(s)' -f $names.Count)
    }
}

$projects = Get-Json 'http://localhost:8000/api/v1/projects'
if ($null -eq $projects -or @($projects.projects).Count -lt 1) {
    Add-Result 'Demo' 'seeded Project' 'FAIL' 'no Project - run .\scripts\demo-reset.ps1'
}
else {
    Add-Result 'Demo' 'seeded Project' 'PASS' ('{0} Project(s)' -f @($projects.projects).Count)
}

$cases = Get-Json 'http://localhost:8000/api/v1/risk-cases'
if ($null -eq $cases) {
    Add-Result 'Demo' 'Risk Cases' 'FAIL' 'Requires Attention did not answer'
}
elseif ($cases.review.state -eq 'NOT_RUN') {
    Add-Result 'Demo' 'Risk Cases' 'FAIL' 'no portfolio review has run - run .\scripts\demo-reset.ps1'
}
else {
    Add-Result 'Demo' 'Risk Cases' 'PASS' ([string]$cases.summary)
}

# The demo workspace, checked from inside the container so no local Python is
# needed. `--check` is read-only and exits non-zero when it finds test residue.
$state = Invoke-Silently 'docker' @('compose', 'exec', '-T', 'backend',
    'python', 'scripts/demo_state.py', '--check')
if ($state.Code -eq 0) {
    Add-Result 'Demo' 'workspace is clean' 'PASS' 'no test residue'
}
else {
    $firstLine = (($state.Output -split "`n") | Where-Object { $_ -match '^\s+-' } | Select-Object -First 1)
    Add-Result 'Demo' 'workspace is clean' 'FAIL' ('test residue found. {0}' -f $firstLine)
}

# ------------------------------------------------------- 6. live verification
Write-Section 'Live verification'

$verification = Get-Json 'http://localhost:8000/api/v1/validation/ai-badge'
if ($null -eq $verification) {
    Add-Result 'Verification' 'stored report' 'WARNING' 'no verification badge is served by this build'
}
elseif ($verification.live_verified) {
    Add-Result 'Verification' 'stored report' 'PASS' ('current for {0}' -f $verification.verified_short_sha)
}
elseif ($verification.stale) {
    Add-Result 'Verification' 'stored report' 'WARNING' ('STALE: {0}' -f $verification.reason)
}
else {
    Add-Result 'Verification' 'stored report' 'WARNING' 'this build has never been live verified'
}

# ------------------------------------------------------------------- 7. routes
Write-Section 'Demo routes'

foreach ($route in @('/', '/projects', '/investigations', '/analyses', '/studio',
        '/data-builder', '/trace', '/workflow')) {
    try {
        $response = Invoke-WebRequest -Uri ('http://localhost:3000{0}' -f $route) `
            -TimeoutSec 20 -UseBasicParsing -Method Get
        if ([int]$response.StatusCode -lt 400) {
            Add-Result 'Routes' $route 'PASS' ('HTTP {0}' -f $response.StatusCode)
        }
        else {
            Add-Result 'Routes' $route 'FAIL' ('HTTP {0}' -f $response.StatusCode)
        }
    }
    catch {
        Add-Result 'Routes' $route 'FAIL' 'did not answer'
    }
}

# ------------------------------------------------------------------- 8. verdict
$failures = @($Script:Results | Where-Object { $_.State -eq 'FAIL' })
$warnings = @($Script:Results | Where-Object { $_.State -eq 'WARNING' })
$go = ($failures.Count -eq 0)

if ($Json) {
    [pscustomobject]@{
        checked  = (Get-Date).ToString('o')
        branch   = $branch
        commit   = $sha
        passed   = @($Script:Results | Where-Object { $_.State -eq 'PASS' }).Count
        warnings = $warnings.Count
        failures = $failures.Count
        verdict  = $(if ($go) { 'GO' } else { 'NO-GO' })
        results  = $Script:Results
    } | ConvertTo-Json -Depth 5
}
else {
    Write-Host ''
    Write-Host ('{0} passed, {1} warning(s), {2} failure(s).' -f `
        (@($Script:Results | Where-Object { $_.State -eq 'PASS' }).Count), `
            $warnings.Count, $failures.Count)
    foreach ($item in $failures) {
        Write-Host ('  BLOCKER  {0}: {1}' -f $item.Name, $item.Detail) -ForegroundColor Red
    }
    Write-Host ''
    if ($go) {
        Write-Host 'DEMO CHECK: GO' -ForegroundColor Green
        if ($warnings.Count -gt 0) {
            Write-Host ('  {0} warning(s). None of them blocks the demonstration; read them above.' -f $warnings.Count) -ForegroundColor Yellow
        }
    }
    else {
        Write-Host 'DEMO CHECK: NO-GO' -ForegroundColor Red
        Write-Host '  Fix every BLOCKER above and run this again.' -ForegroundColor Gray
    }
}

Pop-Location
if ($go) { exit 0 } else { exit 1 }
