param([ValidateSet('start', 'stop', 'status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker was not found. Install/start Docker Desktop (Linux containers), then reopen your terminal.'
    }
    & docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not ready. Start it and wait for the Linux engine.' }
    if ($Action -eq 'start') {
        if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
        & docker compose config --quiet
        if ($LASTEXITCODE -ne 0) { throw 'Compose configuration failed. Review .env against .env.example.' }
        & docker compose --profile worker up --build -d --wait --wait-timeout 180
        if ($LASTEXITCODE -ne 0) {
            throw 'Startup failed. Check docker compose ps -a and docker compose logs --tail 50 migrate backend frontend worker. Check port conflicts and .env. Existing database data has been preserved.'
        }
        Write-Host 'Ready: http://localhost:5173 (default origin); API docs: http://localhost:8000/docs'
    } elseif ($Action -eq 'stop') {
        & docker compose --profile worker --profile test down
        if ($LASTEXITCODE -ne 0) { throw 'Shutdown failed; inspect docker compose ps -a.' }
        Write-Host 'Stopped. PostgreSQL data volume preserved.'
    } else {
        & docker compose --profile worker ps -a
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Compose services.' }
    }
} finally { Pop-Location }
