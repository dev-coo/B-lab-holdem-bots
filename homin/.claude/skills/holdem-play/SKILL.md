---
name: holdem-play
description: 홀덤 봇을 실서버 게임에 참여시키는 원스톱 워크플로우. 환경 점검 → 대시보드 안내 → 백그라운드 기동 → 상태 확인 → 이벤트 모니터링까지 자동화.
---

# holdem-play

홀덤 봇 (holdem-agent) 을 실서버 게임에 참여시킨다.

## 인자 해석

사용자 명령에서 아래 플래그를 확인:
- `safe` 또는 기본값 → Nash chart + pot-odds 만 사용 (가장 안정).
- `ev` 또는 `ev-tree` → D6 EV tree postflop 활성화 (`--ev-tree`).
- `full` 또는 `llm` → EV tree + LLM coordinator (`--full`).

## 실행 절차

1. **사전 점검** — `scripts/bot-check.sh` 실행.
   - `.env` 존재·값 확인, WS URL 의 TCP reachability, WS auth_ok 10초 smoke.
   - 실패 시 원인 진단 후 사용자에게 보고. 진행 중단.
2. **대시보드 안내** — `.env` 의 `HOLDEM_WS_URL` 에서 호스트 부분을 추출해 `http://<host>/` 대시보드 URL 을 사용자에게 제시. "실행" 버튼을 눌러 deploy 하라고 안내.
3. **사용자 확인 대기** — 사용자가 "실행됨" / "눌렀다" 같은 응답을 할 때까지 다음 단계로 넘어가지 말 것.
4. **기동** — 플래그에 따라 `scripts/bot-start.sh [--ev-tree] [--coordinator]` 실행. PID 파일과 세션 로그 경로를 확인하고 사용자에게 보고.
5. **Monitor 배치** — `Monitor` 툴로 최신 세션 로그에 tail -F + 선택적 grep 을 걸어 이벤트 스트림 수신. 필터:
   - 기본: `"(auth_|waiting_room|→|unparseable|Exception|session ended|auth_fail|allin amount)"`.
6. **첫 5초 상태 보고** — `scripts/bot-status.sh` 결과를 사용자에게 요약. profile DB 핸드 수, PID, 최근 10줄 로그.

## 오류 대응

- **TCP 연결 실패**: 서버 주소·운영 상태 의심. `.env` URL 재확인 안내 후 중단.
- **auth_fail**: 토큰 만료/오타 가능. 대시보드에서 토큰 복사 후 `.env` 갱신 안내.
- **기동 직후 프로세스 죽음**: 세션 로그 마지막 30줄을 사용자에게 보여주고 원인 진단.
- **unparseable 다발**: BOT_GUIDE 와 다른 신규 이벤트 타입. `src/holdem/transport/protocol.py` 에 스키마 추가 필요. 사용자에게 payload 보여주고 수정 방향 제시.

## 종료

사용자가 "중지" / "stop" 요청 시 `scripts/bot-stop.sh` 실행. Monitor 는 `TaskStop` 으로 정리.

## 메모

- 봇은 재접속 루프 내장 → deploy 유지되면 24/7 가동.
- `profile-db` 는 기본 `data/profiles.db` 로 warm-start 자동. 신규 세션은 기존 학습 누적.
- EV tree 경로는 `DirichletResponse` 기본 (1,1,1) 이 보수적이지 않으므로, 관측이 적은 초기에는 `safe` 모드 권장.
