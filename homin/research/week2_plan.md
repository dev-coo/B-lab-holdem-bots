# Week 2 Task Breakdown — D1 Transport + Push/Fold Bot

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: plan Section K.4 D1, K.9 week 2
- **BOT_GUIDE refs**: §1.1, §2.2, §2.3, §5.2, §5.3, §5.4, §5.5, §5.6, §6.1, §6.2, §6.3, §7, §8, §9, §11

---

## 1. 목표

주 2 말 마일스톤 **M1: Push/Fold 봇 서버 배포**. 즉 다음을 동작시킨다:

1. WebSocket 으로 서버 접속 → `auth_bot` 인증 성공.
2. `ping`/`pong` 하트비트 20/40s 준수.
3. `hand_start` → `action_request` 이벤트 수신 시 의사결정 후 JSON 응답.
4. M ≤ 12 구간은 Push/Fold 차트 룩업 (R5 미완 → 간이 테이블).
5. M > 12 구간은 모두 fold (다음 주 D2 에서 확장).
6. 재접속 시 `joined_room.snapshot` 을 통해 room_id 복원.
7. 한 게임 완주 (= eliminated 또는 winner 까지) 가능.

**비목표 (D2 이후 범위)**: equity 계산, pot-odds call, multiway EV, class typing, 어떤 Bayesian 연산.

---

## 2. 코드 구조 (초기)

```
src/holdem/
├── __init__.py
├── cli.py                         # uv run python -m holdem.cli ...
├── transport/
│   ├── __init__.py
│   ├── ws_client.py               # WS 연결, ping/pong, 재접속
│   └── protocol.py                # pydantic 이벤트 모델
├── state/
│   ├── __init__.py
│   └── game_state.py              # 한 room_id 의 휘발성 상태 (영속 X)
├── decide/
│   ├── __init__.py
│   ├── mode_selector.py           # M → mode
│   └── push_fold_chart.py         # 간이 차트 + JSON 응답 생성
└── math/
    ├── __init__.py
    └── m_ratio.py                 # M = stack / (sb + bb)

configs/nash_charts/
├── simple_push_9max.yaml          # Week 2 임시판 (R5 에서 교체)
└── simple_call_vs_jam_9max.yaml
```

---

## 3. 작업 단위 (Daily, 5 Days × ~7h)

### Day 6 (월) — Transport 기반 + pyproject 확장 [7h]

- [ ] `pyproject.toml` 에 `websockets>=12` 는 이미 존재. `pydantic>=2` 확인.
- [ ] `src/holdem/transport/protocol.py`
  - BOT_GUIDE §5 의 모든 이벤트 타입을 pydantic `BaseModel` 로 정의:
    `AuthBot, AuthOk, AuthFail, Ping, Pong, JoinedRoom, HandStart, PhaseChange, ActionRequest, ActionPerformed, HandResult, GameEnd, ServerShutdown`.
  - `Action` 액션 outgoing 모델: `fold/check/call/raise/allin`.
  - `action_history` 엔트리: `{name, action, amount}`.
- [ ] 각 모델 골든 케이스 unit test (`tests/test_protocol.py`).

**Exit**: `pytest tests/test_protocol.py` 통과. 샘플 JSON 역직렬화 확인.

### Day 7 (화) — WS 클라이언트 + 인증 [7h]

- [ ] `src/holdem/transport/ws_client.py`:
  - async context manager 로 WS 연결.
  - 연결 직후 `auth_bot` 전송 → `auth_ok` 대기 (timeout 10s).
  - `ping` 수신 시 즉시 `pong` 응답 (§2.3).
  - 메시지 수신 루프 + async queue 로 dispatcher 에 전달.
  - 종료 사유 로깅: `auth_fail`, `server_shutdown`, `close`.
- [ ] `.env` 로딩: `HOLDEM_WS_URL`, `HOLDEM_API_TOKEN`, `HOLDEM_BOT_NAME`.
- [ ] **Deploy API 확인 블로커 (B4)**: 운영자 문의 결과를 `research/deploy_api_notes.md` 에 기록. 미해결 시 수동 대시보드 배포로 우회.
- [ ] Dry-run 스모크: `http://snn.it.kr:5051` 로 접속 → 인증 → ping-pong 5분 지속 확인.

**Exit**: `auth_ok` 로그 1건, 5분간 disconnect 없음.

### Day 8 (수) — Game State + Dispatcher [7h]

