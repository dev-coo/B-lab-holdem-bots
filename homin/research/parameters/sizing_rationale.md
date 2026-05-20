# Sizing Grid — 수치·정책 근거 (sizing.yaml)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: `configs/sizing.yaml` v0.1
- **Sources**:
  - `research/dataset_analysis/eda_04_sizing.md` v0.1 (HU 2.06M hands, 4.3M decisions)
  - plan Section I.1 (보수적 sizing grid)
  - plan Section H.1 (shrinkage → n_effective 단일 스칼라)
- **BOT_GUIDE refs**: §5.3 (action_request.pot), §6.2 (raise amount = round total)

---

## 1. 결정 요약

3-tier sizing grid 를 **n_effective 단일 스칼라로 자동 전환**:

| Grid | 진입 조건 | value 최대 | bluff 옵션 | all-in 허용 |
|---|---|---:|---|---|
| **conservative** | n < 30 | **0.67 × pot** | [0.33] 단일 | nash/eq≥0.85/forced 만 |
| **balanced** | 30 ≤ n < 150 | **1.00 × pot** | [0.33, 0.50] | 표준 EV 트리 |
| **exploit** | n ≥ 150 | **2.00 × pot** | [0.50, 1.00] polarized | 개인 AF 기반 |

n_effective 임계값은 `configs/conservatism_schedule.yaml` 의 schedule 과 **정확히 정합**한다 (교차 `configs_dryload.py` 검증).

---

## 2. 왜 3-tier 인가

### 2.1 단일 grid 는 두 실패 모드를 낳는다

- **영구 공격적 grid**: 콜드 스타트에서 큰 오버벳이 음수 EV → 토너먼트 조기 탈락.
- **영구 보수 grid**: 데이터 누적 후에도 착취 기회 상실 → 정상화된 상대에게 exploitable.

3-tier 는 **CB5 원칙** (보수성은 일시적) 을 구조적으로 강제. n_effective 가 한 스칼라로 이동하면 sizing 도 따라 이동.

### 2.2 왜 3-tier (4 나 5 가 아니라)

- n_effective 함수의 curvature 가 3 구간을 넘어서는 구분력을 주지 않음. `conservatism_schedule.yaml` 은 6 mode 로 세분화하지만 sizing grid 는 그 상위 추상.
- 6 mode × 5 grid = 조합 폭발. **mode → grid 매핑은 3:2:1 고정**:
  - hard_conservative + conservative → conservative
  - transitional + near_balanced + balanced → balanced
  - exploit_ready → exploit

---

## 3. 각 grid 의 수치 근거

### 3.1 Conservative grid

```yaml
value_bet:   [0.33, 0.50]
bluff_bet:   [0.33]
protection:  [0.50, 0.67]
raise_open_bb: [2.2, 2.5]
three_bet_multiplier: [2.8, 3.0]
max_bet_to_pot: 0.67
```

**수치 근거**:

- **value_bet [0.33, 0.50]**: eda_04 §4.2 에서 관측된 LLM peaks 중 **가장 작은 두 모드** (0.50 pot share 11.6%, 0.33 pot share 2.8%). 이보다 더 큰 0.67+ 모드는 제외.
  - **왜**: 저데이터에서 상대 fold_to_bet 모름. `EV(raise@S) = f·P + (1-f)·[eq·(P+2ΔS) - ΔS]` 에서 S 불확실성이 ΔS 에 곱으로 들어가 **Var(EV) 초선형 증가**. 작은 S 는 EV 기대값은 낮추지만 variance 감쇠가 더 크다.

- **bluff_bet [0.33] 단일**: 사이즈 선택이 **정보를 새지 않게** 함. 두 사이즈 혼합하면 "큰 사이즈 = 블러핑" 같은 시그널이 데이터 부족 구간에 누적 오해 생성.

- **raise_open_bb [2.2, 2.5]**: min raise (2.0) 보다 약간 큰 사이즈. 3.0bb+ 의 "표준 오픈" 을 하지 않는 이유 = 콜드 스타트에서 3bet call 범위 모름 → 투입 비용 최소화.

