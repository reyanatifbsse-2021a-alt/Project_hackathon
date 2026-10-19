#!/usr/bin/env bash
# AegisRuntime Startup Script
set -e

PORT=${PORT:-8000}
echo "Starting AegisRuntime on http://127.0.0.1:${PORT}..."

if [ -d ".venv" ]; then
    PYTHONPATH=. ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --reload
else
    PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --reload
fi
