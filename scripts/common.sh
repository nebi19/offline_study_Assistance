# Shared helpers for setup.sh and start.sh (sourced, not run).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${CHAT_MODEL:=qwen2.5:3b}"
: "${EMBED_MODEL:=nomic-embed-text}"
: "${OLLAMA_URL:=http://127.0.0.1:11434}"
export CHAT_MODEL EMBED_MODEL OLLAMA_URL

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

find_uv() {
  if command -v uv >/dev/null 2>&1; then UV=uv
  elif [ -x "$HOME/.local/bin/uv" ]; then UV="$HOME/.local/bin/uv"
  else return 1; fi
}

# Ollama from PATH, or the no-sudo install in ~/.local/ollama.
find_ollama() {
  if command -v ollama >/dev/null 2>&1; then OLLAMA=ollama
  elif [ -x "$HOME/.local/ollama/bin/ollama" ]; then OLLAMA="$HOME/.local/ollama/bin/ollama"
  else return 1; fi
}

ollama_running() { curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; }

ensure_ollama() {
  find_ollama || die "Ollama is not installed. See README → Setup (step 1)."
  if ! ollama_running; then
    say "Starting Ollama (log: data/ollama.log)"
    mkdir -p data
    nohup "$OLLAMA" serve >data/ollama.log 2>&1 &
    for _ in $(seq 30); do ollama_running && break; sleep 1; done
    ollama_running || die "Ollama did not start; see data/ollama.log"
  fi
}