- **max_bet_to_pot 0.67**: hard cap. EV 엔진이 0.75, 1.0 을 최선으로 골라도 grid 가 그 범위를 제공하지 않으면 자동 거절.

- **no_allin_unless**: 4 개 예외 조건. I.8 의 `veto_allin()` 과 정합. Nash 차트가 지시하거나, 거의 확정 nuts 거나, 스택이 too short 거나, call 이 구조적으로 all-in 인 경우만.

### 3.2 Balanced grid

```yaml
value_bet:   [0.33, 0.50, 0.67, 1.00]
bluff_bet:   [0.33, 0.50]
protection:  [0.50, 0.67, 1.00]
raise_open_bb: [2.2, 2.5, 3.0]
three_bet_multiplier: [2.8, 3.0, 3.5]
max_bet_to_pot: 1.00
```

- **value_bet [0.33, 0.50, 0.67, 1.00]**: eda_04 의 4 개 주요 peak. LLM 풀 관측 peak 4 개는 [0.50, 0.67, 1.00, 1.25~1.50] 인데 이 중 1.5+ 는 **overbet** 으로 분류 → exploit grid 이후로 미룸.
- **bluff_bet [0.33, 0.50]**: polarized 미도입. 30 < n < 150 구간은 개인 posterior 가 막 의미를 가지기 시작한 구간 → 작은/중간 bluff 사이즈만.
- **max_bet_to_pot 1.00**: pot-size 까지만. overbet 은 exploit 단계.

### 3.3 Exploit grid

```yaml
value_bet:   [0.33, 0.50, 0.67, 1.00, 1.50]
bluff_bet:   [0.50, 1.00]           # polarized
protection:  [0.50, 0.67, 1.00]
raise_open_bb: [2.2, 2.5, 3.0, 3.5]
three_bet_multiplier: [2.8, 3.0, 3.5, 4.0]
max_bet_to_pot: 2.00
```

- **overbet 1.5 허용**: 개인 posterior 확신 있음 (n ≥ 150). 상대가 특정 블러핑 잡기 실수를 보였을 때 value 극대화.
- **bluff_bet [0.50, 1.00] polarized**: 작은 블러핑은 drawing hand, 큰 블러핑은 pure air. GTO 문헌의 polarized 전략.
- **max_bet_to_pot 2.00**: hard cap 완화. 2.5+ 는 없음 — 서버 30s timeout 안에서도 안전.

---

## 4. 관측값 ↔ 정책값의 간극 (LLM → 인간 전이)

### 4.1 overbet 빈도

- **관측 (eda_04 §4.2)**: LLM 풀 overbet (≥ 1.5×pot) 비율 **약 35%**. Pot 이상 (≥ 1.0) 은 **49%**.
- **가정 (인간 풀)**: overbet < 10%, pot 이상 < 25%.
- **처리**: LLM observed peaks 는 `sizing.yaml` 의 `observed_llm_peaks_raw` 블록에 **참조용으로만 보존**. grid 에는 반영 안 함.

### 4.2 bluff ↔ value sizing 분리

- **관측**: flop/turn 에서 **동일 사이즈**. river 에서는 **역방향** (bluff > value).
- **가정**: 인간 풀은 value-heavy bias 를 가짐 (value 가 더 크거나 동일).
- **처리**: LLM 의 역방향 패턴을 grid 에 적용하지 **않음**. bluff_bet / value_bet 은 각각 별도 목록.

### 4.3 사이즈-equity 선형 상승 부재

- **관측**: equity bucket 별 사이즈 중앙값이 평탄 (0.50 → 0.67 → 0.67 → 0.67 → 0.67).
- **가정**: 인간 풀에서는 nuts 일수록 큰 사이즈.
- **처리**: grid 의 value_bet 목록 범위 내에서 **EV 엔진이 equity 기반 최적 선택** 하도록 위임 (여기서 강제하지 않음).

---

## 5. Conservatism schedule 과의 정합

