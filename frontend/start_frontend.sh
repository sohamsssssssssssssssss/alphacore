#!/bin/bash
cd "$(dirname "$0")"
exec > /tmp/vite_persist.log 2>&1
echo "Starting Vite at $(date)"
./node_modules/.bin/vite --port 5181
