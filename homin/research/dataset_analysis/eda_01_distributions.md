# EDA 01 — Population Prior 분포 (J.3)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Related configs**: `configs/priors.yaml`, `configs/transfer_coefficients.yaml`
- **Related code**: `scripts/calc_population_prior.py`
- **Related BOT_GUIDE sections**: §4 (position), §5.3 (action_request), §5.4 (action_performed), §5.5 (phase_change), §6.1 (action 어휘)

---

## 1. Objective

이 문서가 답하는 단일 질문:
> HU Kaggle 데이터셋에서 주요 post-flop·preflop 행동 빈도 (CBET, FOLD_TO_CBET, BARREL,
> 3BET, FOLD_TO_3BET) 를 집계하여 Beta prior 를 산출한다. 각 지표의 HU→full-ring 전이 후
> 서버용 `priors.yaml` 초안 값은 무엇인가?

---

## 2. BOT_GUIDE Compliance

`research/bot_guide_extracts.md` 에서 인용:

- [§5.3] `action_request.action_history` 에서 스트리트별 액션 재구성 가능. 본 스크립트는 오프라인 데이터를 동일 논리로 재구성.
- [§5.5] `phase_change` 이벤트로 스트리트 전환 확인. 본 집계는 `*** FLOP/TURN/RIVER ***` 마커로 스트리트 분할 — 동등 의미.
- [§6.1] 액션 어휘는 fold/check/call/raise/allin. 본 데이터셋의 `bets` 는 서버의 첫 `raise` 와 등가 → 집계 로직에서 `bets`/`raises` 모두를 "aggression attempt" 로 취급.
- [§4] HU (2인): SB = button, 포지션 수학의 특수성으로 VPIP 및 3bet 빈도가 full-ring 과 크게 다름.

**위배 위험과 방어**:
- `bets` 와 `raises` 를 합쳐 aggression 으로 집계 → 서버에서는 `raise` 만 나오므로 런타임 집계기는 `raise` 단일 어휘로 통일. 본 문서의 rate 는 동일 의미 하에 해석 가능.
- FOLD_TO_3BET 은 "open raiser 가 3bet 후 첫 응답으로 fold" 로 정의. 체크/콜은 별도 카운트에서 분모에 포함 (tries).

---

## 3. Method

### 3.1 데이터
- **원천**: `data/raw/poker/*.txt` (Kaggle `kaggle/poker-heads-up`, 2,059,400 핸드, 105 matchup 파일)
- **필터**: blinds 2인 완전 posting, preflop 에 최소 1 raise 존재 (CBET 분석 trigger).

### 3.2 절차
```bash
uv run python scripts/calc_population_prior.py
# → data/population_prior_report.json
```

### 3.3 도구
- Python stdlib 만 사용 (정규식 기반 파싱).

---

## 4. Results

### 4.1 Population rates (HU LLM 풀, n = 2,059,400 hands)

| Metric | tries | hits | rate | Beta(α, β) |
|---|---:|---:|---:|---|
| THREE_BET | 1,781,721 | 417,118 | **0.234** | Beta(417,118, 1,364,605) |
| FOLD_TO_THREE_BET | 417,117 | 207,392 | **0.497** | Beta(207,392, 209,727) |
| CBET | 1,126,024 | 869,194 | **0.772** | Beta(869,194, 256,832) |
| FOLD_TO_CBET | 869,193 | 298,205 | **0.343** | Beta(298,205, 570,990) |
| BARREL_TURN | 437,664 | 261,614 | **0.598** | Beta(261,614, 176,052) |
| BARREL_RIVER | 138,828 | 66,044 | **0.476** | Beta(66,044, 72,786) |

### 4.2 관찰

**① HU 3BET 빈도 23.4% — 인간 HU 풀 (~12~15%) 대비 높다.**
- LLM 풀은 open 에 대한 3bet 을 적극. 잠재적으로 블러핑 3bet 비중이 큼.

**② CBET 77.2% — 인간 HU 풀 (~65%) 대비 소폭 높음.**
- LLM 들이 flop 에서 "aggressor 라면 bet" 원칙을 거의 자동 적용.

**③ FOLD_TO_CBET 34.3% — HU 에서 defend 가 많음.**
- HU 에서 상대 range 가 넓어 MDF 만족 조건이 낮다 → defend 쪽.
- 인간 HU 풀 (~45~55%) 보다 낮음.

**④ BARREL_TURN 60%, BARREL_RIVER 48%.**
- 일단 cbet 하면 turn 도 60% 확률로 barrel. "원샷 cbet 후 give up" 이 40%.
- River barrel 은 48% — turn 까지 갔으면 river 도 밀어붙이는 경향.

