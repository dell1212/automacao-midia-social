#!/usr/bin/env bash
# Builds webui/ and stages it (plus the local login page) into resource/public/,
# which app/asgi.py already serves at "/" via StaticFiles(html=True).
#
# Usage:
#   ./scripts/build_webui.sh                                  # local default origin
#   DEPLOY_ORIGIN=https://example.com ./scripts/build_webui.sh # different origin
set -euo pipefail
cd "$(dirname "$0")/.."

ORIGIN="${DEPLOY_ORIGIN:-http://localhost:8080}"

npm --prefix webui ci
VITE_PARENT_ORIGIN="$ORIGIN" VITE_API_BASE_URL="/api/v1" npm --prefix webui run build

rm -rf resource/public
mkdir -p resource/public
cp -r webui/dist/. resource/public/
cp resource/login/login.html resource/public/login.html

echo "Built. Serving from $ORIGIN once the backend is up — open $ORIGIN/login.html"
