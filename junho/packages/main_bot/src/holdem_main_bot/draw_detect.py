"""내 드로우(플러시/스트레이트) 감지.

사용자 규칙(CHANGELOG v3 동기):
- 처음 받은 패가 같은 모양(suited) 이면, 플롭에 **내 슈트** 가 2장 이상일 때 플래시 드로우.
- 턴/리버까지 추가 카드 공개되어도 **내 슈트가 4장 이상** 이면 여전히 드로우 또는 메이드 근접.
- 드로우 중에는 싸게 보는 게 목표 — call 우선, raise/bet 크게 금지.

반환값은 `DrawInfo` 구조체로, `_postflop` 이 결정에 반영한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrawInfo:
    has_flush_draw: bool       # 4-flush (9 out)
    has_flush_made: bool       # 5+ flush 카드 (이미 플러시)
    my_suit_count: int         # 내 슈트가 hole+board 에 몇 장
    has_oesd: bool             # open-ended straight draw (8 out) — 보수적 감지
    has_gutshot: bool          # gutshot (4 out)
    outs: int                  # 합산 out (중복 보정 없는 단순합)

    @property
    def is_live_draw(self) -> bool:
        """드로우로 간주되는 상태. 플러시 메이드면 드로우 아님(made hand)."""
        return (self.has_flush_draw or self.has_oesd or self.has_gutshot) and not self.has_flush_made


_RANKS = "23456789TJQKA"
_RANK_INDEX = {r: i for i, r in enumerate(_RANKS)}


def detect_draws(hole: list[str], board: list[str]) -> DrawInfo:
    """내 홀카드 + 보드로 드로우 상태 판정.

    hole=["Ah","Kh"], board=["2h","7h","Jc"] → flush_draw (Ah/Kh 수트 h 가 board 2 장 + hole 2 장 = 4) → DrawInfo(has_flush_draw=True, my_suit_count=4, outs=9).
    """
    if not hole or len(hole) < 2 or len(board) < 3:
        return DrawInfo(
            has_flush_draw=False, has_flush_made=False,
            my_suit_count=0, has_oesd=False, has_gutshot=False, outs=0,
        )

    # 홀 슈트가 같지 않으면 플러시 드로우 후보 아님 (보드만으로 플러시는 내 손 아님).
    suited = hole[0][1] == hole[1][1]
    my_suit = hole[0][1] if suited else None

    my_suit_count = 0
    if my_suit is not None:
        my_suit_count = sum(1 for c in hole if c[1] == my_suit) + sum(1 for c in board if c[1] == my_suit)
    has_flush_made = (my_suit is not None) and (my_suit_count >= 5)
    has_flush_draw = (my_suit is not None) and (my_suit_count == 4) and not has_flush_made

    # 스트레이트 드로우 — 단순 감지.
    # hole + board 의 고유 랭크 조합에서 4 연속/gap1 패턴 존재 여부.
    ranks = sorted({_RANK_INDEX[c[0]] for c in (list(hole) + list(board)) if c[0] in _RANK_INDEX})
    # A-low wheel 고려 (A=12 도 -1 로도 간주)
    if 12 in ranks:
        ranks_with_low_ace = sorted(set(ranks + [-1]))
    else:
        ranks_with_low_ace = ranks

    has_oesd = False
    has_gutshot = False
    if len(ranks_with_low_ace) >= 4:
        # 윈도우 5 중 4 개 존재 → 드로우
        for start in range(-1, 13):
            window = [v for v in range(start, start + 5) if v in ranks_with_low_ace]
            if len(window) >= 4:
                # 연속 4 (OESD) 인지 gap 1 (gutshot) 인지 구분
                diffs = [window[i + 1] - window[i] for i in range(len(window) - 1)]
                if all(d == 1 for d in diffs) and len(window) == 4:
                    has_oesd = True
                elif 4 in [window[-1] - window[0]] and len(window) == 4:
                    has_gutshot = True
        # 스트레이트 이미 완성이면 드로우 아님
        for start in range(-1, 13):
            if all(v in ranks_with_low_ace for v in range(start, start + 5)):
                has_oesd = False
                has_gutshot = False
                break

    outs = 0
    if has_flush_draw:
        outs += 9
    if has_oesd:
        outs += 8
    elif has_gutshot:
        outs += 4
    # 플러시+OESD 같은 콤보는 간단 합. 실제 MC 계산이 이미 더 정확한 equity 주니 보완용.

    return DrawInfo(
        has_flush_draw=has_flush_draw,
        has_flush_made=has_flush_made,
        my_suit_count=my_suit_count,
        has_oesd=has_oesd,
        has_gutshot=has_gutshot,
        outs=outs,
    )