**⑤ FOLD_TO_THREE_BET 49.7% — 인간 풀과 유사.**
- Open raiser 의 3bet 방어는 수학 기반이라 풀 무관 유사.

### 4.3 HU → Full-ring 전이 적용

`configs/transfer_coefficients.yaml` 의 계수 사용.

| Metric | HU rate | hu_to_9max | 9max estimate | hu_to_6max | 6max estimate | 등급 |
|---|---:|---:|---:|---:|---:|---|
| THREE_BET | 0.234 | 0.60 | **0.140** | 0.75 | 0.176 | MID |
| FOLD_TO_3BET | 0.497 | 1.00 | **0.497** | 1.00 | 0.497 | MID |
| CBET | 0.772 | 0.92 | **0.710** | 0.95 | 0.733 | HIGH |
| FOLD_TO_CBET | 0.343 | 0.95 | **0.326** | 0.98 | 0.336 | HIGH |
| BARREL_TURN | 0.598 | 0.90 | **0.538** | 0.95 | 0.568 | HIGH |
| BARREL_RIVER | 0.476 | 0.85 | **0.405** | 0.92 | 0.438 | HIGH |

**Sanity check**:
- 9max CBET 0.71 → 인간 풀 상식 0.65~0.75 범위. ✓
- 9max FOLD_TO_CBET 0.33 → 인간 풀 0.40~0.55 대비 약간 낮음. LLM 특성 일부 잔존.
- 9max BARREL_TURN 0.54 → 상식 0.45 대비 약간 높음.

LLM 풀 편향을 완전히 제거하지 못하므로 **부트스트랩 재보정 필수** (R4 Step 4).

---

## 5. Interpretation

### 5.1 핵심 발견

**① HU 와 인간 풀의 차이는 대체로 aggression 방향.**
- CBET, BARREL_TURN 이 인간 대비 상승, FOLD_TO_CBET 하락. LLM 들이 전체적으로 공격적 스트리트 진행.
- 우리 봇은 **MDF 하한 (§H.4)** 을 엄격히 지키면 LLM 상대 exploitable 하지 않음.

**② 2-way 지표 (CBET/FOLD_TO_CBET/BARREL_*) 는 전이 계수 0.9~1.0 으로 직접 전이 가능.**
- 이 범주가 `priors.yaml` 에서 가장 신뢰할 수 있는 초기값.
- 실서버 확인 전까지 **이 수치로 시작**.

**③ Volume 지표 (VPIP/PFR/3BET) 는 전이 계수 0.3~0.6 필요 → 부트스트랩 의존도 높음.**
- 위 표의 9max estimate 는 "관측 + 전이" 의 단순 곱이라 오차 크다.
- Step 4 self-play 결과와 **blend** (transfer_coefficients.yaml `application_rules` 참조).

**④ Bootstrapping 전 사용 가능한 prior.**
- 첫 배포 (주 2 말) 시점에는 **HU rate 를 그대로 사용 금지**.
- 대신: HU rate × 전이 계수 → `configs/priors.yaml` draft 값 → 첫 20~50핸드 후 개인 posterior 가 populate.

### 5.2 우리 서버로의 전이 가능성

| 지표 | 등급 | 전이 방식 |
|---|---|---|
| CBET | HIGH | HU rate × 0.92 (9max) 또는 × 0.95 (6max) |
| FOLD_TO_CBET | HIGH | HU rate × 0.95 |
| BARREL_TURN | HIGH | HU rate × 0.90 |
| BARREL_RIVER | HIGH | HU rate × 0.85 |
| THREE_BET | MID | HU rate × 0.60 (9max), blend w/ bootstrap 권장 |
| FOLD_TO_3BET | MID | HU rate × 1.00, blend w/ bootstrap 권장 |

### 5.3 전이 불가능 영역

- **Preflop VPIP / PFR 절대값**: HU 특수성이 압도적 (SB blind 위치 수학). 전이 계수만으로 정확 추정 불가능.
- **Position-specific rate (EP/MP/LP VPIP)**: HU 는 SB/BB 두 포지션뿐. 4+way 의 포지션별 VPIP 비대칭은 본 데이터에서 유도 불가.
- **Multiway CBET 감소**: 3+way 팟에서 CBET 빈도는 급감. HU 데이터에 없음.

---

## 6. Parameter Output

