# EDA 04 — Sizing 분포 (J.5)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Related configs**: `configs/sizing.yaml`
- **Related code**: `scripts/sizing_distribution.py`, `src/holdem/decide/sizing.py` (미구현)
- **Related BOT_GUIDE sections**: §6.2 (raise amount = round total), §5.3 (action_request pot)

---

## 1. Objective

이 문서가 답하는 단일 질문:
> LLM-vs-LLM HU 데이터셋에서 bet_to_pot (베팅/레이즈 사이즈 / pot_before) 의 자연 모드는 무엇이며,
> 그 분포를 근거로 conservative / balanced / exploit sizing grid 를 어떻게 확정할 것인가?
> 사이즈가 bluff vs value 판정의 유효 신호인가?

---

## 2. BOT_GUIDE Compliance

`research/bot_guide_extracts.md` 에서 인용:

- [§6.2] `raises X to Y` 의 Y 는 **이번 라운드 총 베팅**. 스크립트는 `extra_bet = Y - 내 기존 round_bet` 로 해석.
- [§5.3] `action_request.pot` 은 현재 팟. pot_before 는 본 액션 직전 기준.

**위배 위험과 방어**:
- bet_to_pot = `extra_bet / pot_before` 정의. 음수/0 pot_before 는 제외 (블라인드 post 직후 preflop 등).

---

## 3. Method

### 3.1 데이터
- **원천**: `data/bluff_decisions.csv` (J.7 full run 결과, 4,298,389 bet/raise 결정)
- **필터**: `bet_to_pot > 0`, `pot_before > 0` (유효 샘플 ~4.3M)
- **전처리**: bin 경계 `[0, 0.15, 0.25, 0.33, 0.40, 0.50, 0.60, 0.66, 0.75, 0.85, 1.00, 1.25, 1.50, 2.00, 3.00, +∞]`

### 3.2 절차
```bash
uv run python scripts/sizing_distribution.py
# → data/sizing_report.json
```

### 3.3 도구
- Python stdlib 만 사용 (csv, json, collections).

---

## 4. Results

### 4.1 전체 사이즈 분포

| 통계 | 값 |
|---|---:|
| n | 4,298,389 |
| mean | **1.07** (pot 의 107%) |
| p05 | 0.33 |
| p10 | 0.40 |
| p25 | **0.50** |
| p50 | **1.00** |
| p75 | **1.67** |
| p90 | 1.67 |
| p95 | 2.00 |

**중앙값이 pot-sized (1.0)**. 평균 1.07 로 약간 right-skew.

### 4.2 상위 5개 사이즈 모드 (전체)

| Bin (×pot) | count | share |
|---|---:|---:|
| 1.50–2.00 | 855k | **19.9%** |
| 1.25–1.50 | 644k | 15.0% |
| 1.00–1.25 | 604k | 14.1% |
| 0.50–0.60 | 498k | 11.6% |
| 0.66–0.75 | 338k | 7.9% |

**관찰**:
- 상위 1, 2, 3 모드 모두 **pot 이상 크기** (overbet ~ pot). 전체 49% 가 pot 이상.
- 0.50 pot 근처가 유일한 "소형" 모드 (11.6%).
- 전통적 `1/3 pot` (0.33) 모드는 2.8% 로 미미. **LLM 풀은 작은 사이즈를 거의 안 쓴다**.

### 4.3 Street × Equity 별 사이즈

| street / equity bucket | n | p50 | p75 |
|---|---:|---:|---:|
| flop / bluff (eq<0.4) | 460k | **0.50** | 0.50 |
| flop / value (eq>0.6) | 598k | **0.50** | 0.67 |
| turn / bluff | 284k | **0.67** | 0.71 |
| turn / value | 302k | **0.67** | 0.73 |
| river / bluff | 121k | **0.66** | 0.73 |
| river / value | 148k | **0.55** | 0.68 |

