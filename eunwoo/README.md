# eunwoo — B-lab 홀덤 봇

> 토너먼트 R1·R2·R3 출전 봇 + 그 봇을 만들면서 Claude Code(Opus)와
> 어떻게 일했는지 기록.
> 1~5번 섹션은 Claude Code 자율 분석으로 자동 추출, 6번·자유 섹션은
> 사람이 직접 작성한다.

---

## 1. 봇 소개

**한 줄**: 캐시게임형 GTO 베이스(쪼랩이) → 토너먼트 점수표(1등 +35, 4-9등 -7~-10)
비대칭에 맞춰 1등률을 극대화하는 방향으로 두 차례 갈아엎은 끝에 만든
**Phase A(GtoBot, multi-way) / Phase B(WoozBot brain, HU·shorty) 라우팅
하이브리드 봇 = HybridBot**.

세션에서 사용자가 봇을 실제로 부른 이름들 그대로 옮기면:

- **쪼랩이(=GtoBot, `bots/gto.py`)** — 캐시게임형 GTO를 토너용으로 강화한 v1/v2.
  세션 안에서 "캐시게임형 GTO 봇 → 토너먼트 봇으로 전환"이라고 자기 정의함
  (`gto.py` 헤더 docstring + `c5f7f116-…` 세션의 4-hour patch plan).
- **HybridBot (`bots/hybrid_bot.py`)** — "쪼랩이 더 쎄다 → gto.py 강화"라는
  최초 가정을, 4897게임 누적 데이터에서 1등률 1위가 (직장동료의)
  Wooz brain이라는 사실을 보고 폐기하고, 두 검증된 brain을 한 봇 안에서
  자리수·shorty 조건으로 라우팅하는 형태로 수렴한 결과물.
  파일 헤더에는 "active 인원 ≤ 3 또는 누군가 effective_bb ≤ 6이면
  Phase B (Wooz brain). 그 외엔 Phase A (Gto brain)."라고 적혀 있음.

분류표(TAG/LAG/GTO 등)에 억지로 넣지 않은 이유: 세션 어디에도 "이건 GTO봇이야"
같은 라벨링 없이, 일관되게 **"점수표가 비대칭이라 1등률을 올려야 한다"**
라는 목표 함수만 반복적으로 나옴. 봇 자체보다 그 사고 흐름이 본체.

---

## 2. 핵심 전략

### 2-1. 쪼랩이 v2 (`bots/gto.py`) — 토너먼트 강화 GTO

`gto.py` docstring이 7-레이어 의사결정을 직접 정리해두고 있다 (요약):

```
1. 안전망       : decide()는 try/except 게이트. _decide_v2 실패시 _decide_legacy.
2. 효과스택 인지: my_stack/bb 계산 → Lv16+/eff_bb≤5/eff_bb≤10/일반 4분기
3. 푸쉬폴드     : preflop_strategy.decide_pushfold() 위임 (Chen 공식 기반)
4. ICM 압박     : 잔여인원 + 스택순위 → 마진핸드 fold 전환 / 칩리더 압박
5. 베이스 결정  : 프리플랍 GTO 차트 + 포스트플랍 equity/팟오즈 (legacy)
6. 변형 보정   : 방마다 랜덤 5개 프리셋이 임계/사이즈 조정
7. 익스플로잇  : 활성 상대 archetype 기반 룰 (충분 표본일 때)
```

쪼랩이가 보는 시그널:

- **스택 깊이 (effective_bb)** — `LV16_BB_THRESHOLD=1500` 이상이거나
  `eff_bb<=5`면 자동올인 모드, `eff_bb<=10`이면 푸쉬폴드 모드, 그 외는
  일반 GTO 흐름. (`bots/gto.py:_decide_v2`)
- **잔여 인원 + 스택 순위 → ICM 압박** — 4명 이하 버블에서 마진 콜을
  자동 폴드로 전환. 칩리더면 raise를 1.4× 증폭(약화 가능).
  (`bots/gto.py:_icm_pressure`, `_chipleader_factor`)
- **방별 변형(VARIANT)** — 같은 봇이 방마다 VALUE/TIGHT/AGGRO/LAG/PROBE 중
  하나로 플레이. 5-1 swap 후 1025게임 재측정 결과 AGGRO 30%/PROBE 25%/
  TIGHT 25%/VALUE 15%/LAG 5%로 가중치를 새로 박았음
  (`lib/strategy_variant.py:SAMPLE_WEIGHTS` + 주석에 출처 표기).
