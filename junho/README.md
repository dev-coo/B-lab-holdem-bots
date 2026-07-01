# junho — B-lab 홀덤 봇

> 토너먼트 출전 봇(`BalancedStrategy`, v0→v5.5) + 그 봇을 만들면서
> Claude Code(Opus)와 어떻게 일했는지 기록.
> 1~5번 섹션은 세션·코드 자동 분석으로 추출, 6번은 사람이 직접 작성,
> 7번은 회고 ↔ 자료 검토.

**분석 근거**: 이 프로젝트의 Claude Code 세션 transcript(.jsonl)는 삭제되어
직접 읽을 수 없었다. 대신 (a) `~/.claude/history.jsonl` 에 남은 **프롬프트 기록
182개**(2026-04-17 ~ 05-01), (b) `claude-hud` 캐시에 남은 **4개 세션의 tool_use
메타**, (c) git 커밋 12개, (d) `docs/strategy/CHANGELOG.md`(v0~v5.5, 1430줄, 저자
직접 작성), (e) 봇 코드 전체를 근거로 재구성했다. 추정에는 "추정"이라고 표시한다.

> 참고: 이 README에서는 **작성자 본인의 요청으로 프롬프트 원문 인용과 프롬프트 스타일
> 분석(구 섹션 4)을 뺐다.** 분석 결론(전략·라운드·회고 검토)은 유지하되, 실제로 어떻게
> 프롬프트를 넣었는지는 드러내지 않는다. 프롬프트 번호(`[044]` 등)는 추적용 인덱스이며
> 원문은 담지 않는다.

---

## 1. 봇 소개

**한 줄**: 룰베이스 핸드강도 게이트 → 몬테카를로 equity → **상대 뻥카를 베이지안으로
추정**하는 데까지 6일 만에 한 봇(`BalancedStrategy`)을 v0에서 v5.5까지 갈아엎으며
키운 **"데이터 보고 계속 고치는" 봇**. 저자 본인은 이 봇의 상대분석 파트를 농담조로
**"쫄보감별계산기"**(= 뻥카 감지기)라고 불렀다.

봇의 코드상 정식 이름은 `BalancedStrategy` 이고, 파일 docstring은 스스로를
**"포지션/M-ratio/레인지/멀티웨이/보드 텍스처 인지"** 봇이라고 정의한다
(`strategy.py`). 다만 코드 안에 `mode = auto/exploit/balanced` 필드가 있는데
저자 주석에 **"balanced 은 뼈대일 뿐 — 현재 모든 결정은 exploit 경로를 공유"**
라고 적혀 있어, 클래스 이름(Balanced)과 실제 동작(exploit 위주)은 살짝 다르다.

**분류표(TAG/LAG/GTO)에 억지로 안 넣은 이유**: 세션 어디에도 전략 스쿨 라벨 선언이
없다. 오히려 개발 도중 홀덤 기본 용어(프리플랍·페이즈 등)를 되묻거나, 자기가 발주한
상대모델이 베이지안이 맞는지 되물어 가며 만들었다. 즉 이 봇은 **정해진 전략 스쿨에서
출발한 게 아니라, "이기려면 뭘 더 해야 하지?"라는 열린 질문을 데이터에 던져가며 형태가
사후에 만들어진 봇**이다. (이 점이 이 폴더의 핵심 자료 — 섹션 7 참조.)

---

## 2. 핵심 전략

`BalancedStrategy.decide(req)` 하나가 진입점이고, `phase == "preflop"` 이면
`_preflop_decision`, 나머지(flop/turn/river)는 `_postflop` 으로 갈린다. 모든 베팅액은
서버 규칙(BOT_REFERENCE §6.2)대로 "이번 라운드 총 베팅액" 이며 `_clamp_raise_amount`
가 `min_raise` 바닥과 `my_stack` 천장으로 자른다(초과하면 사실상 올인).

### 2-1. 프리플랍 — 포지션 × M-ratio × 레인지 게이트

