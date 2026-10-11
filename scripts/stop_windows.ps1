# Stop and remove the FinAlly container. The finally-data volume (the database) is kept.
$Container = "finally"

docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    docker stop $Container | Out-Null
    docker rm $Container | Out-Null
    Write-Host "FinAlly stopped. Data is kept in the finally-data volume."
} else {
    Write-Host "FinAlly is not running."
}
