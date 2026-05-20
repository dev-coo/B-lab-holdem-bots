# D4 Week 7 — ConservatismProfile 엔진

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Related code**: `src/holdem/decide/conservatism.py`, `src/holdem/decide/policy.py`
- **Related configs**: `configs/conservatism_schedule.yaml`, `configs/sizing.yaml`
- **Related BOT_GUIDE sections**: §6.2 (raise total), §11 (M 구간)

## 1. Objective
plan I.9.b 단일 프로파일 엔진을 구현하고, 현재 의사결정 경로(preflop RFI) 에 얕게
배선한다. 남은 항목(all-in veto, bluff factor, pot control) 은 해당 action 이 실제로
생성되는 D5+ 에서 본격 사용.

## 2. BOT_GUIDE Compliance
- [§6.2] raise 는 총 베팅액 — RFI 사이즈 계산은 `round(size_bb * BB)` 그대로 적용.
- [§11] M 구간(deep/mid/hybrid/push_fold) 은 mode_selector 가 별도로 결정.
  Conservatism 은 "data confidence" 축이며 M 과 직교.

## 3. Method
### 3.1 단일 엔진
- `ConservatismSchedule.effective_n(n_personal, n_class_hands, n_pop)`
  = `w_p · n_personal + w_c · n_class_hands + w_pop · n_pop`
  (기본 w=1.0/0.3/0.05, n_pop=100 고정).
- 6개 bucket (`hard_conservative → exploit_ready`) 에 yaml 기반 파라미터 매핑.

### 3.2 테이블-와이드 conservatism
- `_table_conservatism(req, bot_name, deps)`: 활성 상대 중 `n_effective` 가 가장 낮은
  상대 기준. 즉 "가장 모르는 상대" 에 맞춰 보수적.
- profile_store 없음 → `compute_profile(None)` = hard_conservative.

### 3.3 RFI 사이즈 경로
- `_rfi_size_bb(pos_class, cons, fallback_bb)`:
  - EP/MP → `raise_open_bb[0]` (가장 작음).
  - LP/BLIND → `raise_open_bb[len/2]` (중간).
- conservative_grid(`[2.2, 2.5]`) vs balanced_grid(`[2.2, 2.5, 3.0]`) vs exploit_grid(`[2.2, 2.5, 3.0, 3.5]`).

## 4. Results
### 4.1 테스트
- `tests/test_conservatism.py` — 9 케이스 (schedule load, cold→hard_conservative, heavy→exploit_ready, bluff/λ 단조성).
- `tests/test_policy_conservatism.py` — 3 케이스 (cold, warm-mixed, min-n-effective 선택).
- 전체 회귀: **186 passed, 2 warnings, 3.2s**.

### 4.2 배선된 항목
- `DecideDeps.profile_store` 는 이미 D3 Day 18 에서 추가됨.
- RFI size 가 profile_store 기반 conservatism 을 사용하도록 전환.

### 4.3 아직 배선되지 않은 항목 (D5 에서 진행)
- **all-in veto (I.8)** — 현재 push_fold mode 의 jam 만이 all-in 을 생성. 해당 경로는
  Nash chart 이 승인한 것이므로 veto 예외. mid/deep postflop 에서 all-in 이 생성되면
  veto 필요 — D5 EV tree 완성 후 통합.
- **bluff_factor (I.2)** — 현재 봇은 postflop 에서 독자적인 bluff 를 만들지 않음 (전부
  pot-odds call/fold). D5 EV tree 완성 후.
- **opening_multiplier** — 현재 opening_chart 는 range 를 하드코딩. 실제 적용은 Range
  shrink 로직을 D5 에서 도입할 때.

## 5. Interpretation
### 5.1 핵심 발견
- n_effective 함수를 단일 스칼라로 노출한 뒤 bucket 매칭하는 설계가 decision 경로에
  매우 가볍게 삽입됨. 모든 mode 전환이 하나의 yaml 로 관리 가능.
- 실서버 cold-start 는 자동으로 hard_conservative → 위험 봉쇄.

### 5.2 우리 서버로의 전이 가능성
`n_class_hands = profile.hands_seen` 은 classification-granularity 와 무관하게 누적 → 4/6/9-max
모두 동일한 스칼라. 서버 파라미터 튜닝은 yaml 교체만으로 가능.

### 5.3 한계
- `n_pop=100` 고정. 실제로는 population_priors ESS 가 metric 별로 다름 — 근사치로 수용.
- bluff_factor, lambda_multiplier, opening_multiplier 는 "주입 대상" 만 정의했고 수요측
  코드는 D5 에서 생성.

## 6. Parameter Output
`configs/conservatism_schedule.yaml` + `configs/sizing.yaml` 은 이미 R3 에서 작성.
본 단계에서는 loader/엔진만 추가했고 yaml 수정 없음.

## 7. Limitations & Caveats
- `_table_conservatism` 의 기준: 가장 모르는 상대. "헤드업에서 한 명이 unknown 이면
  전부 unknown 취급" 은 보수적이지만 **TAG 상대에게도 conservative grid 를 사용**하게
  됨. 비대칭 전략이 필요하면 per-opponent conservatism 으로 전환.
- cold-start RFI size(BTN AA, hard_conservative) 와 warm balanced 모두 `raise_open_bb[1]=2.5` →
  target 5. 시각적 차이가 작음. 실제 차이는 bluff_factor/allow_allin 이 활성화되는
  D5 이후 드러남.

## 8. Next Steps
- D5 (Week 9–10): Dirichlet 반응 모델 + Thompson sampling + IG bonus. 여기서 bluff_factor
  가 실제로 bluff 후보 확률을 스케일.
- D6 (Week 11): EV tree 도입 시 lambda_multiplier 를 log-utility 곡률에 반영.

## 9. References
- plan I.1 (sizing grid), I.9 (schedule), I.9.b (single profile endpoint).
- `research/parameters/conservatism_schedule_rationale.md`

## Changelog
- 2026-04-19 (v0.1): ConservatismSchedule/SizingGrid loader 작성 + policy RFI 통합.
