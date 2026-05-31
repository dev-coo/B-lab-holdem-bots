# Holdem Agent — 시스템 아키텍처 설계서

> **대상**: 노리밋 텍사스 홀덤 토너먼트 AI 봇
> **기술 스택**: Python 3.14 + uv + websockets + treys + SQLite
> **프로토콜**: `docs/BOT_REFERENCE.md` 참조

---

## 1. 설계 철학 — Strategy Evolution Ecosystem

### 1.1 핵심 질문

> "어떻게 하면 봇이 게임을 할수록 더 강해질 수 있을까?"

이 질문에 대한 답이 본 시스템의 존재 이유다. 정적인 전략이 아닌,
**실행 → 기록 → 분석 → 새 전략 생성 → 실행**의 폐쇄 루프를 구축한다.

### 1.2 설계 원칙

| 원칙 | 설명 |
|------|------|
| **전략은 1급 시민** | 전략은 코드가 아닌 데이터로 취급한다. 버전 관리, 비교, 진화가 가능해야 한다 |
| **모든 게임은 기록된다** | 이벤트, 결정, 결과를 SQLite에 영속화한다 |
| **결과가 전략을 바꾼다** | 성과 분석이 새로운 전략 후보를 자동으로 생성한다 |
| **핵심 계산은 순수 함수** | `core/` 계층은 상태가 없는 순수 계산만 수행한다 |
| **30초 타임아웃 절대 준수** | 어떤 전략이든 30초 내 응답을 보장하는 안전망 |
| **테스트 가능성** | 전략, 분석, 진화 모두 실제 서버 없이 단위 테스트 가능 |

### 1.3 제약 조건

```
서버 프로토콜  ────  WebSocket (JSON)
액션 제한시간  ────  30초 (초과 시 자동 폴드)
멀티 게임      ────  단일 WS 연결, room_id 분리
Python 버전    ────  3.14 (uv 관리)
의존성 최소화  ────  핵심: treys, websockets, pydantic
영속화         ────  SQLite (게임 기록, 메트릭, 전략 버전)
```

---

## 2. 생태계 개요 — 폐쇄 루프

```
                    ┌─────────────────────────────────┐
                    │                                 │
                    ▼                                 │
  ┌──────────────┐     ┌──────────────┐     ┌────────┴───────┐
  │  Strategy    │     │   Harness    │     │   Evolution    │
  │  Registry    │────▶│   Runner     │     │    Engine      │
  │              │     │              │     │                │
  │ 버전 관리    │     │ 전략 실행    │     │ 돌연변이 생성  │
  │ 계보 추적    │     │ 이벤트 기록  │     │ 교배/선택      │
  │ 메타데이터   │     │ 타임아웃     │     │ 검증           │
  └──────────────┘     └──────┬───────┘     └────────────────┘
                             │                     ▲
                             ▼                     │
                    ┌──────────────┐     ┌────────┴───────┐
                    │   Storage    │     │   Analytics    │
                    │   Layer      │     │    Engine      │
                    │              │     │                │
                    │ SQLite DB    │────▶│ 성과 메트릭    │
                    │ 게임 녹화    │     │ 전략 비교      │
                    │ 전략 스냅샷  │     │ 약점 진단      │
                    └──────────────┘     └────────────────┘
```

**핵심 루프**:

```
1. StrategyRegistry에서 활성 전략 로드
2. HarnessRunner가 서버에 연결, 전략으로 게임 플레이
3. 모든 이벤트/결정/결과를 StorageLayer에 기록
4. AnalyticsEngine이 누적 데이터로 성과 분석
5. EvolutionEngine이 분석 결과로 새 전략 후보 생성
6. 새 전략을 Registry에 등록 → 1로 복귀
```

---

## 3. 전략 시스템 — 1급 시민

### 3.1 전략 인터페이스

```python
# strategy/base.py
from abc import ABC, abstractmethod

class Strategy(ABC):
    """모든 전략의 기반 클래스. 전략은 '게임 상태 → 액션' 함수다."""

    @abstractmethod
    def decide(self, context: "DecisionContext") -> "Action":
        """현재 상태에서 액션을 결정한다.

        Args:
            context: 불변 게임 상태 스냅샷 (I/O 없음)

        Returns:
            수행할 액션 (fold/check/call/raise/allin)

        주의:
            - 5초 이내 반환 권장 (28초 하드 리미트)
            - I/O 작업 금지
            - 예외 시 자동 safe_fallback
        """
        ...

    @property
    @abstractmethod
    def genome(self) -> "StrategyGenome":
        """전략을 파라미터 벡터로 직렬화한다. 진화에 사용."""
        ...

    @classmethod
    @abstractmethod
    def from_genome(cls, genome: "StrategyGenome") -> "Strategy":
        """파라미터 벡터에서 전략을 복원한다."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """전략의 고유 식별자 (예: 'gto-aggressive-v1.2')."""
        ...
```

### 3.2 전략 게놈 (StrategyGenome) — 전략을 데이터로

전략을 진화 가능한 파라미터 벡터로 표현한다. 이것이 "전략을 데이터로 취급"하는 핵심이다.

