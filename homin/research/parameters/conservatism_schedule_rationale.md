# Conservatism Schedule — 수치 근거 (conservatism_schedule.yaml)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: `configs/conservatism_schedule.yaml` v0.1
- **Sources**: `research/dataset_analysis/eda_03_convergence.md` v0.1
- **BOT_GUIDE refs**: §1.1 영속 통계, §5.3/5.4 이벤트 counter, §8 블라인드 구조

---

## 1. 결정 요약

`n_effective` 에 따라 **6 단계 mode** 로 점진적 완화. 각 mode 는 sizing grid, bluff factor,
lambda 승수, opening range, allin 허용 여부를 다르게 지정. 경계값은 eda_03 수렴 곡선의
knee 와 일치.

```
n_eff :  0 ─ 10 ─ 30 ─ 80 ─ 150 ─ 400 ─ ∞
mode  :  hard  conserv.  trans.  near_bal.  balanced  exploit_ready
vpip_err: 13%   5%       4.5%    3.5%       2.0%     1.5%
```

---

## 2. 경계값 근거 (J.8 수렴 곡선)

### 2.1 VPIP 절대 오차 (15 LLM 평균)

| N | VPIP err | PFR err | AF rel err | 모드 결정 |
|---:|---:|---:|---:|---|
| 10  | 0.132 | 0.062 | 0.595 | **hard_conservative** 임계 |
| 20  | 0.056 | 0.064 | 0.316 | |
| 30  | 0.049 | 0.060 | 0.206 | **conservative** 진입 |
| 50  | 0.047 | 0.042 | 0.179 | |
| 80  | 0.044 | 0.034 | 0.217 | **transitional** 진입 |
| 120 | 0.028 | 0.031 | 0.235 | |
| 150 | 0.034 | 0.032 | 0.255 | **near_balanced** 진입 |
| 200 | 0.028 | 0.032 | 0.293 | |
| 300 | 0.018 | 0.027 | 0.229 | |
| 400 | 0.016 | 0.022 | 0.234 | **balanced → exploit_ready** |
| 600+ | 0.015 | 0.018 | plateau | plateau |

### 2.2 해석

- N=10 미만은 prior 지배. 개인 데이터 노이즈만 기여 → **최대 보수성**.
- N=30 에서 오차가 절반 감쇠. 개인 데이터가 의미 가지기 시작.
- N=80~150: 추가 ~1%p 개선. 완만.
- N=400 에서 실전적 수렴. 이후는 marginal.

경계 {10, 30, 80, 150, 400} 은 **곡선의 knee 위치** 에 일치.

---

## 3. 각 mode 의 파라미터 근거

### 3.1 hard_conservative (n < 10)

```yaml
sizing_grid:  conservative
bluff_factor: 0.50          # 블러핑 빈도 절반
lambda_mult:  3.0           # 극도 risk-averse
opening_mult: 0.75          # RFI 25% 축소
allow_allin:  false
```

- VPIP 오차 13%p → 개인화가 잘못될 위험 큼. **평균 행동 + MDF 방어**.
- λ 3배: log-utility 곡률 증가. commit 기피.
- All-in 금지 (Nash 차트 예외).

### 3.2 conservative (10 ≤ n < 30)

```yaml
bluff_factor: 0.65
lambda_mult:  2.2
opening_mult: 0.85
allow_allin:  false
```

- VPIP 오차 ~5%p. 개인 posterior 완만하게 진입.
- 여전히 prior 지배. bluff 65% 는 신중 진입.
- All-in 보류 (상대 유형 미확정).

### 3.3 transitional (30 ≤ n < 80)

```yaml
sizing_grid:  balanced
bluff_factor: 0.80
lambda_mult:  1.6
opening_mult: 0.92
allow_allin:  true
```

- VPIP 오차 4.5%p. 충분한 개인화.
- balanced grid 진입 (pot-sized bet 허용).
- All-in 개방 (value-only 조건).

### 3.4 near_balanced (80 ≤ n < 150)

```yaml
bluff_factor: 0.92
lambda_mult:  1.2
opening_mult: 0.98
```

### 3.5 balanced (150 ≤ n < 400)

