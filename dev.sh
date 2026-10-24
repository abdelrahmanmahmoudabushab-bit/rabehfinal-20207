#!/usr/bin/env bash
# Run Rahbeh locally: API on :8000, web app on :3000. Ctrl+C stops both.
set -e
cd "$(dirname "$0")"
[ -f api/.env ] || cp api/.env.example api/.env
if [ ! -d api/.venv ]; then python3 -m venv api/.venv && api/.venv/bin/pip install -q -r api/requirements.txt; fi
[ -d web/node_modules ] || (cd web && npm install)
trap 'kill 0' EXIT
(cd api && .venv/bin/uvicorn rahbeh.main:app --port 8000 --reload) &
(cd web && npm run dev) &
wait