```python
@dataclass
class StrategyGenome:
    """전략의 유전자. 진화 연산의 단위."""

    # ── 프리플롭 파라미터 ──
    # 포지션별 레이즈 레인지 (169 핸드 × 포지션 = threshold 배열)
    preflop_raise_threshold: dict[str, float]  # position → 0.0~1.0
    # 예: {"utg": 0.85, "co": 0.65, "btn": 0.50, "sb": 0.55, "bb": 0.60}
    # 해석: 랭킹 상위 X%까지만 레이즈

    preflop_call_threshold: dict[str, float]   # position → 0.0~1.0
    preflop_3bet_threshold: dict[str, float]   # position → 0.0~1.0

    # ── 포스트플롭 파라미터 ──
    cbet_frequency: float          # 0.0 ~ 1.0  (컨티뉴에이션 벳 빈도)
    cbet_size_pot_fraction: float  # 0.25 ~ 1.0 (팟 대비 CB 사이즈)

    raise_size_pot_fraction: float  # 0.5 ~ 3.0  (레이즈 사이즈)
    three_bet_size_pot_fraction: float  # 0.5 ~ 3.0

    # ── 블러프 파라미터 ──
    bluff_frequency: float          # 0.0 ~ 0.30
    semi_bluff_equity_threshold: float  # 0.15 ~ 0.40 (이 승률 이상에서 세미블러프)
    river_bluff_frequency: float    # 0.0 ~ 0.15

    # ── 방어 파라미터 ──
    fold_to_raise_equity: float     # 0.0 ~ 0.50 (승률이 이 미만이면 폴드)
    check_raise_frequency: float    # 0.0 ~ 0.20
    donk_bet_frequency: float       # 0.0 ~ 0.20

    # ── 리스크 파라미터 ──
    m_conservative: float           # 10.0 ~ 25.0 (이 M값 미만에서 보수적)
    m_desperate: float              # 3.0 ~ 8.0   (이 M값 미만에서 푸시폴드)

    # ── 익스플로잇 파라미터 ──
    exploit_aggression: float       # 0.0 ~ 1.0 (상대 약점 공략 강도)
    adapt_speed: float              # 0.01 ~ 0.5 (상대 모델 업데이트 속도)
```

### 3.3 DecisionContext — 전략에 제공되는 입력

```python
@dataclass(frozen=True)
class DecisionContext:
    """전략에 전달되는 불변 게임 상태. 전략은 이것만 본다."""
    # 현재 핸드
    hand_number: int
    hole_cards: list[str]
    community_cards: list[str]
    phase: str                         # preflop | flop | turn | river
    pot: int
    my_stack: int
    my_seat: str                       # btn | sb | bb | utg | ...
    to_call: int
    min_raise: int
    blind: tuple[int, int]             # (SB, BB)

    # 플레이어
    players: list[PlayerState]

    # 액션 히스토리
    action_history: list[ActionRecord]

    # 토너먼트 컨텍스트
    blind_structure: list[BlindLevel]
    starting_stack: int
    room_id: int
```

### 3.4 내장 전략 (Built-in Strategies)

전략은 `strategy/builtins/`에 구현체로 존재하며, 각각 다른 게놈 구조를 가질 수 있다:

```
strategy/builtins/
├── calling_station.py    # 베이스라인: 항상 콜 (가장 단순)
├── gto_baseline.py       # GTO 기반: 프리플롭 차트 + 포스트플롭 휴리스틱
├── aggressive.py         # 공격형: 높은 블러프/레이즈 빈도
├── tight_aggressive.py   # TAG: 타이트 레인지 + 공격적 베팅
└── adaptive.py           # 적응형: 상대 모델링 기반 익스플로잇
```

---

## 4. 폴더 구조

