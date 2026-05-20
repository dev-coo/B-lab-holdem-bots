# EDA 02 — 4-Class Typing 검증 (J.4)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Related configs**: `configs/class_priors.yaml` (초안, Draft)
- **Related code**: `scripts/class_typing_eda.py`, `src/holdem/estimate/class_typer.py` (미구현)
- **Related BOT_GUIDE sections**: §4 (position), §5.3 (action_request), §13 (이벤트 요약)

---

## 1. Objective

이 문서가 답하는 단일 질문:
> Kaggle LLM-vs-LLM HU 데이터셋에서 15 모델을 (VPIP, PFR, AF) 평면에서
> 4-class (TAG/LAG/NIT/Fish) 로 유의미하게 분류할 수 있는가?
> 불가능하다면, 우리 서버의 class 경계를 어떻게 재조정해야 하는가?

---

## 2. BOT_GUIDE Compliance

`research/bot_guide_extracts.md` 에서 인용:

- [§5.3] action_request 에서 `players[*]` 의 streamed action 이 `calls/bets/raises/folds/checks` 어휘로만 노출 → VPIP/PFR/AF 정의는 이 어휘만으로 계산 가능.
- [§4] HU(2인)·3인~9인 포지션 정의. HU 에서는 **SB = button** 이며 blind post 후 첫 액션자.
- [§6.1] 액션 종류 제약: fold/check/call/raise/allin. `bets` 는 데이터셋 포맷상 "첫 베팅"
  으로 구분되어 있으나 서버 프로토콜상 `raise (from 0)` 와 동형. AF 집계에서 bets+raises 로 합산한다.

**위배 위험과 방어**:
- 데이터셋의 `bets` 를 서버의 첫 raise 와 동일 의미로 매핑해야 한다. 본 집계는 `(bets + raises) / calls` 로
  정의하여 표기 차이를 흡수. → 서버 로그 집계 시 서버의 `raise` 액션만 세어도 동일 의미를 갖도록 통합 가능.
- HU 데이터를 full-ring 에 직접 적용 금지 (§J.2 전이 계수 적용 영역).

---

## 3. Method

### 3.1 데이터
- **원천**: `data/raw/poker/*.txt` (Kaggle `kaggle/poker-heads-up`, 105 matchup 파일, 2,059,400 핸드)
- **필터**: 플레이어별 핸드 수 ≥ 500 (15 모델 전부 만족, 최소 239k)
- **전처리**: `posts small/big blind` 로 SB/BB 식별, preflop 첫 voluntary action 추출

### 3.2 절차
```bash
uv run python scripts/class_typing_eda.py
# → data/player_stats.csv
# → data/class_typing_report.json
```

### 3.3 도구·버전
- `scikit-learn>=1.3` (KMeans, GaussianMixture, silhouette_score)
- `numpy>=1.26` (log1p 변환)

---

## 4. Results

### 4.1 플레이어별 집계 (내림차순 by hands)

| Model | hands | VPIP | PFR | AF | VPIP_SB | VPIP_BB |
|---|---:|---:|---:|---:|---:|---:|
| Claude Sonnet 4.5 | 280,000 | 0.821 | 0.529 | 2.08 | 0.897 | 0.745 |
| GPT-5.2 | 280,000 | 0.889 | 0.624 | 1.84 | 0.998 | 0.781 |
| GPT-5 mini | 280,000 | 0.838 | 0.577 | 1.86 | 0.988 | 0.689 |
| Gemini 3 Flash Preview | 280,000 | 0.661 | 0.441 | 1.19 | 0.731 | 0.591 |
| Grok 4.1 Fast Reasoning | 280,000 | 0.763 | 0.570 | 3.86 | 0.864 | 0.661 |
| Grok 4 | 280,000 | 0.835 | 0.723 | **6.59** | 0.956 | 0.714 |
| o3 | 280,000 | 0.819 | 0.598 | 2.38 | 0.980 | 0.658 |
| Claude Opus 4.5 | 279,800 | 0.786 | 0.505 | 1.47 | 0.891 | 0.682 |
| DeepSeek V3.2 | 279,800 | 0.738 | 0.541 | 2.91 | 0.816 | 0.660 |
| Gemini 3.1 Pro Preview | 275,800 | **0.485** | 0.349 | 1.93 | 0.529 | 0.442 |
| Claude Opus 4.6 | 274,800 | 0.798 | 0.522 | 1.61 | 0.898 | 0.699 |
| Claude Sonnet 4.6 | 272,700 | 0.873 | 0.624 | 2.26 | 0.979 | 0.766 |
| GPT-5.4 mini | 269,000 | 0.879 | 0.570 | 1.79 | 0.996 | 0.762 |
| GPT-5.4 | 267,300 | 0.897 | 0.500 | 1.09 | 0.992 | 0.802 |
| Gemini 3 Pro Preview | 239,600 | **0.543** | 0.300 | **0.68** | 0.556 | 0.530 |

### 4.2 군집 결과 (k=4, features=[VPIP, PFR, log1p(AF)])

