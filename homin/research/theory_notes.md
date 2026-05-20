# R1. 이론 노트 — 핵심 포커 수학·전략 개념

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Related configs**: `configs/blind_schedule.yaml`
- **Related code**: `src/holdem/math/odds.py`, `src/holdem/decide/push_fold_chart.py`
- **Related BOT_GUIDE sections**: §6, §8, §11

---

## 1. Objective

> Section H/I 설계에서 수학·전략 용어(MDF, alpha, Nash Push/Fold, SPR, pot odds, realization, polarized vs linear) 의 **정의·공식·적용 조건**을 단일 문서로 확립한다. 모든 후속 개발 모듈이 이 정의에 기반한다.

---

## 2. BOT_GUIDE Compliance

준수 룰:
- [§6.2] raise amount = 이번 라운드 **누적 총 베팅액**. 본 문서의 모든 사이즈 표기는 동일 정의 사용.
- [§8] 시작 스택 300, 급상승 블라인드 구조. Nash Push/Fold 구간이 게임 후반부 지배(bot_guide_extracts §10.2).
- [§11] M = my_stack / (SB + BB). Push/Fold 전환점의 수치 기준.

**위배 위험**: 외부 문헌(cash game, 100bb deep)의 개념을 우리 **토너먼트(300 stack, 빠른 블라인드)** 에 직접 적용하면 편향. 각 섹션에 전이 조건 명시.

---

## 3. 핵심 개념 — 정의와 공식

### 3.1 Pot Odds (팟 오즈)

**정의**: 콜에 필요한 금액 대비 콜 후 획득 가능한 팟 비율.

**공식**:
```
pot_odds = to_call / (pot + to_call)
```

**해석**: 이 비율이 **콜이 break-even 되는 최소 equity**.

**적용**:
- `eq_vs_opponent_range > pot_odds` → 콜 +EV.
- `eq_vs_opponent_range < pot_odds` → 폴드 +EV.
- `eq_vs_opponent_range = pot_odds` → 무차별.

**예**: `pot=10, to_call=4` → `pot_odds = 4/14 ≈ 0.286`.
콜하려면 상대 range 대비 equity ≥ 28.6% 필요.

**BOT_GUIDE 대응**: `action_request.pot`, `action_request.to_call` 에서 직접 계산.

---

### 3.2 MDF (Minimum Defense Frequency)

**정의**: 상대의 블러핑을 막기 위해 우리 range 가 **최소한** 지켜야 할 defend(콜+레이즈) 비율.

**공식**:
```
MDF = pot / (pot + bet)
```

**유도**: 상대가 0-equity 블러핑으로 bet 할 때, 우리가 `MDF` 미만으로 defend 하면 상대 블러핑이 항상 +EV. MDF 이상 defend 하면 상대 블러핑 이 0-EV 이하로 떨어짐.

**해석**: MDF 는 **range 수준 기준**. 개별 핸드 결정이 아님.

**예**: `pot=10, bet=5` → `MDF = 10/15 = 66.7%`.
우리 range 의 최소 66.7% 가 폴드하지 않고 defend 해야 함.

**우리 설계 적용 (H.4)**: 저데이터 구간의 exploitation 방어 하한선. 개인 데이터 없이도 MDF 는 항상 계산 가능.

**주의**: MDF 는 **상대가 완전 블러핑 능력자** 일 때의 하한선. 실전에서는 상대가 항상 `0-equity bet` 을 하진 않음 → MDF 는 절대 하한, 실제 defend 는 상대 tendency 로 조정.

---

### 3.3 Alpha (공격자의 필요 폴드 빈도)

**정의**: 공격적 베팅(특히 블러핑)이 즉시 +EV 되기 위한 **상대 폴드 최소 빈도**.

**공식**:
```
alpha = bet / (pot + 2·bet)
```

혹은 단순화:
```
alpha = required_fold_frequency = bet / (pot + bet + bet)
```
(콜 발생 시 해당 핸드는 `−bet`, 폴드 발생 시 `+pot`)

**유도**: `EV(bluff) = f·pot − (1−f)·bet = 0` → `f = bet/(pot+bet)`. 이것이 0-equity 블러핑의 break-even.