- **상대 archetype + tags** — `lib/opponent_tracker.py`가 세션 내내 살아서
  VPIP/PFR/3bet/F3b/AF/WTSD 누적 → station/tag/lag/nit/loose +
  passive/stubborn/calldown 태그를 붙임. `lib/exploit.py`가 베이스 결정 위에
  익스플로잇 룰 (vs station 사이즈+20%, vs nit 마진폴드, vs lag 블러프 캐치,
  F3b 누수 수정용 4벳 블러프 EV 분기 등) 을 얹는다.
- **프리플랍** — `lib/preflop_strategy.decide_preflop`이 6-max GTO 차트를
  내 뒤에 남은 액션 수 기준으로 동적 매핑해서 룩업, 변형이 사이즈만 곱한다.
  short-stack 모드에선 Chen 공식 + vs-random equity (사전 계산된 200k MC) 로
  Nash push-fold 결정.

### 2-2. HybridBot (`bots/hybrid_bot.py`) — Phase A/B 라우터

`should_use_phase_b(msg, seat_threshold=3, shorty_bb=6.0)`:
**활성 인원 ≤ 3** 이거나 **활성 인원 중 최저 effective_bb ≤ 6** 이면 Phase B.
4-handed에 한 명이 5bb 숏스택이면 테이블 다이내믹스가 HU에 가까우니까
Phase B로 미리 넘긴다는 휴리스틱 (파일 주석).

핵심 invariant: **두 brain의 state는 모든 WS 이벤트(game_start /
action_request / hand_result / game_end)에서 동시에 갱신**된다 — phase 전환
시점에 휴면 brain이 "장님" 상태가 되지 않도록. `_wooz_observe_action_only`가
Phase A 동안 wooz state만 미러 갱신하는 헬퍼.

### 2-3. 데이터 근거 — 왜 hybrid로 갔나

세션(`c5f7f116-…`, 2026-04-30) 안의 plan에 박힌 4897게임 표본:

```
봇          games  avg_rk  1st%  top3%  conv(1st/top3)
중랩이2     4849   4.50    7.0   37.3   18.8%
중랩이1     4839   4.55    8.0   37.3   21.4%
중랩이3     4871   4.57   10.1   38.4   26.3%
쪼랩익명이4 4967   4.77   12.0   36.1   33.2%
Wooz       …       …      …     …      58%
```

Wooz가 top3 진출 자체는 적지만(29%) 거기서 1등 컨버전이 58% — 양극화
패턴이 토너 점수표(1등만 수익)와 정확히 맞음. 이론 천장 0.373 × 0.583 ≈
21.7% 1등률. 그래서 "쪼랩이만 더 다듬자"가 아니라 **두 brain을 자리수로
스위칭하는 hybrid가 정답**으로 결론남.

---

## 3. 사용한 AI 도구 · 개발 과정

- **Claude Code (Opus, 1M context)** — 압도적 메인. CLI 안에서 `/ultraplan`,
  `/ultrawork`, `/deep-interview`, `/compact` 같은 oh-my-claudecode 슬래시
  커맨드를 적극 사용.
- **세션 수**: `~/.claude/projects/-Users-eunwoo-projects-coo-holdem-bot/`
  기준 약 **10개 .jsonl 세션**. 4월 5일 첫 스캐폴딩(`6a75400`)부터 5월 2일
  메인 README/B-lab 레포 셋업까지 약 4주.
- **레퍼런스 코드**: `references/pokerbot/`(직장동료 황의성 작) 코드를
  그대로 읽고 흡수 — `vendor/pokerbot/strategy.py`의 ExploitativeLAG /
  AdaptiveTAG / Macuil 두뇌를 우리 BotBase 어댑터(`bots/wooz_bot.py`,
  `hugo_bot.py`, `macuil_bot.py`)로 감싸서 사용. **이 세 어댑터 봇은 내가
  쓴 코드지만 두뇌 자체는 동료 코드** — 본 폴더의 `references/`에 별도로
  표시해 둠. (`bots/wooz_bot.py`는 hybrid_bot이 import하는 의존성이라
  `bots/`에도 동시에 둬야 했음.)

### 라운드별 봇 교체 이력 (확신도: R3=high, R1·R2=med)

세션 텍스트에 "R1에는 X, R2에는 Y를 출전시켰다" 같은 명시적 라운드 라인업
서술은 **없음**. 사용자도 별도 답변에서 "이건 내 대화 세션에서 찾아야지"
라고 함 — 즉 라운드별 봇 교체는 본인 기억으로만 정확히 안다. 아래는
**세션 안에 박힌 plan과 시간 순 코드 흔적으로 추정**한 것:

| 라운드 | 출전 봇 (추정) | 근거 |
|---|---|---|
| **R1** | `bots/gto.py` (쪼랩이 v1, gto 4-hour patch 결과) | 4-29 plan: "1단계 (R1 필수): 안전망 → 설정 파일 → 효과 스택 계산 → 푸쉬폴드 차트 → ICM 압박 감지 → wipe 스위치." 토너 직전 6봇 가동 1시간 누적 시점에 "쪼랩익명이4: gto.py (v1 + 변형 가중 + Nash push-fold + 동적 mw_tighten + chipleader 확장)" 로 명시. |
| **R2** | `bots/gto.py` 동일 + `lib/strategy_variant.py` SAMPLE_WEIGHTS swap 적용 본 | 5-1 07:26 "TIGHT 7→45, AGGRO 45→20" swap 후 PID 96582로 재시작한 기록. R2 직전 60분 수정창 시점과 일치. 다만 사용자 자신은 "쪼랩이가 처참해(쪼랩익명이4 -829점/1274게임)"라고 평가 — 그래서 R3에 hybrid로 교체. |
| **R3** | `bots/hybrid_bot.py` (HybridBot) | 4-30 13:18 plan + 14:00 폴백 카드("토너 중 hybrid가 이상하면 wooz_bot.py로 즉시 교체"). 5-1 06:36 `<command-args>쪼랩이 업데이트를 해야겠어</command-args>` 이후 hybrid가 메인. 마지막 커밋 `ddd63a5 feat: HybridBot — Phase A(GtoBot)/B(WoozBot) 라우팅 봇`이 R3 직전 시점. |

> **솔직한 한계**: 위 R1·R2 분리는 추정이다. R1·R2가 사실상 같은 `gto.py`에
> 60분 수정창에서 SAMPLE_WEIGHTS만 바꿔 끼운 정도라, 봇 파일 단위로 보면
> 둘 다 `gto.py`. R3만 hybrid_bot.py로 명확히 다르다. 그래서 본 폴더에는
> R1/R2 의 핵심을 담은 `bots/gto.py` + R3 = `bots/hybrid_bot.py` + 두 봇이
> 의존하는 모든 것을 묶었다. 그 외 `bots/new-*.py` 6종은 토너 출전봇이
> 아니라 **가동 중인 익명이 시리즈** — 시뮬 데이터 모집단 (위 4897게임의
> "다른 봇들") 으로 같이 돌렸음. 참고용으로 함께 둠.

### 3-A. 도구·에이전트 사용 양상 (정량)

세션 로그 약 10개 .jsonl 파일(4-20 ~ 5-20)에서 카운트한 실측 기반.
숫자가 작은 건 표본 한계지 의도된 게 아니다.

**슬래시 커맨드 사용 빈도 (실측, `<command-name>` 태그 기준)**

| 횟수 | 커맨드 |
|---|---|
| 5 | `/ultraplan` |
| 5 | `/compact` |
| 4 | `/login` |
| 1 | `/oh-my-claudecode:deep-interview` |
| 1 | `/statusline` |
| 1 | `/remote-control` |

> 다만 `<command-name>` 태그로는 안 잡힌 변종 호출이 더 있다. 예를 들어
> `<command-args>쪼랩이 업데이트를 해야겠어</command-args>` 같이 인자만 잡힌
> 케이스가 다수 — 실제 `/ultraplan` 호출 횟수는 그것보다 더 많을 수 있다.
> 인상으로는 `/ultraplan` 이 압도적 1티어, `/deep-interview`·`/compact` 가
> 2티어, 나머지는 1회성.

**MCP 도구 호출 양상**

실제 tool_use 이벤트에서 잡힌 MCP 호출은 **5회의
`mcp__plugin_oh-my-claudecode_t__state_write`** 한 종류뿐. 회고용
`session_search`나 메모용 `notepad_*` 같은 MCP는 거의 안 썼다. (도구
가용 목록에는 있었지만 실사용은 안 함.) 그 외 외부 도구 호출의 대부분은
표준 Bash/Read/Edit/Write/Grep 으로 처리.

**서브에이전트·역할 사용 (실측)**

`Agent` 툴 호출 총 52회. 내역:

| 횟수 | subagent_type | 어디에 썼나 |
|---|---|---|
| 35 | `general-purpose` | 큰 plan 의 Task 단위 구현 위임 (예: "Implement Task 1: 공통 헤더", "decide() rename + _decide_v2 도입", "8키 runtime.json 로더") |
| 6 | `oh-my-claudecode:code-reviewer` | 변경 후 spec/quality 리뷰 |
| 2 | `oh-my-claudecode:explore` | 레퍼런스 코드 탐색 |
| 2 | `oh-my-claudecode:planner` | ultraplan 내부 단계 |
| 2 | `oh-my-claudecode:architect` | ultraplan 내부 단계 |
| 2 | `oh-my-claudecode:critic` | ultraplan 내부 단계 |
| 2 | `claude-code-guide` | Claude Code 사용법 질문 |
| 1 | `statusline-setup` | statusline 설정 |