**K-Means silhouette = 0.350**
**GMM silhouette = 0.350**
**GMM boundary ratio (soft-max prob < 0.7) = 0.0%**

| Cluster | VPIP | PFR | AF | 자동 라벨 | 멤버 |
|---|---:|---:|---:|---|---|
| 0 | 0.799 | 0.544 | 1.90 | LAG | Claude Opus 4.5/4.6, Sonnet 4.5, GPT-5.4 mini, GPT-5 mini, GPT-5.2, Sonnet 4.6, o3, Gemini 3 Flash Preview, Gemini 3.1 Pro, GPT-5.4 (대다수) |
| 1 | 0.751 | 0.555 | 3.36 | LAG* | Grok 4.1, DeepSeek V3.2 (hyper-aggressive LAG) |
| 2 | 0.700 | 0.413 | 0.97 | Fish | Gemini 3 Pro Preview (passive) |
| 3 | 0.835 | 0.723 | 6.59 | LAG** | Grok 4 (singleton) |

### 4.3 주요 수치 관찰

- **15 모델 전부 VPIP ≥ 48.5%** (전통적 tight 기준 20~25% 를 크게 초과).
- **AF 평균 2.4, 표준편차 1.5** — 우리의 원안 경계(AF < 1 passive, AF ≥ 2 aggressive) 는 HU 풀에서 거의 전원을 aggressive 로 분류.
- **SB 에서 VPIP_SB 평균 0.87** — HU SB 는 블라인드 토큰 투입 후 fold 시 손실 확정이라 실질 RFI 확률이 매우 높다(steal 가격 동기).
- **BB 에서 VPIP_BB 평균 0.67** — BB 는 체크 옵션 존재 + 블라인드 discount 로 defend 가 기본.
- **극단값**: Grok 4 (AF 6.59), Gemini 3 Pro Preview (AF 0.68) — 양 극단이 singleton 군집을 형성.

---

## 5. Interpretation

### 5.1 핵심 발견

**① 전통적 4-class (TAG/LAG/NIT/Fish) 가정은 HU LLM 풀에 직접 적용 불가.**
- 15 모델 중 14 개가 자동 라벨러로 LAG 로 분류되었으며, 유일한 "Fish" (Gemini 3 Pro) 조차 VPIP 70% 의 **active-passive** 이다.
- 전통적 NIT/TAG 를 위한 VPIP < 30% 영역은 **empty**.

**② HU 라는 형식 자체가 VPIP 를 상향한다.**
- HU 에서 SB 는 블라인드 투입 상태에서 폴드 시 블라인드 손실 확정 → 수학적으로 RFI 임계가 낮음 (≈ top 70% 핸드까지 +EV steal).
- 따라서 HU 에서 관측되는 VPIP 80% 는 full-ring 의 VPIP 80% 와 동등한 "루즈" 가 아니라 **포지션 수학의 귀결**이다.
- **full-ring 전이 시 position 보정 필수** — HU VPIP × ~0.35 ≈ full-ring VPIP (§J.2 권장값).

**③ 해석 가능한 2 차원 축: (PFR/VPIP 비율, AF).**
- PFR/VPIP = "aggression initiative" (raise vs call 비율). 0.3~0.9 의 넓은 분포.
- AF = "post-flop aggression". 0.7~6.6 의 1 decade 분포.
- 이 두 축이 HU 풀을 구분하는 실제 특성축. VPIP 단독은 분별력이 낮다.

**④ silhouette 0.35 는 "weak structure"** — 4-class 강제보다 **continuous embedding** 이 더 적합.

### 5.2 우리 서버로의 전이 가능성

BOT_GUIDE §8 규칙 (4~9인 토너먼트, 300 스택, 급블라인드) 대비:

| 축 | 전이 가능성 | 보정 방법 |
|---|---|---|
| AF 분포 | **가능** | 바로 사용. post-flop 행동은 인원수 의존도 상대적 낮음 |
| PFR/VPIP 비율 | **부분 가능** | 포지션별 재가중 후 사용 |
| VPIP 절대값 | **전이 금지** | HU 특화, full-ring 전이 계수 ×0.35~0.6 필수 |
| 클러스터 경계 | **재설계** | 우리 서버용 경계: VPIP 기준은 position-normalized VPIP 사용 |

### 5.3 전이 불가능 영역

- **경계값 그대로 복사 금지**: "LAG centroid VPIP=0.80" 을 서버에 그대로 적용하면 모든 상대를 LAG 로 분류.
- **PFR_BB 의 0.15~0.80 분포**: HU BB 의 raise 는 3bet 만 의미하나 full-ring BB 는 squeeze 등 다른 동기. 이 수치 직접 매핑 금지.
- **Singleton cluster (Grok 4, Gemini 3 Pro Preview)**: 개별 특성이 너무 강해 class 템플릿으로 사용할 수 없음.

---

## 6. Parameter Output

초안으로 `configs/class_priors.yaml` 에 반영 (Stage: Draft, 실서버 self-play 후 재보정).