```yaml
# configs/priors.yaml (초안, Draft)
version: 0.1
stage: draft
source: "eda_01_distributions.md v0.1 (HU 2.06M) + transfer_coefficients.yaml v0.1"

# HU 관측값 원본 (참조, 전이 적용 전)
hu_observed:
  THREE_BET:         {rate: 0.234, alpha: 417118,  beta: 1364605}
  FOLD_TO_THREE_BET: {rate: 0.497, alpha: 207392,  beta: 209727}
  CBET:              {rate: 0.772, alpha: 869194,  beta: 256832}
  FOLD_TO_CBET:      {rate: 0.343, alpha: 298205,  beta: 570990}
  BARREL_TURN:       {rate: 0.598, alpha: 261614,  beta: 176052}
  BARREL_RIVER:      {rate: 0.476, alpha: 66044,   beta: 72786}

# Full-ring 전이 후 (9max 기본, 서버용 prior 초기값)
server_prior_9max:
  # Beta 는 "effective sample size 100" 기준으로 재스케일
  # α + β ≈ 100 (과도한 confidence 방지, 개인 posterior 에 의한 갱신 용이)
  THREE_BET:         {rate: 0.140, alpha: 14,  beta: 86}
  FOLD_TO_THREE_BET: {rate: 0.497, alpha: 50,  beta: 50}
  CBET:              {rate: 0.710, alpha: 71,  beta: 29}
  FOLD_TO_CBET:      {rate: 0.326, alpha: 33,  beta: 67}
  BARREL_TURN:       {rate: 0.538, alpha: 54,  beta: 46}
  BARREL_RIVER:      {rate: 0.405, alpha: 41,  beta: 59}
  # VPIP / PFR 는 blind_schedule × 포지션 × class 별로 별도. 여기선 단일 값 미기록.

# Full-ring 전이 후 (6max)
server_prior_6max:
  THREE_BET:         {rate: 0.176, alpha: 18,  beta: 82}
  FOLD_TO_THREE_BET: {rate: 0.497, alpha: 50,  beta: 50}
  CBET:              {rate: 0.733, alpha: 73,  beta: 27}
  FOLD_TO_CBET:      {rate: 0.336, alpha: 34,  beta: 66}
  BARREL_TURN:       {rate: 0.568, alpha: 57,  beta: 43}
  BARREL_RIVER:      {rate: 0.438, alpha: 44,  beta: 56}
```

---

## 7. Limitations & Caveats

- **LLM 풀 편향**: 모든 집계는 LLM-vs-LLM. 서버의 인간/봇/혼합 metagame 과 차이 존재. Self-play 부트스트랩 필수.
- **HU 전용**: 멀티웨이 dynamics (3+way CBET 감소, squeeze 등) 는 별도 데이터 필요.
- **Action ordering 재구성 오차**: `bets` 와 `raises` 의 순서 재구성이 정확하다고 가정. 복잡 시퀀스 (check-raise, reopen) 일부는 간소화됨.
- **CBET 정의**: "pf_aggressor 의 flop 첫 액션 = bets". check-behind 후 turn bet 은 CBET 아닌 delayed cbet 으로 미분류.
- **BARREL 정의**: call 로 진행된 경우만. raise 후 call 은 별도. 폴드/check-raise 시퀀스는 BARREL 분모에서 제외.
- **Alpha/Beta 스케일**: hit/tries 그대로 썼을 때 confidence 가 너무 높아 개인 posterior 에 의해 갱신되지 않음. `server_prior_*` 는 effective sample size 100 으로 rescale.

---

## 8. Next Steps

- VPIP/PFR 집계는 이미 `scripts/class_typing_eda.py` 에서 수행됨 (player-level). population 평균은 eda_01.1 로 별도 보고 또는 본 문서에 통합.
- Bootstrap self-play (R4) 후 각 지표의 blend: `final = w_hu × hu_based + w_server × bootstrap`.
- 서버 실로그가 1k 핸드 쌓이면 **per-matchup** 재집계 (인간/봇 구분).
- `src/holdem/persist/priors_loader.py`: `priors.yaml` 의 `server_prior_9max` 를 읽어 `PlayerProfile` 의 Beta counter 초기화.

---

## 9. References

- [1] `guide/BOT_GUIDE.md` §4, §5.3, §5.5, §6.1
- [2] `data/population_prior_report.json`
- [3] `configs/transfer_coefficients.yaml` v0.1
- [4] Kaggle `kaggle/poker-heads-up` — `research/LICENSE_NOTE.md`

---

## Changelog

- 2026-04-19 (v0.1): 전체 2.06M 핸드 집계, HU→full-ring 전이 초안 적용.
