"""J.4 — 4-class typing EDA (TAG/LAG/NIT/Fish).

15 LLM 모델별로 (VPIP, PFR, AF) 를 집계 → VPIP/AF 평면에서
K-Means(k=4) 및 GMM(4 comp) fit → centroid·경계·silhouette 산출.

산출:
- data/player_stats.csv           : 플레이어별 aggregate
- data/class_typing_report.json   : 클러스터 중심·경계·soft assignment

BOT_GUIDE compliance:
- §4 (position): HU 라 포지션은 SB/BB 두 가지. 프리플롭 VPIP/PFR 계산 시
  SB(=button in HU)·BB 집계는 각각 분리하여 저장.
- §5.3 action_request: AF = (bet+raise)/call 로 정의. street 무관 합산.

실행:
  uv run python scripts/class_typing_eda.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "poker"
OUT_DIR = Path(__file__).parent.parent / "data"

RE_EPISODE = re.compile(r'^# (\{.*\})$')
RE_SEAT = re.compile(r"Seat (\d+): (.+?) \((\d+) in chips\)")
RE_BLIND = re.compile(r"(.+?): posts (small|big) blind (\d+)")
RE_ACTION = re.compile(
    r"^(.+?): (folds|checks|calls|bets|raises)(?:\s+(\d+)(?:\s+to\s+(\d+))?)?$"
)
RE_STREET = re.compile(r"\*\*\* (FLOP|TURN|RIVER|SHOWDOWN|SHOW DOWN|SUMMARY) \*\*\*")


def iter_hands(raw_dir: Path):
    """모든 핸드 yield. {name, street, action, amount, raise_to, blinds_by_name}."""
    files = sorted(raw_dir.glob("*.txt"))
    for fp in files:
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        i = 0
        current = None
        current_street = "preflop"
        while i < len(lines):
            line = lines[i]
            m = RE_EPISODE.match(line)
            if m:
                if current is not None:
                    yield current
                current = {"blinds": {}, "actions": [], "matchup": fp.stem}
                current_street = "preflop"
                i += 1
                continue
            if current is None:
                i += 1
                continue

            mst = RE_STREET.match(line)
            if mst:
                s = mst.group(1).lower()
                if s in ("flop", "turn", "river"):
                    current_street = s
                elif s in ("showdown", "show down", "summary"):
                    pass
                i += 1
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
                    "amount": int(ma.group(3)) if ma.group(3) else None,
                    "raise_to": int(ma.group(4)) if ma.group(4) else None,
                })

            i += 1

        if current is not None:
            yield current


def aggregate_stats():
    """플레이어별 VPIP, PFR, AF 집계.

    VPIP: 프리플롭에서 폴드·체크 외 액션을 한 비율 (call/bet/raise).
          HU 의 경우 BB 가 무액션 check 하면 VPIP 아님.
    PFR : 프리플롭에서 raises 를 한 비율.
    AF  : 전체 스트리트에서 (bets+raises) / calls. 0/0 → None.
    """
    per_player = defaultdict(lambda: {
        "hands": 0,
        "vpip_hits": 0,
        "pfr_hits": 0,
        "bets": 0,
        "raises": 0,
        "calls": 0,
        "folds": 0,
        "checks": 0,
        "preflop_hands_as_sb": 0,
        "preflop_hands_as_bb": 0,
        "vpip_as_sb": 0,
        "vpip_as_bb": 0,
        "pfr_as_sb": 0,
        "pfr_as_bb": 0,
    })

    for hand in iter_hands(RAW_DIR):
        players = list(hand["blinds"].keys())
        if len(players) < 2:
            continue

        # 프리플롭 첫 voluntary action 여부
        pf_voluntary = set()  # 폴드/체크 아닌 첫 액션
        pf_raised = set()
        for a in hand["actions"]:
            if a["street"] != "preflop":
                continue
            p = a["player"]
            act = a["action"]
            if act in ("calls", "bets", "raises") and p not in pf_voluntary:
                pf_voluntary.add(p)
            if act == "raises":
                pf_raised.add(p)

        for p in players:
            per_player[p]["hands"] += 1
            blind = hand["blinds"].get(p)
            if blind == "small":
                per_player[p]["preflop_hands_as_sb"] += 1
                if p in pf_voluntary: per_player[p]["vpip_as_sb"] += 1
                if p in pf_raised:    per_player[p]["pfr_as_sb"] += 1
            elif blind == "big":
                per_player[p]["preflop_hands_as_bb"] += 1
                if p in pf_voluntary: per_player[p]["vpip_as_bb"] += 1
                if p in pf_raised:    per_player[p]["pfr_as_bb"] += 1
            if p in pf_voluntary:
                per_player[p]["vpip_hits"] += 1
            if p in pf_raised:
                per_player[p]["pfr_hits"] += 1

        # 액션 카운터
        for a in hand["actions"]:
            p = a["player"]
            act = a["action"]
            if act == "folds": per_player[p]["folds"] += 1
            elif act == "checks": per_player[p]["checks"] += 1
            elif act == "calls": per_player[p]["calls"] += 1
            elif act == "bets": per_player[p]["bets"] += 1
            elif act == "raises": per_player[p]["raises"] += 1

    stats = {}
    for p, v in per_player.items():
        n = v["hands"]
        if n == 0:
            continue
        vpip = v["vpip_hits"] / n
        pfr = v["pfr_hits"] / n
        af = ((v["bets"] + v["raises"]) / v["calls"]) if v["calls"] > 0 else None
        stats[p] = {
            "hands": n,
            "VPIP": round(vpip, 4),
            "PFR": round(pfr, 4),
            "AF": round(af, 4) if af is not None else None,
            "VPIP_SB": round(v["vpip_as_sb"] / v["preflop_hands_as_sb"], 4)
                       if v["preflop_hands_as_sb"] else None,
            "VPIP_BB": round(v["vpip_as_bb"] / v["preflop_hands_as_bb"], 4)
                       if v["preflop_hands_as_bb"] else None,
            "PFR_SB":  round(v["pfr_as_sb"] / v["preflop_hands_as_sb"], 4)
                       if v["preflop_hands_as_sb"] else None,
            "PFR_BB":  round(v["pfr_as_bb"] / v["preflop_hands_as_bb"], 4)
                       if v["preflop_hands_as_bb"] else None,
            "bets": v["bets"],
            "raises": v["raises"],
            "calls": v["calls"],
            "folds": v["folds"],
            "checks": v["checks"],
        }
    return stats


def cluster_players(stats: dict, min_hands: int = 500):
    """K-Means & GMM 둘 다 fit. Silhouette 기록."""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.mixture import GaussianMixture
    from sklearn.metrics import silhouette_score

    eligible = {p: s for p, s in stats.items()
                if s["hands"] >= min_hands and s["AF"] is not None}
    if len(eligible) < 4:
        return {"error": f"too few eligible players: {len(eligible)}"}

    names = list(eligible.keys())
    # (VPIP, PFR, AF) — AF 는 분포가 우편향이라 log 변환.
    X = np.array([[eligible[n]["VPIP"], eligible[n]["PFR"],
                   np.log1p(eligible[n]["AF"])] for n in names])

    k = min(4, len(names))
    km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
    km_labels = km.labels_
    km_sil = silhouette_score(X, km_labels) if len(set(km_labels)) > 1 else None

    gmm = GaussianMixture(n_components=k, covariance_type="full",
                          random_state=42, reg_covar=1e-4).fit(X)
    gmm_labels = gmm.predict(X)
    gmm_probs = gmm.predict_proba(X)
    gmm_sil = silhouette_score(X, gmm_labels) if len(set(gmm_labels)) > 1 else None

    # centroid → TAG/LAG/NIT/Fish 이름 붙이기 (경계 규칙)
    def label(vpip, pfr, af):
        # NIT: tight-passive, TAG: tight-aggressive, LAG: loose-aggressive, Fish: loose-passive
        tight = vpip < 0.30
        aggressive = af > 1.5
        if tight and aggressive: return "TAG"
        if tight and not aggressive: return "NIT"
        if not tight and aggressive: return "LAG"
        return "Fish"

    km_centroid_labels = []
    for c in km.cluster_centers_:
        vpip, pfr, laf = c
        af = float(np.expm1(laf))
        km_centroid_labels.append({
            "centroid": {"VPIP": float(vpip), "PFR": float(pfr), "AF": af},
            "class": label(vpip, pfr, af),
        })

    gmm_centroid_labels = []
    for mu, cov in zip(gmm.means_, gmm.covariances_):
        vpip, pfr, laf = mu
        af = float(np.expm1(laf))
        gmm_centroid_labels.append({
            "centroid": {"VPIP": float(vpip), "PFR": float(pfr), "AF": af},
            "class": label(vpip, pfr, af),
            "covariance_trace": float(np.trace(cov)),
        })

    players_out = []
    for i, n in enumerate(names):
        players_out.append({
            "name": n,
            "hands": eligible[n]["hands"],
            "VPIP": eligible[n]["VPIP"],
            "PFR": eligible[n]["PFR"],
            "AF": eligible[n]["AF"],
            "km_cluster": int(km_labels[i]),
            "km_class": km_centroid_labels[km_labels[i]]["class"],
            "gmm_cluster": int(gmm_labels[i]),
            "gmm_class": gmm_centroid_labels[gmm_labels[i]]["class"],
            "gmm_probs": {f"cluster_{j}": float(gmm_probs[i, j]) for j in range(k)},
            "gmm_soft_max_prob": float(gmm_probs[i].max()),
        })

    boundary_ratio = sum(1 for pl in players_out if pl["gmm_soft_max_prob"] < 0.7) / len(players_out)

    return {
        "n_players_clustered": len(names),
        "min_hands": min_hands,
        "kmeans": {
            "silhouette": km_sil,
            "centroids": km_centroid_labels,
        },
        "gmm": {
            "silhouette": gmm_sil,
            "centroids": gmm_centroid_labels,
            "boundary_ratio_lt_0.7": boundary_ratio,
        },
        "players": players_out,
    }


def main():
    min_hands = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    print(f"Aggregating stats from {RAW_DIR}")
    stats = aggregate_stats()
    print(f"Players aggregated: {len(stats)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    import csv
    out_csv = OUT_DIR / "player_stats.csv"
    if stats:
        sample = next(iter(stats.values()))
        with out_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name"] + list(sample.keys()))
            for name, s in sorted(stats.items(), key=lambda x: -x[1]["hands"]):
                w.writerow([name] + [s[k] for k in sample.keys()])
    print(f"Wrote {out_csv}")

    print("Clustering...")
    cluster = cluster_players(stats, min_hands=min_hands)
    out_json = OUT_DIR / "class_typing_report.json"
    out_json.write_text(json.dumps({
        "min_hands_threshold": min_hands,
        "total_players_aggregated": len(stats),
        "cluster_result": cluster,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"Wrote {out_json}")

    if "error" in cluster:
        print("ERROR:", cluster["error"])
        return
    print(f"K-Means silhouette = {cluster['kmeans']['silhouette']}")
    print(f"GMM     silhouette = {cluster['gmm']['silhouette']}")
    print(f"GMM boundary ratio (prob<0.7) = {cluster['gmm']['boundary_ratio_lt_0.7']:.2%}")
    for i, c in enumerate(cluster["kmeans"]["centroids"]):
        c_ = c["centroid"]
        print(f"  KM cluster {i} → {c['class']:4s} VPIP={c_['VPIP']:.2f} PFR={c_['PFR']:.2f} AF={c_['AF']:.2f}")


if __name__ == "__main__":
    main()
