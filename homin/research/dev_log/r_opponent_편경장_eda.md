# 편경장 EDA · 전략 설계

## Status
- **Stage**: Draft
- **Created**: 2026-04-22
- **Sources**: `data/profiles.db` (hands=3791) · `data/logs/games/*.jsonl` (파싱 2,908 hand actions)
- **Goal**: 편경장 특화 알고리즘 최적화를 위한 경향 파악 및 전략 도출

## 1. 원천 수치 (전역 프로필)

| metric | α | β | rate | n |
|---|---|---|---|---|
| VPIP | 454 | 3337 | **12.0%** | 3791 |
| PFR | 127 | 3664 | **3.4%** | 3791 |
| THREE_BET | 86 | 368 | 18.9% | 454 |
| FOLD_TO_THREE_BET | 20 | 32 | 38.5% | 52 |
| CBET | 15 | 14 | 51.7% | 29 |
| FOLD_TO_CBET | 9 | 2 | 81.8% | 11 |
| BARREL_TURN | 5 | 2 | 71.4% | 7 |
| BARREL_RIVER | 3 | 0 | 100% | 3 |
| CHECK_RAISE | 0 | 109 | **0%** | 109 |

### Dirichlet 응답 분포 (facing bet)
| phase | fold | call | raise | n |
|---|---|---|---|---|
| preflop | 85.1% | 0.6% | 14.3% | 3310 |
| flop    | 26.2% | 9.5% | 64.3% |   42 |
| turn    | 21.4% | 4.8% | 73.8% |   42 |
| river   |  7.4% | 3.7% | 88.9% |   27 |

### 로그 기반 보강
- **우리(whoareyou) 오픈에 대한 편경장 반응 (n=107)**: fold **91.6%**, call 6.5%, raise 1.9%.
- **첫 행동(opening)**: fold 71.7% / call 8.8% / raise 6.8% / check 12.6% (n=2,908).
- **raise 사이즈 중앙값**: preflop 0.62×pot (≈3bb open), flop·turn·river 0.37×pot (**일관되게 ⅓팟**).
- **포지션 편향**: postflop 도달의 80% 이상이 BB. 즉 postflop 관측은 대부분 "BB 로 call 한 뒤" 상황.

## 2. 핵심 경향 (3줄 요약)

1. **프리플롭 초(超) nit — 4% 오픈, 12% VPIP.** 대부분 fold. 우리의 raise 에 91.6% fold.
2. **폴드하거나, 올인급으로 공격.** 콜이 거의 없다 (preflop 0.6%). "raise-or-fold" 양극 스타일.
3. **사이즈는 작다.** 어느 스트리트든 ⅓팟 근처. 3bet/올인 같은 결정타가 드물어 **cheap 한 리레이즈로 쉽게 접힘**.

## 3. 전략 설계 — 5대 축

### A. 스틸(도둑) 대폭 강화
- 근거: 편경장의 fold vs-our-raise = **91.6%**. 2bb 오픈 alpha = 40.0%, 3bb alpha = 50.0%. 두 사이즈 모두 큰 폭으로 초과.
- EV(2bb steal) ≈ **+2.70 bb/핸드** (eq 0.35 가정).
- **실행**: BTN/CO/SB 에서 편경장이 BB 에 있을 때 **72o 포함 top 80%** 까지 오픈. 2–2.5bb **min raise** 선호(비용 최소화).
- 3bb/4bb 도 EV 차이 미미하므로 **상대 raise 관측이 없을 때는 2.5bb** 일관.

### B. 편경장의 raise 는 거의 항상 value → 접는다
- preflop raise 는 14% 전체 액션 중에서도 THREE_BET 18.9% 가 대부분. 매우 tight (대략 top 4–6% 핸드).
- **실행**:
  - 우리가 오픈했는데 편경장이 3bet → **TT- / AQs- / AJo- 전부 fold**. 콜드 콜 금지. 4bet 은 **QQ+, AKs** 만.
  - 포스트플롭 raise/re-raise 는 value 편향 (BARREL_RIVER 100%, BLUFF_AT_SHOWDOWN 0 관측). **Two pair 이하면 fold**.

### C. 편경장이 call 했다면 → c-bet 100%
- Dirichlet 콜 비율 preflop 0.6% (거의 안 함). 콜 = tight-call 의 약 A·K·Q 미들페어 류.
- FOLD_TO_CBET 81.8% (n=11, 신뢰 중). **플랍 ⅔팟 c-bet 전부** → 블러프 EV 압도.
- 턴/리버까지 배럴할지는 **보드 + BARREL_TURN 71% / BARREL_RIVER 100%** 관측 고려 — **그들이 콜로 버틴 뒤 턴에 raise 하면 value 로 읽고 fold**.

