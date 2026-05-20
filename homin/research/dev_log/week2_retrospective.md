# Week 2 Retrospective — D1 (Transport + Push/Fold Bot)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19 (Day 10)
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: `research/week2_plan.md`, plan K.4 D1
- **BOT_GUIDE refs**: §1.1, §2, §5, §6, §8, §11

---

## 1. 목표 vs 결과

| 목표 | 결과 | 비고 |
|---|---|---|
| WS 연결 + `auth_bot`/`auth_ok` | ✅ | `WsClient` + reconnect_loop |
| `ping`/`pong` 20s/40s 준수 | ✅ | `WsClient._event_loop` 내부 즉시 응답 |
| `hand_start`, `action_request`, `phase_change`, `hand_result` 이벤트 파싱 | ✅ | pydantic 모델 전체 필드 |
| 재접속 snapshot 복원 | ✅ | `GameState._on_joined_room` (B3 권고 반영) |
| M ≤ 8 Push/Fold 차트 lookup | ✅ | 4 M-bucket × EP/MP/LP/BLIND |
| 8 < M ≤ 15 hybrid open | ✅ | min-raise open + facing raise 시 call_vs_jam |
| M > 15 구간 fold 수렴 | ✅ | D2 에서 확장 |
| JSONL 이벤트 로그 | ✅ | `data/logs/games/{date}_room{N}.jsonl` |
| 실서버 1 게임 완주 | ⏳ | **deploy API 블로커** — `research/deploy_api_notes.md` 참조 |

**최종 테스트**: `uv run pytest tests/` → **89 passed, 0 failed**.

---

## 2. 산출물

### 코드
```
src/holdem/
├── cli.py                       # argparse + asyncio.run + session loop
├── math/m_ratio.py              # M = stack/(sb+bb)
├── transport/
│   ├── protocol.py              # 15 pydantic event models + Action
│   ├── ws_client.py             # WsClient + reconnect_loop
│   └── config.py                # .env 로더, BotConfig
├── state/game_state.py          # HandState + GameState (멀티룸 dict)
├── decide/
│   ├── mode_selector.py         # M → push_fold/hybrid/mid/deep
│   ├── hand_notation.py         # 169 hand code + range 파서
│   ├── push_fold_chart.py       # YAML bucket lookup
│   ├── position.py              # seat × n_players → EP/MP/LP/BLIND
│   └── policy.py                # decide(req, bot_name) → Action (최상위)
├── persist/event_log.py         # JSONL 로거
└── meta/llm_client.py           # (Day 7 LLM 트랙)
```

### 테스트 (89)
- `test_protocol.py` (21) — pydantic round-trip
- `test_ws_client.py` (5) — auth/ping/pong/action/reconnect
- `test_llm_client.py` (8) — OpenAI-compat 프록시 클라이언트
- `test_m_ratio.py` (5)
- `test_mode_selector.py` (5)
- `test_game_state.py` (9) — 재접속 snapshot 포함
- `test_hand_notation.py` (14)
- `test_push_fold_chart.py` (9)
- `test_policy.py` (11)
- `test_e2e_smoke.py` (2) — 로컬 ws mock 한 핸드 완주

### 설정
- `configs/nash_charts/simple_push_9max.yaml` — Week 2 임시 차트. R5 (주 7) 교체 예정

---

## 3. M1 마일스톤 — O1 관측 체크리스트 (실서버)

**운영자 deploy 후** 최초 1 게임에서 다음을 확인:

- [ ] WS 연결 성공 → auth_ok 로그.
- [ ] `hand_start` 이벤트 수신.
- [ ] 20초 간격 ping → 즉시 pong 응답 (서버 종료 없음).
- [ ] `action_request` 수신 시 < 3s 내 응답 (30s 하드 제약 대비 10x 여유).
- [ ] 자동 폴드 0회 (모든 요청에 실제 action 응답).
- [ ] 한 게임 완주 (`game_end` 이벤트 수신 또는 eliminated).
- [ ] `data/logs/games/*.jsonl` 생성 및 파싱 가능.
- [ ] M ≤ 8 에서 AA 가 실제로 allin 으로 전송됐는지 로그 검증.
- [ ] M > 15 핸드가 fold 비율 100% (D2 이전 의도된 동작).

**예상 성적**: M > 15 전부 fold 이므로 **첫 게임은 블라인드로 소모 후 조기 탈락**. 경쟁력 측정은 D2 완료 후.

---

## 4. 주요 결정·이슈

### 4.1 LLM 트랙 Pivot (Day 7)
- Claude Agent SDK → OpenAI-호환 로컬 프록시 (`http://localhost:8317/v1`).
- 이유: 봇 런타임에서 tool-use/hooks/sessions 모두 비활성 대상 → chat completions 로 충분.
- 산출: `src/holdem/meta/llm_client.py` + 8개 단위 테스트, `configs/llm.yaml` v0.2.
- 토큰 발급 대기 → env 주입 시 `LLMClient.complete()` 즉시 동작.

### 4.2 facing-raise 판정 수정 (Day 10)
- 초기 구현: `to_call > 0` 만으로 "facing raise" 판정 → BB 포스트 상황에서 AA jam 실패.
- 수정: action_history 기반 voluntary raise/allin + `to_call > bb` 조건 추가.
- 추가 회귀 테스트: E2E smoke 에서 확인.

### 4.3 Deploy API 블로커 (B4)
- BOT_GUIDE §2.2 의 `POST /bots/{id}/deploy` 인증 방식 미확정.
- `research/deploy_api_notes.md` 에 7개 문의 항목 + 수동 우회 절차.
- M1 실서버 검증은 운영자 답신 전까지 대시보드 수동 배포로 진행.

---

## 5. 다음 주 (Week 3, D2 Math + Equity) 준비

### 선행 작업
- [ ] `treys` 라이브러리 core API 재확인 (이미 pyproject 에 포함).
- [ ] 169 preflop hand equity LUT 생성 스크립트 초안.
- [ ] `configs/open_ranges/rfi_9max.yaml` 초안 (chart 값 수집).
- [ ] Week 2 실서버 로그에서 M > 15 fold 비율 100% 재확인.

### 기대 아웃풋
- `src/holdem/math/odds.py` — pot_odds, MDF, alpha, break-even equity.
- `src/holdem/estimate/equity.py` — preflop LUT + postflop MC (< 80ms).
- `src/holdem/decide/opening_chart.py` — hybrid/mid/deep 모드에서 opening range 활용.
- M > 15 구간이 fold 가 아닌 실제 의사결정으로 전환.

### 열린 질문
- 9max 기준 opening range 를 문헌값으로 시작 (RFI 3bb, 포지션별 top X%), R3 priors 와 어떻게 결합?
- treys 의 7-card evaluator 가 3-8way MC 에 충분히 빠른지 (목표: turn/river MC < 50ms).

---

## 6. 파일 변경 요약 (주 2 전체)

| 카테고리 | 파일 수 | LoC (근사) |
|---|---:|---:|
| 소스 | 13 (`src/holdem/**/*.py`) | ~950 |
| 테스트 | 10 | ~850 |
| 설정 | 10 yaml | ~300 |
| 문서 | 3 (`week2_plan.md`, `deploy_api_notes.md`, `week2_retrospective.md`) | ~400 |

**테스트 커버리지**: 핵심 순수 함수 100%, ws 비동기 경로 5 케이스 mock, E2E 1 케이스 (한 핸드 완주).

---

## Changelog

- 2026-04-19 (v0.1): Day 10 작성. D1 완료 요약, O1 체크리스트, Week 3 준비 사항.
