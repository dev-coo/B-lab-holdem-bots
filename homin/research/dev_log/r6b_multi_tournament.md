# Multi-way Tournament Runner

## Status
- **Stage**: Draft
- **Created**: 2026-04-22
- **Related code**: `src/holdem/simulate/tournament.py` (run_tournament_multi), `scripts/tournament_sim.py` (--mode multi)
- **Related tests**: `tests/test_tournament_multi.py` (8)

## 1. Objective
r6 멀티웨이 엔진 완성 → 이를 **토너먼트 레벨** 로 승격. N명이 한 테이블에서 플레이, 탈락자 제거, 마지막 1인까지.

## 2. Design
### 2.1 run_tournament_multi
- Dealer button 매 핸드 시계방향 1칸. 탈락자는 `alive` 리스트에서 제거 후 button 이 나머지 내에서 이동.
- `engine_multi.run_hand_multi` 호출 반복.
- `max_hands` 도달 시 남은 생존자들은 finishing_order 에 순서 무관으로 포함 (sort: 스택 내림차순이 아님 — 간단화).

### 2.2 이름 충돌 처리
같은 전략 이름이 여러 명이면 `"tag#1", "tag#2"` 접미.

### 2.3 Result
```
MultiTournamentResult:
  finishing_order: list[str]  # [winner, 2nd, 3rd, ..., last]
  final_stacks: dict[str, int]
```

## 3. Observations — 6-way, 30 tourn
```
strategy       wins    ITM    ITM%   avg_rank
lag              10     14   46.7%       1.80
nitrock           4     10   33.3%       1.90
tag               2     12   40.0%       1.93
nashjam           5     14   46.7%       2.30
random            7      7   23.3%       2.87
callstation       2      3   10.0%       4.20
avg hands=95.5  avg final level=11.5
```

### 해석 (HU 결과와 대조)
| 전략 | HU (winrate) | Multi (ITM%) | 변화 |
|---|---|---|---|
| random | 80% | 23% | **큰 하락** — 멀티웨이에서 변동성만으로는 못 이김 |
| lag | 64% | 47% | 일관 강세 |
| tag | 48% | 40% | 유사 |
| nitrock | 12% | 33% | **큰 상승** — 6-way 프리미엄 대기가 HU 대비 효과적 |
| callstation | 28% | 10% | **추가 하락** — showdown 비용 폭증 |

→ 멀티웨이의 본질적 특성(블러핑↓, showdown equity↑, 프리미엄 가치↑) 자연스럽게 반영.

## 4. Limitations
- Dealer button 회전 구현 단순 (alive 내 idx). 실서버 seat ID 매핑 없음.
- max_hands 도달 시 finishing_order 내 "2+ 생존자" 순서는 미정의 (현재: 첫 발견 순).
- Policy layer (실봇) 미연결 — 현재는 baseline 전략만.

## 5. Next Steps
- 실봇 (policy.decide) 를 BaselineStrategy 어댑터로 감싸 토너먼트 참가 시뮬.
- ICM 실제 상금 구조 적용 시 finishing_order → prize 계산.
- Policy 멀티웨이 보수 가정 (H.8) 벤치마크: `P(all_fold)=min(fᵢ)^n` vs 독립 가정.

## 6. Changelog
- 2026-04-22 (v0.1): run_tournament_multi + MultiTournamentResult + 8 tests + tournament_sim --mode multi.
