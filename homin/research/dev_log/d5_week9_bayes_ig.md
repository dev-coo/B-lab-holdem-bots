# D5 Week 9 — Bayes + IG + Board Texture + Range Inference

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Related code**: `estimate/bayes.py`, `estimate/info_gain.py`, `estimate/board_texture.py`, `estimate/range_inference.py`
- **Related BOT_GUIDE sections**: §3 (카드 표기), §5 (이벤트 → 관측)

## 1. Objective
의사결정에 필요한 "상대 반응 모델 + 보드 구조 + range 추정 + IG 가산치" 의 기본 블록을
모두 모듈 레벨로 노출. 실제 EV 트리 (D6) 가 이 블록들을 조립하여 action scoring 을 수행.

## 2. BOT_GUIDE Compliance
- [§3] 카드 표기 `Ah/Tc` 는 board_texture 가 그대로 수용.
- [§5] Dirichlet observe() 는 hand_result/action_performed 로부터 호출 예정 (후속 와이어업).

## 3. Method
### 3.1 Dirichlet Response (`bayes.py`)
- `DirichletResponse(α_fold, α_call, α_raise)` — 반응 확률의 joint posterior.
- `sample()` — gammavariate → 정규화. 한 decision 호출 내 1회 샘플링으로 일관 EV 계산.
- `mean()/observe()/decay()/merge()` — shrinkage 호환.
- 평가 C2 (Beta 3개 독립 추출의 확률공간 위반) 해결.

### 3.2 Information Gain (`info_gain.py`)
- `ig_schedule(n_total)` — γ_0 · exp(-n/τ), 기본 γ_0=0.02BB, τ=300.
- `action_ig_bonus(action, n_total)` — action-type 별 multiplier × schedule.
  - fold=0, check=0.3, call=1.3 (쇼다운 가능), raise/allin=1.0.
  - cap=0.05BB 로 EV 뒤집기 방지.
- `apply_ig_to_candidates(ev_dict, n_total)` — 후보 EV dict 를 in-place 가산.

### 3.3 Board Texture (`board_texture.py`)
- `analyze(["Jh","9h","8h"])` → BoardTexture.
- wetness = 0.5·connectedness + 0.5·flush_factor (monotone 1.0, two_tone 0.6).
- range_advantage_hint — high_card 기반 ±0.5 범위, wetness 로 감쇠, paired 감쇠.

### 3.4 Range Inference (`range_inference.py`)
- `infer_open_range(pos_class, profile)` — 기본 chart + VPIP 기반 확장/축소.
  - VPIP ≤ 15% → ×0.75 (premium-only).
  - VPIP ∈ [15,22] → ×0.9.
  - VPIP ∈ [22,30] → ×1.0 (default).
  - VPIP ∈ [30,40] → ×1.2.
  - VPIP > 40% → ×1.4.
- `filter_after_raise(r)` — range → _STRONG_HANDS 교집합 (premium 보존).
- `confidence = min(1.0, hands_seen/80)`.

## 4. Results
- `tests/test_bayes.py` — 10 cases (uniform default, sum=1, decay, merge, allin→raise).
- `tests/test_info_gain.py` — 9 cases (decay, cap, fold=0, ordering preservation).
- `tests/test_board_texture.py` — 11 cases (dry/wet/paired/trips/two-tone/low-connect).
- `tests/test_range_inference.py` — 5 cases (default, loose expand, confidence growth, raise narrow, EP<LP).
- 전체 회귀: **221 passed, 2 warnings, 3.3s** (D3+D4 기준 +35 tests).

## 5. Interpretation
### 5.1 구성 요소와 EV 트리의 관계
- D6 EV tree 가 각 후보 액션 a 에 대해:
  ```
  EV(a) = Σ_response  P(response | situation) · outcome(a, response)
        + IG_bonus(a, n_total)
  ```
  에서 `P(response)` = DirichletResponse.sample() (1-sample Thompson).
- Board texture 와 range_inference 는 outcome 의 equity 부분에 사용.

### 5.2 한계 인식
- 현재 DirichletResponse 는 **인스턴스 저장소 없음** — situation_key → DirichletResponse
  매핑 테이블이 D6 에서 필요.
- Range inference 는 coarse. 실제 HU solver 값과 괴리가 있으나 "없음" 보다는 훨씬 낫다.
- IG 는 per-action 이 아닌 global schedule. per-situation IG 는 D6 EV 시그니처가 확정된
  후 리뷰.

## 6. Parameter Output
새로운 yaml 없음. IGConfig 기본값은 코드에서 상수로 유지 (튜닝 시 yaml 로 이관).

## 7. Limitations & Caveats
- 보드 texture 의 connectedness 는 gap 평균으로 근사. 실제 GTO 에선 gap 분포와
  backdoor 잠재력(전략 값) 이 더 정밀.
- Range inference 의 확장 로직은 "premium 유지 + playable 풀에서 정렬된 순차 추가" —
  실제 풀이는 더 비선형.
- IG 의 action multiplier (0.3/1.0/1.3) 은 heuristic. 자기대전 튜닝 대상.

## 8. Next Steps
- D6 Week 11: EV tree 조립 + log-utility 통합 + sizing optimizer.
- DirichletResponse 를 per-situation 테이블로 확장: `estimate/response_store.py`
  (SQLite 또는 in-memory dict).

## 9. References
- plan C2 (Dirichlet), H.5 (board texture), H.6 (IG), 3-2 (range inference).
- `research/bot_guide_extracts.md` §3, §5.

## Changelog
- 2026-04-19 (v0.1): D5 Week 9 4개 모듈 + 35 tests.
