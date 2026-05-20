# Research Index

홀덤 봇 설계의 연구 산출물을 집계한다. 모든 연구 문서는 `_template.md` 기반이며, `Stage: Draft → Validated → Frozen` 라이프사이클(계획 L.4)을 따른다.

**Last updated**: 2026-04-19 (Day 5)

---

## Document Dashboard

| # | Document | Stage | Last Updated | Owner | Related configs |
|---|----------|-------|--------------|-------|-----------------|
| 1 | [bot_guide_extracts.md](./bot_guide_extracts.md) | Draft | 2026-04-19 | holdem-agent | `blind_schedule.yaml`, `position_class_map.yaml` |
| 2 | [theory_notes.md](./theory_notes.md) | Draft | 2026-04-19 | holdem-agent | — |
| 3 | [blind_schedule_analysis.md](./blind_schedule_analysis.md) | Draft | 2026-04-19 | holdem-agent | `blind_schedule.yaml` |
| 4 | [dataset_analysis/inspection_report.md](./dataset_analysis/inspection_report.md) | Draft | 2026-04-19 | holdem-agent | `transfer_coefficients.yaml` |
| 5 | [dataset_analysis/eda_01_distributions.md](./dataset_analysis/eda_01_distributions.md) | Draft | 2026-04-19 | holdem-agent | `priors.yaml` |
| 6 | [dataset_analysis/eda_02_clusters.md](./dataset_analysis/eda_02_clusters.md) | Draft | 2026-04-19 | holdem-agent | `class_priors.yaml` |
| 7 | [dataset_analysis/eda_03_convergence.md](./dataset_analysis/eda_03_convergence.md) | Draft | 2026-04-19 | holdem-agent | `conservatism_schedule.yaml` |
| 8 | [dataset_analysis/eda_04_sizing.md](./dataset_analysis/eda_04_sizing.md) | Draft | 2026-04-19 | holdem-agent | `sizing.yaml` |
| 9 | [dataset_analysis/eda_05_bluff_threshold.md](./dataset_analysis/eda_05_bluff_threshold.md) | Draft | 2026-04-19 | holdem-agent | `bluff_labels.yaml` |
| 10 | [parameters/population_prior_rationale.md](./parameters/population_prior_rationale.md) | Draft | 2026-04-19 | holdem-agent | `priors.yaml` |
| 11 | [parameters/class_prior_rationale.md](./parameters/class_prior_rationale.md) | Draft | 2026-04-19 | holdem-agent | `class_priors.yaml` |
| 12 | [parameters/bluff_label_rationale.md](./parameters/bluff_label_rationale.md) | Draft | 2026-04-19 | holdem-agent | `bluff_labels.yaml` |
| 13 | [parameters/conservatism_schedule_rationale.md](./parameters/conservatism_schedule_rationale.md) | Draft | 2026-04-19 | holdem-agent | `conservatism_schedule.yaml` |
| 14 | [parameters/llm_coordinator_rationale.md](./parameters/llm_coordinator_rationale.md) | Draft | 2026-04-19 | holdem-agent | `llm.yaml` |
| 15 | [parameters/sizing_rationale.md](./parameters/sizing_rationale.md) | Draft | 2026-04-19 | holdem-agent | `sizing.yaml` |
| 16 | [week2_plan.md](./week2_plan.md) | Draft | 2026-04-19 | holdem-agent | `src/holdem/**` (미구현) |
| 17 | bootstrap/baseline_strategies.md | — | — | — | — |
| 18 | bootstrap/self_play_results.md | — | — | — | `priors.yaml` v2 |
| 19 | bootstrap/priors_v2_derivation.md | — | — | — | `priors.yaml` v2 |
| 20 | nash_charts/source_audit.md | — | — | — | `nash_charts/*.yaml` |
| 21 | nash_charts/server_blind_mapping.md | — | — | — | `nash_charts/*.yaml` |
| 22 | validation/ab_report.md | — | — | — | all priors |

**범례**:
- **Stage**: `Draft` (초안, 수치 잠정) · `Validated` (R6 A/B 통과) · `Frozen` (실서버 1주 무회귀)

---

## Current Blockers

