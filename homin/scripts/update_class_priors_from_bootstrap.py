"""Bootstrap self-play 결과 → configs/class_priors.yaml 주입.

입력:
    data/bootstrap_results.json   (scripts/bootstrap_sim.py 산출)

출력:
    configs/class_priors.yaml     (in-place 업데이트, source 태그 갱신)
    configs/class_priors.bootstrap_backup.yaml (원본 백업)

매핑:
    nitrock     → NIT
    tag         → TAG
    lag         → LAG
    callstation → Fish
    (random / nashjam 는 class 대응 없음 → 무시)

혼합 방식 (ESS 정규화):
    기존 class prior Beta(α_old, β_old) 는 그대로.
    Bootstrap rate × ESS=50 → Beta(r·50, (1-r)·50) 를 신선 prior 로.
    50:50 가중 평균: α_new = 0.5·α_old + 0.5·α_boot.

AF 는 Laplace-smoothed (AggressionCounter.factor 와 동일 공식).
af_target_mean = 0.5·old + 0.5·boot_laplace.

Usage:
    uv run python scripts/update_class_priors_from_bootstrap.py
    uv run python scripts/update_class_priors_from_bootstrap.py --dry-run
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT / "data/bootstrap_results.json"
PRIORS_PATH = ROOT / "configs/class_priors.yaml"
BACKUP_PATH = ROOT / "configs/class_priors.bootstrap_backup.yaml"

STRATEGY_TO_CLASS = {
    "nitrock": "NIT",
    "tag": "TAG",
    "lag": "LAG",
    "callstation": "Fish",
}

TARGET_ESS = 50       # Bootstrap 관측을 Beta 환산할 때의 effective sample size
BLEND_WEIGHT_OLD = 0.75  # 기존 prior 비중 — bootstrap 캐리커처(pure strategy) 과신 방지.
# Bootstrap 은 6종 순수 전략 자기대전 → AF/VPIP 가 극단적. 25% 가중으로 nudge 만.
MAX_AF = 10.0


def _safe_af(aggressive: float, passive: float) -> float:
    """AggressionCounter.factor 와 동일: Laplace + cap."""
    if aggressive + passive <= 0:
        return 1.0
    if passive < 1.0:
        af = (aggressive + 1.0) / (passive + 1.0)
    else:
        af = aggressive / passive
    return min(af, MAX_AF)


def aggregate_per_strategy(results: dict) -> dict[str, dict]:
    """Bootstrap pairs → 전략별 평균 VPIP/PFR/AF."""
    acc: dict[str, dict] = {}
    for pair_key, pair in results.get("pairs", {}).items():
        for strat, row in pair.items():
            if strat == "_match":
                continue
            a = acc.setdefault(strat, {
                "opps": 0.0, "vpip_hits": 0.0, "pfr_hits": 0.0,
                "aggressive": 0.0, "passive": 0.0,
            })
            opps = float(row.get("preflop_opps", 0))
            a["opps"] += opps
            a["vpip_hits"] += float(row.get("vpip_rate", 0)) * opps
            a["pfr_hits"] += float(row.get("pfr_rate", 0)) * opps
            a["aggressive"] += float(row.get("n_aggressive_actions", 0))
            a["passive"] += float(row.get("n_passive_actions", 0))

    summary = {}
    for strat, a in acc.items():
        opps = max(1.0, a["opps"])
        vpip = a["vpip_hits"] / opps
        pfr = a["pfr_hits"] / opps
        af = _safe_af(a["aggressive"], a["passive"])
        summary[strat] = {
            "vpip_rate": round(vpip, 4),
            "pfr_rate": round(pfr, 4),
            "af_smoothed": round(af, 3),
            "opps": int(opps),
            "aggressive": int(a["aggressive"]),
            "passive": int(a["passive"]),
        }
    return summary


def _blend_beta(old_alpha: float, old_beta: float, boot_rate: float,
                w_old: float = BLEND_WEIGHT_OLD, ess: float = TARGET_ESS) -> tuple[float, float]:
    """기존 Beta + Bootstrap rate 를 ESS=ess 로 변환 후 w_old/(1-w_old) 가중 평균."""
    w_new = 1.0 - w_old
    boot_alpha = boot_rate * ess
    boot_beta = (1.0 - boot_rate) * ess
    new_alpha = w_old * old_alpha + w_new * boot_alpha
    new_beta = w_old * old_beta + w_new * boot_beta
    return round(new_alpha, 1), round(new_beta, 1)


def update_class_priors(priors_yaml: dict, boot_summary: dict) -> tuple[dict, list[str]]:
    """서버 class prior 의 VPIP/PFR Beta + af_target_mean 갱신.

    Returns:
        (updated_yaml, change_log)
    """
    updated = copy.deepcopy(priors_yaml)
    log: list[str] = []

    sp = updated.get("server_class_priors", {})
    for strat, cls in STRATEGY_TO_CLASS.items():
        if strat not in boot_summary:
            log.append(f"  skip {cls}: bootstrap data for {strat} missing")
            continue
        if cls not in sp:
            log.append(f"  skip {cls}: server_class_priors.{cls} missing")
            continue
        entry = sp[cls]
        b = boot_summary[strat]

        # VPIP
        v_old = entry.get("VPIP", {"alpha": 22, "beta": 78})
        new_a, new_b = _blend_beta(v_old["alpha"], v_old["beta"], b["vpip_rate"])
        entry["VPIP"] = {"alpha": new_a, "beta": new_b}

        # PFR
        p_old = entry.get("PFR", {"alpha": 18, "beta": 82})
        new_a, new_b = _blend_beta(p_old["alpha"], p_old["beta"], b["pfr_rate"])
        entry["PFR"] = {"alpha": new_a, "beta": new_b}

        # AF 는 bootstrap 캐리커처(순수 전략)가 극단적이므로 교체하지 않는다.
        # 상대적 ordering 확인용으로만 보관 (updated['bootstrap_observed']).
        old_af = float(entry.get("af_target_mean", 1.0))

        log.append(
            f"  {cls:5s} ← {strat:12s}  "
            f"VPIP={b['vpip_rate']:.3f}  PFR={b['pfr_rate']:.3f}  "
            f"AF_boot={b['af_smoothed']:.2f} (AF_prior={old_af:.2f}, 유지)"
        )

    # 메타데이터 업데이트
    updated["version"] = str(float(updated.get("version", 0.1)) + 0.1)
    old_source = updated.get("source", "")
    updated["source"] = (
        f"{old_source} + bootstrap_self_play (ESS={TARGET_ESS}, "
        f"blend w_old={BLEND_WEIGHT_OLD}, Laplace AF cap={MAX_AF})"
    )
    updated["bootstrap_observed"] = {
        strat: {k: v for k, v in b.items()}
        for strat, b in boot_summary.items()
        if strat in STRATEGY_TO_CLASS
    }
    return updated, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="결과만 출력, 파일 변경 안 함")
    ap.add_argument("--bootstrap", type=Path, default=BOOTSTRAP_PATH)
    ap.add_argument("--priors", type=Path, default=PRIORS_PATH)
    args = ap.parse_args()

    if not args.bootstrap.exists():
        print(f"ERROR: bootstrap results missing: {args.bootstrap}")
        print("       run `uv run python scripts/bootstrap_sim.py --hands 500 --output data/bootstrap_results.json` first")
        return 1
    if not args.priors.exists():
        print(f"ERROR: class_priors yaml missing: {args.priors}")
        return 1

    with args.bootstrap.open() as f:
        results = json.load(f)
    with args.priors.open() as f:
        priors = yaml.safe_load(f)

    summary = aggregate_per_strategy(results)
    print("=== Bootstrap 전략별 요약 ===")
    for strat in ("random", "callstation", "nitrock", "tag", "lag", "nashjam"):
        b = summary.get(strat)
        if not b:
            continue
        print(f"  {strat:12s}  VPIP={b['vpip_rate']*100:5.1f}%  "
              f"PFR={b['pfr_rate']*100:5.1f}%  AF={b['af_smoothed']:6.2f}  "
              f"opps={b['opps']}  a/p={b['aggressive']}/{b['passive']}")
    print()

    updated, changes = update_class_priors(priors, summary)
    print("=== class prior 갱신 ===")
    for line in changes:
        print(line)

    if args.dry_run:
        print("\n# dry-run: 파일 변경 없음.")
        return 0

    # 백업 + 쓰기
    shutil.copy(args.priors, BACKUP_PATH)
    with args.priors.open("w") as f:
        yaml.safe_dump(updated, f, sort_keys=False, allow_unicode=True, default_flow_style=None)
    print(f"\nwrote → {args.priors}")
    print(f"backup → {BACKUP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
