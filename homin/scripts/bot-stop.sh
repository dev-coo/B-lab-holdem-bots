#!/usr/bin/env bash
# SIGTERM 으로 봇 정지. PID 파일이 없으면 이름으로 검색.
# Usage: scripts/bot-stop.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/data/bot.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "SIGTERM → PID $PID"
        kill -TERM "$PID"
        for _ in $(seq 1 10); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$PID" 2>/dev/null; then
            echo "WARN: 여전히 살아있음. SIGKILL"
            kill -KILL "$PID" 2>/dev/null || true
        fi
    fi
    rm -f "$PID_FILE"
fi

# 잔여 프로세스 청소
PIDS=$(ps aux | grep -E "holdem\.cli" | grep -v grep | awk '{print $2}')
if [ -n "$PIDS" ]; then
    echo "잔여 프로세스 정리: $PIDS"
    echo "$PIDS" | xargs kill -TERM 2>/dev/null || true
fi

echo "STOPPED"