```
holdem-agent/
│
├── pyproject.toml                    # uv 프로젝트 설정
├── uv.lock
├── README.md
│
├── docs/
│   ├── BOT_REFERENCE.md              # 서버 프로토콜 명세
│   └── ARCHITECTURE.md               # 본 설계 문서
│
├── src/
│   └── holdem_agent/
│       ├── __init__.py
│       ├── __main__.py               # CLI 진입점: play / evolve / analyze
│       │
│       ├── core/                     # ── 포커 도메인 (순수 계산, 상태 없음) ──
│       │   ├── __init__.py
│       │   ├── card.py               # 카드 표현, 변환 (treys ↔ 서버 포맷)
│       │   ├── evaluator.py          # 핸드 평가 래퍼 (treys.Evaluator)
│       │   ├── equity.py             # Monte Carlo 승률 계산
│       │   ├── odds.py               # 팟 오즈, 임플라이드 오즈
│       │   ├── range_.py             # 핸드 레인지 표현, 파싱
│       │   └── combos.py             # 카드 조합 수 계산
│       │
│       ├── engine/                   # ── 게임 상태 관리 ──
│       │   ├── __init__.py
│       │   ├── game.py              # GameTracker: room_id별 게임 수명주기
│       │   ├── hand.py              # HandState: 핸드 내 페이즈/베팅 상태
│       │   ├── player.py            # PlayerState: 플레이어 상태 + 누적 통계
│       │   └── action_history.py    # ActionLog: 이벤트 시퀀스 누적
│       │
│       ├── client/                   # ── 통신 계층 ──
│       │   ├── __init__.py
│       │   ├── connection.py        # WebSocket 연결, 재접속, 하트비트
│       │   ├── protocol.py          # 메시지 라우팅, 직렬화/역직렬화
│       │   └── auth.py              # 인증 (auth_bot, auth_ok)
│       │
│       ├── strategy/                 # ── 전략 시스템 (1급 시민) ──
│       │   ├── __init__.py
│       │   ├── base.py              # Strategy ABC, Action, DecisionContext
│       │   ├── genome.py            # StrategyGenome: 파라미터 벡터
│       │   ├── registry.py          # StrategyRegistry: 버전 관리, 로드/세이브
│       │   ├── analysts/            # 재사용 분석 컴포넌트 (전략 내부에서 사용)
│       │   │   ├── __init__.py
│       │   │   ├── hand_strength.py # 핸드 랭크, 강도, 드로우 감지
│       │   │   ├── equity_calc.py   # 승률, 팟오즈, EV 계산 래퍼
│       │   │   ├── position.py      # 포지션 분류, 이점 평가
│       │   │   ├── opponent.py      # 상대 경향 추적 (VPIP, AF 등)
│       │   │   └── risk.py          # M값, 토너먼트 페이즈, 푸시폴드
│       │   ├── builtins/            # 내장 전략 구현체
│       │   │   ├── __init__.py
│       │   │   ├── calling_station.py
│       │   │   ├── gto_baseline.py
│       │   │   ├── aggressive.py
│       │   │   ├── tight_aggressive.py
│       │   │   └── adaptive.py
│       │   └── charts/              # 정적 전략 데이터
│       │       ├── __init__.py
│       │       ├── preflop.py       # 프리플롭 레인지 차트 로더
│       │       └── pushfold.py      # 푸시/폴드 내쉬 균형 테이블
│       │
│       ├── harness/                  # ── 실행 하네스 ──
│       │   ├── __init__.py
│       │   ├── runner.py            # HarnessRunner: 전략 실행, 이벤트 루프
│       │   ├── recorder.py          # GameRecorder: 모든 이벤트를 DB에 기록
│       │   ├── replayer.py          # GameReplayer: 기록된 게임 재생/분석
│       │   └── experiment.py        # ExperimentRunner: 실험 실행 관리
│       │
│       ├── analytics/                # ── 성과 분석 ──
│       │   ├── __init__.py
│       │   ├── metrics.py           # 핵심 메트릭 계산 (승률, ROI, VPIP, ...)
│       │   ├── comparator.py        # 전략 간 비교 분석
│       │   ├── reporter.py          # 분석 리포트 생성 (텍스트/JSON)
│       │   └── weakspot.py          # 약점 진단 (어떤 상황에서 손실 많은지)
│       │
│       ├── evolution/                # ── 전략 진화 ──
│       │   ├── __init__.py
│       │   ├── mutator.py           # 게놈 돌연변이 (파라미터 섭동)
│       │   ├── breeder.py           # 두 전략 교배 (파라미터 교차)
│       │   ├── selector.py          # 적합도 기반 선택 (토너먼트/룰렛)
│       │   ├── generator.py         # 새 전략 후보 생성 파이프라인
│       │   └── validator.py         # 생성된 전략 검증 (기본 합리성 체크)
│       │
│       ├── storage/                  # ── 영속화 계층 ──
│       │   ├── __init__.py
│       │   ├── database.py          # SQLite 연결 관리, 마이그레이션
│       │   ├── game_store.py        # 게임 기록 CRUD
│       │   ├── strategy_store.py    # 전략 버전 CRUD
│       │   └── metrics_store.py     # 메트릭 CRUD
│       │
│       ├── models/                   # ── 데이터 모델 (Pydantic) ──
│       │   ├── __init__.py
│       │   ├── events.py            # 서버 수신 이벤트 (game_start, action_request, ...)
│       │   ├── actions.py           # 서버 송신 액션 (fold, call, raise, ...)
│       │   ├── state.py             # 내부 상태 모델 (PlayerState, ActionRecord, ...)
│       │   └── records.py           # 영속화 모델 (GameRecord, StrategyVersion, ...)
│       │
│       └── utils/
│           ├── __init__.py
│           ├── config.py            # 설정 (CLI 인자, 환경변수)
│           └── logger.py            # 구조화 로깅
│
├── data/                             # ── 정적 데이터 ──
│   ├── preflop/
│   │   ├── rankings_169.json        # 169 핸드 랭킹 테이블
│   │   ├── heads_up.json            # 2인 프리플롭 레인지
│   │   └── full_ring.json           # 9인 프리플롭 레인지
│   └── pushfold/
│       ├── nash_10bb.json           # 10BB 푸시/폴드 테이블
│       └── nash_15bb.json           # 15BB 푸시/폴드 테이블
│
├── db/                               # ── SQLite 데이터베이스 (런타임 생성) ──
│   └── .gitkeep
│
└── tests/
    ├── __init__.py
    ├── conftest.py                  # 공통 픽스처 (인메모리 DB, mock 서버)
    ├── core/
    │   ├── test_card.py
    │   ├── test_evaluator.py
    │   ├── test_equity.py
    │   └── test_range.py
    ├── engine/
    │   ├── test_game.py
    │   └── test_player.py
    ├── strategy/
    │   ├── test_genome.py
    │   ├── test_registry.py
    │   └── test_builtins.py
    ├── harness/
    │   ├── test_recorder.py
    │   └── test_replayer.py
    ├── analytics/
    │   └── test_metrics.py
    ├── evolution/
    │   ├── test_mutator.py
    │   ├── test_breeder.py
    │   └── test_generator.py
    └── integration/
        └── test_full_hand.py        # Mock 서버로 전체 핸드 시뮬레이션
```