추가로 `TaskCreate`/`TaskUpdate` 가 39+76회 — plan 안의 task 단위를
체크리스트화해서 하나씩 처리한 흔적. 가장 큰 sessoin(`c5f7f116`,
gto v2 + hybrid 작업) 한 곳에 거의 다 몰림.

**자동화 vs 대화 비중**

`/ultraplan` → `general-purpose` 서브에이전트로 Task 줄줄이 위임하는
**자동화 흐름이 큰 변경 때마다 한 번씩 깔리고**, 그 사이는 사용자가 한두
줄짜리 대화형 지시(아래 4-(b))로 끊어 들어간다. 인상으로는
**자동화(슬래시 커맨드 + 서브에이전트) 30~40% / 직접 대화 60~70%**.
도구 카운트만 보면 표준 Bash/Read/Edit가 압도적(683/180/139회)이라
"대화 중에 직접 손대는" 비중이 분명히 더 컸다.

---

## 4. 프롬프트 스타일 (세션 텍스트 직접 인용)

### (a) 메타 규칙 — 반복 워크플로 패턴

세션 약 10개 표본에서 일관되게 보이는 4가지:

1. **"plan 먼저 → 실행" 두 단계**. 큰 변경 전엔 거의 항상 `/ultraplan`,
   `/ultrawork`, `/deep-interview` 같은 슬래시 커맨드로 plan 문서를 먼저
   떨궈둔다. `.omc/plans/gto-tournament-strengthen-v2.md`(202줄) 같은
   계획서가 있고, 그 다음에 코드 작업이 시작되는 패턴.
2. **데이터 근거 우선**. "휴리스틱이 맞다"고 결정 안 하고, 4897게임 / 1025게임
   같은 실제 표본을 돌려놓고 거기서 1등률·top3%·conv 비교 → 결정.
   `lib/strategy_variant.py:SAMPLE_WEIGHTS` 주석에 그 출처를 코드 안에까지
   적어둠.
3. **검증 명령 실제 실행**. claude가 "끝났어요"라고 말하면 거의 항상
   `pytest`, 또는 봇 재시작 + `tail -5 ... | grep` 으로 검증. 사용자 본인이
   `superpowers:verification-before-completion` 류를 강하게 적용.
4. **fallback 안전망 강박**. `bots/gto.py`의 `_decide_v2` → `_decide_legacy`,
   `decide()` try/except 게이트, `data/session_tracker.json` 30초 스냅샷,
   "토너 중 이상하면 wooz_bot.py로 즉시 교체" 폴백 카드 — 항상 회복 경로를
   먼저 만들어 둠.

### (b) 자주 쓰는 표현 패턴

- 결정을 시작할 때 거의 매번 **"지금 내가 결정해야하는것은?"** 한 줄.
  Claude가 옵션 A/B/C로 정리해서 던지면 짧게 **"진행해"** 또는 **"D로
  진행해봐"** 같이 한 글자 + 동사로 끊는다.
- 큰 가정에 의문 들 때 한 문장으로 물음 — **"우즈봇을 재가동해??"**,
  **"경기때는 봇 하나만 써야해 그럼 지금 쪼랩이로 충분하다는건가?"**
  (말끝에 `?` 두 개 / 단도직입형)
- AI가 헛다리 짚으면 **목표 자체를 재선언**하는 한 문장으로 끊어버림 (4-(c) 참조).

### (c) 결정적이었던 프롬프트 1~3개 (원문 그대로)

**프롬프트 1 — 프로젝트 방향 자체 재선언 (2026-04-29 16:40)**
직후 4-hour patch plan 승인 → `gto.py` 토너먼트 강화 (`6ad95c5`),
ICM/푸쉬폴드/칩리더 압박이 한꺼번에 들어감.

```
내가 쪼랩이랑 중랩2 만 놔두고 정리했어 어차피 이거 내가 만든 게임서버라
칩이 녹는것도 아니야 손실에 대해서도 문제없고 그리고 지금 손실을
이야기 하는거보니 이 프로젝트의 의의를 아예 놓치고 있나본데
'/Users/eunwoo/projects/coo/holdem-ai/docs/TOURNAMENT.md' 이 문서를 봐
이 게임 대회에서 우승하는 봇을 만들어야 한다고
```

