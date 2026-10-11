#!/usr/bin/env bash
# Start FinAlly in Docker on http://localhost:8000.
# Usage: scripts/start_mac.sh [--build] [--no-open]
#   --build    rebuild the image even if it exists
#   --no-open  do not open the browser
set -euo pipefail

IMAGE=finally
CONTAINER=finally
VOLUME=finally-data
URL=http://localhost:8000
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

build=false
open_browser=true
for arg in "$@"; do
  case "$arg" in
    --build) build=true ;;
    --no-open) open_browser=false ;;
    *) echo "Usage: $0 [--build] [--no-open]" >&2; exit 1 ;;
  esac
done

if [ ! -f "$ROOT/.env" ]; then
  echo "Missing .env. Run: cp .env.example .env  (then set OPENROUTER_API_KEY)" >&2
  exit 1
fi

if $build || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -t "$IMAGE" "$ROOT"
fi

# Recreate the container so it runs the current image and .env. The volume keeps the data.
docker stop "$CONTAINER" >/dev/null 2>&1 || true
docker rm "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" -p 8000:8000 -v "$VOLUME:/app/db" --env-file "$ROOT/.env" "$IMAGE" >/dev/null

echo "Waiting for FinAlly to start..."
for _ in $(seq 30); do
  curl -fs "$URL/api/health" >/dev/null && break
  sleep 1
done

echo "FinAlly is running at $URL"
if $open_browser; then
  open "$URL" 2>/dev/null || xdg-open "$URL" >/dev/null 2>&1 || true
fi
