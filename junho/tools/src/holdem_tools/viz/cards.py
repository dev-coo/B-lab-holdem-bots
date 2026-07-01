"""HTML rendering helpers for poker cards.

Card string format: rank + suit, 2 chars.
Ranks: 2-9, T (=10), J, Q, K, A. Suits: s, h, d, c. See BOT_REFERENCE.md §3.
"""

from __future__ import annotations

_SUIT_SYMBOLS = {"s": "\u2660", "h": "\u2665", "d": "\u2666", "c": "\u2663"}
_RED_SUITS = {"h", "d"}
_VALID_RANKS = set("23456789TJQKA")

_CARD_BASE_STYLE = (
    "display:inline-block; border:1px solid #333; border-radius:6px; "
    "padding:6px 10px; margin:2px; font-family:monospace; "
    "font-size:22px; font-weight:bold; background:#fff; "
    "min-width:36px; text-align:center; line-height:1.1;"
)

_EMPTY_STYLE = (
    "display:inline-block; border:1px dashed #999; border-radius:6px; "
    "padding:6px 10px; margin:2px; font-family:monospace; "
    "font-size:22px; font-weight:bold; background:#fafafa; color:#bbb; "
    "min-width:36px; text-align:center; line-height:1.1;"
)

_BACK_STYLE = (
    "display:inline-block; border:1px solid #123a6b; border-radius:6px; "
    "padding:6px 10px; margin:2px; font-family:monospace; "
    "font-size:22px; font-weight:bold; background:#2a5db0; color:#fff; "
    "min-width:36px; text-align:center; line-height:1.1;"
)


def suit_symbol(suit: str) -> str:
    """Return the unicode symbol for a suit letter, or empty string if unknown."""
    if not isinstance(suit, str):
        return ""
    return _SUIT_SYMBOLS.get(suit, "")


def is_red_suit(suit: str) -> bool:
    """Return True if the suit is hearts or diamonds."""
    return isinstance(suit, str) and suit in _RED_SUITS


def empty_card_html() -> str:
    """Dashed placeholder box for a card slot with no card yet."""
    return f'<span style="{_EMPTY_STYLE}">&nbsp;</span>'


def back_card_html() -> str:
    """Face-down (back) card — blue background with a central marker."""
    return f'<span style="{_BACK_STYLE}">?</span>'


def card_html(card: str | None) -> str:
    """Render a 2-char card string as an inline HTML span.

    Invalid / empty / None input falls back to `empty_card_html()`.
    """
    if not isinstance(card, str) or len(card) != 2:
        return empty_card_html()
    rank, suit = card[0], card[1]
    if rank not in _VALID_RANKS or suit not in _SUIT_SYMBOLS:
        return empty_card_html()
    display_rank = "10" if rank == "T" else rank
    color = "#c00" if is_red_suit(suit) else "#111"
    style = f"{_CARD_BASE_STYLE} color:{color};"
    return f'<span style="{style}">{display_rank}<br>{suit_symbol(suit)}</span>'


def cards_html(cards: list[str] | None, hidden_count: int = 0) -> str:
    """Render a sequence of cards, optionally followed by `hidden_count` back cards.

    Returns an empty string when `cards` is None or empty.
    """
    if not cards:
        return ""
    parts = [card_html(c) for c in cards]
    if hidden_count > 0:
        parts.extend(back_card_html() for _ in range(hidden_count))
    return "".join(parts)