**프롬프트 2 — pokerbot 레퍼런스 흡수 ultraplan 트리거 (2026-04-29 13:10)**
직후 `references/pokerbot/` 흡수 작업 시작 → `lib/range_estimator.py`,
`lib/equity_vs_range.py`, `lib/hand_eval.py`, `lib/poker_math.py` 신규,
`bots/gto_v2.py` + `vendor/pokerbot/`이 들어옴.

```
/ultraplan 홀덤 봇 프로젝트(holdem-bot)를 레퍼런스 프로젝트(pokerbot) 기반으로 레벨업하는 계획을 세워줘.

## 프로젝트 위치
- 우리 봇: /Users/eunwoo/projects/coo/holdem-bot/ (main 브랜치)
- 레퍼런스: /Users/eunwoo/projects/coo/holdem-bot/references/pokerbot/ (이미 클론 완료)

## 우리 봇 현황
- WebSocket 클라이언트가 holdem-ai 서버(...)
```

**프롬프트 3 — 데이터로 가정 뒤집기 (2026-04-30 02:42 → 2026-04-30 12:33 plan)**
이 짧은 한 줄이 **"쪼랩이만 강화"라는 4-hour plan을 폐기**시키고 hybrid로
방향 전환 — 직후 직장동료 brain들을 같은 풀에서 1시간 돌려본 데이터가
hybrid 채택의 근거가 됨.

```
우즈봇을 재가동해??
```

다음 턴에서 본인이 한 번 더 풀어 말함:

```
아냐 돌려도 상관은 없는데 돌려보는게 유의미한거냐고 질문하는거야
그렇다면 중랩 4번 5번을 우즈랑 휴고로 바꿔서 돌리면 되거든
```

### (d) 자주 등장한 키워드 (top 10, 사용자 발화 한정)

세션 로그 약 10개에서 사용자 메시지(총 363건)만 추려서 regex로 매칭한
실측. 단순 빈출어가 아니라 **이 사람이 자기 사고를 호명할 때 반복적으로
쓴 어휘**만 골랐다.

| 횟수 | 키워드 | 종류 |
|---:|---|---|
| 104 | `GTO` | 도메인 |
| 65 | `equity` | 도메인 |
| 62 | `익명이` | 메타 (자기 봇 풀 호칭) |
| 47 | `쪼랩이` | 메타 (자기 봇 호칭) |
| 47 | `데이터` | 메타 (근거 요구) |
| 44 | `우즈` | 메타 (동료 봇 호칭) |
| 39 | `토너(먼트)` | 메타 (목표 함수) |
| 31 | `하이브리드` | 도메인 (전략 형태) |
| 28 | `분석` | 메타 |
| 28 | `exploit` | 도메인 |
| 22 | `archetype` | 도메인 |
| 20 | `3bet` | 도메인 |
| 17 | `VPIP` | 도메인 |
| 16 | `push-fold` | 도메인 |
| 11 | `ICM` | 도메인 |

**도메인 어휘(GTO·equity·exploit·archetype·3bet·VPIP·push-fold·ICM
… ≈ 290회) vs 메타 어휘(데이터·분석·토너·검증·쪼랩이/우즈/익명이 호칭
… ≈ 250회) 비율 약 6 : 4.** 도메인 용어가 조금 더 잦지만, "**쪼랩이**·
**우즈**·**익명이**" 같이 봇을 의인화한 호칭과 "**데이터**·**토너**·
**분석**" 같은 결정 어휘가 같이 자주 나오는 게 특징. 도메인 용어를
던지면서도 그 위에서 결정의 무게중심을 데이터/봇 인격에 두는 흐름.

### (e) 초기 가설 + 프롬프트 톤

**초기 가설 (첫 5세션, 4-20 ~ 4-29 첫머리)**

처음 두 세션(`5ce99496`, 4-20 / `b3b47492`, 4-22)은 봇 컨셉 선언이 거의
없고 **테스트봇/스크립트 운영 디버깅**이 메인. 첫 명시적 방향 선언은
`b3b47492` (4-22) [USER 4-5]:

```
몬테카를로 알고리즘을 돌려보고 싶은데 참가자 9명 기반으로
```

```
아냐 아냐 다시 새로운 봇을 만들거야 new- 라는 접두사를 붙여서 만들건데

1. 봇 A: 'TAG (Tight-Aggressive)' - 정석 플레이어 (일명 '레귤러')
   HUD 스탯 목표: VPIP 20% / PFR 15% / 3Bet 7%
2. 봇 B: 'Calling Station (Loose-Passive)' - ATM 기기 (일명 '물고기')
   HUD 스탯 목표: VPIP 45% / PFR 5% / WTSD 45%
...
```

