#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-evaluate}"

run_holdem() {
  if command -v uv >/dev/null 2>&1; then
    uv run holdem-agent "$@"
  else
    holdem-agent "$@"
  fi
}

run_python() {
  if command -v uv >/dev/null 2>&1; then
    uv run python "$@"
  else
    python "$@"
  fi
}

case "$cmd" in
  evaluate|benchmark)
    strategy="${2:-stage-safe-field-counter}"
    games="${GAMES:-100}"
    run_holdem evaluate --strategy "$strategy" --games "$games" --no-artifact
    ;;
  play)
    server_url="${2:?usage: ./run.sh play <ws_url> <bot_name> [strategy]}"
    bot_name="${3:?usage: ./run.sh play <ws_url> <bot_name> [strategy]}"
    strategy="${4:-stage-safe-field-counter}"
    run_holdem play "$server_url" "$bot_name" --strategy "$strategy" --verbose --hud
    ;;
  list)
    run_python - <<'PY'
from holdem_agent.strategy.registry import list_strategies
for name in list_strategies():
    print(name)
PY
    ;;
  *)
    echo "usage: ./run.sh [evaluate [strategy]|benchmark [strategy]|play <ws_url> <bot_name> [strategy]|list]" >&2
    exit 2
    ;;
esac