- [ ] `src/holdem/state/game_state.py`:
  - `GameState` (per room_id): my_seat, my_stack, community_cards, phase, pot, to_call, min_raise, players[], action_history[].
  - 이벤트 핸들러:
    - `hand_start` → 상태 초기화 (my_cards, 좌석, 블라인드).
    - `phase_change` → community_cards 갱신 (§5.5). **이벤트 A1 권고 사항**.
    - `action_performed` → action_history 누적, pot 갱신.
    - `hand_result` → 상태 마감, 다음 핸드 대기.
    - `joined_room` → snapshot 복원 (재접속 케이스).
  - 멀티룸 분리: `dict[room_id → GameState]`.
- [ ] `src/holdem/math/m_ratio.py`: `M(stack, sb, bb) = stack / (sb + bb)` (§11).
- [ ] `src/holdem/decide/mode_selector.py`: M → `push_fold / hybrid / mid / deep` (blind_schedule.yaml 의 `mode_thresholds` 참조).

**Exit**: `action_request` 수신 시 현재 상태로부터 올바른 M 값 계산. 로컬 재접속 시뮬레이션 테스트 통과.

### Day 9 (목) — Push/Fold Chart + Decide Loop [7h]

- [ ] 간이 차트 YAML 작성 (R5 미완 → 임시값):
  - `configs/nash_charts/simple_push_9max.yaml`: M 구간 × 포지션 별 push 범위 (예: M=8 BTN → {AA, KK, ..., 22, A2s+, A9o+, K9s+, KTo+, QTs+, JTs, T9s}).
  - `configs/nash_charts/simple_call_vs_jam_9max.yaml`: call 범위 (더 타이트).
  - **근거**: 문헌의 개략 Nash (chip-EV 근사). R5 에서 정식 차트로 교체.
- [ ] `src/holdem/decide/push_fold_chart.py`:
  - 차트 로더 + hand_rank (`AA` / `AKs` / `72o` 형식).
  - lookup: (mode, position_class, M_bucket, hand) → action.
  - M ≤ 8: 순수 push_fold. preflop 만 의사결정.
  - 8 < M ≤ 12: hybrid → open = min raise, vs 3bet = jam 차트.
  - 반환: BOT_GUIDE §6.1 의 허용 액션으로 매핑. raise 는 §6.2 의 "총 베팅액" 의미로 계산.
- [ ] Decide loop:
  - `action_request` 수신 → M 계산 → mode → 차트 lookup → action JSON 전송.
  - timeout 예산: 차트 lookup 은 < 50ms. 30s 하드 제약(§6.3) 여유 충분.
  - unknown mode (M > 12) → fold (D2 에서 보강).

**Exit**: 자기 시뮬레이터에서 "M=6, AA" → push, "M=6, 72o" → fold 확인. `tests/test_push_fold_chart.py` 통과.

### Day 10 (금) — End-to-End + 배포 + 로그 [7h]

- [ ] CLI: `uv run python -m holdem.cli --url ... --token ... --name ...`
- [ ] JSON Lines 로그: `data/logs/games/{date}_{room_id}.jsonl`. 각 이벤트 1 줄 기록.
- [ ] 실서버 스모크:
  - 운영자 조율 후 1 테스트 방 배정.
  - 한 게임 완주 (탈락까지) 가능한지 관측.
  - `action_performed.me` 로 봇이 실제 어떤 액션을 했는지 기록.
- [ ] O1 관측 체크리스트:
  - [ ] WS 연결 성공.
  - [ ] `hand_start` 이벤트 수신.
  - [ ] 자동 fold 없이 actual response 비율 100%.
  - [ ] 1게임 완주.
  - [ ] 로그 파일 생성 및 크래시 없음.
- [ ] Catchup 버퍼 (7h 중 미사용분).

**Exit**: 실서버 1 게임 완주 + 로그 파일 확보. M1 마일스톤 달성.

---

## 4. 주말 작업 (5h)

- [ ] 1 게임 로그 리뷰 → 잘못된 판정 사례 목록 (D2 우선순위화).
- [ ] `research/dev_log/week2_retrospective.md` 초안 (O1 관측 기록).
- [ ] D2 (Week 3) 준비: treys 설치 확인, 프리플롭 LUT 초안.

---

## 5. 테스트 전략

### 5.1 Unit

- `tests/test_protocol.py` — 모든 pydantic 이벤트 모델 round-trip.
- `tests/test_m_ratio.py` — Lv1 (300 스택, 1/2 blind) = 100, Lv10 = 2, Lv20 = 0.03 등 경계.
- `tests/test_mode_selector.py` — M=30 → deep, M=12 → mid, M=8 → hybrid, M=5 → push_fold.
- `tests/test_push_fold_chart.py` — AA 항상 push, 72o 항상 fold, 경계 핸드 동작.
- `tests/test_game_state.py` — phase_change 시 community_cards 업데이트, action_performed 시 pot/action_history 갱신.