→ **HUD 스탯(VPIP/PFR/3Bet)을 목표 함수로 박은 archetype-별 봇 라인업**
이 초기 가설. **이 가설은 절반만 살아남았다** — `new-*.py` 6종은 끝까지
모집단 시뮬용으로 가동했지만(R1·R2·R3 출전 봇은 아님), **출전봇 자체는
4-29 ~ 4-30 사이에 "GTO 차트 + 토너 점수표 1등률 최적화"로 방향을 한 번,
다시 4-30 "우즈봇을 재가동해??" 한 줄로 hybrid 라우터로 한 번 더 갈아엎힘.**

세션 4(`0b9a65bd`, 4-29)에 들어가면서 톤이 바뀐다:

```
지금 돌아가는 쪼랩이를 강화하고 싶어 뭘 더 어떻게 강화하면 좋을지
/deep-interview  하자
```

→ 이때부터 "쪼랩이=GTO 베이스 봇" 가설이 메인이 되고, 4-29 16:40
프롬프트(4-(c) 프롬프트 1)에서 "**이 게임 대회에서 우승하는 봇을 만들어야
한다고**" 라고 목표 함수를 토너 우승으로 재선언함. 거기서부터 R3 까지의
경로가 깔린다.

**프롬프트 톤 (실측, 363건 user 메시지)**

| 종류 | 비율 | 예 |
|---|---:|---|
| 위임·질문형 ("어떻게", "뭐해야", "좋을까", 끝에 `?`) | **~43%** | "차트를 강화할 방법이 없을까", "그럼 포스트 플랍 데이터는 어떻게 개선할수 있지?", "우즈봇을 재가동해??" |
| 짧은 명령형 ("진행해", "정리해", "돌려줘", "바꿔") | **~9%** | "ㅇㅋ 진행해", "다 정리해 일단", "다시 돌려줘" |
| 그 외 (관찰·상태 진술·정보 제공) | 약 48% | "지금 게임 시작했어", "로그 잘 남고 있네", "에러 뜬다" |

**결정 무게중심의 인상**: 위임·질문 비중이 명령보다 4~5배 많지만,
질문은 "**A가 맞아 B가 맞아 골라줘**"가 아니라 "**이 가정이 유의미하냐**"
같이 **AI에게 가정 자체를 흔들어달라는 요청**이 많다. 즉 큰 방향은
본인이 잡되, **방향 자체의 검증을 AI에게 던지는** 패턴. 그래서 한 줄
질문 ("우즈봇을 재가동해??")이 4-hour plan 을 폐기시킨 것 같은 일이
일어난다.

---

## 5. 돌리는 방법

### 의존성

```
websockets>=12.0
pydantic>=2.0   # vendor/pokerbot/models.py 가 사용
```

`requirements.txt` 참조.

### 실행 (단일 봇)

```bash
cd eunwoo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# R3 출전 봇 = HybridBot (기본값)
bash run.sh ws://localhost:5051/ws "<API_TOKEN>" "쪼랩이"

# R1·R2 출전 봇 = GtoBot (쪼랩이 v2)
bash run.sh ws://localhost:5051/ws "<API_TOKEN>" "쪼랩이" --bot gto

# 대회 시작 직전 1회만 — 누적 트래커 wipe
bash run.sh ws://localhost:5051/ws "<API_TOKEN>" "쪼랩이" --reset
```

### 인자

| 위치 | 의미 | 예 |
|---|---|---|
| `$1` | WS 서버 URL | `ws://localhost:5051/ws` |
| `$2` | API 토큰 | (서버에서 발급받은 봇 토큰) |
| `$3` | 봇 표시 이름 | `쪼랩이` / `1` 등 |
| `--bot` | `gto` 또는 `hybrid` (기본 `hybrid`) | `--bot gto` |
| `--reset` | `data/session_tracker.json` 초기화 | (대회 시작시 1회) |

### 환경 변수

`run.sh`가 `PYTHONPATH=eunwoo/` 를 자동으로 박는다. `bots/hybrid_bot.py` 와
`bots/wooz_bot.py` 는 자기 부모 디렉토리에 있는 `vendor/pokerbot/` 를 직접
`sys.path.insert(0, …)` 한다.

### 60분 수정창 튜닝 키

`config/runtime.json` 한 파일에 다 모여 있음. 세션 안에서 한 번에 한 키씩만
조정한다는 규칙으로 돌렸음:

```json
{
  "pushfold_tightness": 1.0,
  "icm_pressure_threshold": 0.6,
  "icm_fold_bonus": 0.05,
  "chipleader_aggro_mult": 1.4,
  "fold_equity_margin": 0.0,
  "fallback_to_legacy_on_error": true,
  "exploit_enabled": true,
  "min_hands_for_classification": 30
}
```

### 폴더 안에 들어 있는 것

```
eunwoo/
├── README.md
├── requirements.txt
├── run.sh
├── bots/
│   ├── gto.py            ← **R1·R2 출전 봇** (쪼랩이 v2 = GtoBot)
│   ├── hybrid_bot.py     ← **R3 출전 봇** (HybridBot)
│   ├── wooz_bot.py       ← _레퍼런스 (직장동료에게서 받음, 내 게 아님)._
│   │                       hybrid_bot이 import하므로 함께 둠. 출전 X.
│   ├── new-tag.py        ← **테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)**
│   ├── new-rock.py       ← **테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)**
│   ├── new-wild.py       ← **테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)**
│   ├── new-maniac.py     ← **테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)**
│   ├── new-station.py    ← **테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)**
│   ├── new-passive.py    ← **테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)**
│   └── __init__.py
│
│   > **출전봇은 `gto.py` (R1·R2) 와 `hybrid_bot.py` (R3) 두 개뿐.**
│   > `new-*.py` 6종은 4-22 archetype 라인업의 잔재로, 출전하지 않고
│   > **시뮬 모집단 (4897게임 표본의 "다른 봇들")** 으로만 가동했다.
├── lib/                  ← gto.py 가 의존하는 모듈들 (전부 내가 작성)
│   ├── bot_base.py        ← WS 연결/인증/재접속/로깅 (공통)
│   ├── logger.py          ← 핸드 단위 JSON 로거
│   ├── config.py          ← runtime.json 로더
│   ├── equity.py          ← 몬테카를로 에쿼티 (treys 안 씀, 자체 구현)
│   ├── preflop_charts.py  ← 6-max GTO 차트 룩업
│   ├── preflop_strategy.py ← decide_preflop / decide_pushfold (Nash + Chen)
│   ├── strategy_variant.py ← VALUE/TIGHT/AGGRO/LAG/PROBE 5변형 + 가중 샘플
│   ├── opponent_tracker.py ← VPIP/PFR/3bet/F3b/AF/WTSD → archetype 분류
│   ├── exploit.py          ← archetype 기반 익스플로잇 룰
│   ├── poker_math.py       ← pot_odds/mdf/alpha/ev_call/ev_bluff/implied
│   └── __init__.py
├── data/
│   ├── preflop_charts.json
│   └── preflop_equity_vs_random.csv  ← 200k MC 사전계산
├── config/
│   └── runtime.json       ← 60분 수정창 튜닝 키
├── vendor/                ← _레퍼런스 (직장동료 pokerbot 코드, 내 게 아님)._
│   └── pokerbot/          hybrid 의 Phase B brain 이라 import 필요해서 동봉.
│       ├── strategy.py    ← ExploitativeLAG / AdaptiveTAG (1189줄)
│       ├── profiler.py / game_state.py / hot_config.py / models.py
│       ├── hand_eval.py / equity.py / poker_math.py
│       ├── preflop_equity.py / preflop_equity_matrix.json
│       ├── range_estimator.py
│       └── strategy_config.json
└── references/            ← 동료에게서 받은 어댑터들 (참고용)
    ├── wooz_bot.py        ← bots/와 동일. 출처 명시용 사본.
    ├── hugo_bot.py        ← AdaptiveTAG 어댑터 (R3 hybrid 와 무관)
    └── macuil_bot.py      ← Macuil(EV-max) 어댑터 (R3 hybrid 와 무관)
```

---

## 6. 시행착오 · 회고

홀덤에 대한 지식이 어느정도 갖춰져있는 상태에서, 다른 기존 인원들보다 홀덤을 잘 알고있는 상태에서 만들었음에도 6명중 5등을 하였음.
어줍잖게 알고 있는 지식이 독이 되었던거 같은데 아직까진 잘 이해되지 않음
홀덤에서 기본적으로 중요한 개념인 GTO를 기반으로 플레이 한게 상대방들의 알고리즘에 비해 부족했던건지 아님 룰때문에 생긴 이슈인건지 싶음

어찌되었건 어중간한 지식으로 지시하는것보단 차라리 하나부터 열까지 모든 작업을 오히려 ai 에게 맡기는게 더 나을지도 모른다는 결과를 얻게 되었음 

### 도메인 지식