**핵심 관찰**:
- **Flop 과 Turn 에서는 bluff/value 가 같은 사이즈** 를 쓴다 (p50 동일).
- **River 에서만 bluff 가 value 보다 큰 사이즈** (0.66 vs 0.55 pot) — 예상과 역방향 (인간 풀은 보통 value 가 더 크거나 동일).
- → **LLM 풀의 사이즈는 bluff vs value 판정 신호가 아니다** (eda_05 §5.1 ④ 재확인).

### 4.4 Equity bucket 별 사이즈 중앙값

| equity bucket | n | p50 |
|---|---:|---:|
| pure_bluff (eq<0.20) | 583k | 0.50 |
| weak (0.20–0.40) | 413k | 0.60 |
| marginal (0.40–0.60) | 371k | 0.67 |
| strong (0.60–0.80) | 477k | 0.67 |
| nuts (eq>0.80) | 214k | 0.67 |

**선형 상승 없음**: equity 가 높을수록 사이즈가 크지 않다. Low equity 만 약간 작고, 나머지는 평탄.

---

## 5. Interpretation

### 5.1 핵심 발견

**① LLM 풀은 overbet-heavy**.
- Overbet (bet ≥ pot) 비율 약 **49%**. 인간 풀은 보통 <20%.
- 주 모드가 pot + (raise 반응 후) 1.25~1.67× pot. 서버에 실전 적용 시 우리 봇이 overbet 에 과도하게 fold 하지 않도록 대응 필요.

**② Sizing 분포는 discrete peaks 에 집중**.
- 0.5 pot, 0.67 pot, 1.0 pot, 1.5 pot, 2.0 pot 5 개가 주요. 연속 분포 아님.
- Conservative sizing grid 는 이 주요 모드의 **왼쪽 절반** 만 채택 = [0.33, 0.5, 0.67].

**③ Sizing 은 bluff/value 판정의 주 신호가 아니다**.
- Flop/Turn 에서 동일 사이즈. River 에서는 역방향.
- Equity 우선, sizing 은 보조. `bluff_labels.yaml` 의 방침과 정합.

**④ Street 별 사이즈 진행**.
- Flop p50 = 0.50 pot (작음)
- Turn p50 = 0.67 pot
- River p50 = 0.60 pot
- 이는 인간 풀의 "street 전개 시 사이즈 증가" 경향과 다름 — LLM 은 flop 에서 작게, turn 에서 최대, river 에서 약간 감소.

### 5.2 우리 서버로의 전이 가능성

| 항목 | 전이 가능성 | 보정 |
|---|---|---|
| Sizing grid peaks [0.5, 0.67, 1.0] | **높음** | 중간값 3 개는 사용 |
| Overbet (1.5×+) 비율 49% | **낮음** | 인간/혼합 풀은 <20% 추정. 서버 bootstrap 후 재보정 |
| Conservative grid 상한 | **중** | LLM 풀 대응 시 0.67 상한. 인간 풀에서는 0.5 상한도 가능 |
| bluff/value sizing 분리 | **불가** | LLM 풀 기준. 인간 풀은 이 분리가 존재할 수 있음 |

### 5.3 전이 불가능 영역

- **Overbet 빈도**: LLM 풀의 49% 를 그대로 믿으면 우리 봇이 상대 overbet 에 과도 공포.
- **River bluff-big sizing**: LLM 의 역방향 패턴. 인간 풀에 **적용 금지**.
- **사이즈별 fold 반응**: 본 분석은 사이즈 분포만. 실제 fold rate vs sizing 의 elasticity 는 sizing 단독으로 결정 불가 → 서버 데이터 필수.

---

## 6. Parameter Output

