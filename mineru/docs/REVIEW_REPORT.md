# Adversarial Review Report — 설계 문서 대비 코드 검토

> **검토 일시**: 2026-04-18
> **검토 범위**: `docs/ARCHITECTURE.md` + `docs/BOT_REFERENCE.md` vs 전체 구현 코드 (62개 소스 파일)
> **검토 방법**: 5개 병렬 탐색 에이전트 (Strategy, Harness/Client/Engine, Evolution/Analytics/Storage, Protocol, Test Quality)

---

## 총폐

폐쇄 루프 에코시스템의 개별 컴포넌트는 합리적으로 구현되어 있으나, **컴포넌트 간 연결이 설계서와 크게 다름**. 특히 **Play → Record → Analyze → Evolve** 루프에서 **Record 단계가 완전히 분리**되어 있어, 현재 상태로는 에코시스템이 동작하지 않음.

---

## 🚨 CRITICAL — 실제 서버 연결 시 즉시 실패

### 1. HarnessRunner가 GameRecorder를 사용하지 않음

**파일**: `src/holdem_agent/harness/runner.py:15-18`

설계서(섹션 6.1)는 `HarnessRunner(strategy, recorder)` 구조로 모든 이벤트를 DB에 기록하도록 설계. 실제 구현은 `__init__(self, strategy)`만 받고 recorder가 완전히 분리되어 있음.

```
설계: game_start → recorder.log() → action_request → recorder.record() → hand_result → recorder.record()
실제: game_start → tracker.update() → action_request → strategy.decide() → send_action()
       (recorder 호출이 전혀 없음)
```

**영향**: Play 데이터가 DB에 기록되지 않으므로 Analyze/Evolve가 불가능. 에코시스템 루프가 끊김.

---

### 2. 프로토콜 이벤트 파서 미지원으로 클라이언트 크래시

**파일**: `src/holdem_agent/models/events.py:153-159`

| 서버 이벤트 | 설계서 명시 | 파서 지원 | 영향 |
|---|---|---|---|
| `joined_room` | BOT_REFERENCE 447-463 | ❌ | 재접속 시 `ValueError` 크래시 |
| `player_joined` | BOT_REFERENCE 323-328 | ❌ | 플레이어 입장 시 크래시 |
| `player_left` | BOT_REFERENCE 323-328 | ❌ | 플레이어 퇴장 시 크래시 |
| `action_performed` | BOT_REFERENCE 264-276 | ❌ | 타인 액션 알 수 없음 |

`parse_event()`가 알 수 없는 타입에 `ValueError`를 발생시키며, `PokerConnection.listen()`이 이 예외를 잡지 않아 **이벤트 루프가 종료**됨.

---

### 3. WebSocket 재접속 로직 완전 부재

**파일**: `src/holdem_agent/client/connection.py:1-93`

설계서(섹션 9)는 지수 백오프(1s→2s→4s→8s→최대30s) 재접속 + `auth_bot` 재전송 + snapshot 복원을 명시. 실제 구현은 어떤 재접속 로직도 없음. 연결이 끊기면 프로세스 종료됨.

---

### 4. StrategyRegistry가 설계서와 완전히 다른 구현

**파일**: `src/holdem_agent/strategy/registry.py`

| 설계서(섹션 6.6) 메서드 | 구현 여부 |
|---|---|
| `register(strategy, parent, created_by)` | ❌ (`register_version`만 존재, 시그니처 다름) |
| `load(name) -> Strategy` | ❌ |
| `lineage(name) -> list[dict]` | ❌ |
| `best_strategy(metric) -> Strategy` | ❌ |

또한 DB 기반이 아닌 JSON 파일 기반으로 구현되어 있음.

---

### 5. 미등록 전략으로 `get_strategy()` 호출 시 `KeyError`

**파일**: `src/holdem_agent/strategy/registry.py:127-142`

자동 등록이 `calling-station`, `gto-baseline`, `tight-aggressive` 3개만 수행. 설계서 섹션 3.4에 명시된 `aggressive`와 `adaptive`가 등록되지 않음.

