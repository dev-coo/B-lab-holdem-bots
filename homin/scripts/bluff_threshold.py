"""J.7 — Bluff threshold 분석.

이 Kaggle LLM-vs-LLM 데이터셋은 `Dealt to` 블록에 **양쪽 플레이어의 홀 카드가 모두 공개**
되어 있다. 따라서 쇼다운 도달 여부와 무관하게 모든 베팅/레이즈 결정 시점에서
베터의 **true equity** 를 정확히 계산할 수 있다.

산출:
- data/bluff_decisions.{parquet,csv} : 결정별 레코드
- data/bluff_threshold_report.json   : 분위수·히스토그램·sizing 별 요약

BOT_GUIDE compliance:
- §3 카드 표기: 입력 `8c Ac` → treys `Card.new('8c')` 직접 호환.
- §6.2 raise amount = 라운드 총 베팅: `raises X to Y` 의 Y 를 라운드 총 베팅으로 해석.
  extra_bet = Y - 내 기존 round_bet.
- §5.3 action_request.pot: pot_before 는 이 액션 직전의 누적 팟 (uncalled 반환 전).

주의:
- 한쪽이 폴드하여 쇼다운 미도달 핸드도 포함한다. 폴드한 쪽의 "베팅/레이즈 결정"도
  equity 는 계산 가능 (Dealt to 로 양쪽 카드를 알고 있으므로).
- 프리플롭 equity 는 별도 LUT 가 필요해 이 스크립트에서는 제외 (eq=None 기록).

실행:
  uv run python scripts/bluff_threshold.py [max_files] [max_hands_per_file] [mc_samples]
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from treys import Card, Evaluator

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "poker"
OUT_DIR = Path(__file__).parent.parent / "data"

RE_EPISODE = re.compile(r'^# (\{.*\})$')
RE_SEAT = re.compile(r"Seat (\d+): (.+?) \((\d+) in chips\)")
RE_BUTTON = re.compile(r"Seat #(\d+) is the button")
RE_BLIND = re.compile(r"(.+?): posts (small|big) blind (\d+)")
RE_HOLE = re.compile(r"Dealt to (.+?) \[([A-Za-z0-9 ]+)\]")
RE_ACTION_FULL = re.compile(
    r"^(.+?): (folds|checks|calls|bets|raises)(?:\s+(\d+)(?:\s+to\s+(\d+))?)?$"
)
RE_STREET = re.compile(r"\*\*\* (FLOP|TURN|RIVER|SHOW DOWN|SUMMARY) \*\*\*(?:\s+\[([^\]]*)\])?(?:\s+\[([^\]]*)\])?")
RE_SHOW = re.compile(r"^(.+?): shows \[([A-Za-z0-9 ]+)\]")

EVAL = Evaluator()


def card_str_to_treys(c: str) -> int:
    """treys 는 Card.new('8c') 포맷. 입력도 동일."""
    return Card.new(c)


def equity_river(hero_cards: list[int], villain_cards: list[int],
                 board5: list[int]) -> float:
    """리버(5장 커뮤니티) — 정확."""
    h = EVAL.evaluate(board5, hero_cards)
    v = EVAL.evaluate(board5, villain_cards)
    if h < v: return 1.0  # lower is better in treys
    if h > v: return 0.0
    return 0.5


def equity_mc(hero_cards: list[int], villain_cards: list[int],
              board: list[int], mc_samples: int, rng: random.Random) -> float:
    """Flop/Turn — 남은 보드 카드 샘플링."""
    known = set(hero_cards) | set(villain_cards) | set(board)
    deck = [Card.new(r + s) for r in "23456789TJQKA" for s in "cdhs"
            if Card.new(r + s) not in known]
    need = 5 - len(board)
    if need == 0:
        return equity_river(hero_cards, villain_cards, board)
    wins = 0.0
    for _ in range(mc_samples):
        extra = rng.sample(deck, need)
        full_board = board + extra
        h = EVAL.evaluate(full_board, hero_cards)
        v = EVAL.evaluate(full_board, villain_cards)
        if h < v: wins += 1
        elif h == v: wins += 0.5
    return wins / mc_samples


def parse_hand(lines: list[str], start: int):
    """`# {...}` 로 시작하는 한 핸드 파싱. (hand|None, end_index) 반환."""
    m = RE_EPISODE.match(lines[start])
    if not m:
        return None, start + 1
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None, start + 1

    hand = {
        "meta": meta,
        "seats": {},
        "button_seat": None,
        "blinds": {},          # name -> amount
        "hole_cards": {},      # name -> [card str]
        "board_by_street": {"flop": [], "turn": [], "river": []},
        "actions": [],         # dicts {street, player, action, amount, raise_to}
        "showdown_cards": {},  # name -> [card str]
        "ended_street": "preflop",
    }

    i = start + 1
    current_street = "preflop"

    while i < len(lines):
        line = lines[i]
        if RE_EPISODE.match(line):
            break

        ms = RE_STREET.match(line)
        if ms:
            s = ms.group(1).lower()
            if s in ("flop", "turn", "river"):
                current_street = s
                hand["ended_street"] = s
                # 모든 [ ... ] 블록에서 카드 추출 (방어적 파싱).
                all_cards: list[str] = []
                for g in re.findall(r"\[([^\]]+)\]", line):
                    all_cards.extend(g.strip().split())
                if s == "flop" and len(all_cards) >= 3:
                    hand["board_by_street"]["flop"] = all_cards[:3]
                elif s == "turn" and len(all_cards) >= 4:
                    hand["board_by_street"]["turn"] = [all_cards[3]]
                elif s == "river" and len(all_cards) >= 5:
                    hand["board_by_street"]["river"] = [all_cards[4]]
            i += 1
            continue

        m_seat = RE_SEAT.match(line)
        if m_seat:
            seat, name, chips = int(m_seat.group(1)), m_seat.group(2).strip(), int(m_seat.group(3))
            hand["seats"][seat] = {"name": name, "stack": chips}

        m_btn = RE_BUTTON.search(line)
        if m_btn:
            hand["button_seat"] = int(m_btn.group(1))

        m_blind = RE_BLIND.match(line)
        if m_blind:
            name = m_blind.group(1).strip()
            hand["blinds"][name] = int(m_blind.group(3))

        m_hole = RE_HOLE.match(line)
        if m_hole:
            name = m_hole.group(1).strip()
            hand["hole_cards"][name] = m_hole.group(2).strip().split()

        m_act = RE_ACTION_FULL.match(line)
        if m_act:
            name = m_act.group(1).strip()
            act = m_act.group(2)
            amount = m_act.group(3)
            raise_to = m_act.group(4)
            hand["actions"].append({
                "street": current_street,
                "player": name,
                "action": act,
                "amount": int(amount) if amount else None,
                "raise_to": int(raise_to) if raise_to else None,
            })

        m_show = RE_SHOW.match(line)
        if m_show:
            name = m_show.group(1).strip()
            hand["showdown_cards"][name] = m_show.group(2).strip().split()

        i += 1

    return hand, i


def compute_decisions(hand: dict, mc_samples: int, rng: random.Random) -> list[dict]:
    """양쪽 홀 카드가 공개된 경우 각 베팅/레이즈 결정 시점의 true equity 계산."""
    # LLM-vs-LLM 데이터셋은 Dealt to 로 양쪽 카드를 모두 공개한다.
    if len(hand["hole_cards"]) < 2:
        return []

    hole_treys = {}
    for name, cards in hand["hole_cards"].items():
        try:
            hole_treys[name] = [card_str_to_treys(c) for c in cards]
        except Exception:
            return []

    board_cum = {"preflop": [], "flop": [], "turn": [], "river": []}
    flop = hand["board_by_street"]["flop"]
    turn = hand["board_by_street"]["turn"]
    river = hand["board_by_street"]["river"]
    try:
        board_cum["flop"] = [card_str_to_treys(c) for c in flop]
        board_cum["turn"] = board_cum["flop"] + [card_str_to_treys(c) for c in turn]
        board_cum["river"] = board_cum["turn"] + [card_str_to_treys(c) for c in river]
    except Exception:
        return []

    # 팟 추적 (SB+BB 부터 시작)
    pot = sum(hand["blinds"].values())
    # 라운드별 cumulative per-player bet
    round_bet: dict[str, int] = defaultdict(int)
    for name, amt in hand["blinds"].items():
        round_bet[name] = amt
    current_street = "preflop"

    records = []
    names = list(hole_treys.keys())
    if len(names) != 2:
        return []
    opp = {names[0]: names[1], names[1]: names[0]}

    for act in hand["actions"]:
        if act["street"] != current_street:
            # 스트리트 전환: round_bet 초기화, pot 는 누적 유지
            round_bet = defaultdict(int)
            current_street = act["street"]

        player = act["player"]
        atype = act["action"]

        if atype in ("folds", "checks"):
            continue

        if atype == "calls":
            call_amt = act["amount"] or 0
            round_bet[player] += call_amt
            pot += call_amt
            continue

        if atype in ("bets", "raises"):
            if player not in hole_treys:
                # 폴드된 플레이어의 베팅은 카드 공개 안 됨
                continue
            if atype == "bets":
                # amount = 이번 액션 베팅액
                amt = act["amount"] or 0
                extra = amt
                new_round_total = round_bet[player] + amt
            else:  # raises
                # PokerStars format: "raises X to Y" — Y 는 라운드 총 베팅
                raise_to = act["raise_to"] if act["raise_to"] is not None else act["amount"]
                if raise_to is None:
                    continue
                extra = raise_to - round_bet[player]
                new_round_total = raise_to

            # 결정 시점의 pot (이 액션 직전)
            pot_before = pot
            to_call_before = max(
                (round_bet[n] for n in names if n != player), default=0
            ) - round_bet[player]
            to_call_before = max(0, to_call_before)

            # equity 계산
            hero = hole_treys[player]
            villain_name = opp[player]
            if villain_name not in hole_treys:
                continue
            villain = hole_treys[villain_name]
            board = board_cum.get(current_street, [])

            if current_street == "river":
                eq = equity_river(hero, villain, board)
            elif current_street == "preflop":
                # 프리플롭 MC — 5장 보드 샘플. 비용 크므로 제외(별도 LUT 로).
                eq = None
            else:
                eq = equity_mc(hero, villain, board, mc_samples, rng)

            records.append({
                "street": current_street,
                "action": atype,
                "extra_bet": extra,
                "pot_before": pot_before,
                "bet_to_pot": extra / pot_before if pot_before else None,
                "to_call_before": to_call_before,
                "equity": eq,
                "is_aggressive": True,
            })

            round_bet[player] = new_round_total
            pot += extra

    return records


def iter_hands(raw_dir: Path, max_files: int | None, max_hands_per_file: int | None):
    files = sorted(raw_dir.glob("*.txt"))
    if max_files:
        files = files[:max_files]
    for fp in files:
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        i = 0
        scanned = 0
        while i < len(lines):
            if not RE_EPISODE.match(lines[i]):
                i += 1
                continue
            hand, nxt = parse_hand(lines, i)
            i = nxt
            if hand is None:
                continue
            scanned += 1
            if max_hands_per_file and scanned > max_hands_per_file:
                break
            yield hand, fp.stem


def summarize(records: list[dict]) -> dict:
    """분위수·히스토그램·street 별 agg."""
    by_street: dict[str, list[float]] = defaultdict(list)
    for r in records:
        if r["equity"] is None:
            continue
        by_street[r["street"]].append(r["equity"])

    def quantiles(xs: list[float]) -> dict:
        if not xs:
            return {}
        xs = sorted(xs)
        n = len(xs)
        def q(p): return xs[min(n - 1, int(p * n))]
        return {
            "n": n,
            "mean": sum(xs) / n,
            "p10": q(0.10), "p25": q(0.25), "p50": q(0.50),
            "p75": q(0.75), "p90": q(0.90),
            "bluff_<0.30": sum(1 for x in xs if x < 0.30) / n,
            "bluff_<0.40": sum(1 for x in xs if x < 0.40) / n,
            "value_>0.60": sum(1 for x in xs if x > 0.60) / n,
            "value_>0.70": sum(1 for x in xs if x > 0.70) / n,
        }

    report = {
        "total_records": len(records),
        "records_with_equity": sum(1 for r in records if r["equity"] is not None),
        "by_street": {s: quantiles(xs) for s, xs in by_street.items()},
        "histogram_bins": {},
    }

    # 히스토그램 (20 bins over [0,1])
    for s, xs in by_street.items():
        bins = [0] * 20
        for x in xs:
            b = min(19, int(x * 20))
            bins[b] += 1
        report["histogram_bins"][s] = bins

    # bet_to_pot 별 equity 평균 (aggressive action 만)
    buckets = defaultdict(list)
    for r in records:
        if r["equity"] is None or r["bet_to_pot"] is None:
            continue
        bp = r["bet_to_pot"]
        if bp < 0.33: k = "tiny(<0.33)"
        elif bp < 0.55: k = "half(0.33-0.55)"
        elif bp < 0.85: k = "two-thirds(0.55-0.85)"
        elif bp < 1.25: k = "pot(0.85-1.25)"
        elif bp < 2.0: k = "overbet(1.25-2.0)"
        else: k = "huge(>=2.0)"
        buckets[k].append(r["equity"])
    report["by_sizing"] = {
        k: {"n": len(v), "mean_eq": sum(v)/len(v),
            "pct_bluff_lt0.4": sum(1 for x in v if x < 0.4)/len(v)}
        for k, v in buckets.items()
    }

    # θ_bluff 제안: river 분포의 p10~p15 영역의 bend point
    river = by_street.get("river", [])
    if river:
        river_sorted = sorted(river)
        n = len(river_sorted)
        report["theta_suggestion"] = {
            "river_p10": river_sorted[int(0.10 * n)],
            "river_p15": river_sorted[int(0.15 * n)],
            "river_p20": river_sorted[int(0.20 * n)],
            "river_p80": river_sorted[int(0.80 * n)],
            "river_p85": river_sorted[int(0.85 * n)],
            "river_p90": river_sorted[int(0.90 * n)],
        }

    return report


def write_parquet_or_csv(records: list[dict], out_base: Path):
    """parquet 있으면 parquet, 아니면 csv."""
    try:
        import pandas as pd  # noqa
        df = pd.DataFrame(records)
        df.to_parquet(out_base.with_suffix(".parquet"), index=False)
        return out_base.with_suffix(".parquet")
    except Exception:
        import csv
        path = out_base.with_suffix(".csv")
        if not records:
            path.write_text("")
            return path
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            w.writeheader()
            w.writerows(records)
        return path


def main():
    # 0 또는 음수 → 전체 (None).
    def _as_opt(idx, default=None):
        if len(sys.argv) > idx:
            v = int(sys.argv[idx])
            return None if v <= 0 else v
        return default
    max_files = _as_opt(1)
    max_per = _as_opt(2)
    mc_samples = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    print(f"Scanning {RAW_DIR} max_files={max_files} max_per={max_per} mc={mc_samples}")
    rng = random.Random(42)

    all_records: list[dict] = []
    total_hands = 0
    showdown_hands = 0

    for hand, stem in iter_hands(RAW_DIR, max_files, max_per):
        total_hands += 1
        if hand["showdown_cards"]:
            showdown_hands += 1
        recs = compute_decisions(hand, mc_samples, rng)
        for r in recs:
            r["matchup"] = stem
        all_records.extend(recs)
        if total_hands % 20000 == 0:
            print(f"  scanned={total_hands} showdown={showdown_hands} recs={len(all_records)}")

    print(f"Done. total_hands={total_hands} showdown={showdown_hands} records={len(all_records)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_data = write_parquet_or_csv(all_records, OUT_DIR / "bluff_decisions")
    print(f"Wrote records: {out_data}")

    report = summarize(all_records)
    report["total_hands_scanned"] = total_hands
    report["showdown_hands"] = showdown_hands
    report["mc_samples_used"] = mc_samples
    out_json = OUT_DIR / "bluff_threshold_report.json"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"Wrote report: {out_json}")

    for s, q in report["by_street"].items():
        print(f"  [{s}] n={q['n']} mean={q['mean']:.3f} p25={q['p25']:.3f} p50={q['p50']:.3f} p75={q['p75']:.3f}")
    if "theta_suggestion" in report:
        print(f"  theta suggestion: {report['theta_suggestion']}")


if __name__ == "__main__":
    main()
