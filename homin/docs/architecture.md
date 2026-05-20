# Holdem Agent — 현 동작 구조

> **문서 목적**: 현재 코드베이스(2026-04-22 기준)의 실제 동작을 기술. 계획 문서(`~/.claude/plans/delegated-doodling-sphinx-md-async-hinton.md`) 의 전체 설계가 아니라 **지금 돌아가는 부분**만 다룬다.
>
> **대상**: 새로 합류하거나 맥락을 잃은 개발자가 "이 봇이 지금 무엇을 하는가" 를 30분 안에 파악할 수 있도록.

---

## 1. 한 줄 요약

Python async WebSocket 봇이 Texas Hold'em 토너먼트 서버에 접속해, **M 값 기반 모드 스위치** 로 Push/Fold 차트 · pot-odds · EV tree 를 구간별로 사용하고, 매 핸드 종료 시 상대 프로필(Beta+Dirichlet)을 SQLite 에 영속시킨다. 브라우저 대시보드(stdlib HTTP)로 상태를 실시간 감시한다.

---

## 2. 레이어 구성

```mermaid
flowchart TB
  subgraph L1["L1 Transport (transport/)"]
    WS["ws_client<br/>auth_bot → subscribe<br/>ping/pong · 재접속"]
    PROTO["protocol.py<br/>Pydantic tagged union<br/>(IncomingEvent / Action)"]
  end

  subgraph L2["L2 Perception (state/)"]
    GS["GameState<br/>room_id → hand / phase / cards"]
    PS["ProfileStore<br/>PlayerProfile 딕셔너리"]
    RS["ResponseStore<br/>(name, phase) → Dirichlet"]
  end

  subgraph L3["L3 Estimate (estimate/)"]
    EQ["equity.py<br/>treys preflop LUT + postflop MC"]
    CT["class_typer<br/>4-class soft softmax"]
    SH["shrinkage<br/>3-layer Empirical Bayes"]
    PR["priors.yaml / class_priors.yaml"]
  end

  subgraph L4["L4 Decide (decide/)"]
    MODE["mode_selector<br/>push_fold / hybrid / mid / deep"]
    PF["push_fold_chart"]
    OPEN["opening_chart"]
    CONS["conservatism<br/>n_effective → 6 bucket"]
    EV["ev.py<br/>1-ply log-utility tree"]
    POL["policy.decide / decide_async<br/>(라우터)"]
  end

  subgraph L5["L5 Meta (meta/)"]
    TRIG["triggers.py<br/>borderline / 3+way / M≤ 위험"]
    COORD["llm_coordinator<br/>Claude via OpenAI-호환 프록시"]
    BUD["BudgetTracker<br/>핸드·게임·일간 상한"]
  end

  subgraph L6["L6 Persist (persist/)"]
    DB["SQLite WAL<br/>opponent_profile / opponent_response"]
    EL["EventLogger<br/>JSONL in/out"]
  end

  subgraph L7["L7 Observe (dashboard/)"]
    SRV["server.py<br/>stdlib ThreadingHTTPServer"]
    HTML["static/index.html<br/>3s polling"]
  end

  WS -->|ActionRequest| POL
  WS -->|HandResult| PS
  WS -->|HandResult history| RS
  PROTO -.-> WS

  POL --> MODE
  MODE --> PF
  MODE --> OPEN
  MODE --> EV
  EV --> RS
  EV --> EQ
  POL --> CONS
  CONS --> PR

  POL -->|Action| WS
  POL -.->|escalation| COORD
  COORD --> TRIG
  COORD --> BUD

  PS --> DB
  RS --> DB

  SRV --> DB
  SRV --> EL
  HTML --> SRV

  CT --> PS
  SH --> PR
  SH --> CT
```

**레이어 분리 원칙** (계획 P1):
- 하위 → 상위 만 참조. 역방향 import 없음.
- L5 Meta 는 escalation gate 통과 시에만 호출. 실패/타임아웃 시 fallback = L4 통계 argmax.

---

## 3. WebSocket 이벤트 라이프사이클

