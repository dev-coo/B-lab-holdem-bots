# Class Prior — 수치 근거 (class_priors.yaml)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: `configs/class_priors.yaml` v0.1
- **Sources**: `research/dataset_analysis/eda_02_clusters.md` v0.1
- **BOT_GUIDE refs**: §4 포지션, §5.3 action, §13 이벤트 요약

---

## 1. 결정 요약

4-class 분류(TAG/LAG/NIT/Fish) 는 shrinkage 의 2번째 레이어로, **10~30 핸드 관측만으로 의미 있는
개인화**를 제공한다. HU Kaggle 데이터로 centroid 를 추출했으나 **LAG 쏠림 (silhouette 0.35)** 이므로
전이 금지. 서버 적용용 `server_class_priors` 는 문헌 + HU 질적 구조 혼합.

---

## 2. 설계 의도

### 2.1 왜 4-class 인가
- 개인 posterior 수렴 전 구간에서 **prior 정밀도 향상** 목적.
- 2-class(tight/loose) 는 구분 약함, 6+class 는 과적합.
- 전통적 포커 커뮤니티의 합의: VPIP × AF 의 2D 평면에서 4 사분면.

### 2.2 분류 축

```
               VPIP<30 (tight)     VPIP≥30 (loose)
AF<1.5 (passive)    NIT                 Fish
AF≥2.0 (aggressive) TAG                 LAG
```

- **VPIP 경계 30**: 문헌의 일반 합의 (tight=≤20, loose=≥28 의 중간 절충).
- **AF 경계 1.5~2.0**: passive/aggressive 이중 경계. 1.5~2.0 은 mixed.

### 2.3 왜 HU centroid 를 직접 쓰지 않나
- 15 LLM 전부 VPIP ≥ 48.5% → 4-class 중 NIT/TAG 는 empty.
- 포지션 수학상 HU SB VPIP 는 80%+ 가 정상 → 전통 경계에 무의미.
- 인간 풀 VPIP 는 10~40% 범위. HU 값 × 0.35~0.45 근사.

---

## 3. 각 class 의 Beta prior 근거

### 3.1 NIT (tight-passive)

| metric | α | β | rate |
|---|---:|---:|---:|
| VPIP | 12 | 88 | 12% |
| PFR  |  9 | 91 |  9% |
| 3BET |  3 | 97 |  3% |
| CBET | 55 | 45 | 55% |
| BLUFF_AT_SHOWDOWN | 6 | 94 | 6% |
| AF target | — | — | ~0.6 |

**근거**: NIT 는 premium hand 만 play → PFR/VPIP 비율 0.75 유지. 3bet 은 거의 JJ+/AK. CBET 은 range 상한
(top 12%) 인데 OOP/multiway 에서 check 가 많아 55%. BLUFF 극히 낮음 (6%).

### 3.2 TAG (tight-aggressive) — **우리 봇의 기본 모델**

| metric | α | β | rate |
|---|---:|---:|---:|
| VPIP | 22 | 78 | 22% |
| PFR  | 18 | 82 | 18% |
| 3BET |  9 | 91 |  9% |
| CBET | 70 | 30 | 70% |
| BLUFF_AT_SHOWDOWN | 18 | 82 | 18% |
| AF target | — | — | ~2.5 |

**근거**: 현대 GTO 근사 플레이어의 전형. PFR/VPIP = 0.82 (initiative 강함). 3bet 9% 는 linear + polarized.
CBET 70% 는 IP/OOP 혼합 평균. BLUFF 18% 는 balance 유지.

### 3.3 LAG (loose-aggressive)

| metric | α | β | rate |
|---|---:|---:|---:|
| VPIP | 32 | 68 | 32% |
| PFR  | 24 | 76 | 24% |
| 3BET | 14 | 86 | 14% |
| CBET | 75 | 25 | 75% |
| BLUFF_AT_SHOWDOWN | 28 | 72 | 28% |
| AF target | — | — | ~3.0 |

**근거**: HU LLM centroid (VPIP 0.80) 에 전이 계수 ×0.4 = 0.32 일치. 3bet 14% 는 blufy. CBET 75% 는 실제로
HU 관측값에 근접 (LLM 평균 77%). BLUFF 28% — 고빈도 압박형.

### 3.4 Fish (loose-passive)

