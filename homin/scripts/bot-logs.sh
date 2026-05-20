#!/usr/bin/env bash
# 최신 세션 로그 tail. Ctrl+C 로 종료.
# Usage: scripts/bot-logs.sh           # 전체 스트림
#        scripts/bot-logs.sh errors    # 이상 이벤트만
#        scripts/bot-logs.sh actions   # 내 결정만

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/data/logs/cli"

LATEST=$(ls -t "$LOG_DIR"/session_*.log 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    echo "로그 없음. 먼저 scripts/bot-start.sh 실행"
    exit 1
fi
echo "tail -F $LATEST"
echo "---"

MODE="${1:-all}"
case "$MODE" in
    errors)
        tail -n 0 -F "$LATEST" | grep --line-buffered -E "(unparseable|Exception|ERROR|CRITICAL|auth_fail|session ended|Traceback)"
        ;;
    actions)
        tail -n 0 -F "$LATEST" | grep --line-buffered -E "→"
        ;;
    all|*)
        tail -n 0 -F "$LATEST"
        ;;
esac