```mermaid
sequenceDiagram
  autonumber
  participant S as Server
  participant C as WsClient
  participant H as handler (cli.run)
  participant GS as GameState
  participant P as ProfileStore
  participant R as ResponseStore
  participant D as decide_async
  participant DB as SQLite

  C->>S: WS connect
  C->>S: auth_bot {api_token, bot_name}
  S-->>C: auth_ok {concurrent}
  Note over S,C: 대시보드에서 deploy 전에는 여기서 정지

  loop 게임 진행
    S-->>C: waiting_room / joined_room
    C->>H: route
    H->>GS: handle

    S-->>C: hand_start
    H->>GS: 핸드 초기화 (cards, seat, blind)

    loop 각 스트리트
      S-->>C: action_request
      H->>D: decide_async(req, deps, coordinator)
      D->>D: mode_selector · equity · chart / EV tree
      D-->>H: Action
      H->>C: send_action
      C->>S: action {fold|check|call|raise|allin}

      S-->>C: action_performed (타 플레이어)
      H->>GS: history append

      S-->>C: phase_change (flop/turn/river)
      H->>GS: community_cards update
    end

    S-->>C: hand_result {winners, showdown, history}
    H->>P: on_hand_result → BetaCounter 업데이트
    H->>R: observe_from_hand → Dirichlet α 업데이트
    H->>DB: save_store (UPSERT 멱등)
  end

  alt 서버 종료 또는 disconnect
    S--xC: close / shutdown
    C->>C: reconnect with backoff (1s → 30s)
  end
```

핵심 구현 위치:
- `src/holdem/transport/ws_client.py` — 재접속 루프 + ping/pong
- `src/holdem/cli.py` `handler()` — 이벤트 분기 (33~134줄)
- `src/holdem/state/profile_store.py` — `on_hand_result`
- `src/holdem/state/response_store.py` — `observe_from_hand`

---

## 4. 의사결정 파이프라인

```mermaid
flowchart TD
  IN["action_request 수신"] --> CALCM["compute M = my_stack / (SB+BB)"]
  CALCM --> MODE{mode_selector}

  MODE -->|M ≤ 8| PF["push_fold 차트<br/>(SB jam / BB call · open_jam)"]
  MODE -->|8 &lt; M ≤ 15| HYB["hybrid<br/>(open = min-raise, 3bet = jam)"]
  MODE -->|15 &lt; M ≤ 30| MID["mid<br/>(opening chart + pot-odds)"]
  MODE -->|M &gt; 30| DEEP["deep<br/>(opening chart + EV tree)"]

  subgraph PRE["Preflop 공통"]
    POS["position 추정<br/>pos_class ∈ EP/MP/LP/BLIND"]
    HN["canonicalize_hand<br/>→ AKs/TT/...<br/>(169 bucket)"]
    RFI["opening_chart RFI<br/>or call_vs_jam"]
  end

  PF --> HN
  HYB --> HN
  MID --> POS
  MID --> RFI
  DEEP --> POS
  DEEP --> RFI

  MID -.->|postflop| POTODDS["pot-odds gate<br/>eq ≥ req + margin → call"]
  DEEP -.->|use_ev_tree| EVT["EV tree (ev.py)"]

  subgraph EVT_DETAIL["EV tree 세부"]
    EQM["equity_from_cards<br/>(treys MC 1k~3k)"]
    CONSP["conservatism_profile<br/>n_effective → sizing grid<br/>bluff_factor / allin_veto"]
    RESP["ResponseStore.aggregate<br/>활성 상대들의 (phase) Dirichlet 합산"]
    ENUM["ev_enumerate<br/>fold / check / call / raise×grid"]
    UTIL["log-utility score<br/>= log(E[stack + δ]) − κ·Var"]
    ARG["argmax"]
  end

  EVT --> EQM --> CONSP --> RESP --> ENUM --> UTIL --> ARG

  ARG --> ESC{"borderline +<br/>triggers 통과?"}
  ESC -->|Yes & use_coordinator| LLM["LLMCoordinator<br/>Claude choose from candidates"]
  ESC -->|No| OUT["send Action"]
  LLM -->|timeout/error/budget| OUT
  LLM --> OUT

  POTODDS --> OUT
  PF --> OUT
  HYB --> OUT
  RFI --> OUT
```

