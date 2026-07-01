"""HTML rendering helpers for action badges, bet bars, and timeline rows."""

from __future__ import annotations

from html import escape

ACTION_COLORS: dict[str, str] = {
    "fold": "#888",
    "call": "#3366cc",
    "raise": "#e67e22",
    "check": "#27ae60",
    "allin": "#8e44ad",
}

RESULT_COLORS: dict[str, str] = {
    "win": "#27ae60",
    "lose_showdown": "#c0392b",
    "fold_pre": "#95a5a6",
    "fold_post": "#e67e22",
    "eliminated": "#000000",
    "skipped": "#bdc3c7",
}

UNKNOWN_ACTION_COLOR = "#999"

KIND_COLORS: dict[str, str] = {
    "hand_start": "#2c3e50",
    "action": "#34495e",
    "my_turn": "#e67e22",
    "hand_result": "#c0392b",
}

KIND_KO: dict[str, str] = {
    "hand_start": "핸드 시작",
    "action": "액션",
    "my_turn": "내 차례",
    "hand_result": "핸드 결과",
}

ACTION_KO: dict[str, str] = {
    "fold": "폴드",
    "call": "콜",
    "check": "체크",
    "raise": "레이즈",
    "allin": "올인",
}

PHASE_KO: dict[str, str] = {
    "preflop": "프리플롭",
    "flop": "플롭",
    "turn": "턴",
    "river": "리버",
}

PHASE_COLOR = "#16a085"

_BADGE_STYLE = (
    "display:inline-block; padding:3px 10px; border-radius:12px; "
    "background:{color}; color:#fff; font-size:13px; "
    "font-weight:600; letter-spacing:0.3px;"
)


def action_badge(action: str | None, amount: int | float | None = None) -> str:
    """Render a colored pill for a poker action.

    영어 이름(`call`, `fold`, ...) 뒤에 한국어를 괄호로 병기해 보여준다.
    예: `call(콜) 2`.
    """
    if action is None or action not in ACTION_COLORS:
        color = UNKNOWN_ACTION_COLOR
        label = "?" if action is None else str(action)
    else:
        color = ACTION_COLORS[action]
        ko = ACTION_KO.get(action, "")
        label = f"{action}({ko})" if ko else action
        if amount:
            label = f"{label} {amount}"

    style = _BADGE_STYLE.format(color=color)
    return f'<span style="{style}">{escape(label)}</span>'


def bet_bar(
    amount: int | float | None,
    max_amount: int | float,
    width_px: int = 120,
) -> str:
    """Render a horizontal bet bar; track + filled segment."""
    track_style = (
        f"display:inline-block; width:{width_px}px; height:12px; "
        "background:#eee; border-radius:6px; vertical-align:middle;"
    )

    if not amount or not max_amount:
        filled_px = 0
    else:
        ratio = amount / max_amount
        if ratio > 1:
            ratio = 1
        filled_px = int(round(ratio * width_px))

    filled_style = (
        f"display:block; width:{filled_px}px; height:12px; "
        "background:#e67e22; border-radius:6px;"
    )
    return f'<div style="{track_style}"><div style="{filled_style}"></div></div>'


def player_row_html(
    player: dict,
    max_bet: int | float,
    is_me: bool = False,
) -> str:
    """Render a single player row as flex HTML."""
    name = str(player.get("name", ""))
    position = str(player.get("position", ""))
    stack = player.get("stack", 0)
    bet = player.get("bet", 0)
    action = player.get("action")

    name_style = "font-weight:600;"
    try:
        stack_zero = float(stack) == 0
    except (TypeError, ValueError):
        stack_zero = False
    if stack_zero:
        name_style += " text-decoration:line-through; color:#999;"

    row_bg = "#fff7e6" if is_me else "transparent"
    row_style = (
        "display:flex; align-items:center; gap:10px; "
        f"padding:6px 10px; background:{row_bg}; border-radius:6px;"
    )

    me_label = (
        '<span style="color:#e67e22; font-weight:700; min-width:30px;">&#9654; 나</span>'
        if is_me
        else ""
    )

    parts = [
        f'<div style="{row_style}">',
        me_label,
        f'<span style="{name_style}">{escape(name)}</span>',
        f'<span style="color:#666;">({escape(position)})</span>',
        f'<span style="color:#333;">stack={escape(str(stack))}</span>',
        bet_bar(bet, max_bet),
        action_badge(action, bet if action == "raise" else None),
        "</div>",
    ]
    return "".join(parts)


