"""J.8 — 수렴 속도 분석.

각 플레이어에 대해 **처음 N 핸드** 로 추정한 VPIP/PFR/AF 와
**전체 핸드** 기준 값의 오차 (|estimate(N) - final|) 평균을 구한다.
이 결과로 `n_effective` 경계 {10, 30, 80, 150, 400} 의 의미를 실증한다.

산출:
- data/convergence_report.json

BOT_GUIDE compliance:
- §1.1 봇 이름 고정: player 식별자는 영속. 누적 통계가 세션을 넘어 유효.
- §5.3/5.4: VPIP/PFR/AF 정의는 action_request/action_performed 이벤트로 동일 계산 가능.

실행:
  uv run python scripts/convergence_speed.py
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "poker"
OUT = Path(__file__).parent.parent / "data" / "convergence_report.json"

RE_EPISODE = re.compile(r'^# (\{.*\})$')
RE_BLIND = re.compile(r"(.+?): posts (small|big) blind (\d+)")
RE_ACTION = re.compile(
    r"^(.+?): (folds|checks|calls|bets|raises)(?:\s+(\d+)(?:\s+to\s+(\d+))?)?$"
)
RE_STREET = re.compile(r"\*\*\* (FLOP|TURN|RIVER|SHOWDOWN|SHOW DOWN|SUMMARY) \*\*\*")

CHECKPOINTS = [10, 20, 30, 50, 80, 120, 150, 200, 300, 400, 600, 1000, 2000, 5000]


def iter_hands(raw_dir: Path):
    """Deterministic order: file sorted, hand in-file order."""
    files = sorted(raw_dir.glob("*.txt"))
    for fp in files:
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        current = None
        current_street = "preflop"
        for line in lines:
            m = RE_EPISODE.match(line)
            if m:
                if current is not None:
                    yield current
                current = {"blinds": {}, "actions": []}
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


def compute_convergence():
    # per-player cumulative counters
    cum = defaultdict(lambda: {
        "hands": 0,
        "vpip_hits": 0,
        "pfr_hits": 0,
        "bets": 0,
        "raises": 0,
        "calls": 0,
        # snapshots at each checkpoint
        "snapshots": {},  # N -> {VPIP, PFR, AF}
    })

    for hand in iter_hands(RAW_DIR):
        players = list(hand["blinds"].keys())
        if len(players) < 2:
            continue

        # voluntary / raised
        pf_voluntary = set()
        pf_raised = set()
        for a in hand["actions"]:
            if a["street"] != "preflop":
                continue
            p = a["player"]
            if a["action"] in ("calls", "bets", "raises") and p not in pf_voluntary:
                pf_voluntary.add(p)
            if a["action"] == "raises":
                pf_raised.add(p)

        # 액션 카운터
        action_tally = defaultdict(lambda: {"bets": 0, "raises": 0, "calls": 0})
        for a in hand["actions"]:
            act = a["action"]
            p = a["player"]
            if act in ("bets", "raises", "calls"):
                action_tally[p][act if act != "raises" else "raises"] += 1
                if act == "bets":
                    action_tally[p]["bets"] += 1

        # 업데이트
        for p in players:
            c = cum[p]
            c["hands"] += 1
            if p in pf_voluntary: c["vpip_hits"] += 1
            if p in pf_raised:    c["pfr_hits"] += 1
            c["bets"] += action_tally[p]["bets"]
            c["raises"] += action_tally[p]["raises"]
            c["calls"] += action_tally[p]["calls"]

            # 체크포인트 도달 시 snapshot
            if c["hands"] in CHECKPOINTS:
                af = ((c["bets"] + c["raises"]) / c["calls"]) if c["calls"] > 0 else None
                c["snapshots"][c["hands"]] = {
                    "VPIP": c["vpip_hits"] / c["hands"],
                    "PFR":  c["pfr_hits"]  / c["hands"],
                    "AF":   af,
                    "bets": c["bets"],
                    "raises": c["raises"],
                    "calls": c["calls"],
                }

    # final values
    finals = {}
    for p, c in cum.items():
        if c["hands"] < 5000:
            continue
        af_final = ((c["bets"] + c["raises"]) / c["calls"]) if c["calls"] > 0 else None
        finals[p] = {
            "hands": c["hands"],
            "VPIP": c["vpip_hits"] / c["hands"],
            "PFR":  c["pfr_hits"]  / c["hands"],
            "AF":   af_final,
        }

    # per-checkpoint 오차 집계
    errors_by_n = {}
    for N in CHECKPOINTS:
        vpip_errs = []
        pfr_errs = []
        af_errs = []
        for p, f in finals.items():
            snap = cum[p]["snapshots"].get(N)
            if snap is None:
                continue
            vpip_errs.append(abs(snap["VPIP"] - f["VPIP"]))
            pfr_errs.append(abs(snap["PFR"] - f["PFR"]))
            if snap["AF"] is not None and f["AF"] is not None:
                # AF relative error (since AF unbounded)
                af_errs.append(abs(snap["AF"] - f["AF"]) / max(f["AF"], 0.5))

        if vpip_errs:
            errors_by_n[N] = {
                "n_players": len(vpip_errs),
                "VPIP": {
                    "mean_abs_error":   mean(vpip_errs),
                    "median_abs_error": median(vpip_errs),
                    "max_abs_error":    max(vpip_errs),
                },
                "PFR": {
                    "mean_abs_error":   mean(pfr_errs),
                    "median_abs_error": median(pfr_errs),
                    "max_abs_error":    max(pfr_errs),
                },
                "AF": {
                    "mean_rel_error":   mean(af_errs) if af_errs else None,
                    "median_rel_error": median(af_errs) if af_errs else None,
                    "max_rel_error":    max(af_errs) if af_errs else None,
                },
            }

    return {
        "checkpoints": CHECKPOINTS,
        "n_players_final": len(finals),
        "finals": finals,
        "per_player_snapshots": {p: c["snapshots"] for p, c in cum.items() if c["hands"] >= 5000},
        "errors_by_n": errors_by_n,
    }


def main():
    print(f"Scanning {RAW_DIR} ...")
    rep = compute_convergence()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    print(f"Wrote {OUT}")

    print(f"\nN_players with ≥5000 hands: {rep['n_players_final']}")
    print(f"\nAbsolute error vs final (mean across players):")
    print(f"{'N':>6} | {'n':>3} | VPIP mean/med/max | PFR mean/med/max | AF mean(rel)")
    for N, e in rep["errors_by_n"].items():
        vp = e["VPIP"]
        pf = e["PFR"]
        af = e["AF"]
        af_str = f"{af['mean_rel_error']:.3f}" if af['mean_rel_error'] is not None else "—"
        print(f"{N:>6} | {e['n_players']:>3} | {vp['mean_abs_error']:.3f}/{vp['median_abs_error']:.3f}/{vp['max_abs_error']:.3f}"
              f"   |   {pf['mean_abs_error']:.3f}/{pf['median_abs_error']:.3f}/{pf['max_abs_error']:.3f}"
              f"   |   {af_str}")


if __name__ == "__main__":
    main()
