#!/usr/bin/env bash
# 봇을 백그라운드로 기동. PID 파일 + 세션 로그.
# Usage:
#   scripts/bot-start.sh                 # 기본 (chart + pot-odds)
#   scripts/bot-start.sh --ev-tree       # EV tree postflop 활성
#   scripts/bot-start.sh --coordinator   # LLM coordinator 도 활성 (EV tree 필수)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/data/bot.pid"
LOG_DIR="$ROOT/data/logs/cli"
mkdir -p "$LOG_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "이미 실행 중 (PID=$(cat "$PID_FILE")). 먼저 scripts/bot-stop.sh 실행"
    exit 1
fi

ARGS=(--profile-db "$ROOT/data/profiles.db" --log-level INFO)
for arg in "$@"; do
    case "$arg" in
        --ev-tree)       ARGS+=(--use-ev-tree) ;;
        --coordinator)   ARGS+=(--use-coordinator) ;;
        *)               ARGS+=("$arg") ;;
    esac
done

SESSION_LOG="$LOG_DIR/session_$(date +%Y%m%d_%H%M%S).log"
echo "기동: uv run holdem ${ARGS[*]}"
echo "로그: $SESSION_LOG"

nohup uv run holdem "${ARGS[@]}" > "$SESSION_LOG" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
sleep 2

if kill -0 "$PID" 2>/dev/null; then
    echo "READY pid=$PID"
    echo ""
    echo "상태 확인:   scripts/bot-status.sh"
    echo "실시간 로그: scripts/bot-logs.sh"
    echo "정지:        scripts/bot-stop.sh"
else
    echo "FAIL: 기동 직후 프로세스 죽음. 로그 확인:"
    tail -30 "$SESSION_LOG"
    rm -f "$PID_FILE"
    exit 2
fi
