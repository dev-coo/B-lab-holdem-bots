#!/usr/bin/env bash
# 웹 대시보드 기동 — 봇 상태 · 프로필 · Dirichlet · 로그 실시간 모니터.
#
# 기본 포트 8765. 이미 사용 중이면 HOLDEM_DASHBOARD_PORT 로 변경.
# 기동 후 브라우저로: http://127.0.0.1:8765/
#
# Usage:
#   scripts/bot-dashboard.sh              # 포그라운드 기동
#   scripts/bot-dashboard.sh --bg         # 백그라운드 (data/dashboard.pid)
#   scripts/bot-dashboard.sh --stop       # 백그라운드 정지

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PID_FILE="$ROOT/data/dashboard.pid"
LOG_FILE="$ROOT/data/logs/dashboard.log"
PORT="${HOLDEM_DASHBOARD_PORT:-8765}"

MODE="fg"
for arg in "$@"; do
    case "$arg" in
        --bg) MODE="bg" ;;
        --stop) MODE="stop" ;;
        --port=*) PORT="${arg#*=}" ;;
        *) echo "unknown arg: $arg"; exit 1 ;;
    esac
done

if [ "$MODE" = "stop" ]; then
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill -TERM "$PID"
            sleep 1
            kill -0 "$PID" 2>/dev/null && kill -KILL "$PID" || true
            echo "STOPPED pid=$PID"
        else
            echo "STALE (PID=$PID 사망)"
        fi
        rm -f "$PID_FILE"
    else
        echo "NOT RUNNING"
    fi
    exit 0
fi

mkdir -p "$ROOT/data/logs"

if [ "$MODE" = "bg" ]; then
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "이미 기동 중: pid=$(cat "$PID_FILE"). --stop 후 재기동."
        exit 1
    fi
    nohup uv run python -m holdem.dashboard.server --port "$PORT" \
        > "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"
    sleep 0.4
    if kill -0 "$PID" 2>/dev/null; then
        echo "READY pid=$PID url=http://127.0.0.1:$PORT/ log=$LOG_FILE"
    else
        echo "FAILED (log=$LOG_FILE)"
        rm -f "$PID_FILE"
        exit 1
    fi
else
    echo "대시보드 기동: http://127.0.0.1:$PORT/  (Ctrl+C 로 종료)"
    exec uv run python -m holdem.dashboard.server --port "$PORT"
fi