```bash
uv run holdem-agent play ... --strategy aggressive  # KeyError 발생
```

---

## 🟠 HIGH — 기능적 설계 위반 (동작은 하지만 설계 의도와 다름)

### 6. DB 스키마가 설계서와 상이

**파일**: `src/holdem_agent/storage/database.py:53-109`

| 테이블 | 설계서(섹션 6.5) | 실제 구현 |
|---|---|---|
| `action_requests` | 명시됨 | ❌ 미생성 |
| `strategy_metrics` | 명시됨 | ❌ 미생성 |
| `decisions.elapsed_ms` | 명시됨 | ❌ 누락 |
| `hand_results.winners_json` | 명시됨 | ❌ `won` (bool)으로 대체 |
| `hand_results.showdown_json` | 명시됨 | ❌ 누락 |
| `hand_results.eliminated_json` | 명시됨 | ❌ 누락 |
| `strategy_versions.name UNIQUE` | 명시됨 | ❌ UNIQUE 없음 |

---

### 7. MetricsCalculator가 설계서와 다른 반환 타입

**파일**: `src/holdem_agent/analytics/metrics.py:13-16`

설계서: `calculate_strategy_metrics() -> StrategyMetrics` (games_played, win_rate, avg_roi, vpip, pfr, avg_m_value_at_decision, money_won)

실제: `get_strategy_metrics() -> dict` (avg_rank, folds, raises, calls만 포함)

ROI, PFR, 평균 M값, 수익금이 계산되지 않음 → Evolve 파이프라인의 핵심 입력 누락.

---

### 8. StrategyGenerator가 Genome이 아닌 Strategy를 반환해야 함

**파일**: `src/holdem_agent/evolution/generator.py:16-21`

설계서: `generate_candidates(base_strategy: Strategy, ...) -> list[Strategy]`

실제: `generate_candidates(base_genome: StrategyGenome, ...) -> list[StrategyGenome]`

---

### 9. game_end 처리가 봇 본인이 아닌 rankings[0]를 기록

**파일**: `src/holdem_agent/engine/game.py:79-83`, `src/holdem_agent/harness/recorder.py:95-100`

`rankings[0]`를 무조건 사용하므로, 봇이 1위가 아닐 경우 잘못된 순위/칩이 기록됨.

---

### 10. HandState가 action_request의 일부 필드를 무시

**파일**: `src/holdem_agent/engine/hand.py:39-50`

`hand_number`, `your_cards`, `seat`를 갱신하지 않음. 재접속/특이 케이스에서 상태 불일치 가능.

---

### 11. total_hands가 항상 0으로 기록

**파일**: `src/holdem_agent/harness/recorder.py:98-100`

`record_game_end`에서 `total_hands=0`으로 하드코딩. 실제 핸드 수 미계산.

---

## 🟡 MEDIUM — 설계서와 다르지만 당장 장애는 아님

### 12. API 이름 불일치 (다수)

| 설계서 메서드 | 실제 구현 메서드 | 파일 |
|---|---|---|
| `WeakspotAnalyzer.diagnose(strategy, db)` | `analyze_decisions(decisions, metrics)` + `analyze_metrics(metrics)` | analytics/weakspot.py:23-24 |
| `MetricsCalculator.calculate_strategy_metrics()` | `get_strategy_metrics()` | analytics/metrics.py:13 |
| `Reporter.generate(...)` | `format_metrics()`, `format_weakspots()`, `format_comparison()` | analytics/reporter.py:10-48 |

---

### 13. 포지션 키 불일치로 게놈 복원 시 데이터 손실

**파일**: `src/holdem_agent/strategy/genome.py:6`, `builtins/aggressive.py:92-96`

`StrategyGenome` 기본 포지션: `{btn, sb, bb, utg, co}` (5개)

`aggressive`/`tight_aggressive` 사용 포지션: `hj`, `mp` 포함 (7개)