### 4.1 모드 경계 (plan A1 반영)

| 모드 | M 구간 | 전략 |
|---|---|---|
| `push_fold` | M ≤ 8 | 순수 Nash jam/call 차트. postflop 도달 불가 전제 |
| `hybrid` | 8 < M ≤ 15 | preflop open = min-raise, 3bet = jam. postflop 은 commit |
| `mid` | 15 < M ≤ 30 | opening chart + pot-odds call/fold. postflop aggression 보수 |
| `deep` | M > 30 | opening chart + EV tree(log-utility) + coordinator escalation |

### 4.2 ConservatismProfile

`n_effective = n_personal + 0.3·n_class + 0.05·n_pop` 으로 6-bucket (hard/soft/balanced/exploit…) 에 매핑.

- `sizing_grid` (conservative ⊂ balanced ⊂ exploit)
- `bluff_factor` (0.6 → 1.0 연속)
- `allow_allin` (veto 스위치)

파라미터 파일: `configs/conservatism_schedule.yaml`

### 4.3 EV tree 핵심 식

```
U(a) = log(E[stack + δ]) − κ · Var[stack]
δ = BB · max(1, 5 − n_obs / 20)
κ = κ_base · (1 + 2·exp(−n_hands / 100)) · stack_factor · level_factor
```

`ev_raise` 경로에서 상대 반응은 `ResponseStore.aggregate(active_names, phase)` 의 posterior mean 으로 추정.

---

## 5. 상대 프로필 데이터 구조

```mermaid
classDiagram
  class PlayerProfile {
    +hands_seen: float
    +metrics: dict[str, BetaCounter]
    +aggression: AggressionCounter
    +vpip() float
    +pfr() float
    +af() float
    +on_action(phase, kind)
    +on_hand_end()
  }

  class BetaCounter {
    +alpha: float
    +beta: float
    +observe(success, weight)
    +rate(default) float
    +decay(factor)
    +merge(other, weight)
  }

  class AggressionCounter {
    +aggressive: float
    +passive: float
    +factor(default) float
  }

  class DirichletResponse {
    +alpha_fold: float
    +alpha_call: float
    +alpha_raise: float
    +observe(action)
    +mean() tuple
    +merge(other)
  }

  class ProfileStore {
    +profiles: dict[str, PlayerProfile]
    +responses: ResponseStore
    +on_hand_result(event, state)
  }

  class ResponseStore {
    +table: dict[(name, phase), DirichletResponse]
    +lookup(name, phase)
    +aggregate(names, phase)
    +observe_from_hand(history)
  }

  ProfileStore "1" o-- "*" PlayerProfile
  ProfileStore "1" o-- "1" ResponseStore
  PlayerProfile "1" o-- "*" BetaCounter : metrics
  PlayerProfile "1" o-- "1" AggressionCounter
  ResponseStore "1" o-- "*" DirichletResponse : table
```

### 5.1 SQLite 스키마

```sql
-- opponent_profile (하나 행 = 한 상대)
name           TEXT PRIMARY KEY,
hands_seen     REAL,
metrics_json   TEXT,       -- {metric: {alpha, beta}} 전체 블롭
agg_aggressive REAL,
agg_passive    REAL,
updated_at     TEXT

-- opponent_response (복합 키)
name         TEXT,
phase        TEXT,         -- preflop/flop/turn/river
alpha_fold   REAL,
alpha_call   REAL,
alpha_raise  REAL,
updated_at   TEXT,
PRIMARY KEY (name, phase)
```

- 매 `hand_result` 시점에 `save_store()` 로 UPSERT (plan P7 멱등성).
- WAL 모드 + synchronous=NORMAL. 대시보드 읽기와 봇 쓰기가 락 없이 공존.

### 5.2 3-Layer Shrinkage (H.1)

