# Tournament Simulator — 블라인드 레벨 상승

## Status
- **Stage**: Draft
- **Created**: 2026-04-22
- **Related code**: `src/holdem/simulate/tournament.py`, `scripts/tournament_sim.py`
- **Related tests**: `tests/test_tournament.py` (8)
- **Related configs**: `configs/blind_schedule.yaml`

## 1. Objective
`bootstrap_sim.py` (고정 SB/BB=1/2 cash style) 의 한계(r4 §5) 제거. BOT_GUIDE §8 의 20-레벨 블라인드 급상승을 재현하여, 각 baseline 전략이 **실제 토너먼트 구조에서 얼마나 버티는가** 를 측정.

## 2. Method
### 2.1 BlindSchedule
`configs/blind_schedule.yaml` 로드. `level_at(hand_no)` 로 1-indexed 핸드 → `BlindLevel(sb, bb, hands)` 매핑. `hands=null` 은 catch-all 최종 레벨.

### 2.2 run_tournament(A, B, schedule, max_hands, rng)
- 시작 스택 = `schedule.starting_stack`.
- HU 교대 (hand_no % 2 == 1 → A=SB).
- 매 핸드 `run_hand(bb=lv.bb, sb_amount=lv.sb)`.
- 스택 누적, ≤0 면 종료. `max_hands` 초과 시 winner=None (cap truncation).

### 2.3 round_robin(strategies, …)
모든 쌍 × N 토너먼트. 쌍별 `{wins_a, wins_b, splits, avg_hands, avg_final_level}` 집계.

## 3. Engine Fix
시뮬 구동 중 **부분 올인 무한 루프** 발견:
- 상대가 allin with partial bet (내 bet 보다 작음) → 내 `to_call=0`.
- CallStation 은 check, 그러나 bets 는 여전히 불일치 → 종료 조건 미충족 → 무한 loop.

수정 (`engine.py:_run_street`):
```python
if players[0].allin or players[1].allin:
    acting = 1 if players[0].allin else 0
    if acted_since_raise[acting]:
        break
```

## 4. Results
### 5 tourn × 15 pair (75 토너먼트, 0.1s)

| 전략 | winrate | avg_hands | avg_level |
|---|---|---|---|
| random | 80% | 56.5 | 6.4 |
| nashjam | 68% | 62.6 | 7.2 |
| lag | 64% | 57.4 | 6.6 |
| tag | 48% | 67.5 | 7.8 |
| callstation | 28% | 41.4 | 4.8 |
| **nitrock** | **12%** | 67.8 | 7.9 |

### 관찰
- **nitrock 최하 12%** — 느린 블라인드 상승(cash) 에서는 AF=10 수준이나, 토너먼트 구조에서는 프리미엄 대기 중 블라인드로 소멸. **plan A1 의 주장(타이트-패시브는 급상승 토너먼트에서 부적합) 경험적 확인**.
- random 1위(80%) — 분산 큰 전략이 lucky run 에서 winner-takes-all 로 과대 평가. n=5 는 작음, 100+ 에서 변화 예상.
- nashjam/lag 상위 — 공격적 short-stack 전략이 평균 Lv 6~7 에서 자연스럽게 압박 전환.

## 5. Limitations
- HU only (3-9인 #6 후속).
- Side pot 미처리 (엔진 단일 pot).
- 재접속·disconnect 시뮬 없음.
- max_hands=500 cap 내 대부분 종료 — 장기 토너 (Lv20 도달) 측정은 1000+ 필요.

## 6. Next Steps
- n=100+ round-robin 으로 winrate 신뢰 구간 좁히기.
- 실봇(coordinator 사용) 을 strategies 에 추가해 baseline 대비 상대 winrate 측정 (R6).
- Multi-way (3+ player) 엔진 확장 → 실제 9-max 모사.

## 7. Changelog
- 2026-04-22 (v0.1): BlindSchedule + run_tournament + round_robin + 8 tests + 엔진 부분올인 버그 수정.