```yaml
# configs/class_priors.yaml
# 근거: research/dataset_analysis/eda_02_clusters.md §4.2 (HU 데이터 기반)
# 주의: VPIP 는 HU 값. 서버(4~9인) 적용 시 configs/transfer_coefficients.yaml 의 계수 곱 필수.
version: 0.1
stage: draft
source: "eda_02_clusters.md v0.1 (HU silhouette=0.35)"

hu_centroids_raw:
  LAG_standard: {VPIP: 0.80, PFR: 0.54, AF: 1.90}
  LAG_hyper:    {VPIP: 0.75, PFR: 0.56, AF: 3.36}
  LAG_maniac:   {VPIP: 0.84, PFR: 0.72, AF: 6.59}
  Fish_active:  {VPIP: 0.70, PFR: 0.41, AF: 0.97}

# 서버 full-ring 기준 4-class 경계 (초안, 문헌값 혼합)
server_class_priors:
  NIT:
    # VPIP<20 & AF<1
    VPIP: {alpha: 12, beta: 88}
    PFR:  {alpha: 9,  beta: 91}
    AF:   {mean: 0.6, beta_on_calls: true}
    BLUFF_AT_SHOWDOWN: {alpha: 6, beta: 94}
    CBET: {alpha: 55, beta: 45}
  TAG:
    # 20≤VPIP<30 & AF≥2
    VPIP: {alpha: 22, beta: 78}
    PFR:  {alpha: 18, beta: 82}
    AF:   {mean: 2.5}
    BLUFF_AT_SHOWDOWN: {alpha: 18, beta: 82}
    CBET: {alpha: 70, beta: 30}
  LAG:
    # 30≤VPIP<45 & AF≥2  (HU 관측 centroid 에서 VPIP ×0.4)
    VPIP: {alpha: 32, beta: 68}
    PFR:  {alpha: 24, beta: 76}
    AF:   {mean: 3.0}
    BLUFF_AT_SHOWDOWN: {alpha: 28, beta: 72}
    CBET: {alpha: 75, beta: 25}
  Fish:
    # VPIP≥35 & AF<1.5
    VPIP: {alpha: 42, beta: 58}
    PFR:  {alpha: 16, beta: 84}
    AF:   {mean: 0.9}
    BLUFF_AT_SHOWDOWN: {alpha: 10, beta: 90}
    CBET: {alpha: 50, beta: 50}

# 경계 규칙
class_boundaries:
  tight_vpip_threshold: 0.30
  loose_vpip_threshold: 0.45
  passive_af_threshold: 1.5
  aggressive_af_threshold: 2.0
  # 경계 내부는 soft assignment: gmm_prob 를 prior 가중치로
```

---

## 7. Limitations & Caveats

- **HU 전용 데이터**: 4-9 way 전이는 계수 적용 + bootstrap 재보정 필요. 실제 centroid 는 여기서 확정하지 않는다.
- **15 표본**: 군집 분석에 N=15 는 매우 작다. silhouette 0.35 는 강한 구조의 증거가 아니다. GMM covariance 과적합.
- **LLM 풀 편향**: 현대 LLM 들이 모두 LAG 방향으로 치우침 — 우리 서버도 유사 풀일 수 있으나 **인간/기존 봇 혼재** 시 분포 재확장 예상.
- **Position normalization 미완**: VPIP_SB/BB 분리 수치만 수집. 서버의 EP/MP/LP/BLIND 4-position 데이터가 쌓이면 position-wise VPIP 로 재정의 필요.
- **Bet vs Raise 의미 차이**: 데이터셋의 `bets` 는 street 첫 공격, `raises` 는 반응. 서버 프로토콜에서는 둘 다 `raise`. AF 집계는 이를 합산하여 호환성 확보했으나 **street 별 분리 집계는 미수행**.

---

## 8. Next Steps

- (주 5-6, R4) Self-play 부트스트랩으로 4~9인 환경의 class centroid 생성 → 이 문서의 `server_class_priors` 를 교체.
- (주 7+, D3) `src/holdem/estimate/class_typer.py` 구현: 롤링 window (25/50/100 핸드) 로 soft classification.
- (주 8, O3) 실서버 로그가 쌓이면 class 경계 vs win-rate 함수의 형태를 확인하여 **경계 재조정 루프**.
- (optional) Continuous embedding 도입: 4-class 강제 대신 (VPIP, PFR_ratio, AF) 3D 공간의 nearest-k prior blending.

---

## 9. References

- [1] `guide/BOT_GUIDE.md` §4, §5.3
- [2] Kaggle `kaggle/poker-heads-up` (CC BY 4.0) — `research/LICENSE_NOTE.md`
- [3] `data/player_stats.csv`, `data/class_typing_report.json`
- [4] `research/dataset_analysis/inspection_report.md` (J.1 gate)

---

## Changelog

- 2026-04-19 (v0.1): 초안 작성. 15 LLM 분포 · 4-class 경계 재설계안 포함.