`from_dict()` 시 `_coerce_position_dict()`가 기본 5개만 유지하고 `hj`/`mp`가 소실됨.

---

### 14. CallingStation.from_genome()이 게놈을 무시

**파일**: `src/holdem_agent/strategy/builtins/calling_station.py:19-22`

`return cls()`로 항상 기본 인스턴스 반환. 진화 파이프라인에서 CallingStation 게놈이 실제로 적용되지 않음.

---

### 15. Targeted mutation이 중첩 파라미터 경로 지원 안 함

**파일**: `src/holdem_agent/evolution/generator.py:39-50`

설계서 예시: `param_to_adjust="preflop_raise_threshold.utg"`

실제 구현: 최상위 필드명만 매칭 → `preflop_raise_threshold` 전체가 수정됨.

---

## 📊 테스트 품질 분석

### 위험도별 커버리지 갭

| 영역 | 위험도 | 현황 |
|---|---|---|
| WebSocket 재접속 | 🔴 Critical | 코드도, 테스트도 없음 |
| Evolve CLI E2E | 🔴 Critical | `__main__._evolve()` 경로 테스트 없음 |
| 전체 파이프라인 통합 | 🔴 Critical | `test_full_hand.py`는 mock 기반, 실제 DB/Recorder 미검증 |
| 30초 타임아웃 실측 | 🟠 High | monkeypatch로만 테스트, 실제 경과 시간 미검증 |
| 멀티 룸 동시성 | 🟡 Medium | 기본 분리만 테스트, 인터리브/경쟁 조건 미검증 |
| 프로토콜 파서 강건성 | 🟠 High | 알 수 없는 이벤트 = 크래시, 테스트 없음 |

### 테스트 신뢰도 평가

- **369개 테스트**는 **개별 컴포넌트 단위 품질**은 보장
- 하지만 **컴포넌트 간 연결(Record → Analyze → Evolve)**의 E2E 검증이 없어 **실제 동작 보장 불가**
- `conftest.py`가 카드 픽스처 4개만 제공하여 통합 테스트 작성 기반이 취약

---

## 📋 우선순위 수정 계획

### P0 — 실서버 연결 전 필수

1. **이벤트 파서 강건화**: `joined_room`, `player_joined`, `player_left`, `action_performed` 추가 + 알 수 없는 타입은 log+skip
2. **HarnessRunner에 Recorder 연결**: `__init__`에 recorder 추가 + 모든 이벤트에 record 호출
3. **재접속 로직 구현**: 지수 백오프 + auth 재시도 + snapshot 복원
4. **aggressive/adaptive 레지스트리 등록**

### P1 — 에코시스템 루프 동작을 위해

5. **DB 스키마 정합**: `action_requests`, `strategy_metrics` 테이블 추가 + 컬럼 보완
6. **MetricsCalculator 보완**: ROI, PFR, 평균 M값, 수익금 계산 구현
7. **game_end 봇 본인 순위 조회** 수정
8. **total_hands 실계산**

### P2 — 설계서 정합성

9. StrategyRegistry DB 기반 전환 또는 설계서 업데이트
10. StrategyGenerator → Strategy 반환으로 변경
11. API 이름 통일 (diagnose, calculate_strategy_metrics, generate)
12. 포지션 키 union 처리 (hj/mp 보존)

---

## ✅ 설계서와 일치하는 부분

- `Strategy` ABC (`decide`, `genome`, `from_genome`, `name`) — base.py
- `StrategyGenome` 16개 필드 전부 — genome.py
- `DecisionContext` 불변 데이터클래스 + 모든 필드 — base.py
- `GenomeMutator` 가우시안 섭동 — mutator.py
- `GenomeBreeder` uniform crossover — breeder.py
- `Weakspot` 데이터클래스 필드 — weakspot.py
- 인증 플로우 (auth_bot / auth_ok) — auth.py
- 액션 응답 JSON 포맷 — protocol.py, actions.py
- ping/pong 즉시 응답 — connection.py
