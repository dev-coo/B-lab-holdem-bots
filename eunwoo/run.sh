#!/bin/bash
# ============================================================
# eunwoo 봇 실행 스크립트 (단일 봇 — 토너먼트 R3 출전 봇)
# 사용법:
#   bash run.sh <SERVER_WS_URL> <API_TOKEN> <BOT_NAME> [--bot gto|hybrid] [--reset]
#
# 예:
#   bash run.sh ws://localhost:5051/ws "MY_API_TOKEN" "쪼랩이"
#   bash run.sh ws://localhost:5051/ws "MY_API_TOKEN" "쪼랩이" --bot hybrid --reset
#
# 기본 봇: hybrid (R3 출전 봇 = HybridBot — Phase A=Gto / Phase B=Wooz brain).
# --bot gto 로 R2 출전 봇(쪼랩이 = GtoBot v2)을 단독 가동할 수도 있음.
# --reset: 누적 트래커(data/session_tracker.json) 초기화. 대회 시작 직전 1회만 권장.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "$1" || -z "$2" || -z "$3" ]]; then
  echo "사용법: bash run.sh <SERVER_WS_URL> <API_TOKEN> <BOT_NAME> [--bot gto|hybrid] [--reset]"
  exit 1
fi

SERVER="$1"
TOKEN="$2"
NAME="$3"
shift 3

BOT="hybrid"
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bot)
      BOT="$2"; shift 2 ;;
    --reset)
      EXTRA+=("--reset"); shift ;;
    *)
      echo "알 수 없는 옵션: $1"; exit 1 ;;
  esac
done

case "$BOT" in
  gto)    SCRIPT="bots/gto.py" ;;
  hybrid) SCRIPT="bots/hybrid_bot.py" ;;
  *)      echo "지원 봇: gto | hybrid"; exit 1 ;;
esac

# venv 가 있으면 우선, 없으면 시스템 python3
if [[ -x "$SCRIPT_DIR/.venv/bin/python3" ]]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python3"
else
  PYTHON="python3"
fi

export PYTHONPATH="$SCRIPT_DIR"

echo "=== eunwoo 봇 시작 ==="
echo "  봇      : $BOT  ($SCRIPT)"
echo "  서버    : $SERVER"
echo "  봇이름  : $NAME"
echo "  옵션    : ${EXTRA[*]:-없음}"
echo "  python  : $PYTHON"
echo "==========================="

exec "$PYTHON" "$SCRIPT_DIR/$SCRIPT" "$SERVER" "$TOKEN" "$NAME" "${EXTRA[@]}"