- [x] ~~Kaggle CLI 인증 설정~~ (kaggle.json 으로 성공, Task #7)
- [x] ~~게임 종류 확인~~ (NLHE 확정, inspection_report §5.1)
- [ ] 서버 deploy API 인증 방식 확인 (BOT_GUIDE §2.2, 계획 평가 B4) — **운영자 문의 필요**
- [ ] HU → 4–9-way 전이 계수 실증 확정 (J.3)

---

## Next Sprint Focus

**Day 1 ✅ 완료 (2026-04-19)**:
- [x] 디렉토리·템플릿 생성
- [x] `bot_guide_extracts.md` 작성
- [x] `configs/blind_schedule.yaml` + `configs/position_class_map.yaml`
- [x] `theory_notes.md`
- [x] `blind_schedule_analysis.md`
- [x] `pyproject.toml` + uv sync
- [x] Kaggle 다운로드 (2M 핸드)
- [x] `dataset_inspect.py` 실행 + inspection_report (**J.1.a gate PASS**)

**Day 2 ✅ 완료 (2026-04-19)**:
- [x] J.7 `scripts/bluff_threshold.py` — Dealt-to 로 양쪽 홀카드 공개 활용. 전체 2.06M 런 진행 중
- [x] J.4 `scripts/class_typing_eda.py` — 15 LLM 모델 (VPIP, PFR, AF) 집계 + K-Means/GMM(k=4)
- [x] `eda_02_clusters.md` — 4-class 경계 재설계안. silhouette=0.35 → HU 풀은 LAG 쏠림 확인
- [x] `eda_05_bluff_threshold.md` v0.1 — 샘플 15k 기반 초안 (turn θ_bluff=0.35/θ_value=0.65)
- [x] `configs/class_priors.yaml` Draft
- [x] `configs/bluff_labels.yaml` Draft (v0.2, full run 반영)
- [x] `configs/transfer_coefficients.yaml` Draft
- [x] bluff_threshold.py full 2.06M 런 완료 (4.3M records, 57분 소요) → eda_05 v0.2, bluff_labels.yaml v0.2 갱신

**Day 3 ✅ 완료 (2026-04-19)**:
- [x] J.5 `scripts/sizing_distribution.py` → `data/sizing_report.json` (4.3M bet_to_pot)
- [x] `eda_04_sizing.md` Draft — LLM overbet-heavy (49% ≥ pot), sizing-bluff 분리 없음 확인
- [x] `configs/sizing.yaml` Draft — conservative/balanced/exploit 3-tier grid
- [x] J.3 `scripts/calc_population_prior.py` → CBET 77%, FOLD_TO_CBET 34%, BARREL_TURN 60%, BARREL_RIVER 48%, 3BET 23%
- [x] `eda_01_distributions.md` Draft — HU→9max/6max/4max 전이 추정
- [x] `configs/priors.yaml` Draft — ESS=100 재스케일한 server_prior_{4,6,9}max

**Day 4 ✅ 완료 (2026-04-19)**:
- [x] J.8 `scripts/convergence_speed.py` → 오차 곡선 측정 (VPIP 13%p→1.5%p 단조 감소)
- [x] `eda_03_convergence.md` Draft — n_effective 경계 {10,30,80,150,400} 실증
- [x] `configs/conservatism_schedule.yaml` Draft — 6-mode 전환 스케줄
- [x] R3 rationale 4개 문서:
  - [x] `parameters/population_prior_rationale.md` (priors.yaml 근거)
  - [x] `parameters/class_prior_rationale.md` (class_priors.yaml 근거)
  - [x] `parameters/bluff_label_rationale.md` (bluff_labels.yaml 근거)
  - [x] `parameters/conservatism_schedule_rationale.md` (conservatism_schedule.yaml 근거)

**Day 5 ✅ 완료 (2026-04-19)**:
- [x] `scripts/configs_dryload.py` — 9개 yaml 동시 로드 + cross-reference 검증 (all checks passed)
- [x] Published Configs 점검 — 9개 Draft 전부 동일 stage, source 필드 정합
- [x] `research/week2_plan.md` Draft — D1 (transport + push/fold) 5일 분해, 테스트 계획, 리스크 매트릭스
- [x] `research/parameters/sizing_rationale.md` Draft — sizing.yaml 3-tier grid 수치 근거

**Week 2 (다음, Day 6~10)**:
- [ ] D1 transport + 간이 push/fold 봇 서버 배포 (M1 마일스톤)
- [ ] `src/holdem/transport/{ws_client,protocol}.py`, `src/holdem/state/game_state.py`, `src/holdem/decide/{mode_selector,push_fold_chart}.py`
- [ ] `configs/nash_charts/simple_push_9max.yaml` 임시값 (R5 에서 정식 차트 대체)
- [ ] Deploy API 인증 확인 (평가 B4 블로커) — 운영자 문의 선결

---

## Published Configs

현재 `configs/*.yaml` 중 연구 근거가 있는 파일:

| Config | Derived from | Stage |
|--------|--------------|-------|
| `configs/blind_schedule.yaml` | `bot_guide_extracts.md §10`, `blind_schedule_analysis.md` | Draft |
| `configs/position_class_map.yaml` | `bot_guide_extracts.md §6` | Draft |
| `configs/class_priors.yaml` | `eda_02_clusters.md §4.2` (HU centroid + 문헌 4-class 경계) | Draft |
| `configs/bluff_labels.yaml` | `eda_05_bluff_threshold.md §4` (full 2.06M, MC=120) | Draft v0.2 |
| `configs/transfer_coefficients.yaml` | `inspection_report.md §5`, `eda_02_clusters.md §5.2` | Draft |
| `configs/sizing.yaml` | `eda_04_sizing.md §4` (2.06M, 4.3M decisions) | Draft |
| `configs/priors.yaml` | `eda_01_distributions.md §4.3` + `population_prior_rationale.md` | Draft |
| `configs/conservatism_schedule.yaml` | `eda_03_convergence.md §6` + `conservatism_schedule_rationale.md` | Draft |
| `configs/llm.yaml` | plan Section M + `llm_coordinator_rationale.md` | Draft |

**검증 상태**: `uv run python scripts/configs_dryload.py` (2026-04-19 실행) — **all 8 checks passed**.

---

## 문서 작성 규칙

1. 신규 문서는 `_template.md` 를 복사하여 시작.
2. 모든 문서는 `BOT_GUIDE Compliance` 섹션에 `bot_guide_extracts.md` 의 어느 항목을 준수하는지 명시.
3. `Parameter Output` 섹션의 yaml 값은 실제 `configs/*.yaml` 과 동기화.
4. 이 README 의 Dashboard 는 매 문서 추가/수정 시 갱신.

---

## 참조

- 상위 계획: `~/.claude/plans/delegated-doodling-sphinx-md-async-hinton.md`
  - Section K: 12주 타임라인
  - Section L: 문서화 프로토콜 (이 디렉토리의 운영 원칙)
- 서버 가이드: `guide/BOT_GUIDE.md`