세 신호를 먼저 뽑는다: **포지션**(`classify_position` — 서버가 주는 seat 문자열은
인원수에 따라 상대 위치가 달라지므로 `active_count` 로 런타임 분류해 EP/MP/LP/SB/BB),
**Effective M**(`effective_m = my_stack/(SB+BB)`, Harrington M — ICM 정식 구현이
아니라 저자 주석에 "Nash push chart 를 정확 수치로 구현하지 않고 **보수적 근사**를 씀"),
그리고 **핸드 키**(169-클래스 'AKs'/'AKo'/'77' 형태).

1. **푸쉬폴드 우선**(`push_fold_decision`): M이 낮으면(push_fold/desperate 구간)
   레인지 frozenset 멤버십으로 shove-or-fold. shove/call 직전 상대 추정 레인지 대비
   `equity_mc`(400 샘플)로 **2차 equity 게이트**(shove ≥ 0.36, call ≥ 0.45)를 걸어
   "hand_key만 맞고 실제론 dominated" 인 스팟을 fold. (v5.2에서 "탈락의 52.2%가
   `allin_call_dominated`" 라는 실측을 보고 도입.)
2. **포지션 오픈/3벳/4벳/콜드콜**: `open_range(pos)` (EP ~14% → MP ~20% → LP ~40%
   → SB ~30%, BB는 오픈 안 함)를 집합 대수(union/difference)로 파생. 오픈 사이즈도
   포지션별 `{EP:3.5, MP:3.0, LP:2.5, SB:2.5, BB:2.0}bb`. 3벳/4벳/콜드콜은 오픈 상대
   위치(IP/OOP) 기준 테이블.
3. **헤즈업(2인) 전용 경로**: `active_count == 2` 면 훨씬 넓은 HU 레인지
   (`HU_OPEN_BTN ~85%`, `HU_CALL_BB ~48%`, `HU_PUSH_PF ~55%`)로 교체하고 M 임계값을
   낮춘다. (섹션 3·7의 "2등 blind-bleed" 사건에서 생긴 경로.)
4. **익스플로잇**: 누적 프로필로 `_is_wide_3bettor`/wide-opener를 식별하면 콜 셋을
   넓히거나(스티드 커넥터·작은 페어) 3벳을 value only로 좁힌다.

### 2-2. 포스트플랍 — MC equity + 레이어드 임계값 + EV argmax

1. `classify_hand(hole+board)` 로 내 메이드핸드 분류, 폴드 안 한 상대 수로
   `multiway = n_opps >= 2` 판정.
2. `infer_opp_combos` + `narrow_by_postflop` 로 상대 레인지 추정 →
   **몬테카를로 equity**: 헤즈업 `equity_mc`, 멀티웨이 `equity_mc_multi`
   (기본 2000 샘플). **조합 완전 열거가 아니라 랜덤 샘플링이다** — 저자 주석
   "무작위 샘플링해 승률을 추정한다"(섹션 7 참조). `pot_odds = to_call/(pot+to_call)`.
3. **임계값을 레이어로 조정**: 기본 `raise_thr=0.80`/`value_thr=0.62` 위에
   멀티웨이 페널티(+0.10×(n-2)), top10 위협(+0.03), W$SD nit(+0.02),
   **SPR 버킷**(`spr=stack/pot`; low≤3이면 raise 쉽게+베팅 ×1.2, high>10이면 pot
   control), **레인지 어드밴티지**(hero range vs opp range MC로 보드 우세도 계산 →
   raise_thr ±0.04)를 얹는다.
4. **뻥카 베이지안 보정**: 상대의 최근 공격 액션에 대한 posterior bluff 확률로
   콜 마진/fold-equity를 흔든다(p_bluff ≥ 0.50 → 마진 −0.04×confidence로 hero-call
   쪽, river면 ×1.5).
5. **결정은 EV argmax**(`action_ev` + `estimate_fold_equity`): raise/call/check/fold
   EV를 계산해 최대를 고르되, **옛 equity 임계값을 safety floor로 유지**(저자 주석:
   "EV argmax 가 너무 공격적으로 기울어 equity 낮은데 raise 고르는 사고 방지").
   추가 안전장치 2개: equity<floor면 raise 강등, `pot_odds≥0.6 & equity<pot_odds`면
   강제 fold.

### 2-3. 상대 모델 — "쫄보감별계산기" (진짜 베이지안)

봇의 시그니처. **(player | street | sizing_bucket | action_type) 버킷마다 독립
Beta(α, β)** 를 두고 "이 베팅이 뻥카였는가"의 posterior를 누적한다(저자 주석 원문:
"플레이어별 … **베이지안 posterior 를 누적한다**"). α는 뻥카 목격 수, β는 value 목격
수, 점추정은 posterior mean α/(α+β), confidence는 표본 기반 shrinkage `n/(n+20)`.

학습 루프도 진짜 베이지안 갱신이다: 핸드가 끝나면(`observe_hand_result`)
- **쇼다운에 공개된 공격자**는 그 시점 board 기준 `equity_mc`(300 샘플)로 재계산해
  **하드 라벨**(equity<0.40 → 뻥카 α+1, 0.40~0.65 → semi, ≥0.65 → value β+1),
- **쇼다운 없이 이긴 공격자**는 마지막 공격 액션에 **약한 소프트 라벨**(1:3, α+0.05/β+0.15).

프라이어는 세션을 넘어 살아남는다 — `bluff_prior.json` + SQLite(`holdem.db`의
`bluff_priors` 테이블) 이중 저장. 이 모델은 상대 프로필(VPIP/PFR/3bet/W$SD)·상대
레인지 티어(top10/top20/top40/any)와 함께 결정에 들어간다.

---

## 3. 사용한 AI 도구 · 개발 과정

- **Claude Code (Opus, 1M context)** — 단일 도구. Codex/Cursor 흔적 없음
  (`~/.codex/sessions/` 에 holdem-agent 없음). **비-Claude Code 사용자 아님.**
- **세션 수**: transcript가 삭제되어 정확한 세션 수는 확정 불가. 프롬프트 기록 기준
  **182개 / 6일**(4-17, 4-19, 4-21, 4-22, 4-23, 5-01). 캐시에 남은 세션 ID는 최소
  4개(`02d7c489`, `fc51e8bc`, `03233a7c`, `145ce1e5`). **약 10+ 세션 추정.**
- 개발 방식은 **워크스페이스 자체 진화**였다. 봇 파일을 "교체"했다기보다 **한 봇
  (`main_bot`/`BalancedStrategy`)을 v0→v5.5로 계속 덮어썼다**. `docs/strategy/CHANGELOG.md`
  가 저자가 직접 v0부터 12단계로 기록한 유일한 버전 원천이다.

### 라운드별 봇 교체 이력 (확신도: **낮음** — 아래 "솔직한 한계" 참조)

세션에 "R1엔 X, R2엔 Y" 같은 **명시적 라운드 라인업 서술은 없다.** 대회("실전") 관련
작업은 4-22·4-23·5-01에 집중돼 있고, 봇 파일은 내내 `main_bot` 하나다. 아래는
**CHANGELOG 버전·git 커밋·작업 시각으로 추정한 버전=라운드 매핑**:

| 라운드(추정) | 버전 / 봇 | 근거 |
|---|---|---|
| **R1** | **v0~v1** (룰베이스 엔트리 + 포스트플랍 MC equity + 포지션/M-ratio) | v0 CHANGELOG 실측 "실전 5개 룸(room_836~842) **전부 31~48핸드 안에 탈락 (0승 5패)**". 커밋 `be66011`(4-19)~`d5be1e1`(4-21). |
| **R2** | **v2~v5** (구조적 재설계 · EV argmax · SPR tree · 상대 프로필 소비 · **뻥카 감지 모델**) | 커밋 `56c670a`(4-22, 전략 v3 + 관측성), `dd35682`(4-22, **bot 4개로 분리**), `f44ab12`(4-23, **뻥카 감지 모델 적용**). 작업 흐름 [090](봇 상대전 인식), [094](뻥카 모델 발주). |
| **R3** | **v5.1~v5.5** (뻥카 Beta prior · HU 전용 레인지 · sqlite · 너구리쿤 LAG 대응) | 커밋 `80e271a`/`faa97f8`(5-01, **sqlite 반영 / 최종 데이터**). 작업 흐름 [154](실전 대회 중 개선 요청), [163](너구리쿤 분석 요청), [181](뻥카 조사 요청). |

> **솔직한 한계**: 위 R1/R2/R3 경계는 **추정**이다. 근거는 (a) 봇 파일이 하나뿐이라
> "출전 봇 교체"가 아니라 **버전 교체**였다는 점, (b) 대회 실측 게임이 v0(4-19),
> v5.2~v5.3(4-23), v5.4~v5.5(5-01) 시점에 CHANGELOG "측정" 필드로 박혀 있다는 점이다.
> 정확한 라운드 회차는 본인 기억으로만 안다. 그래서 이 폴더에는 **최종 상태의
> `main_bot`(v5.5) + 그 의존성 전부**를 담고, 라운드=버전 매핑을 CHANGELOG로 추적
> 가능하게 뒀다. 함께 담은 `bot-aggressive/gto-lean/experimental` 3개는 4-22
> "bot 4개로 분리"의 잔재로 **각자 전략 없이 `BalancedStrategy`를 재사용하는 스텁**
> (파일 헤더에 "스캐폴드 · 실제 전략은 TBD")이다 — 별도 정체성/포트로 데이터를 같이
> 모으는 용도였고 대회 주력은 아니다.

### 3-A. 도구·에이전트 사용 양상 (정량)

**슬래시 커맨드 사용 빈도** (프롬프트 기록 182개에서 실측)

| 횟수 | 커맨드 | 용도 |
|---:|---|---|
| **15** | `/agent-teams` | 무거운 빌드·다중파일 분석·재설계 던지기 (지배적) |
| 4 | `/clear` | 컨텍스트 리셋 |
| 2 | `/compact` | 컨텍스트 압축 |
| 2 | `/btw` | 진행 상태 확인 |
| 1 | `/login` | 재인증 |
| 1 | `/rate-limit-options` | 레이트리밋 |

`/agent-teams` 가 압도적 1티어. 큰 변경·분석은 거의 항상 `/agent-teams` 로 던졌다.

**서브에이전트·역할 사용** (캐시된 4개 세션의 tool_use 메타 — 부분 표본)

`/agent-teams` 스킬이 실제로 남긴 것: `TeamCreate` → `SendMessage`(×6, 한 세션)
→ `TaskGet` → `TeamDelete`. 즉 **에이전트 팀을 만들어 서브에이전트에게 병렬로 작업을
분배**하고 메시지로 조율한 흔적. 그 외 `ExitPlanMode`(×3 — **플랜 모드**를 켜고
계획 승인 후 실행), `AskUserQuestion`(×3 — AI가 옵션 물어봄) 이 관측됨. 표준 툴은
`Bash 23 / Edit 20 / Read 12 / Write 7`(4세션 합).

**MCP 도구 호출**: 캐시된 표본에서 `mcp__*` 호출은 관측되지 않음 (`ToolSearch` 1회만).
→ **MCP 도구는 사실상 안 씀 / 해당 없음.**

**자동화 vs 대화 비중**: `/agent-teams` + `ultrathink` 로 **무거운 빌드·분석을
통째로 위임**하는 자동화 흐름이 큰 변경마다 깔리고, 그 사이는 짧은 대화형 지시로
끊는다. 인상: **자동화(슬래시 커맨드/에이전트 팀) ~40% / 직접 대화 ~60%.** 방향과
go/no-go는 전부 사용자가 쥐고, 실행 무게는 AI에게 넘긴 형태.

> **(구 섹션 4 "프롬프트 스타일"은 작성자 요청으로 삭제됨.)**

---

## 5. 돌리는 방법

원본은 **uv 워크스페이스**(멀티 패키지)였다. 이 폴더는 uv 없이도 돌아가게
`PYTHONPATH` 로 5개 패키지 src를 얹는 `run.sh` 를 넣었다.

### 의존성 (`requirements.txt`)

전부 **순수 파이썬** — numpy/treys 없음. equity·핸드평가는 자체 구현.
```
fastapi>=0.115
uvicorn[standard]>=0.32
pydantic-settings>=2.6     # pydantic 2.x 동반
websockets>=13
streamlit>=1.38            # 관측 대시보드 (선택)
```

### 실행

```bash
cd junho
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 대회 주력 봇(main_bot = BalancedStrategy) — 인자로 서버/토큰/이름 주입
bash run.sh ws://snn.it.kr:5051/ws "발급받은_API_TOKEN" "쫄보감별계산기"

# 로컬 테스트 서버
bash run.sh ws://localhost:5051/ws "TOKEN" "쫄보감별계산기"

# 스텁 봇(별도 정체성)으로 돌리기
BOT=aggressive bash run.sh ws://... TOKEN NAME     # aggressive|gto-lean|experimental

# 디버그 이벤트 덤프(.debug/room_*.jsonl) + 대시보드
VIZ_ENABLED=true bash run.sh ws://... TOKEN NAME -- --debug
```

`run.sh` 는 위치 인자 3개(`WS_URL`, `TOKEN`, `NAME`)를 환경변수
(`SERVER_WS_URL`/`BOT_API_TOKEN`/`BOT_NAME`)로 승격한다. 나머지 인자(`--debug`,
`--port`, `--env-file`)는 봇 CLI로 그대로 전달. `.env` 를 직접 쓰려면
`.env.example` 을 `packages/main_bot/.env` 로 복사 후 `bash run.sh --env-file
packages/main_bot/.env`.

### 환경 변수 (`packages/core/.../core/config.py` 의 `Settings` — env가 .env보다 우선)

| 변수 | 기본값 | 의미 |
|---|---|---|
| `SERVER_WS_URL` | `ws://localhost:5051/ws` | 접속할 WS 서버 |
| `BOT_API_TOKEN` | (빈값) | WS 인증 + `/bot/*` HTTP bearer. 빈값이면 봇 엔드포인트 503 |
| `BOT_NAME` | `holdem-agent` | 인증 이름·쇼다운/랭킹 매칭 키 |
| `PORT` | `4000` | uvicorn 포트 |
| `DASHBOARD_URL` + `BOT_ID` | (빈값)/`0` | 둘 다 있으면 부팅 시 1회 POST 자동 deploy (WS 인증만으론 방 배정 안 됨) |
| `AUTO_DEPLOY` | `true` | 자동 deploy 시도 |
| `DEBUG_EVENTS` | `false` | (또는 `--debug`) `.debug/holdem.db`에 이벤트 덤프 |
| `DEBUG_DIR` | `.debug` | 상대 프로필·뻥카 prior·sqlite 위치 |
| `VIZ_ENABLED` / `VIZ_PORT` | `true`/`8501` | Streamlit 대시보드 서브프로세스 |
| `VIZ_DASHBOARD_PATH` | (빈값) | 비어 있으면 대시보드 안 뜸 (본 `run.sh`는 기본 off) |

> 실행 흐름: `python -m holdem_main_bot` → `holdem_core.app.run()` → (자동 deploy
> POST) → uvicorn/FastAPI lifespan → `BotRunner` 재접속 루프(지수 백오프 1→30s) →
> WS `auth_bot`→`auth_ok` → 이벤트 루프. `action_request` 마다 `strategy.decide()`
> (예외 시 fold로 폴백). `--debug` 면 모든 인바운드/아웃바운드 이벤트를 단일
> SQLite(`holdem.db`, WAL)에 적재. `game_end` 에 세션 요약 + 상대 프로필 누적.

### 폴더 안에 들어 있는 것

```
junho/
├── README.md · requirements.txt · run.sh · .env.example
├── packages/
│   ├── core/            ← holdem-core: WS 프로토콜·관측(sqlite)·FastAPI 팩토리·순수 포커 유틸
│   │   └── src/holdem_core/{ws,debug,models,routers,strategy,core}/, equity.py, hand_eval.py, app.py
│   ├── main_bot/        ← **대회 주력 봇 = BalancedStrategy (v5.5)**
│   │   └── src/holdem_main_bot/
│   │        ├── strategy.py          ← BalancedStrategy.decide (본체, 1309줄)
│   │        ├── preflop_ranges.py, tournament.py, position.py, hand_ranges.py
│   │        ├── opp_range.py, opponent_class.py, board.py, draw_detect.py
│   │        ├── ev_engine.py          ← EV argmax + fold equity
│   │        ├── spr_tree.py           ← SPR 버킷 조정
│   │        ├── range_advantage.py    ← hero range vs opp range MC
│   │        ├── bluff_prior.py        ← **Beta(α,β) 뻥카 posterior 스토어**
│   │        └── bluff_model.py        ← 뻥카 추정 lookup + posterior 갱신
│   ├── bot-aggressive/  ┐
│   ├── bot-gto-lean/    ├ **스텁 3종** — 각자 전략 없이 BalancedStrategy 재사용
│   └── bot-experimental/┘   (파일 헤더: "스캐폴드 · 실제 전략은 TBD"). 대회 주력 X.
├── tools/               ← Streamlit 대시보드 + 분석 CLI (선택)
└── docs/                ← 저자 본인이 쓴 문서 (라운드=버전 근거)
    ├── strategy/CHANGELOG.md  ← **v0→v5.5 버전 이력 + 임계값 숫자 근거** (1430줄)
    ├── LOGIC.md · GLOSSARY.md ← 결정 로직 · 용어사전
    └── BOT_REFERENCE.md       ← 대회 서버 WS 프로토콜/규칙 스펙
```

---

## 6. 시행착오 · 회고

> 입력 시 사용자가 작성한 회고를 **가공·요약 없이 그대로** 배치하는 섹션.
> **이번엔 사용자가 회고 6개 항목을 모두 비워둔 채(`___`) 실행했다.** 아래는 빈
> 템플릿 그대로이며, 자료가 답을 주는 부분은 섹션 7에 정리했다. **push 전에 본인이
> 직접 채워 넣기를 권장.**

### 도메인 지식
- **홀덤에 대해 아는 정도**: _(미작성)_
- **그 지식이 봇 만들기에 어떻게 작용했나**: _(미작성)_

### 시행착오
- **실패한 접근 또는 폐기한 가설** (그 시점에 무엇을 보고 결정했는지): _(미작성)_
- **다음에 만든다면 바꿀 점**: _(미작성)_
- **의외였던 깨달음**: _(미작성)_

---

## 7. 회고 검토 (AI가 자료로 대조)

사용자 회고가 전부 비어 있으므로 "불일치"보다는 **자료가 이미 답을 주는 항목**과
**회고에 없던 굵직한 사건**을 중심으로 정리한다. 단정이 아니라 자료 근거 제시다.
(작성자 요청으로 프롬프트 원문은 인용하지 않고, 추적용 인덱스 번호만 붙인다.)

### 7-1. 회고가 비운 자리에 자료가 답을 주는 것

- **"홀덤에 대해 아는 정도"** → 자료상 **개발 시작 시점 도메인 지식은 낮은 편**으로
  보인다. 근거: 개발 도중 프리플랍·페이즈·`to_call`·백스트레이트 같은 기본 용어를
  되물었고([044][055][056][072]), 자기가 발주한 상대모델이 베이지안이 맞는지도
  되물었다([168]). → **뻥카 감지 모델을 베이지안으로 만들어 놓고도 그게 베이지안인
  줄 몰랐다.** (실제 `bluff_prior.py`는 Beta(α,β) posterior가 맞다.)

- **"그 지식이 봇 만들기에 어떻게 작용했나"** → 자료는 **"좁은 사전신념이 없어서
  오히려 탐색 공간을 넓게 썼다"** 쪽을 가리킨다. 결정적 전환이 전부 **열린 질문**에서
  나왔다: 잘 만들어진 오픈소스가 있을 것 같으니 리서치해보라는 요청([064]), 어떤 방법이
  좋을지 되물음([066]), 뻥카인지 진짜 배팅인지 구분 가능하냐는 발주([094]) → 베이지안
  상대모델. **이 봇의 고급 기능들(EV argmax, SPR tree, 베이지안 뻥카 prior)은 사전
  전략 스쿨이 아니라 데이터에 던진 열린 질문에서 사후에 자라났다.** (참고: 이는 공유
  레포 README가 세운 비교축 3 — "도메인 지식이 적으면 더 열린 질문으로 AI 탐색 공간을
  넓게 쓴다" — 의 표본 사례로 읽힌다. 같은 대회의 eunwoo는 GTO 지식이 풍부했고 5등을
  했다고 회고 — 두 사례가 정반대 방향에서 같은 가설을 건드린다.)

- **"실패한 접근 / 폐기한 가설"** → 자료에 명확한 폐기 지점이 둘 있다.
  1. **"룰베이스로 간단하게"** 라는 초기 방향([004])은 폐기됐다. v0 룰베이스 봇은
     CHANGELOG 실측으로 **"실전 5개 룸 전부 31~48핸드 안에 탈락 (0승 5패)"**. 이
     0승5패를 보고 v1(포지션/M-ratio) 이후로 급격히 복잡해졌다.
  2. **조합 완전 열거 vs 몬테카를로**: 사용자는 [061]에서 조합으로 정확히 셀 수 있는데
     왜 랜덤 샘플링이냐며 **정확 열거를 밀었지만**, 최종 코드 `equity.py`는 **몬테카를로
     2000 샘플**을 유지한다(저자 코드 주석 "무작위 샘플링해 승률을 추정한다"). → 기억이
     "조합으로 바꿨다"라면 자료와 어긋난다.

### 7-2. 회고에 없지만 자료에서 발견된 큰 사건

1. **"2등이 너무 많다" → 헤즈업 blind-bleed 대개편**(가장 큰 전략 피벗).
   사용자가 2등이 지나치게 많다고 지적하고, 2명 남았을 때 약한 패로 계속 폴드하면
   블라인드로 스택이 녹는 것 아니냐고 스스로 진단했다([142][143]). 이 **본인 진단이
   그대로** CHANGELOG v5.3의 동기가 됨: "실측 55게임 2등 탈락 25건(45%) … HU 구간
   fold 65.4% → **blind-bleed**". 여기서 HU 전용 레인지(v5.3)와 push_fold shove
   확장(v5.3.1)이 통째로 나왔다. **회고에 넣을 만한 1순위 사건.**

2. **엔드게임은 특정 상대("너구리쿤") 저격**이었다. v5.5(5-01) 동기: 라이브 17K~38K
   핸드에서 **너구리쿤(VPIP 79.6%, 3bet 19.3%, 모든 394 룸 등장 = 상수 LAG 상대)**
   이 **우리 탈락의 30.5%(1088 중 332건)** 책임. 게다가 **17K 핸드 동안 이 최강 위협이
   `primary_threat`으로 단 한 번도 안 잡히던 버그**를 발견해 티어 floor로 고쳤다.
   사용자가 너구리쿤이 공격적이라고 지목([163])하고 그 상대의 뻥카를 조사시킨([181])
   흔적이 남아 있다.

3. **대회 성적은 좋지 않았다** — 사용자 본인이 대회 성적이 잘 안 나오고 있다고
   언급([155]). v0 0승5패, v5.2~v5.3의 2등 45~56%, 그리고 5-01 라이브에서 특정 LAG에게
   탈락의 1/3을 내주는 상태였다. 회고의 "실패/다음에 바꿀 점"을 채운다면 이 데이터가
   근거가 될 수 있다.

4. **관측 인프라를 파일 → sqlite로 대이관**(5-01, [156]). `.debug`의 jsonl 파일을
   전부 단일 `holdem.db`(WAL)로 옮기고 대시보드/전략이 sqlite를 참조하게 바꿈. 봇
   로직만큼이나 **"데이터를 어떻게 쌓고 볼 것인가"에 시간을 많이 썼다**(텔레메트리
   관련 작업이 초반부터 끝까지 반복됨).

5. **(참고) 같은 대회 참가자와 직접 붙음**: 너구리쿤 분석 리포트의 상대 목록에
   **`쪼랩익명이4`(95K 핸드)** 가 있다 — 이는 같은 레포의 **eunwoo 봇 이름**이다.
   즉 junho와 eunwoo는 **같은 테이블에서 실제로 맞붙었다**(단정은 아님, 이름 일치 근거).

> **다음 단계**: 위 섹션 7을 보고 섹션 6 회고(현재 전부 비어 있음)를 채우거나 그대로
> 둘지 결정한 뒤, 공유 레포에서 `git add junho/ && git commit && git push` 하세요.
> 특히 7-1의 "베이지안인 줄 몰랐다", 7-2의 "2등 blind-bleed"·"대회 결과"는 본인 기억과
> 대조해볼 가치가 큰 지점입니다.