### D. BB 로 편경장이 있을 때 블러프 3bet 금지 (포스트플롭 donk 위험)
- postflop 도달의 대부분이 BB defense 샘플. 이들이 flop 에서 raise 64%, turn raise 74%, river raise 89% → **들어오면 곤봉**.
- BB 편경장 대비 sb-open 은 하되, **콜 받았을 때 보드가 monotone/paired/wet 하면 c-bet 포기**. 단순 dry 보드에서만 c-bet. 
- 스프로딩 턴/리버 블러프 금지 (their raise rate 73–89% = loss-capped loss).

### E. check-raise 는 **안전한 자유 익스플로잇**
- CHECK_RAISE 0/109 = 0%. 109번 기회 모두 check 유지.
- **실행**: 편경장이 PFR 이어도 check-back 을 받은 우리가 턴 probe 시 **100% 보장 no CR**. 이 구간에 블러프 성공률 극대화.
- 포지션 잡히면: **flop 체크백 → 턴 ½ pot probe bet** 공식화.

## 4. 파라미터화 제안 (`configs/opponent_overrides.yaml` 초안)

```yaml
# 대상 이름 매칭은 exact ("편경장")
편경장:
  tags: [nit_polar, fold_heavy]
  preflop:
    steal_open_multiplier: 1.8       # policy 의 open range 를 1.8x 확장
    default_open_bb: 2.5              # min-raise 선호 (alpha 에 여유)
    vs_3bet_fold_threshold: 0.25     # 상위 25% 핸드만 call/4bet. 그 외 fold
    4bet_value_only: true            # 블러프 4bet 금지
    cold_call_vs_raise: false        # 편경장이 raise 했을 때 콜 금지
  postflop:
    cbet_against_caller: 1.0         # 콜 받으면 100% c-bet
    bluff_raise_faced: 0.0           # 이들이 raise 하면 블러프 콜/re-raise 금지
    fold_to_their_raise_threshold: "two_pair"   # two_pair 미만 fold
    exploit_no_check_raise: true     # 체크 뒤 probe bet 활성화
  sizing:
    c_bet: 0.66                       # ⅔ pot — 상대 fold 81% 에 최적 사이즈
    turn_probe_after_checkback: 0.50
  notes: |
    91.6% preflop fold → 2–2.5bb 스틸 EV 최대화.
    CHECK_RAISE 0/109 → 우리 delayed c-bet 안전.
    postflop 도달 시 BB 편향, raise 하면 value-heavy.
```

## 5. 구현 경로 (policy 우선순위 1~3 추천)

| # | 파일/모듈 | 변경 | 예상 LoC |
|---|---|---|---|
| 1 | `src/holdem/decide/opponent_overrides.py` (신설) | `configs/opponent_overrides.yaml` 로더 + `apply_overrides(decision, opp_name)` | 80 |
| 2 | `src/holdem/decide/policy.py` | `decide()` 말미에 override 훅; preflop open range multiplier, vs-their-raise tightening | 40 |
| 3 | `src/holdem/decide/sizing.py` | cbet_against_caller / turn_probe_after_checkback 파라미터 배선 | 20 |
| 4 | `tests/test_opponent_overrides.py` | 편경장 고정 fixture: steal 범위 확장 / 3bet 대응 fold / c-bet 강제 | 70 |
| 5 | `src/holdem/dashboard/static/index.html` | 프로필 테이블에 "override 적용 중" 뱃지 | 15 |

### 안전장치
- override 는 **n_personal ≥ 300** 일 때만 적용 (편경장 3791 — 충분).
- 동일 이름의 다른 타입(bot/human) 구분은 추후.
- override on/off 토글 `configs/opponent_overrides.yaml` 의 `enabled: true/false`.

## 6. Limitations
1. **Postflop 표본 극소** — flop/turn/river Dirichlet n=42/42/27. BARREL_RIVER 100% 는 n=3.
2. **BB 편향** — postflop 도달의 80% 가 BB. 이들이 다른 포지션에서 보이는 성향 미관측.
3. **쇼다운 카드 0건** — 우리는 폴드가 많아서 편경장의 실제 range 를 확인 못 함. range 추정은 간접(fold/raise rate)만.
4. **상대 풀 분포 변화** — 대회 본선 기간에는 편경장이 없을 가능성. override 는 배정 시 활성되도록.

## 7. Next Step
1. `configs/opponent_overrides.yaml` 스켈레톤 작성 + 편경장 항목.
2. `opponent_overrides.py` 모듈 + 단위 테스트.
3. sim 상에서 편경장 프록시(`class_fold_heavy` 베이스라인 5-7bb/100 fold 비율) 생성 후 override on/off A/B.
4. 실서버에 override on 배포 → 1일 관측 → winrate 반영.

## Changelog
- 2026-04-22 (v0.1): 초기 EDA + 전략 초안.
