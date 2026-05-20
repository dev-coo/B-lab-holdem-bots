"""Kaggle poker-heads-up 데이터셋 inspection — J.1.a gate.

Scans raw hand-history text files and produces dataset_report.json with:
- game type (NLHE/LHE), heads-up confirmation
- total hand count
- per-model hand counts and win rates
- action vocabulary
- showdown ratio (ground truth for bluff threshold tuning)
- bet sizing distribution (sanity check)
- card notation sample

BOT_GUIDE compliance (research/bot_guide_extracts.md):
- §5 (cards): `[Ah Kh]` → normalize to `Ah, Kh`
- §8.2 (actions): fold/check/call/raise/allin vocabulary must subset
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "poker"
OUT_PATH = Path(__file__).parent.parent / "data" / "dataset_report.json"

RE_EPISODE = re.compile(r'^# (\{.*\})$')
RE_STAKES = re.compile(r"Hold'em (No Limit|Limit) \(\$(\d+)/\$(\d+)\)")
RE_SEAT = re.compile(r"Seat (\d+): (.+?) \((\d+) in chips\)")
RE_BUTTON = re.compile(r"Seat #(\d+) is the button")
RE_BLIND = re.compile(r"(.+?): posts (small|big) blind (\d+)")
RE_HOLE = re.compile(r"Dealt to (.+?) \[([A-Za-z0-9 ]+)\]")
RE_ACTION = re.compile(
    r"(.+?): (folds|checks|calls|bets|raises|mucks)(?:\s+(\d+)(?:\s+to\s+(\d+))?)?"
)
RE_STREET = re.compile(r"\*\*\* (FLOP|TURN|RIVER|SHOW DOWN|SUMMARY) \*\*\*")
RE_SHOW = re.compile(r"(.+?): shows \[([A-Za-z0-9 ]+)\]")
RE_COLLECT = re.compile(r"(.+?) collected ([\d.]+) from pot")
RE_UNCALLED = re.compile(r"Uncalled bet \((\d+)\) returned to (.+)")


def parse_file(path: Path):
    """Yield dicts describing each hand in file."""
    current = None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = RE_EPISODE.match(line)
        if m:
            if current is not None:
                yield current
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError:
                meta = {}
            current = {
                "meta": meta,
                "seats": {},  # seat# -> {name, stack}
                "button_seat": None,
                "blinds": {},  # name -> (type, amount)
                "stakes": None,
                "game_type": None,
                "hole_cards": {},  # name -> cards
                "board": [],  # cumulative
                "actions": [],  # ordered
                "streets_reached": ["preflop"],
                "showdown_cards": {},  # name -> cards
                "collected": {},  # name -> amount
                "uncalled_returned_to": None,
                "ended_street": "preflop",
            }
            i += 1
            continue
        if current is None:
            i += 1
            continue

        m = RE_STAKES.search(line)
        if m:
            current["game_type"] = m.group(1)
            current["stakes"] = (int(m.group(2)), int(m.group(3)))

        m = RE_BUTTON.search(line)
        if m:
            current["button_seat"] = int(m.group(1))

        m = RE_SEAT.match(line)
        if m:
            seat, name, chips = int(m.group(1)), m.group(2).strip(), int(m.group(3))
            current["seats"][seat] = {"name": name, "stack": chips}

        m = RE_BLIND.match(line)
        if m:
            name, blind_type, amount = m.group(1).strip(), m.group(2), int(m.group(3))
            current["blinds"][name] = (blind_type, amount)

        m = RE_HOLE.match(line)
        if m:
            name = m.group(1).strip()
            cards = m.group(2).strip().split()
            current["hole_cards"][name] = cards

        m = RE_STREET.match(line)
        if m:
            street = m.group(1).lower()
            if street in ("flop", "turn", "river"):
                current["streets_reached"].append(street)
                current["ended_street"] = street
                # extract community cards from remainder
                cards = re.findall(r"\[([A-Za-z0-9 ]+)\]", line)
                if cards:
                    all_cards = []
                    for c in cards:
                        all_cards.extend(c.strip().split())
                    current["board"] = all_cards

        m = RE_ACTION.match(line)
        if m:
            name = m.group(1).strip()
            act = m.group(2)
            amount = m.group(3)
            raise_to = m.group(4)
            current["actions"].append({
                "street": current["ended_street"],
                "player": name,
                "action": act,
                "amount": int(amount) if amount else None,
                "raise_to": int(raise_to) if raise_to else None,
            })

        m = RE_SHOW.match(line)
        if m:
            name = m.group(1).strip()
            cards = m.group(2).strip().split()
            current["showdown_cards"][name] = cards

        m = RE_COLLECT.match(line)
        if m:
            name = m.group(1).strip()
            amount = float(m.group(2))
            current["collected"][name] = amount

        m = RE_UNCALLED.search(line)
        if m:
            current["uncalled_returned_to"] = m.group(2).strip()

        i += 1

    if current is not None:
        yield current


def summarize(raw_dir: Path, max_files: int | None = None, max_hands_per_file: int | None = None):
    files = sorted(raw_dir.glob("*.txt"))
    if max_files:
        files = files[:max_files]

    report = {
        "dataset": "kaggle/poker-heads-up",
        "scanned_files": len(files),
        "total_hands": 0,
        "game_types": Counter(),
        "stakes_distribution": Counter(),
        "n_players_per_hand": Counter(),
        "player_names_unique": set(),
        "model_hand_counts": Counter(),
        "model_winnings": defaultdict(float),  # total collected
        "model_hand_participations": Counter(),
        "action_vocab": Counter(),
        "showdown_hand_count": 0,
        "streets_ended": Counter(),
        "preflop_fold_count": 0,
        "bet_sizes_relative_to_pot": [],
        "hole_card_format_samples": set(),
        "btn_seat_distribution": Counter(),
        "starting_stack_distribution": Counter(),
    }

    for fp in files:
        scanned = 0
        for hand in parse_file(fp):
            scanned += 1
            if max_hands_per_file and scanned > max_hands_per_file:
                break
            report["total_hands"] += 1
            report["game_types"][hand["game_type"]] += 1
            if hand["stakes"]:
                report["stakes_distribution"][str(hand["stakes"])] += 1
            n_players = len(hand["seats"])
            report["n_players_per_hand"][n_players] += 1
            report["btn_seat_distribution"][hand["button_seat"]] += 1
            for seat_info in hand["seats"].values():
                report["player_names_unique"].add(seat_info["name"])
                report["model_hand_participations"][seat_info["name"]] += 1
                report["starting_stack_distribution"][seat_info["stack"]] += 1
            for name, amt in hand["collected"].items():
                report["model_winnings"][name] += amt
            if hand["uncalled_returned_to"]:
                report["model_winnings"][hand["uncalled_returned_to"]] += 0  # noop
            for a in hand["actions"]:
                report["action_vocab"][a["action"]] += 1
            if hand["showdown_cards"]:
                report["showdown_hand_count"] += 1
            report["streets_ended"][hand["ended_street"]] += 1
            if hand["ended_street"] == "preflop":
                fold_preflop = any(a["action"] == "folds" and a["street"] == "preflop"
                                    for a in hand["actions"])
                if fold_preflop:
                    report["preflop_fold_count"] += 1
            for cards in hand["hole_cards"].values():
                for c in cards:
                    report["hole_card_format_samples"].add(c)
                    if len(report["hole_card_format_samples"]) > 30:
                        break

    # post-process
    report["player_names_unique"] = sorted(report["player_names_unique"])
    report["hole_card_format_samples"] = sorted(report["hole_card_format_samples"])
    report["game_types"] = dict(report["game_types"])
    report["stakes_distribution"] = dict(report["stakes_distribution"])
    report["n_players_per_hand"] = dict(report["n_players_per_hand"])
    report["model_hand_counts"] = dict(report["model_hand_counts"])
    report["model_winnings"] = {k: round(v, 2) for k, v in report["model_winnings"].items()}
    report["model_hand_participations"] = dict(report["model_hand_participations"])
    report["action_vocab"] = dict(report["action_vocab"])
    report["streets_ended"] = dict(report["streets_ended"])
    report["btn_seat_distribution"] = dict(report["btn_seat_distribution"])
    report["starting_stack_distribution"] = dict(report["starting_stack_distribution"])

    # derived
    report["derived"] = {
        "showdown_ratio": (report["showdown_hand_count"] / report["total_hands"]
                            if report["total_hands"] else 0),
        "preflop_end_ratio": (report["preflop_fold_count"] / report["total_hands"]
                                if report["total_hands"] else 0),
        "unique_models": len(report["player_names_unique"]),
    }

    # per-model BB winrate (heads-up, 200 stack, $1/$2 blinds → 1 BB = 2)
    bb_winnings = {}
    for model, wins in report["model_winnings"].items():
        hands = report["model_hand_participations"].get(model, 1)
        # this is total collected, not net profit. Real profit would need to
        # subtract the model's contributed bets. Use as rough proxy.
        bb_winnings[model] = {
            "total_collected": round(wins, 2),
            "hands_played": hands,
            "collected_per_hand": round(wins / hands, 4),
        }
    report["derived"]["model_rough_profit_proxy"] = bb_winnings

    return report


if __name__ == "__main__":
    max_files = int(sys.argv[1]) if len(sys.argv) > 1 else None
    max_per_file = int(sys.argv[2]) if len(sys.argv) > 2 else None
    print(f"Scanning {RAW_DIR} (max_files={max_files}, max_hands_per_file={max_per_file})")
    rep = summarize(RAW_DIR, max_files=max_files, max_hands_per_file=max_per_file)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    print(f"Wrote report to {OUT_PATH}")
    print(f"Total hands scanned: {rep['total_hands']}")
    print(f"Game types: {rep['game_types']}")
    print(f"Players per hand: {rep['n_players_per_hand']}")
    print(f"Showdown ratio: {rep['derived']['showdown_ratio']:.2%}")
    print(f"Preflop-end ratio: {rep['derived']['preflop_end_ratio']:.2%}")
    print(f"Unique models: {rep['derived']['unique_models']}")
    print(f"Action vocab: {rep['action_vocab']}")