def _extract_action(detail: str) -> tuple[str | None, int | float | None]:
    """Best-effort extraction of (action, amount) from an action detail string."""
    tokens = detail.split()
    for i, tok in enumerate(tokens):
        if tok in ACTION_COLORS:
            amount: int | float | None = None
            if i + 1 < len(tokens):
                nxt = tokens[i + 1]
                try:
                    amount = int(nxt)
                except ValueError:
                    try:
                        amount = float(nxt)
                    except ValueError:
                        amount = None
            return tok, amount
    return None, None


def decision_overlay_html(meta: dict | None) -> str:
    """Render a small inline summary of `Action.meta` decision fields.

    Fields consulted (all optional): equity (0~1), pot_odds (0~1), made_hand_ko/made_hand,
    reason, opp_tier. Returns empty string when no usable fields.
    """
    if not isinstance(meta, dict) or not meta:
        return ""
    parts: list[str] = []
    eq = meta.get("equity")
    try:
        if eq is not None:
            parts.append(f"equity {float(eq) * 100:.1f}%")
    except (TypeError, ValueError):
        pass
    po = meta.get("pot_odds")
    try:
        if po is not None:
            parts.append(f"pot_odds {float(po) * 100:.1f}%")
    except (TypeError, ValueError):
        pass
    made = meta.get("made_hand_ko") or meta.get("made_hand")
    if made:
        parts.append(f"made={made}")
    reason = meta.get("reason")
    if reason:
        parts.append(f"reason={reason}")
    tier = meta.get("opp_tier")
    if tier and tier != "any":
        parts.append(f"opp={tier}")
    if not parts:
        return ""
    style = (
        "display:inline-block; margin-left:8px; padding:2px 8px; "
        "border-radius:10px; background:#fff3cd; color:#6c4f00; "
        "font-size:12px; font-family:ui-monospace, monospace;"
    )
    return (
        f'<span class="decision-overlay" style="{style}">'
        f"{escape(' · '.join(parts))}</span>"
    )


def flow_row_html(row: dict) -> str:
    """Render a single flow row (kind badge + detail text)."""
    kind = str(row.get("kind", ""))
    detail = str(row.get("detail", ""))
    ts = row.get("ts")

    if kind.startswith("phase:"):
        color = PHASE_COLOR
        phase_key = kind.split(":", 1)[1]
        kind_label = f"페이즈: {PHASE_KO.get(phase_key, phase_key)}"
    else:
        color = KIND_COLORS.get(kind, "#7f8c8d")
        kind_label = KIND_KO.get(kind, kind)

    badge_style = _BADGE_STYLE.format(color=color)
    kind_badge = f'<span style="{badge_style}">{escape(kind_label)}</span>'

    action_html = ""
    if kind == "action":
        act, amount = _extract_action(detail)
        if act is not None:
            action_html = action_badge(act, amount)

    ts_html = ""
    if ts is not None:
        try:
            ts_html = (
                f'<span style="color:#aaa; font-size:12px; min-width:44px;">'
                f"{float(ts):.1f}s</span>"
            )
        except (TypeError, ValueError):
            ts_html = ""

    row_style = (
        "display:flex; align-items:center; gap:8px; "
        "padding:4px 8px; font-family:ui-monospace, monospace;"
    )
    detail_style = "color:#333; font-size:13px;"

    overlay_html = decision_overlay_html(row.get("decision_meta"))

    return (
        f'<div style="{row_style}">'
        f"{ts_html}"
        f"{kind_badge}"
        f"{action_html}"
        f'<span style="{detail_style}">{escape(detail)}</span>'
        f"{overlay_html}"
        f"</div>"
    )
