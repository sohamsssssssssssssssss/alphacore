#!/bin/bash
# AlphaCore backend auto-restart script
# Usage: bash scripts/restart_backend.sh
# Keeps backend running, restarts on crash, logs to logs/backend.log

mkdir -p logs

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)/backend"
VENV="$(cd "$(dirname "$0")/.." && pwd)/venv"
LOG_FILE="$(cd "$(dirname "$0")/.." && pwd)/logs/backend.log"

echo "Starting AlphaCore backend with auto-restart..."

while true; do
    echo "[$(date)] Starting backend..." >> "$LOG_FILE"
    cd "$BACKEND_DIR"
    "$VENV/bin/python3" -m uvicorn main:app --host 0.0.0.0 --port 8000 >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    echo "[$(date)] Backend exited with code $EXIT_CODE. Restarting in 5s..." >> "$LOG_FILE"
    sleep 5
done
