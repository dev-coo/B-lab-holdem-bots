"""J.3 — Population prior 집계.

CBET / FOLD_TO_CBET / BARREL_TURN / BARREL_RIVER / THREE_BET / FOLD_TO_THREE_BET
을 전체 2.06M 핸드에서 집계하여 Beta(α, β) prior 산출.

정의 (HU 기준):
- CBET: preflop aggressor 가 flop 에서 **맨 첫** 액션으로 bet 했는가.
- FOLD_TO_CBET: CBET 받은 쪽이 flop 에서 fold 했는가.
- BARREL_TURN: flop cbet 을 계속해서 turn 에서도 **맨 첫** 액션으로 bet 했는가.
- BARREL_RIVER: turn barrel 후 river 에서도 bet 했는가.
- THREE_BET: preflop 에서 상대의 open raise 에 대해 **re-raise** 로 응답한 비율.
- FOLD_TO_THREE_BET: 3bet 받은 원 raiser 가 fold 한 비율.

산출:
- data/population_prior_report.json
- Beta prior 로 α = hits + 1, β = tries - hits + 1 (Laplace smoothing).

BOT_GUIDE compliance:
- §5.3 action_request: action_history 의 누적. street 내 첫 액션자 = 공격 시도 시점.
- §5.4 action_performed: 각 액션이 독립 이벤트. 본 스크립트는 offline data 를 사용하나
  집계 논리는 서버의 실시간 이벤트 스트림과 동형.

실행:
  uv run python scripts/calc_population_prior.py [max_files]
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "poker"
OUT = Path(__file__).parent.parent / "data" / "population_prior_report.json"

RE_EPISODE = re.compile(r'^# (\{.*\})$')
RE_BLIND = re.compile(r"(.+?): posts (small|big) blind (\d+)")
RE_ACTION = re.compile(
    r"^(.+?): (folds|checks|calls|bets|raises)(?:\s+(\d+)(?:\s+to\s+(\d+))?)?$"
)
RE_STREET = re.compile(r"\*\*\* (FLOP|TURN|RIVER|SHOWDOWN|SHOW DOWN|SUMMARY) \*\*\*")


def iter_hands(raw_dir: Path, max_files: int | None = None):
    files = sorted(raw_dir.glob("*.txt"))
    if max_files:
        files = files[:max_files]
    for fp in files:
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        current = None
        current_street = "preflop"
        for line in lines:
            m = RE_EPISODE.match(line)
            if m:
                if current is not None:
                    yield current
                current = {"blinds": {}, "actions": [], "matchup": fp.stem}
                current_street = "preflop"
                continue
            if current is None:
                continue

            mst = RE_STREET.match(line)
            if mst:
                s = mst.group(1).lower()
                if s in ("flop", "turn", "river"):
                    current_street = s
                continue

            mb = RE_BLIND.match(line)
            if mb:
                current["blinds"][mb.group(1).strip()] = mb.group(2)

            ma = RE_ACTION.match(line)
            if ma:
                current["actions"].append({
                    "street": current_street,
                    "player": ma.group(1).strip(),
                    "action": ma.group(2),
                })
        if current is not None:
            yield current


def aggregate(raw_dir: Path, max_files: int | None):
    # tallies: key -> {tries, hits}
    tallies = defaultdict(lambda: {"tries": 0, "hits": 0})
    per_player = defaultdict(lambda: defaultdict(lambda: {"tries": 0, "hits": 0}))

    scanned = 0
    for hand in iter_hands(raw_dir, max_files):
        scanned += 1
        if scanned % 100000 == 0:
            print(f"  scanned={scanned}")

        acts = hand["actions"]
        blinds = hand["blinds"]
        if len(blinds) < 2:
            continue

        # street 별 action 분리
        by_street = defaultdict(list)
        for a in acts:
            by_street[a["street"]].append(a)

        # --- 1. PREFLOP: 3BET / FOLD_TO_3BET ---
        pf = by_street["preflop"]
        # preflop 의 raise 시퀀스. HU: SB 가 open, BB 가 3bet, SB 가 4bet ...
        raises = [a for a in pf if a["action"] == "raises"]
        if len(raises) >= 1:
            open_raiser = raises[0]["player"]
            # THREE_BET attempt = "open_raiser 가 아닌 다른 사람이 raise 기회가 있었는가"
            # HU 에서 raises[1] 가 있으면 3bet 성사
            # raise 기회는 open_raiser 의 open 을 본 모든 non-raiser 에게 있음
            other = [p for p in blinds.keys() if p != open_raiser]
            for p in other:
                tallies["THREE_BET"]["tries"] += 1
                per_player[p]["THREE_BET"]["tries"] += 1
                # p 가 3bet 했는지 확인: open_raiser 후 p 의 raises 액션 존재
                did_3bet = False
                for a in pf:
                    if a["player"] == p and a["action"] == "raises":
                        did_3bet = True
                        break
                if did_3bet:
                    tallies["THREE_BET"]["hits"] += 1
                    per_player[p]["THREE_BET"]["hits"] += 1

        if len(raises) >= 2:
            # 3bet 이 있었음. open_raiser 의 반응 = FOLD_TO_3BET
            open_raiser = raises[0]["player"]
            three_better = raises[1]["player"]
            tallies["FOLD_TO_THREE_BET"]["tries"] += 1
            per_player[open_raiser]["FOLD_TO_THREE_BET"]["tries"] += 1
            # 3bet 이후 open_raiser 의 첫 응답
            seen_3bet = False
            for a in pf:
                if a is raises[1]:
                    seen_3bet = True
                    continue
                if seen_3bet and a["player"] == open_raiser:
                    if a["action"] == "folds":
                        tallies["FOLD_TO_THREE_BET"]["hits"] += 1
                        per_player[open_raiser]["FOLD_TO_THREE_BET"]["hits"] += 1
                    break

        # --- 2. FLOP CBET / FOLD_TO_CBET ---
        # preflop aggressor = 마지막 raise 플레이어
        if not raises:
            continue
        pf_aggressor = raises[-1]["player"]
        pf_non_aggressor = [p for p in blinds.keys() if p != pf_aggressor]
        if not pf_non_aggressor:
            continue
        pfa_opp = pf_non_aggressor[0]

        flop = by_street.get("flop", [])
        if not flop:
            continue

        # CBET attempt: pf_aggressor 가 flop 에 참여 (일반적으로 둘 다 참여)
        tallies["CBET"]["tries"] += 1
        per_player[pf_aggressor]["CBET"]["tries"] += 1

        # CBET 발생 조건: flop 에서 pf_aggressor 가 **맨 첫** voluntary action 으로 bet.
        # HU 에서는 non-aggressor 가 먼저 act (OOP 라 가정). 만약 pf_aggressor 가 OOP
        # 면 첫 액션자. 둘 다 다루려면: pf_aggressor 가 flop 에서 첫 번째 `bets` 를 했는가.
        cbet_made = False
        first_flop_by_player = {}
        for a in flop:
            first_flop_by_player.setdefault(a["player"], a["action"])
            if a["player"] == pf_aggressor:
                # 첫 액션이 bet 이면 cbet.
                # non_aggressor 가 먼저 check 한 후 aggressor 가 bet 해도 cbet 인정.
                if a["action"] == "bets":
                    cbet_made = True
                break
        if cbet_made:
            tallies["CBET"]["hits"] += 1
            per_player[pf_aggressor]["CBET"]["hits"] += 1

            # FOLD_TO_CBET : opponent 의 응답이 fold
            tallies["FOLD_TO_CBET"]["tries"] += 1
            per_player[pfa_opp]["FOLD_TO_CBET"]["tries"] += 1
            seen_cbet = False
            for a in flop:
                if a["player"] == pf_aggressor and a["action"] == "bets" and not seen_cbet:
                    seen_cbet = True
                    continue
                if seen_cbet and a["player"] == pfa_opp:
                    if a["action"] == "folds":
                        tallies["FOLD_TO_CBET"]["hits"] += 1
                        per_player[pfa_opp]["FOLD_TO_CBET"]["hits"] += 1
                    break

        # --- 3. BARREL_TURN (cbet 이 있었고 turn 에 도달한 경우) ---
        if not cbet_made:
            continue
        # cbet 을 opponent 가 콜했으면 turn 진입. fold/raise 는 turn 진입 X.
        cbet_response = None
        seen_cbet2 = False
        for a in flop:
            if a["player"] == pf_aggressor and a["action"] == "bets" and not seen_cbet2:
                seen_cbet2 = True
                continue
            if seen_cbet2 and a["player"] == pfa_opp:
                cbet_response = a["action"]
                break
        if cbet_response != "calls":
            continue
        turn = by_street.get("turn", [])
        if not turn:
            continue

        tallies["BARREL_TURN"]["tries"] += 1
        per_player[pf_aggressor]["BARREL_TURN"]["tries"] += 1
        barrel_turn_made = False
        for a in turn:
            if a["player"] == pf_aggressor:
                if a["action"] == "bets":
                    barrel_turn_made = True
                break
        if barrel_turn_made:
            tallies["BARREL_TURN"]["hits"] += 1
            per_player[pf_aggressor]["BARREL_TURN"]["hits"] += 1

        # --- 4. BARREL_RIVER (turn barrel 이 있고 river 도달) ---
        if not barrel_turn_made:
            continue
        turn_response = None
        seen_turn = False
        for a in turn:
            if a["player"] == pf_aggressor and a["action"] == "bets" and not seen_turn:
                seen_turn = True
                continue
            if seen_turn and a["player"] == pfa_opp:
                turn_response = a["action"]
                break
        if turn_response != "calls":
            continue
        river = by_street.get("river", [])
        if not river:
            continue
        tallies["BARREL_RIVER"]["tries"] += 1
        per_player[pf_aggressor]["BARREL_RIVER"]["tries"] += 1
        for a in river:
            if a["player"] == pf_aggressor:
                if a["action"] == "bets":
                    tallies["BARREL_RIVER"]["hits"] += 1
                    per_player[pf_aggressor]["BARREL_RIVER"]["hits"] += 1
                break

    # Beta prior (Laplace smoothing)
    def to_beta(v):
        h, t = v["hits"], v["tries"]
        return {
            "tries": t,
            "hits": h,
            "rate": h / t if t > 0 else None,
            "alpha": h + 1,
            "beta": t - h + 1,
        }

    return {
        "scanned_hands": scanned,
        "population": {k: to_beta(v) for k, v in tallies.items()},
        "per_player": {
            p: {k: to_beta(v) for k, v in m.items() if v["tries"] >= 200}
            for p, m in per_player.items()
        },
    }


def main():
    max_files = int(sys.argv[1]) if len(sys.argv) > 1 and int(sys.argv[1]) > 0 else None
    print(f"Scanning {RAW_DIR} max_files={max_files}")
    rep = aggregate(RAW_DIR, max_files)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(f"Wrote {OUT}")

    print(f"\nPopulation rates:")
    for k, v in rep["population"].items():
        r = v["rate"]
        if r is not None:
            print(f"  {k:22s}  tries={v['tries']:9d}  rate={r:.4f}  Beta({v['alpha']}, {v['beta']})")


if __name__ == "__main__":
    main()