`configs/conservatism_schedule.yaml` 의 6 mode 매핑:

| mode | n_max | sizing_grid | bluff_factor | allow_allin |
|---|---:|---|---:|---|
| hard_conservative | 10 | conservative | 0.50 | false |
| conservative | 30 | conservative | 0.65 | false |
| transitional | 80 | balanced | 0.80 | true |
| near_balanced | 150 | balanced | 0.92 | true |
| balanced | 400 | balanced | 1.00 | true |
| exploit_ready | null | exploit | personal_AF_based | true |

**검증**: `scripts/configs_dryload.py` 의 `check_sizing_grid_consistency()` 가 mode_params.sizing_grid 의 모든 값이 sizing.yaml 의 grid 라벨과 일치함을 **실행 시 강제**.

---

## 6. 수학적 일관성 (I.11 공리)

최적 액션 선택:

```
a* = argmax_a [ log(E[stack_after_a] + δ) - κ(n, M, level) · Var[stack_after_a] ]
     subject to sizing_candidates ∈ current_grid
                action ∉ vetoed_allin (I.8.b)
```

- grid 축소 = `argmax` 의 feasible set 축소.
- 이는 `κ · Var` 항의 curvature 증가와 **동치** (Lagrangian 쌍대):
  - Conservative grid: 큰 S 를 거부 = κ 를 큰 S 방향으로 증가시킨 것과 동등.
- **장점**: 런타임은 discrete grid lookup 만 수행 → O(1). κ 계산·Var 적분 없음.

---

## 7. Limitations · Risks

| 리스크 | 완화 |
|---|---|
| **인간 풀에 grid 경계가 맞지 않을 수 있음** | R4 bootstrap + 실서버 O3 winrate 로 검증. 벗어나면 v0.2 수정 |
| **bet vs raise 미분리** (eda_04 §7) | eda_04.1 에서 분리 재집계. grid 는 raise 우선 해석 |
| **Preflop sizing 은 BB 단위, postflop 은 pot 단위** — 혼용 위험 | `raise_open_bb` / `three_bet_multiplier` 는 bb, 그 외는 pot 단위로 명시 분리 |
| **grid 전환의 hysteresis 부재** | n_effective 가 30, 150 경계를 오르내릴 때 grid 가 깜빡일 수 있음 → 실무에서는 ±3 hand hysteresis 고려 |
| **overbet 공격 대응 미정** | LLM 풀 대비 49% overbet 에 우리 봇이 어떻게 반응할지는 **decide/defense.py** (H.4 MDF) 에서 별도 처리 |
| **uncalled bet return 영향** | §4.1 pot_before 정의 모호성. 실서버 로그에서 post-uncalled pot 재정규화 |

---

## 8. Next Steps

- **D6 단계 (주 11)**: `src/holdem/decide/sizing.py` 구현. grid lookup + EV argmax 통합.
- **D4 단계 (주 7)**: `conservatism_schedule.yaml` 과 sizing 연결. Profile 주입.
- **R4 bootstrap**: 10k self-play 핸드 sizing 분포 수집 → 인간/GTO 풀에서 예상 peak 와 비교.
- **R6 A/B**: conservative on/off, 10k 핸드 → BB/100, ITM rate, variance 비교.
- **sizing_bluff_rate** (eda_04 §4.2): U-shape 관측 (39~47% 변동). **sizing 이 bluff 신호 아님** 확인. EV 엔진은 equity 우선.

---

## 9. References

- [1] `research/dataset_analysis/eda_04_sizing.md` v0.1
- [2] `research/dataset_analysis/eda_05_bluff_threshold.md` v0.2 (sizing 신호 검증)
- [3] plan Section I.1 (Conservative sizing), I.8 (All-in veto), I.11 (수학적 공리)
- [4] `research/parameters/conservatism_schedule_rationale.md`

---

## Changelog

- 2026-04-19 (v0.1): eda_04 §4 + plan I.1 통합 초안. 3-tier grid + n_effective 전환 확정.
