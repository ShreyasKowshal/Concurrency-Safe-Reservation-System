# Recovery only affects a fresh project generated here. No volume deletion occurs.
$ErrorActionPreference = 'Stop'
$project = 'csrs-phase8-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$composeArgs = @('compose', '-p', $project, '-f', 'compose.yaml', '-f', 'compose.validation.yaml', '--profile', 'worker')
function Invoke-Compose {
    param([string[]]$Arguments)
    & docker @composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Isolated verification failed: ' + ($Arguments -join ' ')) }
}
Push-Location (Split-Path -Parent $PSScriptRoot)
$state = $null
$verificationFailed = $false
try {
    if (-not (Test-Path -LiteralPath '.env')) { throw 'Run scripts/local.ps1 start first to prepare .env.' }
    Write-Host "Isolated project: $project. Separate PostgreSQL volume; no host ports."
    Invoke-Compose -Arguments @('config', '--quiet')
    $isolatedConfiguration = (Invoke-Compose -Arguments @('config', '--format', 'json')) | ConvertFrom-Json
    foreach ($service in @('postgres', 'redis', 'backend', 'frontend')) {
        if ($isolatedConfiguration.services.$service.ports) { throw 'Isolation override retained a host port.' }
    }
    if ($isolatedConfiguration.volumes.postgres_data.name -ne ($project + '_postgres_data')) {
        throw 'Recovery database volume is not scoped to the generated project.'
    }
    Invoke-Compose -Arguments @('up', '--build', '-d', '--wait', '--wait-timeout', '180')
    Write-Host 'PASS: generated project volume and zero published host ports verified'
    Invoke-Compose -Arguments @('stop', 'worker')
    # Contains random fixture credentials; keep in memory and pass only through stdin.
    $state = Invoke-Compose -Arguments @('exec', '-T', 'backend', 'python', 'scripts/smoke_recovery.py', 'prepare')
    Invoke-Compose -Arguments @('up', '-d', 'worker')
    $state | & docker @composeArgs exec -T backend python scripts/smoke_recovery.py verify
    if ($LASTEXITCODE -ne 0) { throw 'Initial persistence fixture failed.' }
    foreach ($service in @('backend', 'frontend', 'redis', 'worker', 'postgres')) {
        Invoke-Compose -Arguments @('restart', $service)
        Invoke-Compose -Arguments @('up', '-d', '--wait', '--wait-timeout', '180')
        $state | & docker @composeArgs exec -T backend python scripts/smoke_recovery.py verify
        if ($LASTEXITCODE -ne 0) { throw "Recovery check failed after $service restart." }
        Write-Host "PASS: $service restart, session, replay, worker, SQL counters"
    }
    Invoke-Compose -Arguments @('down')
    Invoke-Compose -Arguments @('up', '-d', '--wait', '--wait-timeout', '180')
    $state | & docker @composeArgs exec -T backend python scripts/smoke_recovery.py verify
    if ($LASTEXITCODE -ne 0) { throw 'Data did not survive ordinary down/up.' }
    Write-Host 'PASS: full down/up persistence'
    try {
        Invoke-Compose -Arguments @('stop', 'postgres')
        $state | & docker @composeArgs exec -T backend python scripts/smoke_recovery.py database-outage
        if ($LASTEXITCODE -ne 0) { throw 'Database outage did not produce controlled 503 responses.' }
    } finally { Invoke-Compose -Arguments @('up', '-d', '--wait', '--wait-timeout', '90', 'postgres') }
    Invoke-Compose -Arguments @('up', '-d', '--wait', '--wait-timeout', '180')
    $state | & docker @composeArgs exec -T backend python scripts/smoke_recovery.py verify
    if ($LASTEXITCODE -ne 0) { throw 'Database outage recovery failed.' }
    Write-Host 'PASS: database unavailable 503 and recovery'
    Invoke-Compose -Arguments @('exec', '-T', 'backend', 'python', 'scripts/smoke_reservations.py')
    Invoke-Compose -Arguments @('exec', '-T', 'backend', 'python', 'scripts/smoke_redis.py', 'available')
    try {
        Invoke-Compose -Arguments @('stop', 'redis')
        Invoke-Compose -Arguments @('restart', 'worker')
        Invoke-Compose -Arguments @('up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '90', 'backend')
        Invoke-Compose -Arguments @('exec', '-T', 'backend', 'python', 'scripts/smoke_redis.py', 'outage')
    } finally { Invoke-Compose -Arguments @('up', '-d', '--wait', '--wait-timeout', '90', 'redis') }
    Invoke-Compose -Arguments @('exec', '-T', 'backend', 'python', 'scripts/smoke_redis.py', 'recovered')
    Write-Host 'PASS: isolated restart/outage/recovery verification'
} catch {
    $verificationFailed = $true
    Write-Warning $_.Exception.Message
} finally {
    if ($state) {
        $state | & docker @composeArgs exec -T backend python scripts/smoke_recovery.py cleanup
        if ($LASTEXITCODE -ne 0) {
            $verificationFailed = $true
            Write-Warning "Fixture cleanup failed; inspect isolated project $project."
        }
    }
    & docker @composeArgs down
    if ($LASTEXITCODE -ne 0) { $verificationFailed = $true }
    Write-Host "Stopped $project. Its named volumes are retained; application project csrs was untouched."
    Pop-Location
}
if ($verificationFailed) { exit 1 }
