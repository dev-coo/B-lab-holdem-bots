#!/usr/bin/env bash
# junho 홀덤 봇 실행 스크립트 (uv 없이 pip + PYTHONPATH 로 독립 실행)
#
# 원본은 uv workspace 였음. 여기서는 5개 패키지 src 를 PYTHONPATH 에 얹어
# 그대로 `python -m holdem_main_bot` 을 띄운다. 봇 설정은 원래 각 봇 폴더의
# `.env` 로 주입했지만, .env 에는 대회 토큰이 들어 있어 커밋하지 않았다.
# 여기서는 인자/환경변수로 대신 넣는다 (pydantic Settings 가 OS 환경변수를 읽음).
#
# 사용법:
#   bash run.sh <WS_URL> <API_TOKEN> <BOT_NAME> [-- 추가옵션]
#   예) bash run.sh ws://snn.it.kr:5051/ws "발급받은_토큰" "쫄보감별계산기"
#
#   봇 종류 바꾸기 (기본 main):
#   BOT=aggressive bash run.sh ws://... TOKEN NAME     # aggressive/gto-lean/experimental 스텁
#
#   .env 파일을 직접 쓰고 싶으면:
#   bash run.sh --env-file packages/main_bot/.env
#
#   디버그 이벤트 덤프(.debug/room_*.jsonl) + 대시보드:
#   VIZ_ENABLED=true bash run.sh ws://... TOKEN NAME -- --debug
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 5개 패키지 + tools 의 src 를 import 경로에 얹는다.
export PYTHONPATH="\
$DIR/packages/core/src:\
$DIR/packages/main_bot/src:\
$DIR/packages/bot-aggressive/src:\
$DIR/packages/bot-gto-lean/src:\
$DIR/packages/bot-experimental/src:\
$DIR/tools/src${PYTHONPATH:+:$PYTHONPATH}"

# 어떤 봇을 띄울지 (기본: main = 대회 주력 BalancedStrategy).
case "${BOT:-main}" in
  main)          MODULE=holdem_main_bot ;;
  aggressive)    MODULE=holdem_bot_aggressive ;;
  gto-lean|gto)  MODULE=holdem_bot_gto_lean ;;
  experimental)  MODULE=holdem_bot_experimental ;;
  *) echo "unknown BOT=$BOT (main|aggressive|gto-lean|experimental)"; exit 2 ;;
esac

# 대시보드는 기본 off (streamlit 없이도 봇만 돌아가게). 켜려면 VIZ_ENABLED=true.
export VIZ_ENABLED="${VIZ_ENABLED:-false}"

# 위치 인자 3개(WS_URL, TOKEN, NAME)를 환경변수로 승격. '--' 나 '-' 로 시작하면 옵션으로 넘김.
PASSTHRU=()
if [[ "${1:-}" && "${1:-}" != -* ]]; then export SERVER_WS_URL="$1"; shift; fi
if [[ "${1:-}" && "${1:-}" != -* ]]; then export BOT_API_TOKEN="$1"; shift; fi
if [[ "${1:-}" && "${1:-}" != -* ]]; then export BOT_NAME="$1"; shift; fi
# 남은 인자(예: --debug --port 4000 --env-file ...)는 그대로 봇 CLI 로 전달.
[[ "${1:-}" == "--" ]] && shift
PASSTHRU=("$@")

PY="${PYTHON:-python3}"
echo "[run.sh] BOT=${BOT:-main} MODULE=$MODULE  WS=${SERVER_WS_URL:-<from .env/default>}  NAME=${BOT_NAME:-<default>}"
exec "$PY" -m "$MODULE" "${PASSTHRU[@]}"
