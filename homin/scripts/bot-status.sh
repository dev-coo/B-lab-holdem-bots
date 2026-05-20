#!/usr/bin/env bash
# 봇 프로세스·DB·최근 활동 요약.
# Usage: scripts/bot-status.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PID_FILE="$ROOT/data/bot.pid"
DB="$ROOT/data/profiles.db"
LOG_DIR="$ROOT/data/logs/cli"

echo "=== process ==="
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        UPTIME=$(ps -p "$PID" -o etime= 2>/dev/null | xargs)
        echo "RUNNING pid=$PID uptime=$UPTIME"
    else
        echo "STALE PID 파일 (PID=$PID 사망). rm data/bot.pid 권장"
    fi
else
    echo "STOPPED (PID 파일 없음)"
fi

echo ""
echo "=== profile DB ($DB) ==="
if [ -f "$DB" ]; then
    uv run python -c "
import sqlite3
conn = sqlite3.connect('$DB')
n_prof = conn.execute('SELECT COUNT(*) FROM opponent_profile').fetchone()[0]
has_resp = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='opponent_response'\").fetchone()
n_resp = conn.execute('SELECT COUNT(*) FROM opponent_response').fetchone()[0] if has_resp else 0
rows = conn.execute('SELECT name, hands_seen FROM opponent_profile ORDER BY hands_seen DESC LIMIT 10').fetchall()
print(f'profiles={n_prof}, responses={n_resp}')
for n, hs in rows:
    print(f'  {n:30s} hands={int(hs)}')
"
else
    echo "DB 없음"
fi

echo ""
echo "=== dashboard ==="
DASH_PID_FILE="$ROOT/data/dashboard.pid"
if [ -f "$DASH_PID_FILE" ]; then
    DPID=$(cat "$DASH_PID_FILE")
    if kill -0 "$DPID" 2>/dev/null; then
        echo "RUNNING pid=$DPID → http://127.0.0.1:${HOLDEM_DASHBOARD_PORT:-8765}/"
    else
        echo "STALE dashboard PID ($DPID). rm data/dashboard.pid"
    fi
else
    echo "STOPPED (scripts/bot-dashboard.sh --bg 로 기동)"
fi

echo ""
echo "=== 최근 세션 로그 ==="
LATEST=$(ls -t "$LOG_DIR"/session_*.log 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo "파일: $LATEST"
    echo "마지막 10줄:"
    tail -10 "$LATEST" | sed 's/^/  /'
else
    echo "로그 없음"
fi
