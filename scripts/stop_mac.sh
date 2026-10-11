#!/usr/bin/env bash
# Stop and remove the FinAlly container. The finally-data volume (the database) is kept.
set -euo pipefail

CONTAINER=finally

if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  docker stop "$CONTAINER" >/dev/null
  docker rm "$CONTAINER" >/dev/null
  echo "FinAlly stopped. Data is kept in the finally-data volume."
else
  echo "FinAlly is not running."
fi
