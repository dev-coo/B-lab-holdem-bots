# EDA 05 — Bluff Threshold 분석 (J.7)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.2 (2.06M full run 반영, 2026-04-19 18:05)
- **Related configs**: `configs/bluff_labels.yaml` (초안)
- **Related code**: `scripts/bluff_threshold.py`, `src/holdem/estimate/bluff_labeler.py` (미구현)
- **Related BOT_GUIDE sections**: §3 (카드 표기), §5.6 (hand_result), §6.2 (raise amount)

---

## 1. Objective

이 문서가 답하는 단일 질문:
> 각 베팅/레이즈 결정 시점의 **true equity** (상대 카드 포함) 분포가 bimodal 인가?
> 그렇다면 bluff vs value 경계 θ 를 어디에 두어야 하는가? street 별로 다른가?

---

## 2. BOT_GUIDE Compliance

`research/bot_guide_extracts.md` 에서 인용:

- [§3] 카드 표기 `Ah, Kh, 2s, Tc`. `T=10`. treys 의 `Card.new('Ah')` 와 호환 확인.
- [§5.6] hand_result 의 showdown 에 폴드자는 포함되지 않음. 이 데이터셋은 `Dealt to` 로 양쪽 카드 공개 → true equity 계산 가능 (쇼다운 미도달 핸드 포함).
- [§6.2] raise amount = 이번 라운드 **총 베팅액**. 기록된 `extra_bet = raise_to - round_bet[player]` 로 정규화.

**위배 위험과 방어**:
- 서버에서는 상대 카드가 공개되지 않으므로 bluff labeling 은 MC-based 근사를 사용해야 한다. 이 문서는 **오프라인 튜닝** 용 true equity 를 사용하되, 결과 θ 는 서버 런타임의 expected equity 에 적용한다.
- raise_to 필드가 없는 데이터 → extra_bet = amount 로 대체 fallback. 체크 완료.

---

## 3. Method

### 3.1 데이터
- **원천**: `data/raw/poker/*.txt` (Kaggle `kaggle/poker-heads-up`, 2,059,400 핸드)
- **필터**: hole_cards 가 양쪽 모두 공개된 핸드 (≈ 100%). action ∈ {bets, raises}.
- **전처리**: `board_by_street` 누적, `round_bet` 재계산으로 `extra_bet`, `pot_before` 산출.

### 3.2 절차
```bash
# 샘플 스모크 (검증용):
uv run python scripts/bluff_threshold.py 3 5000 100

# 전체 (mc=120 샘플):
uv run python scripts/bluff_threshold.py 0 0 120
# → data/bluff_decisions.csv
# → data/bluff_threshold_report.json
```

### 3.3 도구·버전
- `treys>=0.1.8` (Evaluator, Card.new)
- Python `random` with `seed=42`

---

## 4. Results

### 4.1 전체 집계 (2,059,400 hands, 4,298,389 records, equity 계산 2,058,482, MC=120)

| Street | n records | mean | p10 | p25 | p50 | p75 | p90 | bluff(<0.30) | bluff(<0.40) | value(>0.60) | value(>0.70) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| flop  | 1,174,956 | 0.544 | 0.133 | 0.242 | 0.617 | 0.817 | 0.925 | 32.4% | 39.2% | 50.7% | 43.8% |
| turn  |   605,340 | 0.523 | 0.050 | 0.142 | 0.588 | 0.900 | 0.975 | **42.7%** | 47.0% | 49.8% | 47.1% |
| river |   278,186 | 0.548 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 43.6% | 43.6% | 53.2% | 53.2% |

### 4.2 Turn equity 히스토그램 (20 bins, [0, 1])

```
bin:  0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19
n:   54k 50k 55k 46k 31k 23k 16k 10k  5k  4k  7k  3k  6k  9k 15k 24k 39k 57k 60k 93k
      ##############      valley (0.35~0.55)      ##################
       BLUFF peak                                     VALUE peak
```

**명확한 bimodal distribution**:
- Bluff peak: bin 0~2 (eq 0~0.15) = 158,481 records
- Valley: bin 7~11 (eq 0.35~0.55) = 31,058 records (최소)
- Value peak: bin 17~19 (eq 0.85~1.00) = 209,136 records

### 4.3 Flop equity 히스토그램

```
bin:  0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19
n:   43k 40k 53k 77k 89k 78k 49k 31k 26k 31k 34k 26k 29k 47k 83k106k101k 78k 66k 87k
              ########              valley (0.35~0.60)           ###################
              semi-bluff/draw                                      value/made hand
```

