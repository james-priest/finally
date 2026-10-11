# Start FinAlly in Docker on http://localhost:8000.
# Usage: scripts\start_windows.ps1 [-Build] [-NoOpen]
#   -Build   rebuild the image even if it exists
#   -NoOpen  do not open the browser
param(
    [switch]$Build,
    [switch]$NoOpen
)

$Image = "finally"
$Container = "finally"
$Volume = "finally-data"
$Url = "http://localhost:8000"
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $EnvFile)) {
    Write-Host "Missing .env. Run: Copy-Item .env.example .env  (then set OPENROUTER_API_KEY)"
    exit 1
}

docker image inspect $Image *> $null
if ($Build -or $LASTEXITCODE -ne 0) {
    docker build -t $Image $Root
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Recreate the container so it runs the current image and .env. The volume keeps the data.
docker stop $Container *> $null
docker rm $Container *> $null
docker run -d --name $Container -p 8000:8000 -v "${Volume}:/app/db" --env-file $EnvFile $Image | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Waiting for FinAlly to start..."
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

Write-Host "FinAlly is running at $Url"
if (-not $NoOpen) {
    Start-Process $Url
}
