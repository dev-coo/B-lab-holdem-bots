---
name: holdem-diagnose
description: 봇이 예상대로 동작하지 않을 때 호출. 로그·DB·프로세스 상태를 종합 분석해 원인을 진단하고, 가장 가능성 높은 다음 액션을 제시.
---

# holdem-diagnose

## 진단 순서

1. **프로세스 생존** — `ps aux | grep holdem.cli | grep -v grep` 결과. 없으면 사망.
2. **세션 로그** — 최신 `data/logs/cli/session_*.log` 마지막 100 줄. 패턴 분석:
   - `auth_fail` → 토큰 오류. `.env` 의 `HOLDEM_API_TOKEN` 확인.
   - `TimeoutError` 반복 → WS 연결 불안정. 네트워크·서버 상태 확인.
   - `unparseable event` → 서버가 우리 스키마에 없는 이벤트 전송. payload 출력 후 `src/holdem/transport/protocol.py` 에 새 타입 추가 필요.
   - `equity calc failed` → `treys` 평가 실패. `your_cards` 포맷 확인.
   - `no active client` → 이벤트 수신 중 재연결 race. 일반적으로 자동 복구됨.
3. **이벤트 로그** — `data/logs/games/` 최신 JSONL. 수신 이벤트 종류 분포.
4. **DB 상태** — `data/profiles.db` 프로필·반응 테이블 크기, 락 여부.
5. **결정 패턴** — 최근 50 결정의 action 분포:
   - 100% fold → chart/opening 범위 설정 이슈 또는 너무 보수적.
   - 100% allin → push/fold 구간에 머무른 것. 정상일 수 있음.
   - raise 가 min_raise 미달 → policy.py 의 amount 계산 버그.

## 대응 맵

| 증상 | 원인 후보 | 대응 |
|---|---|---|
| "미연결" 유지 | WS auth 실패 / 대시보드 deploy 안 됨 | `scripts/bot-check.sh` + 대시보드 실행 |
| `hand_start` 만 파싱 실패 | 탈락 후 관전 상태 | `HandStart` 필드 Optional 확인 (이미 수정됨) |
| 프로필 DB 미업데이트 | `on_hand_result` 경로 차단 | CLI 에서 `HandResult` 핸들러 확인 |
| LLM 호출 0 회 | trigger 비활성 / budget 초과 | `configs/llm.yaml` 의 gate 와 카운터 확인 |
| 결정 지연 > 3 s | equity MC 샘플 과다 | `DecideDeps.equity_samples` 감소 |

## 종합 보고

사용자에게는 (1) 관측된 이상, (2) 가장 가능성 높은 원인, (3) 권장 액션 3 줄로 요약.
필요한 경우 자동 수정 제안을 하되, 파일 수정은 확인 후 실행.
