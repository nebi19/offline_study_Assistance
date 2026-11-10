#!/usr/bin/env bash
# One-time setup (needs internet once): Python packages, AI models, search index.
# After this, the app runs with the network cable unplugged.
set -euo pipefail
source "$(dirname "$0")/common.sh"

say "1/5 Python packages"
if ! find_uv; then
  say "Installing uv (Python package manager) into ~/.local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
  find_uv || die "uv install failed"
fi
"$UV" sync --frozen

say "2/5 Local AI models ($CHAT_MODEL, $EMBED_MODEL)"
ensure_ollama
"$OLLAMA" pull "$CHAT_MODEL"
"$OLLAMA" pull "$EMBED_MODEL"

say "3/5 Textbooks"
if ! ls textbooks/*.pdf >/dev/null 2>&1 && ! ls lessons/*.md >/dev/null 2>&1; then
  die "No textbooks in textbooks/ and no lessons in lessons/. See README → Adding textbooks."
fi
ls textbooks/*.pdf 2>/dev/null | sed 's/^/    /' || true

say "4/5 Building the search index (first run OCRs scanned pages: a few minutes)"
"$UV" run python -m studyassistant.build

if [ "${SKIP_SUMMARIES:-0}" = "1" ]; then
  say "5/5 Unit summaries skipped (they will be written when first opened)"
else
  say "5/5 Writing the unit summaries (2-3 minutes per unit; skip with SKIP_SUMMARIES=1)"
  "$UV" run python -m studyassistant.prepare || say "Some summaries failed; they will be retried when opened"
fi

say "Done. Start the app with: scripts/start.sh"