```yaml
# configs/sizing.yaml — §4 Results 기반
version: 0.1
stage: draft
source: "eda_04_sizing.md v0.1 (2.06M hands, 4.3M decisions)"

conservative_grid:
  # n_effective < 30 : exploitable 최소화. 큰 사이즈/오버벳 봉쇄.
  value_bet:   [0.33, 0.50]
  bluff_bet:   [0.33]
  protection:  [0.50, 0.67]
  raise_open:  [2.2, 2.5]             # bb multiplier
  three_bet:   [2.8, 3.0]             # IP 최소
  no_allin_unless: ["nash_chart_says_jam", "eq_ge_0.85", "stack_lt_5bb"]
  max_bet_to_pot: 0.67                # hard cap

balanced_grid:
  # 30 ≤ n < 150
  value_bet:   [0.33, 0.50, 0.67, 1.00]
  bluff_bet:   [0.33, 0.50]
  protection:  [0.50, 0.67, 1.00]
  raise_open:  [2.2, 2.5, 3.0]
  three_bet:   [2.8, 3.0, 3.5]

exploit_grid:
  # n ≥ 150 (개인 posterior 확신)
  value_bet:   [0.33, 0.50, 0.67, 1.00, 1.50]
  bluff_bet:   [0.50, 1.00]           # polarized 허용
  protection:  [0.50, 0.67, 1.00]
  raise_open:  [2.2, 2.5, 3.0, 3.5]
  three_bet:   [2.8, 3.0, 3.5, 4.0]

# Observed LLM pool peak sizing (참조. 전이 금지 — §5.2 참조)
observed_llm_peaks_raw:
  - {range: [1.50, 2.00], share: 0.199}
  - {range: [1.25, 1.50], share: 0.150}
  - {range: [1.00, 1.25], share: 0.141}
  - {range: [0.50, 0.60], share: 0.116}
  - {range: [0.66, 0.75], share: 0.079}
```

---

## 7. Limitations & Caveats

- **LLM-only 풀**: 인간/혼합 metagame 과 분포가 다를 가능성 크다. 서버 부트스트랩 후 재보정.
- **bet_to_pot 정의 모호성**: pot_before 는 **본 액션 직전**. 프리플롭 open 은 pot 이 SB+BB 라 비율이 크게 왜곡 (e.g. 2.5bb open = 1.25× pot). 이 문서의 사이즈 분포는 open/re-open 포함. 별도 분리 분석 권장.
- **raise-vs-bet 미분리**: `bets` 와 `raises` 를 합쳐 집계. 첫 베팅과 리레이즈의 사이즈 구조는 본질적으로 다름 → eda_04.1 에서 분리 재분석 필요.
- **Uncalled bet return 미반영**: pot_before 는 상대 콜 전 상태. "uncalled" 반환 후 실질 pot 이 작아지는 상황은 현재 반영 안 됨.
- **Equity pairwise only**: bluff/value 분리는 villain 실제 카드 기준. range-vs-range 로 재평가 시 사이즈-equity 결합이 달라질 수 있음.
- **Sample 편향**: 한 매치업 (Grok 4 등 특정 모델) 의 사이즈 전략이 전체 평균을 왜곡할 수 있음. 매치업별 breakdown 은 미수행.

---

## 8. Next Steps

- **bet vs raise 분리 재집계** (eda_04.1).
- **Preflop 사이즈 (RFI, 3bet, 4bet) 별도 분석** — pot_before 기준 비율이 아닌 BB 기준.
- **Sizing × opponent model** 교차: 같은 상대 클래스에서만 집계.
- **Server bootstrap 대비**: 10k self-play 핸드의 사이즈 분포와 비교 → 인간/GTO 풀에서의 기대 peaks 설정.
- `src/holdem/decide/sizing.py` 구현 (D6): conservative/balanced/exploit grid 전환기.

---

## 9. References

- [1] `guide/BOT_GUIDE.md` §5.3, §6.2
- [2] `data/bluff_decisions.csv`, `data/sizing_report.json`
- [3] `research/dataset_analysis/eda_05_bluff_threshold.md` (bluff rate context)
- [4] Kaggle `kaggle/poker-heads-up`

---

## Changelog

- 2026-04-19 (v0.1): 2.06M hand sample 초안. LLM 풀의 overbet-heavy 패턴 확인.