```
α_eff = α_personal + w_class · α_class + w_pop · α_pop
w_class    = n / (n + τ_class)            τ_class ≈ 8
w_pop      = (τ_class − n) / (τ_class + τ_pop) · clamp(0,1)
w_personal = 1 − w_class − w_pop
```

`n` 이 작을수록 population prior 로, 커질수록 개인 posterior 로 연속 이동.

---

## 6. LLM Coordinator (L5)

```mermaid
flowchart LR
  CANDS["EV candidates<br/>(n ≥ 2)"] --> GATE{triggers?}
  GATE -->|ΔU &lt; 5% + 분산 큼<br/>or M≤10 or bubble| FIRE
  GATE -->|다른 경우| LOCAL["local argmax<br/>(fallback 경로와 동일)"]

  FIRE[BudgetTracker 체크] --> OK{budget OK?}
  OK -->|No| LOCAL
  OK -->|Yes| BUILD["prompt 조립<br/>(system prefix 고정,<br/>candidates JSON)"]
  BUILD --> CLAUDE["LLMClient<br/>(OpenAI-호환 /v1, base_url 오버라이드)"]
  CLAUDE --> PARSE{"응답 파싱<br/>allowed action?"}
  PARSE -->|Yes| DECIDE["candidate_to_action"]
  PARSE -->|No / timeout / 429| LOCAL
  DECIDE --> OUT["Action"]
  LOCAL --> OUT
```

- **모델 선택**: `configs/llm.yaml` — sonnet 기본, critical 구간만 opus.
- **안전 가드**: LLM 이 **선택지 밖 액션 생성 금지**. 스키마 검증 실패 → fallback.
- **비용 상한**: `BudgetTracker` per_hand / per_game / per_day 세 축.
- **현재 상태**: `--use-coordinator` 플래그 미활성 시 전 경로에서 LLM 미호출.

---

## 7. CLI · 스크립트 레이어

```mermaid
flowchart LR
  subgraph BOT["봇 프로세스"]
    CLI["uv run holdem<br/>--profile-db / --use-ev-tree /<br/>--use-coordinator"]
    BOTPID["data/bot.pid"]
    BOTLOG["data/logs/cli/session_*.log"]
  end

  subgraph DASH["대시보드 프로세스"]
    DASHSRV["uv run holdem-dashboard<br/>:8765"]
    DASHPID["data/dashboard.pid"]
    DASHLOG["data/logs/dashboard.log"]
  end

  subgraph SCRIPTS["scripts/"]
    CHECK["bot-check.sh<br/>env + TCP + auth smoke"]
    START["bot-start.sh<br/>(nohup, bot.pid)"]
    STOP["bot-stop.sh"]
    STATUS["bot-status.sh<br/>(프로세스 + DB + 대시보드 요약)"]
    LOGS["bot-logs.sh<br/>all / errors / actions"]
    PLAY["bot-play.sh<br/>(check → 안내 → start → status)"]
    DASHSH["bot-dashboard.sh<br/>--bg / --stop / --port=N"]
  end

  subgraph DATA["공유 상태"]
    DB["data/profiles.db<br/>(SQLite WAL)"]
    LOGSCOM["data/logs/"]
    PIDS["data/*.pid"]
  end

  CLI --> DB
  CLI --> BOTLOG
  CLI --> BOTPID

  DASHSRV --> DB
  DASHSRV --> BOTLOG
  DASHSRV --> BOTPID
  DASHSRV --> DASHLOG
  DASHSRV --> DASHPID

  START --> CLI
  STOP --> BOTPID
  STATUS --> BOTPID
  STATUS --> DB
  STATUS --> DASHPID
  CHECK --> CLI
  PLAY --> CHECK
  PLAY --> START
  PLAY --> STATUS
  DASHSH --> DASHSRV
  LOGS --> BOTLOG
```

---

## 8. Dashboard 동작

