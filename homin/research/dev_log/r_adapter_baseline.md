# PolicyAdapter — 실봇 sim 측정 루프

## Status
- **Stage**: Draft
- **Created**: 2026-04-22
- **Related code**: `src/holdem/simulate/policy_adapter.py`
- **Related tests**: `tests/test_policy_adapter.py` (8)

## 1. Motivation
실서버 테스트모드의 상대 분포가 대회 본선과 다를 수 있음 → 실데이터 기반 튜닝 위험. **시뮬 내 실봇 측정** 이 유일 안전 루프.

## 2. Design
`PolicyAdapter(BaselineStrategy)` — SimState 를 ActionRequest 로 합성, `decide()` 호출, `p.Action` 을 `Decision` 으로 역변환. 각 인스턴스는 독립 `ProfileStore` 보유.

## 3. Initial Measurement (첫 baseline)
### HU (5 tourn / 상대)
| vs | wins | 비고 |
|---|---|---|
| random | 4/5 | 강함 |
| callstation | 1/5 | **약점** — loose-passive 상대에 EV tree 블러핑 손실? |
| nitrock | 4/5 | 강함 |
| tag | 4/5 | 강함 |
| lag | 2/5 | 중간 |
| nashjam | 4/5 | 강함 |

**합계: 19/30 = 63%** — plan K.10 [M-2] criteria (≥55%) 달성.

### 6-way Multi (10 tourn)
- wins: **4/10 (40%)** (random 기대치 17% 대비 +23%p)
- ITM(top-2): 4/10 (40%)
- avg_rank: 2.20

## 4. Key Findings
1. callstation HU 20% 는 **가장 큰 개선 여지**. ev_raise 블러핑 사이즈가 콜링 스테이션 상대에 음수 EV 를 내는 것으로 추정.
2. 6-way 40% winrate 는 multi-way 보수(H.8) 가 effective.
3. plan M-2 기준선 달성 — 개선 출발점 확보.

## 5. Next Optimizations (priority)
1. callstation 패턴 분석 — flop/turn 블러핑 빈도 감소
2. EV tree 2-ply 확장 (plan C3) → realization 0.9 매직 제거
3. Preflop 오픈 사이즈 조정 (callstation 에 2.5bb 오픈이 너무 저렴)
4. MC sample 적응형 — 결정 간 chip_ev 차이가 크면 500 샘플 충분

## 6. Changelog
- 2026-04-22 (v0.1): adapter + 8 tests + 첫 HU/6-way 측정.