정상 가동. λ 1.0, bluff 1.0, opening 1.0.

### 3.6 exploit_ready (n ≥ 400)

```yaml
sizing_grid:  exploit         # overbet 허용
bluff_factor: personal_AF_based
opening_mult: personal_optimum
```

- 개인 관측 확정 → **상대 특성 착취**.
- AF 5.0 인 maniac 상대 → 우리 bluff 축소, value trap 증가.

---

## 4. Decay (§ I.10, eda_03 §5.1 ④)

```yaml
tau_decay_hands:  2000
min_weight:       0.2
```

- **왜 2000?** LLM 풀의 수렴 floor 가 2% 이하로 안 떨어지는 이유: metagame drift.
- 2000 핸드 반감: 2000 전 관측은 가중치 e^-1 = 37%, 4000 전은 14%.
- **min_weight 0.2**: 완전 망각 방지. 오래된 관측도 최소 20% 가중 유지.
- **서버 튜닝**: 인간 풀은 drift 빠름. τ_decay 는 서버 실로그 1k 후 재조정 대상.

---

## 5. Self-image check (§ I.10.b)

```yaml
self_image_check:
  window_hands:     20
  vpip_floor_ratio: 0.5
  pfr_floor_ratio:  0.4
```

- 우리 봇이 최근 20 핸드 내 VPIP < population × 0.5 (예: 10% 미만) 면 **과도 tight** → mode 한 단계 상승.
- 이는 보수성이 지나쳐 상대가 착취할 여지가 생기는 것을 방지.

---

## 6. 갱신 규칙

### 6.1 실시간 계산

```python
def current_mode(opp_profile):
    n_eff = (opp_profile.n_personal
             + 0.3 * opp_profile.n_class
             + 0.05 * opp_profile.n_population)
    for row in schedule:
        if row.n_max is None or n_eff < row.n_max:
            return row.mode
```

### 6.2 hot-swap

- mode 는 매 의사결정 시점에 재계산 (hand 중간에도 변경 가능).
- 파라미터 주입은 `ConservatismProfile` 으로 단일 주입점 (§D4, §I.9).

### 6.3 v0.2 승격 조건

- Self-play 10k 에서:
  - ITM rate (보수성 on) ≥ ITM rate (off) + 5%p
  - 분산 (BB/100 std) 40% 이상 감소

불충족 시 mode_params 튜닝.

---

## 7. 통합 시 주의사항

### 7.1 다른 config 와의 관계

- `sizing.yaml` 의 grid 는 conservatism 의 `sizing_grid` 라벨로 선택.
- `priors.yaml` / `class_priors.yaml` 의 Beta 는 shrinkage 를 거쳐 posterior 에 반영.
- `bluff_labels.yaml` 의 continuous_weight 는 raw eq 에 적용 후 bluff_factor 로 추가 감쇠.

### 7.2 Nash chart mode 와의 관계 (§ H.2.b)

- M ≤ 12 구간에서 `mode_selector` 가 push_fold/hybrid 를 강제 → conservatism schedule 무시.
- 즉 conservatism 은 M > 12 의 deep/mid 구간에서만 의미.

---

## 8. Limitations

- **N=15 플레이어 수렴 곡선**: 경계 위치 ±30 핸드 오차 가능.
- **LLM stationarity**: 인간의 tilt/session 드리프트 미반영. τ_decay 재튜닝 필요.
- **mode 전환의 hysteresis 부재**: n_eff 가 경계를 오르내릴 때 mode 가 깜빡일 수 있음 → hysteresis 필요 시 구현.
- **self_image_check 계수 (0.5, 0.4)** 는 경험값. self-play 후 조정.

---

## 9. Next Steps

- `src/holdem/decide/conservatism.py` 구현 (D4, 약 3일 예산).
- 모든 decision 경로에 `ConservatismProfile` 주입.
- Self-play 10k 에서 mode on/off A/B → BB/100, ITM rate, variance 비교.
- 실서버 1주 가동 후 τ_decay 재조정.

---

## Changelog

- 2026-04-19 (v0.1): J.8 수렴 곡선 knee 기반 6-mode 경계 확정. 각 mode param 초안.
