# Population Prior — 수치 근거 (priors.yaml)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: `configs/priors.yaml` v0.1
- **Sources**:
  - `research/dataset_analysis/eda_01_distributions.md` v0.1
  - `research/dataset_analysis/eda_02_clusters.md` v0.1 (VPIP/PFR/AF 평균)
  - `configs/transfer_coefficients.yaml` v0.1
- **BOT_GUIDE refs**: §5.3 action 스트림, §4 포지션, §1.1 영속 통계

---

## 1. 결정 요약

`configs/priors.yaml` 은 **"상대 데이터 0인 상태에서도 합리적 기본값"** 제공이 목적이다.
HU Kaggle 관측값 → 포지션·인원 전이 계수 → Beta 재스케일(ESS=100) 의 3단계로 산출.

```
관측값 (HU 2.06M) ──×──> 전이 계수 (hu_to_{9,6,4}max)
                          │
                          ▼
               population rate (full-ring 추정)
                          │
                          ▼
               Beta(α, β) with α + β ≈ 100
                          │
                          ▼
              shrinkage 의 third layer 로 주입
```

---

## 2. 각 지표의 근거

### 2.1 CBET — `rate: 0.710` (9max)

- **HU 관측**: 0.772 (n=1,126,024)
- **전이 계수 (9max)**: 0.92 (CBET 은 2-way dynamics 유지, 전이 신뢰도 HIGH)
- **도출**: 0.772 × 0.92 = **0.710**
- **Beta**: α=71, β=29 (ESS=100)
- **타당성 체크**: 인간 9max 풀 통상값 0.65~0.75 범위 안 → ✓

### 2.2 FOLD_TO_CBET — `rate: 0.326`

- **HU 관측**: 0.343
- **전이 계수**: 0.95
- **도출**: 0.343 × 0.95 = **0.326**
- **Beta**: α=33, β=67
- **타당성**: 인간 풀 0.40~0.55 보다 낮다. **LLM 풀 defend-heavy** 편향 잔존 → 부트스트랩 재조정 대상.

### 2.3 BARREL_TURN — `rate: 0.538`

- **HU**: 0.598
- **계수**: 0.90
- **도출**: **0.538**
- **Beta**: α=54, β=46
- **타당성**: 인간 풀 0.45~0.55. 살짝 상단 — LLM 성향. 허용.

### 2.4 BARREL_RIVER — `rate: 0.405`

- **HU**: 0.476
- **계수**: 0.85
- **도출**: **0.405**
- **Beta**: α=41, β=59
- **타당성**: 인간 풀 0.30~0.40. 역시 LLM 상단 편향.

### 2.5 THREE_BET — `rate: 0.140` (MID 등급)

- **HU**: 0.234
- **계수**: 0.60
- **도출**: **0.140**
- **Beta**: α=14, β=86
- **타당성**: 인간 9max 평균 0.05~0.08. 여전히 높음 — MID 등급이라 부트스트랩 blend 권장 (hu 0.4 : server 0.6).
- **주의**: 서버 배포 시점 실제 값은 **0.08 근처**로 수렴 예상. 초기 14 tries 는 금방 상쇄.

### 2.6 FOLD_TO_THREE_BET — `rate: 0.497`

- **HU**: 0.497
- **계수**: 1.00 (인원 무관 수학적 수비 비율)
- **도출**: **0.497**
- **Beta**: α=50, β=50
- **타당성**: 인간 풀 0.55~0.70. 약간 낮음 — 상대 3bet range 광범위 가정 시.

### 2.7 BLUFF_AT_SHOWDOWN — `rate: 0.200`

- **근거**: eda_05 river 분석에서 river bet 의 43.6% 가 pure bluff (eq=0). 전이 계수 0.75 → **0.33**. 하지만 HU 특유 편향을 더 감쇠 → **0.20** (인간 풀 문헌값 0.15~0.25 범위).
- **Beta**: α=20, β=80
- **주의**: 본 수치는 **문헌값 + 보정** 혼합. 순수 실증 아니라 self-play 후 재확정.

### 2.8 CHECK_RAISE — `rate: 0.080`

- **근거**: 본 데이터셋에서 직접 집계 안 함 (스크립트 미구현). 문헌값 0.08 사용.
- **Beta**: α=8, β=92
- **Next**: `scripts/check_raise_rate.py` 추가 계획.

---

## 3. Beta 스케일 결정 (ESS = 100)

**왜 rescale 하나?**
- 원본 Beta(869194, 256832) 를 그대로 두면 confidence 가 너무 커서 개인 posterior 의 20~50 관측치가 prior 에 파묻힘.
- Effective sample size = α + β. 이를 100 으로 통일하면:
  - 개인 n=20 관측 시 weight_personal ≈ 0.17 (과도한 개인 의존 방지)
  - 개인 n=100 관측 시 weight_personal ≈ 0.50 (균형)
  - 개인 n=500 관측 시 weight_personal ≈ 0.83 (개인 지배)

**스케일 공식**:
```
α_new = rate × 100
β_new = 100 − α_new
```

`priors.yaml` 의 `server_prior_*` 가 이 규칙으로 산출됨.

---

## 4. 포지션별 VPIP (문헌값 기반)

HU 데이터로는 full-ring 포지션별 VPIP 를 직접 유도 불가 (포지션이 SB/BB 둘뿐).
`priors.yaml` 의 `position_vpip_9max` 는 **순수 문헌값**:

| Position | α | β | VPIP |
|---|---:|---:|---:|
| EP | 12 | 88 | 12% |
| MP | 18 | 82 | 18% |
| CO | 26 | 74 | 26% |
| BTN | 38 | 62 | 38% |
| SB | 30 | 70 | 30% |
| BB | 22 | 78 | 22% |

**출처**: 포커 커뮤니티의 반복적 실측 근사. 비율 자체는 안정적. 절대값은 stake/풀에 따라 ±5%p.

---

## 5. 갱신 규칙

### 5.1 실시간 Bayesian 업데이트

```
posterior_α = prior_α + hits_personal
posterior_β = prior_β + (tries_personal - hits_personal)
```

매 관측 (액션 완료 또는 hand_result) 시 `+1`.

### 5.2 Shrinkage blend (§H.1, conservatism_schedule.yaml)

```
final = w_personal · posterior
      + w_class    · class_prior_rate
      + w_pop      · population_rate

w_personal = n_personal / (n_personal + τ_class)
τ_class = 8, τ_pop = 40
```

### 5.3 v0.2 승격 조건

- 부트스트랩 self-play 10k 핸드 결과와 ±15% 이내 일치 시 `stage: validated`.
- 불일치 시 transfer_coefficients.yaml 의 계수 수정 → 본 yaml 재산출.

---

## 6. Limitations

- **LLM 풀 편향**: 모든 지표가 LLM 상단. 서버 metagame 이 인간 혼재면 상향 편향.
- **Preflop volume (VPIP/PFR) 절대값 누락**: position × class 혼합 정의로 단일 값 적합 않음. 서버 로그로 직접 생성.
- **Rake/stakes 구조 무시**: HU cash game vs tournament 구조 전이. blind 급등 환경에선 aggression 증폭.
- **CHECK_RAISE 미집계**: 문헌값 사용. 직접 측정 계획 (Day 5 이후).

---

## 7. Change control

- 이 문서 v0.2 발행 = `configs/priors.yaml` v0.2 발행. 항상 동기 버전.
- 어느 한쪽만 변경 금지.

---

## Changelog

- 2026-04-19 (v0.1): HU 2.06M 관측 × 전이계수 + ESS=100 재스케일 방식 확정.