**Softer bimodal**:
- Semi-bluff/draw peak: bin 3~5 (eq 0.15~0.30) = 243,227 records
- Valley: bin 7~11 (eq 0.35~0.55) = 147,648 records
- Value peak: bin 14~16 (eq 0.70~0.85) = 289,838 records

### 4.4 River equity (binary 확정)

```
eq=0.00: 121,155 (43.6% — 완전 블러핑 / bad beat 후)
eq=0.50:   9,041 (3.2% — tie)
eq=1.00: 147,990 (53.2% — pure value)
```

River 의 블러핑 비율이 43.6% 인 점은 **LLM 풀이 river 에서 의외로 많이 베팅** 을 시도함을 의미.

### 4.5 Sizing × 블러핑 비율

| bet_to_pot bucket | n | mean equity | bluff_rate (eq<0.4) |
|---|---:|---:|---:|
| tiny (<0.33) | 245,079 | 0.505 | **45.3%** |
| half (0.33–0.55) | 868,005 | 0.542 | 40.9% |
| two-thirds (0.55–0.85) | 719,976 | 0.545 | 42.6% |
| pot (0.85–1.25) | 155,609 | 0.536 | 41.4% |
| overbet (1.25–2.0) | 66,523 | 0.550 | 39.5% |
| huge (≥2.0) | 3,290 | 0.496 | **46.8%** |

**관찰**:
- U-자 커브: 극단 사이즈 (tiny / huge) 의 bluff rate 가 더 높다.
- 중간 사이즈 (half ~ overbet) 의 bluff rate 는 39~43% 로 평탄.
- Sizing 단독으로 bluff 판정은 약한 신호. **equity 가 주, sizing 은 보조**.

### 4.6 임계값 확정

**Turn 이 가장 명확한 polarization**. 히스토그램 valley 에서:
- **θ_bluff (turn) = 0.35** — 이 이하 = 구조적 블러핑
- **θ_value (turn) = 0.60** — 이 이상 = 구조적 value

**Flop**:
- **θ_bluff (flop) = 0.30**
- **θ_value (flop) = 0.65**

**River**:
- Pairwise equity 는 binary → range 기반 재평가 필요 (D5 단계).

---

## 5. Interpretation

### 5.1 핵심 발견

**① Turn 은 뚜렷한 bimodal — polarization 확증.**
- Turn histogram 의 valley (eq 0.35~0.55) 가 peak 대비 1/5~1/6 수준으로 뚜렷한 골짜기.
- **θ_bluff (turn) = 0.35, θ_value (turn) = 0.60** 이 히스토그램 구조에서 직접 도출됨.
- LLM 풀은 turn 에서 "drawing / pure bluff" 와 "made hand / strong draw + showdown value" 로 **이분 행동**.

**② Flop 은 softer bimodal — valley 는 얕지만 존재.**
- Flop valley (eq 0.35~0.55) 의 bin 수는 peak 의 1/3~1/4 수준.
- Flop 베팅은 pot control, semi-bluff, draw 의 비중이 높아 중간 equity 가 많다.
- **θ_bluff (flop) = 0.30, θ_value (flop) = 0.65** 로 보수적 경계 채택.

**③ River 는 binary → range 기반 재평가 필요.**
- 43.6% river bet 이 **eq=0 (pure bluff loss)**. 생각보다 높음.
- Pairwise equity 는 river 에서 의미 소멸 → caller range 재구성 기반 equity 로 대체 (D5 단계).

**④ Sizing 은 bluff 판정의 주 신호가 아니다.**
- Bluff rate (eq<0.4) 가 sizing bucket 별 39~47% 로 평탄.
- 극단 사이즈 (tiny / huge) 에서만 소폭 상승 (U-shape).
- 결론: **equity 가 주 신호, sizing 은 보조 필터**.

**⑤ 프리플롭 분석은 별도 LUT 필요.**
- 이 스크립트는 프리플롭 equity 는 계산하지 않음 (보드 5장 샘플 비용).
- 169×169 matchup LUT 를 프리컴퓨트 후 J.7.b 단계에서 추가.

### 5.2 우리 서버로의 전이 가능성

| 축 | 전이 가능성 | 보정 |
|---|---|---|
| θ_bluff / θ_value 경계값 | **높음** | HU 2-way 베팅의 수학적 구조는 4-9way 에서도 유지 (equity 정의 동일) |
| Street 별 경계 차이 | **높음** | 구조적 관찰. 바로 사용. |
| bluff 절대 빈도 | **중** | LLM 풀은 블러핑이 상대적으로 많을 수 있음. 서버의 실제 비율과 ±10%p 차이 허용 범위. |
| River binary → range 분석 | **보정 필요** | 서버 데이터에서 villain range 재구성 파이프라인 필요. |

