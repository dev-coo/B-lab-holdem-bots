#!/usr/bin/env bash
# 서버 연결·인증 사전 점검. 실제 게임 참여 전에 실행.
# 주의: 서버는 bot_name 당 단일 WS 연결만 허용. 봇이 이미 실행 중이면 auth smoke 는 skip.
# Usage: scripts/bot-check.sh [--force]

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FORCE=0
for arg in "$@"; do
    [ "$arg" = "--force" ] && FORCE=1
done

if [ ! -f .env ]; then
    echo "FAIL: .env 없음. .env.example 복사 후 토큰/URL 기입 필요"
    exit 1
fi

WS_URL=$(grep -E '^HOLDEM_WS_URL=' .env | cut -d= -f2- | tr -d '"')
TOKEN_SET=$(grep -cE '^HOLDEM_API_TOKEN=.+' .env || true)
BOT_NAME=$(grep -E '^HOLDEM_BOT_NAME=' .env | cut -d= -f2- | tr -d '"')
LLM_KEY_SET=$(grep -cE '^HOLDEM_LLM_API_KEY=.+' .env || true)

echo "=== .env ==="
echo "WS URL:   $WS_URL"
echo "Bot:      $BOT_NAME"
echo "Token:    $( [ "$TOKEN_SET" = "1" ] && echo set || echo MISSING )"
echo "LLM key:  $( [ "$LLM_KEY_SET" = "1" ] && echo set || echo MISSING )"

HOST=$(echo "$WS_URL" | sed -E 's|ws://([^:/]+):.*|\1|')
PORT=$(echo "$WS_URL" | sed -E 's|ws://[^:]+:([0-9]+).*|\1|')
echo ""
echo "=== 네트워크 (host=$HOST port=$PORT) ==="
if nc -z -G 3 "$HOST" "$PORT" 2>/dev/null; then
    echo "TCP $HOST:$PORT OPEN"
else
    echo "FAIL: TCP $HOST:$PORT 도달 불가"
    exit 2
fi

echo ""
RUNNING=""
PID_FILE="$ROOT/data/bot.pid"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    RUNNING=$(cat "$PID_FILE")
fi
if [ -z "$RUNNING" ]; then
    # PID 파일 없어도 프로세스 탐색
    RUNNING=$(ps aux | grep -E "holdem\.cli" | grep -v grep | awk '{print $2}' | head -1)
fi

if [ -n "$RUNNING" ] && [ "$FORCE" -ne 1 ]; then
    echo "=== WS auth smoke — SKIP ==="
    echo "기존 봇 프로세스 PID=$RUNNING 탐지됨."
    echo "서버는 bot_name 당 단일 연결만 허용하므로 smoke 를 실행하면 기존 세션이 끊어짐."
    echo "강제로 실행하려면: scripts/bot-check.sh --force"
    echo ""
    echo "READY (기존 세션 유지)"
    exit 0
fi

echo "=== WS auth smoke (10s) ==="
uv run python -c "
import asyncio, sys
from holdem.transport.config import load_bot_config
from holdem.transport.ws_client import WsClient, BotConfig
from holdem.transport import protocol as p

_result = {'rc': 4, 'msg': 'no event'}

async def main():
    cfg = load_bot_config()
    stop = asyncio.Event()
    async def handler(event):
        if isinstance(event, p.AuthOk):
            _result['rc'] = 0
            _result['msg'] = f'AUTH_OK bot_name={event.bot_name} concurrent={event.concurrent_games}'
            stop.set()
        elif isinstance(event, p.AuthFail):
            _result['rc'] = 3
            _result['msg'] = f'AUTH_FAIL reason={event.reason}'
            stop.set()
    c = WsClient(BotConfig(ws_url=cfg.ws_url, api_token=cfg.api_token, bot_name=cfg.bot_name), handler)
    task = asyncio.create_task(c.run())
    try:
        await asyncio.wait_for(stop.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        _result['rc'] = 4
        _result['msg'] = 'TIMEOUT — auth_ok not received within 10s'
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

asyncio.run(main())
print(_result['msg'])
sys.exit(_result['rc'])
" 2>/dev/null
RC=$?
if [ "$RC" -eq 0 ]; then
    echo ""
    echo "READY — 대시보드에서 '실행' 누른 뒤 scripts/bot-start.sh 실행"
else
    echo "FAIL: auth smoke 실패 (rc=$RC)"
    exit $RC
fi