**실제 equity 포함** 버전: 블러핑 핸드도 약간의 equity `e` 가 있으면 `f = (bet − e·(pot+2·bet)) / (pot+bet)`.

**우리 설계 적용**: `estimate/bayes.py` 의 `FOLD_TO_BET` posterior 와 비교하여 블러핑 +EV 여부 판정. 저데이터 구간은 `P(fold)` 불확실하므로 alpha 근처에서는 블러핑 금지(I.2 cs_factor).

---

### 3.4 Equity

**정의**: 주어진 보드·핸드 조합에서 **쇼다운까지 갔을 때 이길 확률** (스플릿은 0.5 가중).

**계산**:
- **Preflop**: 169×169 lookup 또는 프리컴퓨트 JSON. 2–9-way.
- **Postflop**: Monte Carlo rollout (1k–5k 샘플). 알려지지 않은 카드를 랜덤 분배 후 핸드 랭킹 비교.

**라이브러리**: `treys` (호환 표기 `Ah,Tc`; BOT_GUIDE §3 일치).

**변종**:
- `raw_equity`: 위 정의.
- `realized_equity = raw_equity · ρ(position, SPR)`: 실제 쇼다운 도달 비율 보정. OOP 일수록 ρ 작음.

**주의**: ρ 의 경험적 값은 문헌마다 다름. 우리 초안은 Section 부록 C 의 `× 0.9` 임시값. 후속 R2/R4 에서 실증 보정.

---

### 3.5 SPR (Stack-to-Pot Ratio)

**정의**:
```
SPR = effective_stack / pot
```
(effective_stack = 상대와 내 스택 중 작은 쪽)

**전략 함의**:
| SPR | 해석 | 주요 전략 |
|-----|------|-----------|
| < 1 | 거의 commit | 모든 made hand 로 jam |
| 1–3 | commit 문턱 | 강한 made hand → commit, 블러핑 금지 |
| 3–6 | 표준 | 대부분 NLHE 전략 적용 |
| > 6 | deep | implied odds↑, 드로 가치↑, top-pair 조심 |

**BOT_GUIDE 대응**:
- 우리 서버의 SPR 은 **Lv이 올라갈수록 급감**. Lv6+ 는 거의 모든 포스트플롭 SPR < 3.
- 저SPR 플레이는 단순함 (commit or fold) → 콜드 스타트 구간에서 유리.

---

### 3.6 Polarized vs Linear Ranges

**Linear range (강한 핸드부터 순서대로)**:
- 예: {AA, KK, QQ, JJ, AKs, AQs, AKo} — 상위 핸드 집합.
- **합리적 default**: 정보 적을 때.
- Exploitation 저항성이 높음.

**Polarized range (강함 ∪ 약함)**:
- 예: value {AA, KK} ∪ bluff {76s, 54s, K2s suited-with-flush-card}.
- **큰 사이즈 베팅에 적합**: value 는 commit, bluff 는 fold equity 활용.
- 상대 calling range 예측 가능할 때 효과적.

**우리 설계 적용**:
- Cold-start: **linear 선호** (I.2 value-heavy default).
- Balanced/Exploit: polarized 로 전환 (개인 데이터 기반).

---

### 3.7 Realization of Equity (ρ)

**정의**: 쇼다운까지 도달한 비율 × raw equity.

**영향 요인**:
- **Position**: IP ρ ≈ 1.0–1.1, OOP ρ ≈ 0.85–0.95.
- **SPR**: SPR 높을수록 ρ 편차↑ (realize 실패 가능성).
- **Range 구성**: 드로-heavy 는 ρ < 1, made-heavy 는 ρ ≥ 1.
- **상대 공격성**: aggressive villain 은 우리 ρ 감소.

**공식 근사** (문헌):
```
ρ = 1.0 + 0.1 · position_bonus - 0.05 · spr_excess - 0.1 · villain_aggression
```

**우리 설계**: 부록 C 의 `× 0.9` 상수는 **모든 요인의 평균적 감소량**. 실증 데이터(R2/R4) 로 대체.

