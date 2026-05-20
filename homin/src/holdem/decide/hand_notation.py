"""Hand notation — card string → canonical hand code + range expansion.

Canonical form:
    Pairs:    "AA", "KK", ..., "22"
    Suited:   "AKs", "T9s", "76s"  (높은 랭크 먼저)
    Offsuit:  "AKo", "T9o"

Range shorthand:
    "22+"     → 모든 페어 ≥ 22
    "A2s+"    → A2s, A3s, ..., AKs
    "KTo+"    → KTo, KJo, KQo
    "any"     → 169 전체
    comma separated: "22+,A2s+,KTo+"
"""
from __future__ import annotations

RANKS = "23456789TJQKA"   # ascending strength; index 0=2, 12=A
_RANK_SET = set(RANKS)
_SUIT_SET = set("shdc")


def canonicalize_hand(c1: str, c2: str) -> str:
    """두 카드 → 169 canonical code. 입력이 잘못되면 ValueError."""
    for c in (c1, c2):
        if len(c) != 2 or c[0] not in _RANK_SET or c[1] not in _SUIT_SET:
            raise ValueError(f"invalid card: {c!r}")
    r1, s1 = c1[0], c1[1]
    r2, s2 = c2[0], c2[1]
    # 높은 랭크 먼저
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2, s1, s2 = r2, r1, s2, s1
    if r1 == r2:
        if s1 == s2:
            raise ValueError(f"duplicate card: {c1}, {c2}")
        return r1 + r2
    return f"{r1}{r2}{'s' if s1 == s2 else 'o'}"


def all_hands() -> set[str]:
    out: set[str] = set()
    for i, r1 in enumerate(RANKS):
        out.add(r1 + r1)
        for r2 in RANKS[:i]:
            out.add(f"{r1}{r2}s")
            out.add(f"{r1}{r2}o")
    return out


def _expand_token(tok: str) -> set[str]:
    tok = tok.strip()
    if not tok:
        return set()
    if tok.lower() == "any":
        return all_hands()

    plus = tok.endswith("+")
    if plus:
        tok = tok[:-1]

    # pair: "AA" or (with plus) "22+"
    if len(tok) == 2 and tok[0] == tok[1] and tok[0] in _RANK_SET:
        if not plus:
            return {tok}
        start = RANKS.index(tok[0])
        return {RANKS[i] + RANKS[i] for i in range(start, len(RANKS))}

    # suited/offsuit: "AKs" / "AKo" (3 chars, last is s|o)
    if len(tok) == 3 and tok[0] in _RANK_SET and tok[1] in _RANK_SET and tok[2] in "so":
        r1, r2, s = tok[0], tok[1], tok[2]
        if r1 == r2:
            raise ValueError(f"invalid suited/offsuit token with same rank: {tok}{s}")
        i1, i2 = RANKS.index(r1), RANKS.index(r2)
        if i1 < i2:
            raise ValueError(f"expected higher rank first: {tok}")
        if not plus:
            return {f"{r1}{r2}{s}"}
        # expand second rank upward to one below first
        return {f"{r1}{RANKS[j]}{s}" for j in range(i2, i1)}

    raise ValueError(f"cannot parse token: {tok!r}")


def expand_range(spec: str) -> set[str]:
    """콤마 구분 토큰을 확장하여 hand code set 반환."""
    out: set[str] = set()
    for tok in spec.split(","):
        out |= _expand_token(tok)
    return out