---

## 5. 핵심 의존성

```toml
[project]
name = "holdem-agent"
version = "0.1.0"
description = "Texas Hold'em AI with strategy evolution ecosystem"
requires-python = ">=3.14"
dependencies = [
    "websockets>=14.0",
    "treys>=0.1.8",
    "pydantic>=2.10",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "ruff>=0.9",
    "mypy>=1.14",
]

[project.scripts]
holdem-agent = "holdem_agent.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/holdem_agent"]

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.mypy]
python_version = "3.14"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

| 패키지 | 용도 | 선택 이유 |
|--------|------|----------|
| `websockets` | 서버 통신 | asyncio 네이티브, 사실상 표준 |
| `treys` | 핸드 평가 | Pure Python (3.14 보장), 235k eval/s |
| `pydantic` | 데이터 모델 | 타입 안전, JSON 직렬화 자동화 |
| `sqlite3` | 영속화 | 표준 라이브러리, 별도 설치 불필요 |

---

## 6. 컴포넌트 상세 설계

### 6.1 Harness — 실행 하네스

```python
# harness/runner.py
class HarnessRunner:
    """전략을 실제 서버에서 실행하는 하네스."""

    def __init__(self, strategy: Strategy, recorder: GameRecorder):
        self._strategy = strategy
        self._recorder = recorder
        self._game_tracker = GameTracker()

    async def run(self, server_url: str, token: str, bot_name: str) -> None:
        """메인 이벤트 루프. 전략으로 게임을 플레이한다."""
        async with PokerConnection(server_url) as conn:
            await conn.authenticate(token, bot_name)
            async for msg in conn.listen():
                await self._handle(conn, msg)

    async def _handle(self, conn: PokerConnection, msg: dict) -> None:
        """이벤트 라우팅 + 기록 + 전략 실행."""
        match msg["type"]:
            case "ping":
                await conn.send_pong()
            case "action_request":
                # 1. 상태 업데이트
                self._game_tracker.update_from_request(msg)
                snapshot = self._game_tracker.get_snapshot(msg["room_id"])

                # 2. 기록
                self._recorder.record_action_request(msg)

                # 3. 전략 실행 (타임아웃 보장)
                action = await self._safe_decide(snapshot)

                # 4. 응답
                await conn.send_action(msg["room_id"], action)
                self._recorder.record_decision(msg["room_id"], action)

            case "hand_result":
                self._game_tracker.record_result(msg)
                self._recorder.record_hand_result(msg)
            case "game_end":
                self._recorder.record_game_end(msg)
            # ... 나머지 이벤트

    async def _safe_decide(self, snapshot: DecisionContext) -> Action:
        """타임아웃 보장 래퍼. 28초 내 응답."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._strategy.decide, snapshot),
                timeout=28.0,
            )
        except (TimeoutError, Exception):
            return safe_fallback(snapshot)  # to_call==0 → check, else fold
```

### 6.2 Recorder — 게임 녹화

```python
# harness/recorder.py
class GameRecorder:
    """모든 게임 이벤트를 SQLite에 기록한다."""

    def __init__(self, db: Database):
        self._db = db

    def record_action_request(self, msg: dict) -> None:
        """action_request 이벤트를 기록."""
        self._db.insert("action_requests", {
            "room_id": msg["room_id"],
            "hand_number": msg["hand_number"],
            "phase": msg["phase"],
            "hole_cards": json.dumps(msg["your_cards"]),
            "community_cards": json.dumps(msg["community_cards"]),
            "pot": msg["pot"],
            "my_stack": msg["my_stack"],
            "to_call": msg["to_call"],
            "min_raise": msg["min_raise"],
            "seat": msg["seat"],
            "players_json": json.dumps(msg["players"]),
            "action_history_json": json.dumps(msg["action_history"]),
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def record_decision(self, room_id: int, action: Action) -> None:
        """봇의 결정을 기록."""
        self._db.insert("decisions", {
            "room_id": room_id,
            "action_type": action.action,
            "amount": action.amount,
            "reasoning": action.reasoning,
            "strategy_name": action.strategy_name,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def record_hand_result(self, msg: dict) -> None:
        """핸드 결과 기록."""
        ...
```

### 6.3 Analytics — 성과 분석

```python
# analytics/metrics.py
class MetricsCalculator:
    """전략별 성과 메트릭을 계산한다."""

    def calculate_strategy_metrics(self, strategy_name: str, db: Database) -> StrategyMetrics:
        """특정 전략의 누적 성과."""
        return StrategyMetrics(
            games_played=db.count("games", strategy=strategy_name),
            win_rate=db.avg_finish_rank(strategy=strategy_name),
            avg_roi=self._calc_roi(strategy_name, db),
            total_hands=db.count("decisions", strategy=strategy_name),
            vpip=self._calc_vpip(strategy_name, db),
            pfr=self._calc_pfr(strategy_name, db),
            avg_m_value_at_decision=self._calc_avg_m(strategy_name, db),
            money_won=db.sum("hand_results", "amount", winner=strategy_name),
        )

    def compare_strategies(self, names: list[str], db: Database) -> ComparisonReport:
        """여러 전략을 나란히 비교."""
        ...
```

```python
# analytics/weakspot.py
class WeakspotAnalyzer:
    """전략의 약점을 진단한다."""

    def diagnose(self, strategy_name: str, db: Database) -> list[Weakspot]:
        """어떤 상황에서 손실이 많은지 분석."""
        weakspots = []

        # 포지션별 손실 분석
        position_losses = self._losses_by_position(strategy_name, db)
        if position_losses["utg"] > threshold:
            weakspots.append(Weakspot(
                area="preflop_utg",
                description="UTG에서 과도한 손실",
                suggestion="프리플롭 UTG 레이즈 레인지 축소",
                param_to_adjust="preflop_raise_threshold.utg",
                direction="increase",  # threshold 올리면 레인지 축소
            ))

        # 블러프 성공률 분석
        bluff_success = self._bluff_success_rate(strategy_name, db)
        if bluff_success < 0.35:
            weakspots.append(Weakspot(
                area="bluff",
                description="블러프 성공률 낮음",
                suggestion="블러프 빈도 감소 또는 더 나은 스팟 선택",
                param_to_adjust="bluff_frequency",
                direction="decrease",
            ))

        # M값 구간별 손실
        # 쇼다운 승률
        # 팟 오즈 대비 콜 결정
        ...

        return weakspots
```

### 6.4 Evolution — 전략 진화

```python
# evolution/mutator.py
class GenomeMutator:
    """전략 게놈에 돌연변이를 적용한다."""

    def mutate(self, genome: StrategyGenome, rate: float = 0.1) -> StrategyGenome:
        """각 파라미터에 rate 확률로 가우시안 섭동."""
        mutated = dataclasses.replace(genome)
        fields = dataclasses.fields(mutated)

        for field in fields:
            if random() > rate:
                continue
            current = getattr(mutated, field.name)
            if isinstance(current, dict):
                # dict 파라미터: 각 값에 개별 섭동
                perturbed = {k: self._perturb(v) for k, v in current.items()}
                setattr(mutated, field.name, perturbed)
            elif isinstance(current, float):
                setattr(mutated, field.name, self._perturb(current))

        return mutated

    def _perturb(self, value: float, sigma: float = 0.1) -> float:
        """값에 가우시안 노이즈 추가 후 [0, 1] 클램핑."""
        return max(0.0, min(1.0, value + gauss(0, sigma)))
```

```python
# evolution/breeder.py
class GenomeBreeder:
    """두 전략 게놈을 교배한다."""

    def breed(self, parent_a: StrategyGenome, parent_b: StrategyGenome) -> StrategyGenome:
        """유니폼 교차: 각 파라미터를 50% 확률로 각 부모에서 상속."""
        child_kwargs = {}
        for field in dataclasses.fields(parent_a):
            val_a = getattr(parent_a, field.name)
            val_b = getattr(parent_b, field.name)
            if isinstance(val_a, dict):
                child_kwargs[field.name] = {
                    k: val_a[k] if random() < 0.5 else val_b[k]
                    for k in val_a
                }
            else:
                child_kwargs[field.name] = val_a if random() < 0.5 else val_b
        return StrategyGenome(**child_kwargs)
```

```python
# evolution/generator.py
class StrategyGenerator:
    """분석 결과로부터 새 전략 후보를 생성한다."""

    def generate_candidates(
        self,
        base_strategy: Strategy,
        weakspots: list[Weakspot],
        n_candidates: int = 5,
    ) -> list[Strategy]:
        """약점 진단을 바탕으로 개선된 전략 후보 생성."""
        candidates = []

        # 1. 약점 직접 수정 (지식 기반)
        for weakspot in weakspots:
            targeted = self._targeted_mutation(base_strategy.genome, weakspot)
            candidates.append(base_strategy.__class__.from_genome(targeted))

        # 2. 랜덤 돌연변이 (탐색)
        for _ in range(n_candidates - len(weakspots)):
            mutated = self._mutator.mutate(base_strategy.genome, rate=0.15)
            candidates.append(base_strategy.__class__.from_genome(mutated))

        return candidates

    def _targeted_mutation(self, genome: StrategyGenome, weakspot: Weakspot) -> StrategyGenome:
        """특정 약점을 직접 수정."""
        mutated = dataclasses.replace(genome)
        current = getattr(mutated, weakspot.param_to_adjust)
        adjustment = 0.1 if weakspot.direction == "increase" else -0.1
        setattr(mutated, weakspot.param_to_adjust,
                max(0.0, min(1.0, current + adjustment)))
        return mutated
```

### 6.5 Storage — 영속화

```python
# storage/database.py
class Database:
    """SQLite 데이터베이스 관리."""

    def __init__(self, path: str = "db/holdem.db"):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        """스키마 초기화."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY,
                room_id INTEGER,
                strategy_name TEXT,
                started_at TEXT,
                finished_at TEXT,
                final_rank INTEGER,
                final_chips INTEGER,
                total_hands INTEGER
            );

            CREATE TABLE IF NOT EXISTS action_requests (
                id INTEGER PRIMARY KEY,
                room_id INTEGER,
                hand_number INTEGER,
                phase TEXT,
                hole_cards TEXT,        -- JSON
                community_cards TEXT,   -- JSON
                pot INTEGER,
                my_stack INTEGER,
                to_call INTEGER,
                min_raise INTEGER,
                seat TEXT,
                players_json TEXT,      -- JSON
                action_history_json TEXT, -- JSON
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY,
                room_id INTEGER,
                hand_number INTEGER,
                phase TEXT,
                action_type TEXT,       -- fold/check/call/raise/allin
                amount INTEGER,
                reasoning TEXT,
                strategy_name TEXT,
                elapsed_ms INTEGER,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS hand_results (
                id INTEGER PRIMARY KEY,
                room_id INTEGER,
                hand_number INTEGER,
                pot INTEGER,
                winners_json TEXT,      -- JSON
                showdown_json TEXT,     -- JSON
                community_cards TEXT,   -- JSON
                eliminated_json TEXT,   -- JSON
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE,
                parent_name TEXT,
                genome_json TEXT,       -- JSON (StrategyGenome 직렬화)
                generation INTEGER,
                created_at TEXT,
                created_by TEXT,        -- manual / mutation / breeding / analysis
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS strategy_metrics (
                id INTEGER PRIMARY KEY,
                strategy_name TEXT,
                games_played INTEGER,
                avg_finish_rank REAL,
                win_rate REAL,
                total_hands INTEGER,
                money_won INTEGER,
                vpip REAL,
                calculated_at TEXT
            );
        """)

    def insert(self, table: str, data: dict) -> int: ...
    def query(self, sql: str, params: tuple = ()) -> list[Row]: ...
```

### 6.6 Strategy Registry — 전략 버전 관리

```python
# strategy/registry.py
class StrategyRegistry:
    """전략의 버전 관리, 로드, 세이브."""

    def __init__(self, db: Database):
        self._db = db

    def register(self, strategy: Strategy, parent: str | None = None,
                 created_by: str = "manual", notes: str = "") -> str:
        """새 전략을 레지스트리에 등록."""
        name = strategy.name
        self._db.insert("strategy_versions", {
            "name": name,
            "parent_name": parent,
            "genome_json": json.dumps(dataclasses.asdict(strategy.genome)),
            "generation": self._next_generation(parent),
            "created_at": datetime.now(UTC).isoformat(),
            "created_by": created_by,
            "notes": notes,
        })
        return name

    def load(self, name: str) -> Strategy:
        """저장된 전략을 복원."""
        row = self._db.query(
            "SELECT genome_json FROM strategy_versions WHERE name = ?",
            (name,)
        )[0]
        genome = StrategyGenome(**json.loads(row["genome_json"]))
        return GtoBaseline.from_genome(genome)  # 또는 타입에 따라 분기

    def lineage(self, name: str) -> list[dict]:
        """전략의 계보 추적 (부모 → 자식 트리)."""
        ...

    def best_strategy(self, metric: str = "win_rate") -> Strategy:
        """가장 성과가 좋은 전략 반환."""
        ...
```

---

## 7. 데이터 흐름

### 7.1 Play 모드 — 실전 실행

```
서버 WebSocket
     │
     ▼
┌───────────────────────────────────────────────────────────┐
│  HarnessRunner                                            │
│                                                           │
│  1. Client.connection ←→ 서버 (WebSocket)                 │
│                                                           │
│  2. protocol.route(msg):                                  │
│     ping        → pong                                    │
│     game_start  → engine.new_game() + recorder.log()      │
│     hand_start  → engine.new_hand()  + recorder.log()      │
│     phase_change→ engine.update()    + recorder.log()      │
│     action_req  ─┐                                        │
│                   ▼                                       │
│     3. engine.get_snapshot(room_id)                       │
│                                                           │
│     4. strategy.decide(snapshot)   ← 전략이 여기서 실행됨  │
│        ├─ analysts.hand_strength()                        │
│        ├─ analysts.equity_calc()                          │
│        ├─ analysts.position()                             │
│        ├─ analysts.opponent()                             │
│        └─ analysts.risk()                                 │
│                                                           │
│     5. client.send_action(action)                         │
│     6. recorder.record_decision(action)                   │
│                                                           │
│     hand_result → engine.record() + recorder.log()        │
│     game_end    → recorder.finalize()                     │
└───────────────────────────────────────────────────────────┘
```

### 7.2 Evolve 모드 — 전략 진화

```
┌───────────────────────────────────────────────────────────┐
│  Evolution Pipeline                                        │
│                                                           │
│  1. StrategyRegistry.best_strategy("win_rate")             │
│     → base_strategy                                       │
│                                                           │
│  2. MetricsCalculator.calculate(base_strategy, db)         │
│     → StrategyMetrics                                     │
│                                                           │
│  3. WeakspotAnalyzer.diagnose(base_strategy, db)           │
│     → [Weakspot(utg_손실, bluff_성공률, ...)]             │
│                                                           │
│  4. StrategyGenerator.generate_candidates(                 │
│        base_strategy,                                     │
│        weakspots,                                         │
│        n_candidates=5                                     │
│     )                                                     │
│     → [candidate_1, candidate_2, ..., candidate_5]        │
│                                                           │
│  5. Validator.validate(candidate)                          │
│     - 기본 합리성 체크 (모든 폴드? 과도한 블러프?)        │
│     - 범위 검사 (파라미터 [0,1] 내)                       │
│                                                           │
│  6. StrategyRegistry.register(candidate,                   │
│        parent=base_strategy.name,                         │
│        created_by="mutation")                             │
│                                                           │
│  7. 사용자가 다음 run에서 새 전략 선택 가능               │
│     $ holdem-agent play --strategy gto-baseline-v1.3       │
└───────────────────────────────────────────────────────────┘
```

### 7.3 Analyze 모드 — 성과 분석

```
┌───────────────────────────────────────────────────────────┐
│  Analytics Pipeline                                        │
│                                                           │
│  $ holdem-agent analyze --strategy gto-baseline-v1.2       │
│                                                           │
│  1. MetricsCalculator.calculate(strategy, db)              │
│     - 승률: 35%                                           │
│     - 평균 순위: 2.1 / 6                                  │
│     - VPIP: 22%                                           │
│     - ROI: +15%                                           │
│                                                           │
│  2. Comparator.compare(["gto-v1.1", "gto-v1.2"])          │
│     - v1.2이 UTG에서 수익 개선                            │
│     - v1.2이 블러프 성공률 하락                            │
│                                                           │
│  3. WeakspotAnalyzer.diagnose(strategy, db)                │
│     - SB 디펜스에서 과도한 폴드                           │
│     - 턴 레이즈 후 리버에서 패배율 높음                   │
│                                                           │
│  4. Reporter.generate(strategy, metrics, weakspots)        │
│     → 터미널 출력 / JSON 리포트                           │
└───────────────────────────────────────────────────────────┘
```

---

## 8. 타임아웃 전략

```
action_request 수신 (T+0s)
     │
     ├─ T+0s: 빠른 경로
     │   - to_call == 0 → check 즉시 반환 (0.01s)
     │   - M < 5 → 푸시/폴드 테이블 즉시 조회 (0.1s)
     │
     ├─ T+0 ~ T+20s: 전략 실행
     │   - strategy.decide(snapshot)
     │   - Monte Carlo iterations 동적 조정
     │
     ├─ T+25s: 안전 폴백
     │   - equity > pot_odds → call
     │   - equity < pot_odds → fold
     │
     ├─ T+28s: 최후 폴백
     │   - to_call == 0 → check
     │   - to_call > 0 → fold
     │
     └─ T+30s: 서버 자동 폴드 (여기까진 오면 안 됨)
```

---

## 9. 재접속 및 장애 복구

```
연결 끊김 감지
     │
     ▼
재접속 시도 (지수 백오프: 1s, 2s, 4s, 8s, 최대 30s)
     │
     ▼
auth_bot 재전송
     │
     ▼
joined_room + snapshot 수신?
     │
     ├─ YES → snapshot으로 GameTracker 상태 복원
     └─ NO  → 다음 hand_start 대기
```

---

## 10. CLI 인터페이스

```bash
# 실전 플레이
holdem-agent play ws://서버:5051/ws "TOKEN" "bot-name" \
    --strategy gto-baseline-v1.2        # 특정 전략 지정
    --strategy latest                   # 가장 성과 좋은 전략 자동 선택

# 전략 진화 (오프라인)
holdem-agent evolve \
    --base-strategy gto-baseline-v1.2 \
    --n-candidates 5 \
    --mutation-rate 0.15

# 성과 분석
holdem-agent analyze \
    --strategy gto-baseline-v1.2 \
    --compare-with gto-baseline-v1.1 \
    --format json

# 게임 재생 (디버깅)
holdem-agent replay \
    --game-id 42 \
    --with-strategy aggressive-v1.0     # 다른 전략으로 반사적 분석

# 전략 목록
holdem-agent list-strategies
```

---

## 11. 로깅

```python
# 모든 결정을 핸드 단위로 기록
@dataclass
class DecisionLog:
    room_id: int
    hand_number: int
    phase: str
    strategy_name: str
    action: str
    amount: int | None
    reasoning: str
    elapsed_ms: int
    # 분석 컴포넌트 요약
    hand_rank: str
    equity: float
    m_value: float

# 출력 예시
# INFO | room=1 hand=#5 phase=flop strategy=gto-v1.2
#      | action=raise amount=12 equity=0.67 pot_odds=0.25 m=15.2
#      | reasoning="strong pair + position advantage, value raise"
#      | elapsed=234ms
```

---

## 12. 구현 우선순위

### Phase 1: 기반 — 동작하는 최소 봇 (플레이 가능)

| 순서 | 컴포넌트 | 목표 |
|------|----------|------|
| 1 | `pyproject.toml` + uv | 프로젝트 초기화 |
| 2 | `models/` | Pydantic 데이터 모델 전체 정의 |
| 3 | `core/card.py` + `core/evaluator.py` | 카드 변환 + treys 래퍼 |
| 4 | `client/` | WebSocket 통신 (연결, 인증, 라우팅) |
| 5 | `engine/` | 게임 상태 관리 (room_id 분리) |
| 6 | `strategy/base.py` + `genome.py` | 전략 인터페이스 + 게놈 정의 |
| 7 | `strategy/builtins/calling_station.py` | 최소 전략 (fold/check/call) |
| 8 | `harness/runner.py` (간단 버전) | 실행 루프 |
| 9 | `__main__.py` | CLI 진입점 (`play` 명령) |

**목표**: `holdem-agent play ws://... TOKEN bot-name` 실행 → 서버에서 핸드 플레이

### Phase 2: 지능 — 전략적 플레이

| 순서 | 컴포넌트 | 목표 |
|------|----------|------|
| 10 | `core/equity.py` | Monte Carlo 승률 계산 |
| 11 | `core/odds.py` | 팟 오즈, EV 계산 |
| 12 | `strategy/analysts/` | 5개 분석 컴포넌트 |
| 13 | `strategy/builtins/gto_baseline.py` | GTO 기반 전략 |
| 14 | `strategy/charts/` | 프리플롭 차트, 푸시폴드 테이블 |
| 15 | `strategy/builtins/tight_aggressive.py` | TAG 전략 |
| 16 | `strategy/registry.py` | 전략 버전 관리 |

**목표**: GTO 기반 전략으로 합리적인 플레이

### Phase 3: 기록 — 게임 녹화 + 분석

| 순서 | 컴포넌트 | 목표 |
|------|----------|------|
| 17 | `storage/database.py` | SQLite 스키마 + CRUD |
| 18 | `harness/recorder.py` | 모든 이벤트 DB 기록 |
| 19 | `analytics/metrics.py` | 성과 메트릭 계산 |
| 20 | `analytics/comparator.py` | 전략 비교 |
| 21 | `analytics/weakspot.py` | 약점 진단 |
| 22 | `__main__.py` 확장 | `analyze` 명령 추가 |

**목표**: 게임 후 성과 분석 리포트 생성

### Phase 4: 진화 — 전략 자동 개선

| 순서 | 컴포넌트 | 목표 |
|------|----------|------|
| 23 | `evolution/mutator.py` | 게놈 돌연변이 |
| 24 | `evolution/breeder.py` | 게놈 교배 |
| 25 | `evolution/generator.py` | 약점 기반 전략 생성 |
| 26 | `evolution/validator.py` | 전략 검증 |
| 27 | `harness/replayer.py` | 게임 재생 + 반사적 분석 |
| 28 | `__main__.py` 확장 | `evolve`, `replay` 명령 추가 |

**목표**: 분석 결과로 새 전략 자동 생성

### Phase 5: 적응 — 상대 모델링

| 순서 | 컴포넌트 | 목표 |
|------|----------|------|
| 29 | `strategy/analysts/opponent.py` | 상대 경향 추적 |
| 30 | `strategy/builtins/adaptive.py` | 익스플로잇 전략 |
| 31 | `strategy/builtins/aggressive.py` | 공격형 전략 |

**목표**: 상대 약점을 파악하고 익스플로잇하는 적응형 플레이

---

## 13. 테스트 전략

### 단위 테스트

| 영역 | 테스트 | 내용 |
|------|--------|------|
| `core/` | 카드, 평가, 승률 | 순수 함수: 알려진 입력 → 예상 출력 |
| `engine/` | 게임 상태 | 이벤트 시퀀스 → 올바른 상태 전이 |
| `strategy/` | 게놈, 전략 | 직렬화/복원, 알려진 상황 → 예상 액션 |
| `harness/` | 녹화, 재생 | 이벤트 기록 → DB 조회 → 재생 |
| `analytics/` | 메트릭 | 더미 게임 데이터 → 예상 메트릭 |
| `evolution/` | 돌연변이, 교배 | 게놈 변이 → 범위 보존, 유효성 |

### 통합 테스트

```python
# tests/integration/test_full_hand.py
async def test_full_game_with_recording():
    """Mock 서버로 전체 게임 → DB 기록 → 분석 파이프라인."""
    db = Database(":memory:")
    strategy = CallingStation()
    recorder = GameRecorder(db)
    runner = HarnessRunner(strategy, recorder)
    mock = MockPokerServer()

    await runner.run(mock.url, "token", "test-bot")
    # 게임이 끝나면...

    # 1. DB에 기록됐는지 확인
    assert db.count("action_requests") > 0
    assert db.count("decisions") > 0
    assert db.count("hand_results") > 0

    # 2. 메트릭 계산
    metrics = MetricsCalculator().calculate_strategy_metrics("calling-station", db)
    assert metrics.games_played > 0

    # 3. 진화
    candidates = StrategyGenerator().generate_candidates(strategy, [], n_candidates=3)
    assert len(candidates) == 3
```

---

## 14. 실행 방법

```bash
# 설정
uv sync

# Phase 1: 최소 봇 실행
uv run holdem-agent play ws://snn.it.kr:5051/ws "TOKEN" "bot-name"

# Phase 2: 전략 지정 실행
uv run holdem-agent play ws://snn.it.kr:5051/ws "TOKEN" "bot-name" --strategy gto-v1.2

# Phase 3: 성과 분석
uv run holdem-agent analyze --strategy gto-v1.2

# Phase 4: 전략 진화
uv run holdem-agent evolve --base-strategy gto-v1.2 --n-candidates 5

# 테스트
uv run pytest
uv run mypy src/
uv run ruff check src/
```
