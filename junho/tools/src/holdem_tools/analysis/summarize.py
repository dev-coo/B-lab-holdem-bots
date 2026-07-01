"""오프라인 세션 요약 CLI.

사용 예:
  python -m holdem_tools.analysis.summarize --rooms-glob '.debug/room_*.jsonl' --out reports/
  python -m holdem_tools.analysis.summarize --db-glob '.debug/**/holdem.db' --out reports/
  python -m holdem_tools.analysis.summarize --db .debug/holdem.db --out reports/
  python -m holdem_tools.analysis.summarize --room 836

각 세션에 대해 `reports/session_{room}_{run_id}.md` 를 생성하고
전체 합산 `reports/aggregate.json` 을 쓴다.

데이터 소스 우선순위:
  1) `--db` 단일 SQLite DB 경로
  2) `--db-glob` SQLite DB glob (recursive `**` 지원)
  3) `--rooms-glob` JSONL glob (legacy)
  4) `--room <N>` 단일 room JSONL
  5) (default) `.debug/**/holdem.db` 가 있으면 SQLite, 없으면 `.debug/room_*.jsonl`
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from holdem_core.debug.store import DebugStore, default_db_path
from holdem_core.debug.summary import SummaryWriter

from holdem_tools.analysis.classify import (
    LossCause,
    classify_loss,
    my_in_showdown,
    my_won_hand,
    villain_showdown_cards,
)
from holdem_tools.analysis.loader import (
    HandRecord,
    Session,
    load_sessions,
    load_sessions_from_store,
    merge_decisions,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="holdem_tools.analysis.summarize")
    p.add_argument("--room", type=int, default=None, help="단일 room_id (JSONL 모드)")
    p.add_argument(
        "--rooms-glob",
        type=str,
        action="append",
        default=None,
        help=".debug/room_*.jsonl 패턴 (legacy JSONL). 여러 번 지정 가능",
    )
    p.add_argument(
        "--db",
        type=str,
        default=None,
        help="단일 SQLite DB 파일 경로 (e.g. .debug/holdem.db)",
    )
    p.add_argument(
        "--db-glob",
        type=str,
        action="append",
        default=None,
        help="SQLite DB glob. recursive ** 지원. 여러 번 지정 가능. "
        "기본: .debug/**/holdem.db",
    )
    p.add_argument(
        "--debug-dir", type=str, default=".debug", help=".debug 디렉토리"
    )
    p.add_argument(
        "--decisions",
        type=str,
        default="logs/decisions.jsonl",
        help="폴백 조인 대상 결정 로그",
    )
    p.add_argument("--out", type=str, default="reports/", help="출력 디렉토리")
    p.add_argument("--bot-name", type=str, default=None, help="봇 이름 힌트")
    p.add_argument(
        "--write-debug-summary",
        action="store_true",
        help="오프라인 모드로도 .debug/summary_*.json 과 opponent_profiles.json 생성",
    )
    return p.parse_args(argv)


def _resolve_db_paths(args: argparse.Namespace) -> list[Path]:
    """`--db` / `--db-glob` 인자를 펼쳐 실재하는 db 파일 경로 리스트로."""
    out: list[Path] = []
    seen: set[str] = set()
    if args.db:
        p = Path(args.db)
        if p.exists() and str(p) not in seen:
            seen.add(str(p))
            out.append(p)
    globs = args.db_glob or []
    for g in globs:
        for hit in sorted(glob.glob(g, recursive=True)):
            if hit not in seen:
                seen.add(hit)
                out.append(Path(hit))
    return out


def _resolve_jsonl_paths(args: argparse.Namespace) -> list[Path]:
    """`--room` / `--rooms-glob` 인자를 펼쳐 JSONL 파일 경로 리스트로."""
    if args.room is not None:
        return [Path(args.debug_dir) / f"room_{args.room}.jsonl"]
    globs = args.rooms_glob or []
    seen: set[str] = set()
    out: list[Path] = []
    for g in globs:
        for hit in sorted(glob.glob(g, recursive=True)):
            if hit not in seen:
                seen.add(hit)
                out.append(Path(hit))
    return out


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = Path(args.decisions)

    db_paths = _resolve_db_paths(args)
    jsonl_paths = _resolve_jsonl_paths(args)

    # 명시 인자가 아무것도 없을 때: SQLite 우선, 없으면 JSONL.
    if not db_paths and not jsonl_paths and args.room is None:
        default_dbs = sorted(glob.glob(".debug/**/holdem.db", recursive=True))
        if default_dbs:
            db_paths = [Path(x) for x in default_dbs]
        else:
            jsonl_paths = [Path(x) for x in sorted(glob.glob(".debug/room_*.jsonl"))]

    # 오프라인 재집계 시 opponent_profiles 를 초기화해서 중복 누적 방지.
    if args.write_debug_summary:
        debug_dir = Path(args.debug_dir)
        # JSON 폴백 (legacy)
        profile_json = debug_dir / "opponent_profiles.json"
        if profile_json.exists():
            profile_json.unlink()
        # SQLite 백엔드도 동일하게 reset
        if default_db_path(debug_dir).exists():
            try:
                ds = DebugStore.open(debug_dir)
                ds.reset_opponent_profiles()
                ds.close()
            except Exception as e:  # noqa: BLE001
                print(f"[warn] failed to reset SQLite opponent_profiles: {e}")

    aggregate: dict[str, Any] = {
        "sessions": 0,
        "rank_distribution": {},
        "loss_cause_distribution": {},
        "equity_bin_outcome": {},  # e.g. "0.6-0.8": {"won": 2, "lost": 3}
        "opp_tier_accuracy": {},  # tier -> {"call_sd": n, "won": n, "raise_sd": n, "raise_won": n}
        "per_session": [],
    }

    rank_counter: Counter[int] = Counter()
    loss_counter: Counter[str] = Counter()
    eq_bins: dict[str, Counter[str]] = {}
    tier_stats: dict[str, dict[str, int]] = {}

    # ── SQLite path ─────────────────────────────────────────────────────────
    for db_path in db_paths:
        if not db_path.exists():
            print(f"[skip] {db_path} not found")
            continue
        try:
            store = DebugStore.open(db_path.parent, read_only=True, db_filename=db_path.name)
        except FileNotFoundError:
            print(f"[skip] {db_path} not openable")
            continue
        try:
            pairs = store.list_room_run_pairs()
            if not pairs:
                # 단일 room/run 없는 경우 전체를 한꺼번에 처리
                sessions = load_sessions_from_store(store, bot_name_hint=args.bot_name)
            else:
                sessions = []
                seen_runs: set[str] = set()
                for room_id, _run_id in pairs:
                    for sess in load_sessions_from_store(
                        store, room_id=room_id, bot_name_hint=args.bot_name
                    ):
                        if sess.run_id in seen_runs:
                            continue
                        seen_runs.add(sess.run_id)
                        sessions.append(sess)
            for sess in sessions:
                if not sess.hands:
                    continue
                merged = merge_decisions(sess.hands, decisions_path)
                _process_session(
                    sess,
                    out_dir,
                    rank_counter=rank_counter,
                    loss_counter=loss_counter,
                    eq_bins=eq_bins,
                    tier_stats=tier_stats,
                    aggregate=aggregate,
                    merged_decisions=merged,
                )
                if args.write_debug_summary:
                    try:
                        sw = SummaryWriter(Path(args.debug_dir), sess.bot_name)
                        sw.write(sess.room_id, sess.run_id, sess.rankings)
                    except Exception as e:  # noqa: BLE001
                        print(f"[warn] debug summary write failed: {e}")
        finally:
            store.close()

    # ── JSONL path (legacy / fallback) ─────────────────────────────────────
    for path in jsonl_paths:
        if not path.exists():
            print(f"[skip] {path} not found")
            continue
        sessions = load_sessions(path, bot_name_hint=args.bot_name)
        for sess in sessions:
            if not sess.hands:
                continue
            merged = merge_decisions(sess.hands, decisions_path)
            _process_session(
                sess,
                out_dir,
                rank_counter=rank_counter,
                loss_counter=loss_counter,
                eq_bins=eq_bins,
                tier_stats=tier_stats,
                aggregate=aggregate,
                merged_decisions=merged,
            )
            if args.write_debug_summary:
                try:
                    sw = SummaryWriter(Path(args.debug_dir), sess.bot_name)
                    sw.write(sess.room_id, sess.run_id, sess.rankings)
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] debug summary write failed: {e}")

    aggregate["rank_distribution"] = dict(rank_counter)
    aggregate["loss_cause_distribution"] = dict(loss_counter)
    aggregate["equity_bin_outcome"] = {k: dict(v) for k, v in eq_bins.items()}
    aggregate["opp_tier_accuracy"] = tier_stats

    agg_path = out_dir / "aggregate.json"
    _atomic_write_json(agg_path, aggregate)
    print(f"[wrote] {agg_path}")
    return 0


def _process_session(
    sess: Session,
    out_dir: Path,
    *,
    rank_counter: Counter,
    loss_counter: Counter,
    eq_bins: dict[str, Counter[str]],
    tier_stats: dict[str, dict[str, int]],
    aggregate: dict[str, Any],
    merged_decisions: int,
) -> None:
    bot_name = sess.bot_name
    rank = _my_rank(sess, bot_name)
    if rank is not None:
        rank_counter[rank] += 1

    loss_by_hand: list[tuple[int, LossCause | None]] = []
    for hand in sess.hands:
        cause = classify_loss(hand, bot_name)
        loss_by_hand.append((hand.hand_number, cause))
        if cause is not None:
            loss_counter[cause] += 1
        _update_equity_bins(hand, bot_name, eq_bins)
        _update_tier_stats(hand, bot_name, tier_stats)

    md_path = out_dir / f"session_{sess.room_id}_{sess.run_id}.md"
    md = _render_session_md(sess, bot_name, loss_by_hand, merged_decisions)
    md_path.write_text(md, encoding="utf-8")
    print(f"[wrote] {md_path}")

    aggregate["sessions"] += 1
    aggregate["per_session"].append({
        "room_id": sess.room_id,
        "run_id": sess.run_id,
        "total_hands": len(sess.hands),
        "final_rank": rank,
        "ended": sess.ended,
        "loss_causes": {
            c: sum(1 for _, cc in loss_by_hand if cc == c)
            for c in set(cc for _, cc in loss_by_hand if cc)
        },
    })


def _my_rank(sess: Session, bot_name: str) -> int | None:
    for r in sess.rankings:
        if isinstance(r, dict) and r.get("name") == bot_name:
            return r.get("rank")
    return None


def _update_equity_bins(
    hand: HandRecord, bot_name: str, eq_bins: dict[str, Counter[str]]
) -> None:
    in_sd = my_in_showdown(hand, bot_name)
    if not in_sd:
        return
    outcome = "won" if my_won_hand(hand, bot_name) else "lost"
    for dec in hand.my_actions:
        meta = dec.meta or {}
        eq = meta.get("equity")
        if eq is None:
            continue
        try:
            ef = float(eq)
        except (TypeError, ValueError):
            continue
        bin_key = _bin_equity(ef)
        eq_bins.setdefault(bin_key, Counter())[outcome] += 1


def _bin_equity(eq: float) -> str:
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
    for i in range(len(edges) - 1):
        if edges[i] <= eq < edges[i + 1]:
            return f"{edges[i]:.1f}-{edges[i + 1]:.1f}"
    return "?"


def _update_tier_stats(
    hand: HandRecord, bot_name: str, tier_stats: dict[str, dict[str, int]]
) -> None:
    in_sd = my_in_showdown(hand, bot_name)
    won = my_won_hand(hand, bot_name)
    for dec in hand.my_actions:
        meta = dec.meta or {}
        tier = meta.get("opp_tier")
        if not tier:
            continue
        tier = str(tier)
        bucket = tier_stats.setdefault(
            tier,
            {"call_or_raise_n": 0, "showdown_n": 0, "showdown_won_n": 0},
        )
        if dec.action in ("call", "raise", "allin"):
            bucket["call_or_raise_n"] += 1
        if in_sd:
            bucket["showdown_n"] += 1
            if won:
                bucket["showdown_won_n"] += 1


def _render_session_md(
    sess: Session,
    bot_name: str,
    loss_by_hand: list[tuple[int, LossCause | None]],
    merged_decisions: int,
) -> str:
    rank = _my_rank(sess, bot_name)
    total = len(sess.hands)
    participated = sum(1 for h in sess.hands if h.my_actions)
    sd_total = sum(1 for h in sess.hands if my_in_showdown(h, bot_name))
    sd_won = sum(1 for h in sess.hands if my_won_hand(h, bot_name) and my_in_showdown(h, bot_name))
    elim_hand = next(
        (h for h in sess.hands if bot_name in h.eliminated), None
    )

    lines: list[str] = []
    lines.append(f"# Session {sess.room_id} — {sess.run_id}")
    lines.append("")
    lines.append(f"- Bot: **{bot_name}**")
    lines.append(f"- Total hands: {total} / Participated: {participated}")
    lines.append(f"- Showdowns: {sd_total} / Won: {sd_won}")
    lines.append(f"- Final rank: {rank if rank is not None else '—'}")
    lines.append(f"- Rankings: {_format_rankings(sess.rankings)}")
    lines.append(f"- Merged decisions (logs/decisions.jsonl fallback): {merged_decisions}")
    lines.append(f"- Ended cleanly (game_end received): {sess.ended}")
    lines.append("")
    lines.append("## 패배 원인 분포")
    cause_counter: Counter[str] = Counter()
    for _, c in loss_by_hand:
        if c is not None:
            cause_counter[c] += 1
    if cause_counter:
        lines.append("")
        lines.append("| cause | count |")
        lines.append("| --- | ---:|")
        for cause, n in cause_counter.most_common():
            lines.append(f"| {cause} | {n} |")
    else:
        lines.append("(no losses classified — 전부 승이거나 미참여)")
    lines.append("")

    # 탈락 상세
    if elim_hand is not None:
        lines.append("## 탈락 핸드 상세")
        lines.append("")
        lines.append(f"- Hand #{elim_hand.hand_number}")
        lines.append(f"- My cards: {_fmt_cards(elim_hand.your_cards)}")
        lines.append(f"- Board: {_fmt_cards(elim_hand.board_final)}")
        lines.append(f"- Start stack: {elim_hand.start_stack}, blind: {elim_hand.blind}")
        sd_lines = _format_showdown(elim_hand, bot_name)
        if sd_lines:
            lines.append("- Showdown:")
            for s in sd_lines:
                lines.append(f"  - {s}")
        lines.append("- My actions:")
        for d in elim_hand.my_actions:
            meta = d.meta or {}
            reason = meta.get("reason") or ""
            eq = meta.get("equity")
            tier = meta.get("opp_tier") or ""
            lines.append(
                f"  - {d.phase}: {d.action} {d.amount or ''}"
                f" (to_call={d.to_call} pot={d.pot} eq={eq} tier={tier} reason={reason})"
            )
        lines.append(
            f"- 분류: **{next((c for hn, c in loss_by_hand if hn == elim_hand.hand_number), 'unknown')}**"
        )
        lines.append("")

    # 최근 20 핸드 액션 히스토리
    lines.append("## 최근 20 핸드")
    lines.append("")
    lines.append("| # | cards | seat | start | end | participated | sd | result | cause |")
    lines.append("| ---:| --- | --- | ---:| ---:| --- | --- | --- | --- |")
    recent = sess.hands[-20:]
    cause_map = dict(loss_by_hand)
    for h in recent:
        participated_s = "Y" if h.my_actions else "-"
        sd_s = "Y" if my_in_showdown(h, bot_name) else "-"
        won = my_won_hand(h, bot_name)
        eliminated = bot_name in h.eliminated
        result = "WIN" if won else ("BUST" if eliminated else "LOSE")
        cause = cause_map.get(h.hand_number) or ""
        lines.append(
            f"| {h.hand_number} | {_fmt_cards(h.your_cards)} | {h.your_seat} |"
            f" {h.start_stack} | {h.end_stack} | {participated_s} | {sd_s} |"
            f" {result} | {cause} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_rankings(rankings: list[dict[str, Any]]) -> str:
    if not rankings:
        return "(none)"
    parts = []
    for r in rankings:
        if not isinstance(r, dict):
            continue
        parts.append(f"{r.get('rank')}:{r.get('name')}({r.get('chips')})")
    return ", ".join(parts)


def _fmt_cards(cards: list[str]) -> str:
    return " ".join(cards) if cards else "—"


def _format_showdown(hand: HandRecord, bot_name: str) -> list[str]:
    from holdem_core.hand_eval import classify_hand as _classify

    out: list[str] = []
    for s in hand.showdown:
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        cards = s.get("cards") or []
        made = ""
        if len(cards) >= 2 and len(hand.board_final) >= 3:
            try:
                c = _classify(list(cards) + list(hand.board_final))
                made = f" ({c.get('category')})"
            except Exception:  # noqa: BLE001
                pass
        marker = " *" if name == bot_name else ""
        out.append(f"{name}{marker}: {_fmt_cards(list(cards))}{made}")
    return out


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(tmp, path)


if __name__ == "__main__":
    raise SystemExit(main())