```mermaid
sequenceDiagram
  participant B as 브라우저
  participant H as index.html
  participant S as server.py (:8765)
  participant D as SQLite + log/pid files

  B->>H: GET /
  H-->>B: static HTML + JS

  loop 3s polling
    B->>S: GET /api/status
    S->>D: PID/uptime · db row count · latest log path
    S-->>B: JSON

    alt 현재 탭 = 프로필
      B->>S: GET /api/profiles
      S->>D: load_store() → 각 프로필 VPIP/PFR/AF + class softmax
      S-->>B: JSON rows
    else 탭 = 응답
      B->>S: GET /api/responses
      S->>D: SELECT * FROM opponent_response
      S-->>B: JSON rows (+ P(f/c/r))
    else 탭 = 이벤트
      B->>S: GET /api/events?n=500
      S->>D: tail + 키워드 필터 (hand_start/allin/auth_ok/...)
      S-->>B: JSON events
    else 탭 = 로그
      B->>S: GET /api/logs?n=500
      S->>D: tail N lines
      S-->>B: JSON lines
    end
  end
```

- **의존성 Zero**: stdlib `http.server` 만. 외부 패키지 미사용.
- **포트**: 기본 8765 (`HOLDEM_DASHBOARD_PORT` 으로 변경).
- **바인딩**: `127.0.0.1` 만 — 외부 노출 의도 없음.

---

## 9. 설정 파일 지도

| 파일 | 역할 | 소비자 |
|---|---|---|
| `.env` | `HOLDEM_WS_URL` / `HOLDEM_API_TOKEN` / `HOLDEM_BOT_NAME` | `cli.py`, `bot-check.sh` |
| `configs/priors.yaml` | population-level Beta α,β (VPIP/PFR/CBET/...) | `estimate/priors.py` |
| `configs/class_priors.yaml` | 4-class centroid + per-class Beta | `estimate/class_typer.py` |
| `configs/conservatism_schedule.yaml` | n_effective → (grid, bluff_factor, λ, allow_allin) | `decide/conservatism.py` |
| `configs/sizing.yaml` | 3단계 sizing grid | `decide/sizing.py` |
| `configs/nash_charts/*.yaml` | Push/Fold · open_jam · call_vs_jam (169×M_bucket) | `decide/push_fold_chart.py` |
| `configs/open_ranges/*.yaml` | RFI / 3bet / 4bet chart | `decide/opening_chart.py` |
| `configs/blind_schedule.yaml` | 레벨별 SB/BB (R1 분석) | 현재 참조 없음 (문서용) |
| `configs/llm.yaml` | default/critical 모델, max_tokens, budget | `meta/llm_coordinator.py` |

---

## 10. 실행 흐름 (현재 운영 시나리오)

```mermaid
stateDiagram-v2
  [*] --> DISCONNECTED
  DISCONNECTED --> AUTH: bot-start.sh
  AUTH --> IDLE: auth_ok
  AUTH --> DISCONNECTED: 네트워크 에러 / 토큰 오류
  IDLE --> IN_ROOM: waiting_room / joined_room<br/>(대시보드 deploy 필요)
  IN_ROOM --> IN_HAND: hand_start
  IN_HAND --> ACTING: action_request
  ACTING --> IN_HAND: Action 전송
  IN_HAND --> IN_ROOM: hand_result + DB 저장
  IN_ROOM --> GAME_END: game_end
  GAME_END --> IDLE: 다음 게임 대기
  IDLE --> DISCONNECTED: server_shutdown
  DISCONNECTED --> AUTH: reconnect backoff 1s→30s
```

**중요 제약** (BOT_GUIDE §2.2):
- `auth_ok` 상태만으로는 방 배정 안 됨. **대시보드에서 deploy 버튼** 수동 조작 필요.
- 서버는 동일 `bot_name` 으로 **WS 연결 1개만** 허용 → auth smoke 와 봇 프로세스 공존 불가.

---

## 11. 테스트 구성

- 총 ~300 테스트 (pytest). 카테고리:
  - `test_protocol.py` · `test_ws_client.py` — L1
  - `test_player_profile.py` · `test_response_store.py` · `test_profile_store.py` — L2
  - `test_equity.py` · `test_odds.py` · `test_class_typer.py` · `test_shrinkage.py` — L3
  - `test_push_fold_chart.py` · `test_opening_chart.py` · `test_conservatism.py` · `test_ev.py` · `test_policy.py` — L4
  - `test_llm_coordinator.py` · `test_budget.py` · `test_triggers.py` — L5
  - `test_persist_db.py` · `test_persist_response.py` — L6
  - `test_simulate.py` — 6 baseline + HU 엔진 7 test

