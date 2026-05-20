"""방별 전략 변형 시스템.

같은 봇이 방마다 다른 성향(밸류/타이트/공격/LAG/프로브)으로 플레이한다.
목적:
  1. 데이터 다양성 — 어떤 스타일이 어떤 상대에 강한지 실험
  2. 예측 불가성 — 단일 패턴으로 읽히지 않음
  3. 탐색/활용 — Phase 3 익스플로잇 레이어의 기반 데이터 확보
"""
import random
from dataclasses import dataclass, asdict
from typing import Dict


@dataclass(frozen=True)
class StrategyVariant:
    name: str

    # ── 프리플랍 사이즈 (bb 배수) ──
    open_size_bb: float = 2.5     # RFI 오픈 사이즈
    threebet_mult: float = 3.0    # 3벳은 상대 오픈의 N배
    fourbet_mult: float = 2.3     # 4벳은 상대 3벳의 N배

    # ── 포스트플랍 에쿼티 임계 ──
    eq_nuts: float = 0.80   # 오버베팅/너트급
    eq_std: float = 0.65    # 표준 밸류
    eq_thin: float = 0.50   # 씬 밸류 (상대 체크시만)

    # ── 포스트플랍 사이징 (팟 비율) ──
    size_nuts: float = 0.75
    size_std: float = 0.60
    size_thin: float = 0.50

    # ── 공격성 빈도 (0 = 블러프 없음) ──
    cbet_freq: float = 0.0          # 프리플랍 레이저의 플랍 C-bet 블러프
    turn_barrel_freq: float = 0.0   # 플랍 공격 → 턴 연속 베팅
    river_probe_freq: float = 0.0   # 양쪽 체크로 흘러온 리버 프로브
    semibluff_freq: float = 0.0     # 플랍 드로우 범위(eq 0.40~0.55) 세미블러프 레이즈

    # ── 콜 결정 마진 (에쿼티 > 팟오즈 + edge 면 콜) ──
    call_edge: float = 0.03


# ── 프리셋 ──
VALUE = StrategyVariant(
    name="VALUE",
    # 현재 v1 롤백과 동일. 순수 밸류.
)

TIGHT = StrategyVariant(
    name="TIGHT",
    eq_nuts=0.82, eq_std=0.70, eq_thin=0.58,
    size_nuts=0.70, size_std=0.55, size_thin=0.40,
    call_edge=0.06,
)

AGGRO = StrategyVariant(
    name="AGGRO",
    eq_nuts=0.78, eq_std=0.62, eq_thin=0.48,
    size_nuts=0.85, size_std=0.70, size_thin=0.55,
    cbet_freq=0.55, turn_barrel_freq=0.40, semibluff_freq=0.20,
    call_edge=0.01,
)

LAG = StrategyVariant(
    name="LAG",
    open_size_bb=3.0, threebet_mult=3.5,
    eq_nuts=0.75, eq_std=0.58, eq_thin=0.42,
    size_nuts=1.0, size_std=0.80, size_thin=0.60,
    cbet_freq=0.75, turn_barrel_freq=0.55,
    river_probe_freq=0.45, semibluff_freq=0.30,
    call_edge=-0.01,  # 공격적 → 에쿼티 살짝 아래여도 콜
)

PROBE = StrategyVariant(
    name="PROBE",
    eq_nuts=0.80, eq_std=0.64, eq_thin=0.48,
    size_nuts=0.75, size_std=0.55, size_thin=0.35,
    cbet_freq=0.30, river_probe_freq=0.50, semibluff_freq=0.10,
    call_edge=0.02,
)

VARIANTS = [VALUE, TIGHT, AGGRO, LAG, PROBE]
_BY_NAME = {v.name: v for v in VARIANTS}

# 5-1 swap 후 1025게임 재측정: AGGRO 1등 21.5/꼴등 46.1, PROBE 22.6/43.0,
# TIGHT 16.3/48.3 — 새 표본에서 AGGRO/PROBE가 양 지표 우위.
# 이전 TIGHT 우위는 n=117 노이즈였음. 안정+공격 균형으로 재배분.
SAMPLE_WEIGHTS = {
    "AGGRO": 30,
    "PROBE": 25,
    "TIGHT": 25,
    "VALUE": 15,
    "LAG": 5,
}

# 방별 할당 캐시
_ROOM_VARIANT: Dict = {}


def sample() -> StrategyVariant:
    """1등률 높은 변형 위주 가중 샘플링."""
    weights = [SAMPLE_WEIGHTS.get(v.name, 1) for v in VARIANTS]
    return random.choices(VARIANTS, weights=weights, k=1)[0]


def get_for_room(room_id) -> StrategyVariant:
    """방 ID에 할당된 변형 반환. 없으면 샘플링해서 고정."""
    if room_id not in _ROOM_VARIANT:
        _ROOM_VARIANT[room_id] = sample()
    return _ROOM_VARIANT[room_id]


def assign_room(room_id, variant: StrategyVariant) -> None:
    _ROOM_VARIANT[room_id] = variant


def reset_room(room_id) -> None:
    _ROOM_VARIANT.pop(room_id, None)


def by_name(name: str) -> StrategyVariant:
    return _BY_NAME.get(name, VALUE)


def as_dict(variant: StrategyVariant) -> dict:
    return asdict(variant)