---

### 3.8 Nash Push/Fold

**정의**: 짧은 스택 heads-up (또는 n-way open shove) 에서의 **게임 이론적 균형**. 특정 M 값 이하에서는 all-in 또는 fold 만 합리적이며, Nash 평형은 상대 도박 시에도 exploitable 하지 않은 range.

**전제**:
- M ≤ 10 (대략). 레이즈 → 콜 → 포스트플롭 의사결정의 EV 가 0-depth all-in 대비 의미 있게 높지 않음.
- SPR 이 너무 낮아 post-flop play 가 불가능.

**공개 차트 출처**:
- **HoldemResources** (HRC): HU 및 n-way Nash chip-EV 및 ICM.
- **ICMIZER**: 토너먼트 Nash, ICM 적용 가능.
- **SnapShove** (무료): HU + short-stack 단순판.

**우리 서버 적용**:
- 상금 구조 없음 → **chip-EV Nash** 또는 **선형 ICM 근사** (1.0/0.5/0.3/...) 차트 사용.
- 실제 상금 표 입수 시 ICMIZER 재계산.

**M bucket 매핑** (configs/blind_schedule.yaml `mode_thresholds`):
- `M ≤ 5`: Nash jam 범위 (예: HU UTG 5BB jam ≈ top 40%).
- `5 < M ≤ 8`: 혼합 (open min raise vs jam).
- `8 < M ≤ 15`: hybrid (open/3bet 차트 + postflop 단순 룰).

---

### 3.9 ICM (Independent Chip Model)

**정의**: 토너먼트에서 **칩 가치 ≠ 상금 가치**. 칩은 한계효용 체감 (많은 칩일수록 1칩의 상금 가치 감소).

**공식** (단순):
```
$EV_i = Σ_k P(i 가 k위) · Payout_k
```
확률 `P(i 가 k위)` 는 반복 계산 (Malmuth-Harville 또는 Roberts 공식).

**적용 조건**:
- 상금 구조(Payout_k) 알려져 있어야 함.
- **우리 서버는 상금 미제공 (§5.8)** → 정식 ICM 불가.

**우리 대체안 (평가 C1/A4)**:
- **log-utility**: `U(stack) = log(stack + ε)`. Stack 작을수록 곡률↑ = 자연 risk-aversion. 선형 상금에서는 ICM 과 유사 효과.
- **순위 기반 가상 상금**: `[1.0, 0.5, 0.3, 0.2, 0.1, 0, 0, 0, 0]` 등. 임의 가정.
- **결론**: log-utility 단일화.

---

### 3.10 Implied / Reverse-Implied Odds

**Implied odds**: 현재 팟만이 아니라 **미래 스트리트에서 받을 추가 베팅** 까지 고려한 조정 pot odds.
- 드로 핸드: `required_equity = to_call / (pot + to_call + expected_future_bet)`
- implied odds 가 높으면 pot odds 이하 equity 로도 콜 가능.

**Reverse-implied odds**: 우리 핸드가 맞아도 **우리가 더 큰 베팅에 당할 위험**.
- 지배 당한 핸드 (K9 vs KQ) 가 전형적.

**우리 설계 적용**:
- 부록 C 의 `future_street_adjustment` 가 implied odds 를 `× 0.9` 로 거칠게 근사.
- EV tree 1-ply 확장 시 자동으로 implied 가 계산됨.
- 저데이터 구간(I.5.c) 의 dominated hand 제외 정책은 reverse-implied 방어.

---

### 3.11 Board Texture

**축 1. Wetness**:
- **Dry** (K72 rainbow, low connection): preflop aggressor 유리, cbet 높음.
- **Wet** (9h8h7d, many draws): caller range 유리, cbet 낮춤.

**축 2. High Card**:
- **A-high, K-high**: aggressor 의 raise range 에 많음 → range advantage.
- **Low boards (2-9)**: caller 의 콜드-콜/블라인드 defend range 에 연결.

**축 3. Paired**:
- **Paired boards**: 둘 다 2-pair+ 확률 낮음 → static, cbet 가능.
- **Unpaired wet**: 에퀴티 분산 크고 drawing-heavy.