실행: `uv run pytest -q`

---

## 12. 현 미완 · 알려진 한계

| 항목 | 상태 | 계획 섹션 |
|---|---|---|
| Deploy API 자동화 | ⚠ 수동 | B4 블로커 |
| Nash 차트 공식 출처 확보 | ⚠ placeholder | R5 |
| R6 A/B 검증 | 미진행 | R6 |
| Multi-way(3~9인) 시뮬레이터 | ⚠ HU only | H.8 |
| Side pot | ⚠ 단일 pot | engine.py 한계 |
| 블라인드 상승 시뮬 | ⚠ 고정 | engine.py 한계 |
| LLM snapshot test | 경로 예약만 | D7 미완 |
| AF 지표 정규화 | ⚠ passive 희소 시 폭주 | dev_log r4 §5 |
| Bootstrap 결과 → priors.yaml 주입 | 미진행 | H.9 Step 4 |

---

## 13. 핵심 파일 지도 (빠른 탐색)

```
src/holdem/
├── cli.py                           # 엔트리: asyncio + reconnect
├── transport/
│   ├── ws_client.py                 # auth · subscribe · ping · 재접속
│   └── protocol.py                  # Pydantic tagged union
├── state/
│   ├── game_state.py                # room_id → 휘발성
│   ├── player_profile.py            # Beta + AF
│   ├── profile_store.py             # 영속 입구
│   └── response_store.py            # Dirichlet 저장소
├── estimate/
│   ├── equity.py                    # treys preflop LUT + postflop MC
│   ├── class_typer.py               # 4-class softmax
│   ├── shrinkage.py                 # 3-layer
│   ├── priors.py                    # yaml 로더
│   └── board_texture.py             # H.5
├── decide/
│   ├── policy.py                    # 최상위 라우터 (decide / decide_async)
│   ├── mode_selector.py             # M → mode
│   ├── push_fold_chart.py
│   ├── opening_chart.py
│   ├── conservatism.py              # 6-bucket 프로파일
│   ├── ev.py                        # 1-ply log-utility tree
│   └── sizing.py
├── meta/
│   ├── llm_coordinator.py           # escalation → Claude
│   ├── llm_client.py                # OpenAI-호환 프록시
│   ├── triggers.py
│   └── budget.py
├── persist/
│   ├── db.py                        # SQLite + UPSERT
│   └── event_log.py                 # JSONL in/out
├── simulate/
│   ├── engine.py                    # HU NLHE 시뮬
│   └── strategies.py                # 6종 baseline
└── dashboard/
    ├── server.py                    # :8765 stdlib HTTP
    └── static/index.html            # 3s polling UI

scripts/
├── bot-check.sh / bot-start.sh / bot-stop.sh
├── bot-status.sh / bot-logs.sh / bot-play.sh
├── bot-dashboard.sh
├── bootstrap_sim.py                 # 6 baseline 자기대전
└── (EDA 스크립트 — J.x)
```

---

## 14. 요약 도표

```mermaid
graph LR
  ENV[(.env<br/>configs/*)] --> BOT
  BOT[holdem CLI] --> WS[(서버 WS)]
  WS --> BOT
  BOT --> DB[(profiles.db)]
  BOT --> LOG[(session log)]
  DASH[holdem-dashboard :8765] --> DB
  DASH --> LOG
  DASH --> BOTPID[(bot.pid)]
  USER{{Browser}} --> DASH
```

**현재 한 줄 상태**: `holdem` 봇 프로세스 + `holdem-dashboard` 프로세스 2개가 SQLite/로그 파일을 매개로 느슨 결합. 서버와는 단일 WS 연결. 의사결정은 M 모드 스위치로 분기, 상대 프로필은 매 핸드 UPSERT 로 영속.
