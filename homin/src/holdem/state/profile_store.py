"""ProfileStore — 영속 대상인 PlayerProfile 의 in-memory 저장소 + 이벤트 훅.

근거:
  - plan P4: 전역·영속 프로필 (name 기반 고정 키).
  - D3 Day 17: hand_result 시점에 stat_updater 로 metric 갱신.

책임:
  - `name → PlayerProfile` 저장 (메모리).
  - hand 종료 시 action_history 로 profile 갱신.
  - 추후 SQLite persist 계층이 이 store 를 snapshot/restore.

책임 외:
  - GameState 와 별도. GameState 는 room 단위 휘발성, ProfileStore 는 글로벌.
  - 쇼다운 기반 BLUFF_AT_SHOWDOWN 은 별도 라벨러(후속).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..estimate.stat_updater import update_from_hand
from ..transport import protocol as p
from .game_state import GameState
from .player_profile import PlayerProfile
from .response_store import ResponseStore

log = logging.getLogger(__name__)


_TEST_BOT_PREFIX = "__test_"
_TEST_BOT_WEIGHT = 0.3

# P-Decay: posterior 자동 감쇠. N hands 마다 모든 누적치에 factor 적용.
# 메타 drift 에 적응하기 위해 frozen posterior 방지. 1주일 ≈ 50k hands 가정 시
# decay factor 0.999 / 100 hands → 1주일 후 영향 ≈ 60%, 2주일 후 ≈ 36%.
# 보수적 시작값. 메타 변화가 빠르면 0.998 등으로 강화 가능.
_DECAY_INTERVAL_HANDS = 100
_DECAY_FACTOR = 0.999


def is_test_bot(name: str | None) -> bool:
    """`__test_` prefix 인 자체 학습 봇 식별 (P-Bias).

    실서버에서는 누적 핸드의 86% 가 이 prefix 이므로, 메타 추론 시 가중치를
    낮춰 실 플레이어 메타에 더 치우치게 한다.
    """
    return bool(name) and name.startswith(_TEST_BOT_PREFIX)


def name_weight(name: str | None) -> float:
    """villain 이름 → 메타 가중치. test bot 은 down-weight (P-Bias)."""
    return _TEST_BOT_WEIGHT if is_test_bot(name) else 1.0


@dataclass
class ProfileStore:
    profiles: dict[str, PlayerProfile] = field(default_factory=dict)
    responses: ResponseStore = field(default_factory=ResponseStore)
    # P-Decay: 마지막 decay 이후 처리한 hand 수. _DECAY_INTERVAL_HANDS 마다 trigger.
    _hands_since_decay: int = 0

    def get(self, name: str) -> PlayerProfile:
        return self.profiles.setdefault(name, PlayerProfile(name=name))

    def has(self, name: str) -> bool:
        return name in self.profiles

    def names(self) -> list[str]:
        return list(self.profiles.keys())

    def decay_all(self, factor: float) -> None:
        """모든 profile 의 metric/aggression + responses 의 Dirichlet 누적치를 감쇠.

        근거: 누적 alpha 가 무한 증가하면 새 관측 영향력이 0 에 수렴 (frozen posterior).
        주기적 decay 로 최근 데이터에 더 무게 → 메타 drift 적응. 비율은 보존되므로
        rate() 결과는 변하지 않으나 effective sample size 가 줄어 새 관측 weight ↑.
        """
        for prof in self.profiles.values():
            for cnt in prof.metrics.values():
                cnt.decay(factor)
            prof.aggression.decay(factor)
        for resp in self.responses.table.values():
            resp.decay(factor)

    def on_hand_result(self, result: p.HandResult, game_state: GameState) -> None:
        """hand_result 시점에 action_history 를 읽어 profile 갱신.

        game_state 의 HandState 가 해당 room 에 남아있어야 한다.
        (GameState._on_hand_result 는 상태를 유지하므로 OK.)

        P-Decay: 매 _DECAY_INTERVAL_HANDS 마다 모든 posterior 에 _DECAY_FACTOR 적용.
        """
        hand = game_state.get(result.room_id)
        if hand is None:
            return
        participants = [pl.name for pl in hand.players]
        update_from_hand(
            self.profiles,
            hand.action_history,
            participants=participants,
        )
        self.responses.observe_from_hand(hand.action_history)
        self._hands_since_decay += 1
        if self._hands_since_decay >= _DECAY_INTERVAL_HANDS:
            self.decay_all(_DECAY_FACTOR)
            self._hands_since_decay = 0
            log.debug("profile decay applied: factor=%.4f", _DECAY_FACTOR)
        log.debug(
            "profile_store updated room=%s hand=%s participants=%s",
            result.room_id,
            result.hand_number,
            participants,
        )
