$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Create backend/.env with POSTGRES_PASSWORD and LBLSTDIO_DATABASE_URL first."
}

foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^(POSTGRES_PASSWORD|LBLSTDIO_DATABASE_URL)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}
if (-not $env:POSTGRES_PASSWORD -or -not $env:LBLSTDIO_DATABASE_URL) {
    throw "backend/.env must define POSTGRES_PASSWORD and LBLSTDIO_DATABASE_URL."
}

Push-Location $PSScriptRoot
try {
    docker compose --env-file $envFile -f compose.postgres.yaml up -d --wait
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not start successfully." }
    & (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m uvicorn app.main:app --host 127.0.0.1 --port 8000
} finally {
    Pop-Location
}