| metric | α | β | rate |
|---|---:|---:|---:|
| VPIP | 42 | 58 | 42% |
| PFR  | 16 | 84 | 16% |
| 3BET |  4 | 96 |  4% |
| CBET | 50 | 50 | 50% |
| BLUFF_AT_SHOWDOWN | 10 | 90 | 10% |
| AF target | — | — | ~0.9 |

**근거**: call 위주. PFR/VPIP = 0.38 (낮은 initiative). Fish 는 레저 플레이어 전형 — 많이 보러 다니지만 raise 는
보수적. CBET 50% 는 랜덤에 가까움.

---

## 4. 경계 로직 (soft assignment 권장)

### 4.1 경계값 (`class_priors.yaml::boundaries`)

```yaml
tight_vpip_max:     0.30
loose_vpip_min:     0.45
passive_af_max:     1.5
aggressive_af_min:  2.0
```

### 4.2 Hard assignment (fallback)

```python
tight = vpip < 0.30
aggressive = af > 1.5
if tight and aggressive: return "TAG"
if tight and not aggressive: return "NIT"
if not tight and aggressive: return "LAG"
return "Fish"
```

### 4.3 Soft assignment (권장, GMM 기반)

- 관측값 (VPIP, PFR, log1p(AF)) 3D.
- 각 class 의 centroid 기준 Mahalanobis 거리 → softmax → 4-class 확률.
- `class_prior_rate = Σ_c P(class=c) × class_prior[c]` (blend).
- 경계 내부 (hard boundary 불일치) 플레이어는 soft 확률로 두 class 의 prior 섞음.

### 4.4 Min hands threshold

- `min_hands_for_typing = 20`: 20 미만이면 class 미할당, population 만 사용.
- 이는 eda_03 수렴 결과(N=20 에서 VPIP 오차 5.6%) 기반.

---

## 5. 전이 리스크

| 리스크 | 완화 |
|---|---|
| HU 풀은 NIT/TAG 전무 → 서버에서도 이 분류가 희귀할 가능성 | class_prior 자체는 사용 가능. 단지 LAG 에 편향된 상대 풀을 예상해야 함 |
| 경계값 (VPIP 30%, AF 2.0) 은 문헌값 | 서버 실로그 1k 이후 경계 재조정 (O5) |
| Fish 의 PFR 16% 는 다소 높을 수 있음 | 인간 fish 는 PFR 5~10%. 인간 풀 혼재 시 재튜닝 |
| AF 경계의 noisy 함 | §eda_03 결과로 AF 는 이분만 신뢰. 경계 내부는 AF 에 의존하지 않게 |

---

## 6. 갱신 규칙

### 6.1 실시간 classification

매 핸드 종료 시:
1. 플레이어의 최근 25핸드 슬라이딩 VPIP/PFR/AF 갱신.
2. soft-assign (GMM) 재계산.
3. class 확률 분포 P 를 PlayerProfile 에 저장.

### 6.2 Class prior 의 개인 posterior 통합

```
α_effective = α_personal + Σ_c P(class=c) × α_class[c] × w_class(n)
β_effective = β_personal + Σ_c P(class=c) × β_class[c] × w_class(n)
```

`w_class(n) = (τ_class / (n + τ_class))` — n 증가 시 class prior 영향력 감소.

### 6.3 v0.2 승격 조건

- 서버 실로그 2k 핸드에서 "자칭 LAG" 플레이어 집단의 실제 VPIP/AF centroid 가 본 yaml 과 ±10% 일치.
- Silhouette ≥ 0.4 (HU 의 0.35 보다 개선).
- 실패 시 경계값 재조정.

---

## 7. Limitations

- **N=15 centroid**: 15 개 LLM 으로 4-class 경계를 확증하기는 부족. 보조 참고용.
- **LLM stationarity**: 실제 인간은 tilt 로 class 변동. 본 분류는 snapshot.
- **Multiway 무시**: 3+way 에서의 class 특성 차이는 반영 안 됨. 4~9way 에 동일 prior 사용.
- **Position 무관 class**: 사실 BTN 에서의 LAG vs EP 에서의 LAG 는 다른 분포. 여기선 통합.

---

## 8. Next Steps

- `src/holdem/estimate/class_typer.py` 구현 (D3 단계).
- Bootstrap self-play (R4) 에서 6종 baseline 전략을 본 class prior 로 재분류 → centroid 일치성 검증.
- Position 별 class (EP-LAG vs BTN-LAG) 확장 — sprint 2 이후.

---

## Changelog

- 2026-04-19 (v0.1): HU centroid 참조 + 문헌 4-class 경계 혼합. soft assignment 원칙 수립.
