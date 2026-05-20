#!/usr/bin/env bash
# 원스톱 게임 참여 스크립트.
# 1. bot-check: 환경·네트워크·auth 검증.
# 2. 사용자에게 대시보드 실행을 요청.
# 3. bot-start: 봇을 백그라운드로 기동.
# 4. 5초 후 상태 요약 출력.
# Usage:
#   scripts/bot-play.sh             # chart + pot-odds (안전)
#   scripts/bot-play.sh --ev-tree   # EV tree 경로
#   scripts/bot-play.sh --full      # EV tree + LLM coordinator

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FLAGS=()
MODE="chart"
for arg in "$@"; do
    case "$arg" in
        --ev-tree)     FLAGS+=(--ev-tree); MODE="ev-tree" ;;
        --coordinator) FLAGS+=(--coordinator); MODE="ev-tree+coord" ;;
        --full)        FLAGS+=(--ev-tree --coordinator); MODE="full" ;;
    esac
done

echo "=========================================="
echo " holdem-agent 게임 참여 ($MODE)"
echo "=========================================="
echo ""

echo "[1/4] 환경·네트워크·auth 점검"
if ! scripts/bot-check.sh; then
    echo ""
    echo "점검 실패 → 종료"
    exit 1
fi

echo ""
echo "[2/4] 대시보드에서 봇 '실행' 상태인지 확인"
BOT_NAME=$(grep -E '^HOLDEM_BOT_NAME=' .env | cut -d= -f2- | tr -d '"')
WS_URL=$(grep -E '^HOLDEM_WS_URL=' .env | cut -d= -f2- | tr -d '"')
DASH_URL=$(echo "$WS_URL" | sed -E 's|ws://([^/]+)/.*|http://\1/|')
echo ""
echo "  대시보드: $DASH_URL"
echo "  봇 이름:  $BOT_NAME"
echo ""
printf "대시보드에서 '실행' 버튼 눌렀으면 Enter (또는 Ctrl+C 로 중단): "
read -r _

echo ""
echo "[3/4] 봇 기동"
if ! scripts/bot-start.sh "${FLAGS[@]}"; then
    echo "기동 실패 → 종료"
    exit 2
fi

echo ""
echo "[4/4] 5초 후 상태 요약"
sleep 5
scripts/bot-status.sh

echo ""
echo "=========================================="
echo " 실시간 이벤트: scripts/bot-logs.sh actions"
echo " 이상 감지:     scripts/bot-logs.sh errors"
echo " 정지:          scripts/bot-stop.sh"
echo "=========================================="