**우리 설계 (H.5)**:
- `board_texture.py` 로 `{wetness, high_card, paired, monotone}` 벡터화.
- CBET 기본 확률 = `sigmoid(range_advantage - 0.3·wetness)`.

---

## 4. 핵심 공식 요약

| 공식 | 수식 | 사용처 |
|------|------|--------|
| Pot odds | `to_call / (pot + to_call)` | 콜 break-even equity |
| MDF | `pot / (pot + bet)` | 방어 최소 빈도 |
| Alpha | `bet / (pot + 2·bet)` | 블러핑 필요 폴드 빈도 |
| SPR | `eff_stack / pot` | commit 성향 지표 |
| M | `stack / (SB + BB)` | 토너먼트 긴장도 |
| EV(call) | `eq·(pot + call) − call` | 콜의 기대값 |
| EV(raise) | `f·pot + (1−f)·[eq·(pot+2ΔS) − ΔS]` | 레이즈의 기대값 (부록 C) |

---

## 5. Interpretation

### 5.1 핵심 발견
- **우리 서버의 특성상 SPR < 3 구간이 지배**. 복잡한 polarized 전략보다 commit decision 이 핵심.
- **ICM 불가** → log-utility 로 대체가 수학적 정당성 있음.
- **저데이터 구간의 MDF 방어**는 외부 데이터 없이도 즉시 적용 가능한 안전장치.

### 5.2 우리 서버로의 전이
- **완전 전이**: pot odds, MDF, alpha, SPR, M, EV 공식.
- **조건부 전이**: realized equity ρ (실증 값 필요), Nash 차트 (chip-EV 모드만).
- **불가 전이**: 정식 ICM, implied odds (EV tree 없이).

### 5.3 전이 불가능 영역
- cash game 기반 "100bb deep GTO" 논의: 우리 서버에 Lv3 까지만 유효. 이후는 완전 다른 게임.

---

## 6. Parameter Output

이 문서 직접 산출물은 없음. 개념적 근거만 제공. 구체 파라미터는:
- `configs/blind_schedule.yaml` (§3.8 Nash 경계)
- `configs/sizing.yaml` (향후 작성, §3.7 realization)
- `configs/priors.yaml` (향후 작성, §3.6 range 기본값)

---

## 7. Limitations & Caveats

1. **외부 문헌 의존**: 각 개념의 정의는 Chen & Ankenman, Sklansky 등의 표준 문헌 기반. 그러나 우리 서버 고유의 metagame (AI 봇 혼합, 시즌 제한 등) 은 반영 안 됨.
2. **Nash 차트 출처 미확정**: §3.8 의 공개 차트 접근 가능성은 R5 에서 확인 필요.
3. **ρ 의 경험값 부재**: §3.7 은 문헌 평균. 우리 서버의 실측은 self-play 후에만 가능.
4. **MDF 의 range 단위 적용**: 개별 핸드 결정과 range 결정의 구분이 실제 구현에서 모호. range-wise tracking 이 복잡.

---

## 8. Next Steps

- R2 EDA 에서 **실측 ρ** 계측: 쇼다운 도달 비율 vs raw equity.
- R5 에서 **HU Nash chip-EV 차트** 확보 및 9-max 차트 파생.
- R3 의 `sizing.yaml` 에서 §3.6 polarized vs linear 사용 조건 파라미터화.
- `src/holdem/math/odds.py` 에 §4 의 공식 전부 구현 (D2).

---

## 9. References

1. `guide/BOT_GUIDE.md` — 서버 규칙.
2. Chen, Bill & Ankenman, Jerrod. *The Mathematics of Poker*. (MDF, alpha, EV 공식)
3. Sklansky, David. *The Theory of Poker*. (pot odds, implied odds)
4. HoldemResources Calculator — Nash Push/Fold 참고.
5. ICMIZER — 토너먼트 Nash 참고.
6. `research/bot_guide_extracts.md` — 내부 룰 출처.

---

## Changelog

- 2026-04-19 (v0.1): 초안. §3 핵심 개념 10개 정의·공식·적용 조건.