### 5.3 전이 불가능 영역

- **sizing × equity 결합 분포**: HU 에서 pot 비 1.5x 베팅이 value heavy 인지 bluff heavy 인지의 비율은 4-9way 에서 달라진다. 개별 sizing 별 bluff 비율은 서버 데이터로 재학습.
- **LLM 고유 패턴**: Grok 4 의 AF=6.6 은 독특한 블러핑 성향 — 평균에 희석되지 않도록 **percentile robust** 임계값 사용.

---

## 6. Parameter Output

```yaml
# configs/bluff_labels.yaml
# 근거: research/dataset_analysis/eda_05_bluff_threshold.md §4 (full 2.06M, MC=120)
version: 0.2
stage: draft
source: "eda_05_bluff_threshold.md v0.2 (2.06M hands, 4.3M records, MC=120)"

theta:
  flop:
    bluff: 0.30
    value: 0.65
  turn:
    bluff: 0.35
    value: 0.60
  river:
    # pairwise 0/0.5/1 → range 기반 equity 대기 (D5)
    bluff: null
    value: null

street_weights:
  flop:  0.8
  turn:  1.3
  river: 1.5   # river 는 의미 명확하나 pairwise 에서만. range-vs-range 적용 시 유효

continuous_weight:
  # bluff_weight(eq) = clip((cutoff - eq) / width, 0, 1)
  flop:  {cutoff: 0.55, width: 0.25}
  turn:  {cutoff: 0.55, width: 0.20}
  river: {cutoff: null, width: null}

use_range_vs_range: false
```

---

## 7. Limitations & Caveats

- **MC 120 sample**: flop/turn equity 에 약 ±3%p 표준오차. theta 경계 근처 개별 판정은 불안정 (집계 통계는 안정).
- **True equity vs Expected equity 격차**: 본 분석의 equity 는 상대 실제 카드를 알고 계산 (오프라인). 서버 런타임은 range 기대값 기반 → bluff 라벨링의 적중/오탐은 실서버 검증 필요.
- **Pairwise only**: villain range 분포 고려 없음. turn 베팅 equity 12% 여도 villain range 에 드로 많으면 실제 value.
- **HU 2인**: 멀티웨이에서 all-fold 확률 계산은 독립 가정 위반. 이 문서 결과는 **2-way 적용** 으로 한정.
- **Action ordering 재구성 오차 가능**: 일부 핸드의 action 순서 불일치 리스크. `extra_bet` 음수 가드는 미적용 (집계에서는 영향 미미하나 record-level 에서는 점검 필요).
- **Preflop equity 미계산**: 이 스크립트는 flop/turn/river 만 대상. 프리플롭은 별도 169×169 LUT 필요.
- **LLM 풀 편향**: LLM 들이 river 에서 43.6% bluff rate 는 인간 풀 (~20%) 대비 높다. 서버 metagame 이 인간 혼재면 재학습 필요.

---

## 8. Next Steps

- 2.06M full run 완료 시 결과 표 갱신 (v0.2).
- range-vs-range equity 파이프라인 설계 (J.7 v2): 프리플롭 range → flop 범위 fold 율 → turn 의 상대 range 추정 → equity.
- Pure air (eq<5%) 비율을 street 별로 집계하여 "진짜 블러핑 빈도" 리포트.
- `src/holdem/estimate/bluff_labeler.py` 구현 (D5 단계): 런타임 equity ← action 관찰 → Bayesian posterior update.
- Sizing × equity 2D 분포 시각화 (eda_04 sizing 과 교차) — polarization 발견 시 sizing-specific θ.

---

## 9. References

- [1] `guide/BOT_GUIDE.md` §3, §5.6, §6.2
- [2] Kaggle `kaggle/poker-heads-up` — `research/LICENSE_NOTE.md`
- [3] `data/bluff_decisions.csv`, `data/bluff_threshold_report.json`
- [4] treys library — https://github.com/ihendley/treys
- [5] Chen & Ankenman, *The Mathematics of Poker* (polarization, indifference) — `research/theory_notes.md`

---

## Changelog

- 2026-04-19 (v0.1): 샘플 15k 기반 초안.
- 2026-04-19 (v0.2): full 2.06M run 결과 반영. turn bimodal 확증, sizing-bluff 약한 결합 발견. θ_value_turn 0.65→0.60, θ_value_flop 0.70→0.65.