- **홀덤에 대해 아는 정도** — 중급~숙련. 아마추어 대회 출전 경험 있음.
- **그 지식이 봇 만들기에 어떻게 작용했나** — 오히려 독으로 작용.
  "GTO 기반"이라는 신념이 가설 공간을 너무 일찍 좁혔음. 4897게임 누적
  데이터로 흔들리기 전까지 "쪼랩이만 강화" 방향에 시간을 썼고, 결국
  토너 점수표(1등 +35, 4-9등 -7~-10) 비대칭과 GTO(=EV 균등화) 가정이
  근본적으로 안 맞는다는 걸 데이터로 확인하고 나서야 hybrid로 갈아엎음.
  (상단 자유 회고 참조 — "차라리 하나부터 열까지 AI에게 맡기는 게
  나을지도".)

### 시행착오

- **실패한 접근 또는 폐기한 가설** —
  4-22에 `new-*.py` 6봇 archetype 라인업(TAG / Calling Station / Maniac /
  Wild / Rock / Passive)을 만들었지만 출전봇으로 밀고 가지 않고 모집단
  시뮬용으로만 가동. 4-29 "쪼랩이만 강화" 4-hour plan은 이튿날 4-30
  13:18 plan으로 폐기되고 hybrid 라우터 방향으로 전환 — 폐기 근거는
  4897게임 누적 conv 표(Wooz brain의 1등 conv 58%)와 본인의 한 줄
  자문 "우즈봇을 재가동해??". 그 후 60분 수정창에서 SAMPLE_WEIGHTS
  swap(TIGHT 7→45, AGGRO 45→20) 후 쪼랩이가 -829점/1274게임으로
  무너진 시점은 R2 직전에 가설 변경의 비용을 직접 본 순간.

- **다음에 만든다면 바꿀 점** —
  자료 기반 추론으로는 (a) R1 직전에 누적 트래커 인프라부터 돌려서
  데이터를 일찍 모았다면 4-22 archetype 6봇 시리즈를 더 빠르게
  폐기할 수 있었을 것, (b) hybrid 라우터를 R1부터 도입했다면 R1·R2의
  GTO 강화 작업 시간을 hybrid 튜닝에 쓸 수 있었을 것.
  _본인 판단으로 보강·정정 필요._

- **의외였던 깨달음** —
  Wooz brain의 4897게임 표본 결과 — top3 진출률은 약 29%로 낮지만
  그 안에서 1등 conv가 58%로 양극화된 패턴. 이론 천장
  0.373 × 0.583 ≈ 21.7% 1등률. 토너 점수표(1등만 수익) 비대칭과
  정확히 맞물리면서 "GTO = EV 균등화"가 토너에 부적합하다는 결정을
  데이터로 확정시킨 사실.

---

## 7. 회고 검토

자동 추출(섹션 1~5)이 본 자료와, 사용자가 적은 회고(섹션 6 상단 자유 4줄 + 도메인 지식 + 시행착오) 사이의 정합성 검토.

### 회고 ↔ 자료 불일치
없음. 사용자 회고("어줍잖은 지식이 독", "GTO 기반 플레이가 부족", "차라리 AI에게 다 맡기는 게 나았을지도")는 자동 추출 자료와 충돌하지 않으며 오히려 자료가 회고를 뒷받침한다.

### 회고가 추측으로 남긴 항목 중 자료가 답을 주는 경우
- 사용자 회고: "GTO를 기반으로 플레이한 게 상대방 알고리즘에 비해 부족했던 건지, 아님 룰 때문에 생긴 이슈인건지 싶음" — 추측으로 남김.
- 자료가 시사하는 답: **둘 다**.
  1. **4897게임 누적 conv 표** (섹션 2-3): GTO 기반 쪼랩이/중랩이 1등률 7~10%, Wooz brain 약 16.8%. → GTO 기반이 상대 brain 대비 1등률에서 부족했음이 데이터로 확인됨.
  2. **점수표 비대칭** (1등 +35, 4-9등 -7~-10): GTO = EV 균등화 가정이 1등만 수익인 룰과 정면 충돌. → 룰이 GTO 가정을 무력화시킨 측면도 동시에 존재.
- 즉 "GTO 부족"과 "룰 이슈"는 분리된 가설이 아니라 같은 현상의 두 얼굴.

### 회고에서 빠진 큰 사건
- **R1·R2 분리의 추정 한계** — 사용자 회고에 라운드별 라인업이 명시되지 않음. 자료에서도 R1·R2 모두 `bots/gto.py`로 추정만 가능 (확신도 med). 본인 기억으로 정정 가능한 영역.
- **(자유) 섹션 비어 있음** — 대회 성적·코드 아키텍처·다음 계획 등 자유롭게 추가하면 자료 가치가 늘어남. (이번 README에서는 생략.)
