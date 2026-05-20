# Bluff Labels — 수치 근거 (bluff_labels.yaml)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: `configs/bluff_labels.yaml` v0.2
- **Sources**: `research/dataset_analysis/eda_05_bluff_threshold.md` v0.2
- **BOT_GUIDE refs**: §3 카드 표기, §5.6 showdown, §6.2 raise amount

---

## 1. 결정 요약

상대 베팅의 **equity 기반 bluff/value 라벨링** 경계. Turn/Flop 히스토그램의 valley 에서
직접 도출. Sizing 은 보조 신호.

```
theta.turn:  bluff < 0.35,  value > 0.60,  mixed [0.35, 0.60]
theta.flop:  bluff < 0.30,  value > 0.65,  mixed [0.30, 0.65]
theta.river: pairwise 무의미 → range-vs-range 대기 (D5)
```

---

## 2. θ 경계 도출

### 2.1 Turn (bimodal valley 에서 직접)

Full run 히스토그램 (20 bins over [0,1]):
```
bin:  0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19
n:   54k 50k 55k 46k 31k 23k 16k 10k  5k  4k  7k  3k  6k  9k 15k 24k 39k 57k 60k 93k
                                      ↑ valley ↑
```

- Bluff peak: bins 0~2 (eq 0~0.15) = 158k records
- Valley: bins 7~11 (eq 0.35~0.55) = 31k records (5분의 1)
- Value peak: bins 17~19 (eq 0.85~1.00) = 209k records

**Valley 의 좌측 엣지** = bin 7 경계 = eq 0.35 → **θ_bluff_turn = 0.35**.
**Valley 의 우측 엣지** = bin 12 경계 = eq 0.60 → **θ_value_turn = 0.60**.

### 2.2 Flop (softer bimodal)

```
bin:  0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19
n:   43k 40k 53k 77k 89k 78k 49k 31k 26k 31k 34k 26k 29k 47k 83k106k101k 78k 66k 87k
                                      ↑ valley ↑
```

- Semi-bluff peak: bins 3~5 (eq 0.15~0.30) = 243k
- Valley: bins 7~11 (eq 0.35~0.55) = 148k (peak 의 1/3~1/4)
- Value peak: bins 14~16 (eq 0.70~0.85) = 290k

**θ_bluff_flop = 0.30** (valley 시작 약간 앞, 보수적).
**θ_value_flop = 0.65** (valley 끝 약간 뒤).

### 2.3 River (binary)

```
eq=0.00: 121k (43.6%)
eq=0.50:   9k  (3.2%)
eq=1.00: 148k (53.2%)
```

Pairwise equity 에서 river 는 0/0.5/1 세 값만. valley 개념 무의미.
→ **θ 미정의 (null)**, **D5 range-vs-range** 에서 재계산.

---

## 3. Street Weights

```yaml
street_weights:
  flop:  0.8    # soft valley, semi-bluff 혼재
  turn:  1.3    # 명확 bimodal
  river: 1.5    # range-vs-range 적용 후 유효
```

**근거**:
- Flop 의 낮은 가중은 **false positive** 가능성 (드로 = semi-bluff 를 bluff 로 과잉 라벨).
- Turn 은 polarization 명확. 라벨 신뢰도 높음.
- River 는 pairwise 에서는 binary noise. range 기반 전환 후 가장 신뢰.

---

## 4. Continuous weight (세미블러핑 대응)

```yaml
continuous_weight:
  flop:  {cutoff: 0.55, width: 0.25}   # bluff_weight = clip((0.55 - eq) / 0.25, 0, 1)
  turn:  {cutoff: 0.55, width: 0.20}
  river: null
```

**이유**: 이분 label 은 eq=0.34 와 eq=0.36 을 극단 분리 → 경계 근처 노이즈 큼. 연속 함수는 매끄럽게.

---

## 5. Sizing 의 역할

### 5.1 Sizing 단독은 약한 신호

| bet_to_pot | bluff rate (eq<0.4) |
|---|---:|
| tiny (<0.33) | 45.3% |
| half (0.33-0.55) | 40.9% |
| two-thirds (0.55-0.85) | 42.6% |
| pot (0.85-1.25) | 41.4% |
| overbet (1.25-2.0) | 39.5% |
| huge (≥2.0) | 46.8% |

변동 39~47%. **평탄**. Sizing 단독으로 bluff 판정 불가.

### 5.2 Flop/Turn 의 bluff vs value 사이즈 동일

- flop_bluff p50 = 0.50 = flop_value p50
- turn_bluff p50 = 0.67 = turn_value p50

→ 서버에서도 **상대 sizing 으로 bluff/value 판단 금지** (적어도 LLM 풀에서).

### 5.3 결론

- Sizing 은 **equity 판정의 보조** 로만.
- 향후 "sizing × equity × street" 3D 교차 분석 시 유효 가능 (현재는 미수행).

---

## 6. 갱신 규칙

### 6.1 라벨링 절차 (실시간)

1. 상대 베팅/레이즈 관찰.
2. 우리가 가진 상대 range 에 대해 expected equity 계산.
3. `theta[street]` 과 비교:
   - eq < theta.bluff → label "bluff", weight = street_weights[street] × 1.0
   - eq > theta.value → label "value", weight = street_weights[street] × 1.0
   - mixed → label "mixed", weight = street_weights[street] × continuous_weight(eq)
4. 상대 PlayerProfile 의 `bluff_at_street` Beta counter 갱신.

### 6.2 Shadow pipeline

- 매 핸드 종료 시 showdown 카드 공개되면 **true equity** 재계산.
- shadow label 과 online label 비교 → drift 탐지. 차이 >10%p 면 theta 재조정 경고.

### 6.3 v0.2 / v0.3 승격

- **v0.2 (현재)**: 2.06M pairwise 결과 반영.
- **v0.3 계획**: range-vs-range equity 파이프라인 도입 후 river theta 설정.
- **v1.0 (실서버 validated)**: 실서버 2k 쇼다운 핸드로 label accuracy 검증 (Precision ≥ 0.75).

---

## 7. Limitations

- **Pairwise equity 의 한계**: 실제 상대 range 정보 없이 카드만 알고 계산. river 에서 의미 상실.
- **LLM 풀 bluff 과다**: river 43.6% 는 인간 풀 (~20%) 대비 높음. 서버에서는 이 값이 하락 예상 → theta 상향 가능.
- **Street weight 의 검증 부재**: {0.8, 1.3, 1.5} 는 주관 비율. self-play 에서 Precision/Recall 로 튜닝 대상.
- **Continuous width 선택**: 0.25 / 0.20 은 경험값. A/B 시 재조정.

---

## 8. Next Steps

- `src/holdem/estimate/bluff_labeler.py` 구현 (D5): 실시간 labeling + shadow pipeline.
- `scripts/range_vs_range_eda.py` (J.7 v2): villain range 모델링 후 river equity 재계산.
- Sizing × equity 2D 집계 (eda_04.1 에 병합 예정).
- 실서버 로그에서 bluff label 의 다음 핸드 outcome 과 상관 분석 — label 유효성 검증.

---

## Changelog

- 2026-04-19 (v0.1): 2.06M pairwise 기반 θ/street_weights/continuous 확정. river 는 v0.3 까지 null 유지.
