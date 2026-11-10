#!/usr/bin/env bash
# Start the study assistant for the whole lab. Works offline.
set -euo pipefail
source "$(dirname "$0")/common.sh"

PORT="${PORT:-8000}"
find_uv || die "uv not found; run scripts/setup.sh first"
ensure_ollama
[ -f data/index/chunks.json ] || die "No search index yet; run scripts/setup.sh first"

say "Study Assistant is starting. Open it in a browser on any lab computer or tablet:"
echo "    This PC:      http://localhost:$PORT"
for ip in $(hostname -I 2>/dev/null); do
  case "$ip" in *:*) ;; *) echo "    Lab network:  http://$ip:$PORT" ;; esac
done
[ -n "${TEACHER_PIN:-}" ] && echo "    Teacher view is protected by TEACHER_PIN"
echo

exec "$UV" run uvicorn studyassistant.app:create_app --factory --host 0.0.0.0 --port "$PORT"