### 5.2 Integration

- `tests/test_ws_mock.py` — asyncio WS mock server 로 인증 + ping/pong + 한 핸드 시뮬레이션.

### 5.3 E2E

- 실서버 1 게임 완주. 자동화된 assertion 은 없음 (O 트랙에서 수동 검수).

---

## 6. 리스크 및 대응

| # | 리스크 | 확률 | 대응 |
|---|---|---|---|
| W2-R1 | Deploy API 인증 방식 미확정 | **중** | Day 7 에 운영자 문의. 미해결 시 수동 대시보드 배포로 진행 (자동화는 D2 이후) |
| W2-R2 | 간이 Push/Fold 차트가 과도 tight/loose | 중 | 문헌값 사용. R5 에서 ICMIZER/HRC 공개 Nash 값으로 교체 |
| W2-R3 | M > 12 구간 전부 fold 하면 첫 게임 조기 탈락 | **높음** | 수용. D2 에서 open chart 추가하여 방어. Week 2 는 프로토콜 동작만 검증 목표 |
| W2-R4 | 재접속 시 hand_result 누락 (B3) | 낮음 | 현재는 무시. O 트랙에서 관측 후 Week 5+ 에 완화책 |
| W2-R5 | 서버 WS 메시지 스키마가 BOT_GUIDE 와 다름 | **치명** | Day 7 첫 접속 시 raw 로그 pydantic 실패를 모니터. 차이 발견 즉시 protocol.py 수정 |
| W2-R6 | 30s timeout 하드 제약 위반 | 낮음 | 전 경로 로깅. 최악의 경우도 < 200ms |

---

## 7. 의존성 (다른 트랙)

- **R 트랙**: 이번 주는 의존 없음. Week 2 의 차트는 임시값.
- **O 트랙**: Day 10 배포 직후 O1 (첫 배포 관측) 시작.
- **Deploy API 인증**: 가장 큰 블로커 (B4). Day 7 에 반드시 확인.

---

## 8. Exit Criteria (M1)

- [x] 모든 Day 의 Exit criteria 충족.
- [ ] 실서버에서 한 게임 완주.
- [ ] `data/logs/games/*.jsonl` 로그 ≥ 1 파일.
- [ ] 자동 폴드 비율 = 0 (30s timeout 위반 없음).
- [ ] 봇이 보낸 action 의 `amount` 가 `min_raise` 이상 (§6.2) 준수 — raise 선택 시.

---

## 9. 파일 구조 최종 (주 2 말)

```
holdem-agent/
├── pyproject.toml                 # (no change)
├── configs/
│   ├── blind_schedule.yaml
│   ├── position_class_map.yaml
│   ├── priors.yaml
│   ├── class_priors.yaml
│   ├── sizing.yaml
│   ├── conservatism_schedule.yaml
│   ├── bluff_labels.yaml
│   ├── transfer_coefficients.yaml
│   ├── llm.yaml
│   └── nash_charts/
│       ├── simple_push_9max.yaml           # NEW (Week 2 임시)
│       └── simple_call_vs_jam_9max.yaml    # NEW
├── src/holdem/                             # NEW 전체
│   ├── __init__.py
│   ├── cli.py
│   ├── transport/ {ws_client, protocol}
│   ├── state/ {game_state}
│   ├── decide/ {mode_selector, push_fold_chart}
│   └── math/ {m_ratio}
├── tests/                                  # NEW 전체
│   ├── test_protocol.py
│   ├── test_m_ratio.py
│   ├── test_mode_selector.py
│   ├── test_push_fold_chart.py
│   ├── test_game_state.py
│   └── test_ws_mock.py
└── data/logs/games/                        # NEW (runtime)
```

---

## 10. Week 3 로 인계

주 2 종료 시 D2 (Equity + preflop open chart) 의 사전 준비:
- treys 설치 및 core API 확인.
- 169 preflop hand LUT 생성 방식 선택 (hand_rank_percentile 테이블).
- Open range YAML (`configs/open_ranges/rfi_9max.yaml`) 초안.
- Week 2 로그에서 관찰된 fold-all 패턴의 상대 반응 분석.

---

## Changelog

- 2026-04-19 (v0.1): Day 5 작성. D1 5일 분해, 테스트 계획, 리스크 매트릭스, 의존성 정리.
