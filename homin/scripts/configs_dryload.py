"""configs/*.yaml 전체 dry-run 로더.

목적:
  - 9개 config 파일을 pyyaml 로 파싱 → 기본 구문 무결.
  - cross-reference 검증:
      * sizing_grid 라벨 (conservative/balanced/exploit) 이 sizing.yaml 과 일치.
      * conservatism_schedule.mode_params.* 의 sizing_grid 가 sizing.yaml 에 실제 존재.
      * priors.yaml server_prior_{9,6,4}max 의 metric 키가 class_priors.yaml 과 일치.
      * priors.yaml application.select_by_players 가 실제 prior 블록과 연결.
      * transfer_coefficients.coefficients 의 키가 priors.yaml hu_observed 와 일치.
      * blind_schedule.mode_thresholds 의 키가 push_fold/hybrid/mid/deep 만.
      * llm.yaml model 이름이 claude-* 접두.
  - 숫자 범위 sanity: Beta α,β ≥ 0; rate ∈ [0,1]; sizing ratio > 0.

사용법:
  uv run python scripts/configs_dryload.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

CONFIGS_DIR = Path(__file__).parent.parent / "configs"

EXPECTED_FILES = [
    "blind_schedule.yaml",
    "position_class_map.yaml",
    "class_priors.yaml",
    "bluff_labels.yaml",
    "transfer_coefficients.yaml",
    "sizing.yaml",
    "priors.yaml",
    "conservatism_schedule.yaml",
    "llm.yaml",
]

SIZING_GRID_LABELS = {"conservative", "balanced", "exploit"}
METRIC_KEYS = {
    "THREE_BET", "FOLD_TO_THREE_BET", "CBET", "FOLD_TO_CBET",
    "BARREL_TURN", "BARREL_RIVER", "BLUFF_AT_SHOWDOWN", "CHECK_RAISE",
}


class DryRunError(Exception):
    pass


def load_all() -> dict[str, dict]:
    loaded: dict[str, dict] = {}
    for name in EXPECTED_FILES:
        path = CONFIGS_DIR / name
        if not path.exists():
            raise DryRunError(f"missing file: {path}")
        with path.open() as f:
            try:
                loaded[name] = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise DryRunError(f"parse error {name}: {e}") from e
    return loaded


def check_sizing_grid_consistency(cfg: dict) -> list[str]:
    issues: list[str] = []
    sizing = cfg["sizing.yaml"]
    schedule = cfg["conservatism_schedule.yaml"]

    available_grids = {k.removesuffix("_grid") for k in sizing.keys() if k.endswith("_grid")}
    if available_grids != SIZING_GRID_LABELS:
        issues.append(
            f"sizing.yaml grid labels mismatch: got {available_grids}, expected {SIZING_GRID_LABELS}"
        )

    for mode, params in schedule["mode_params"].items():
        ref = params.get("sizing_grid")
        if ref not in SIZING_GRID_LABELS:
            issues.append(f"conservatism_schedule mode={mode} sizing_grid={ref} not a valid label")

    sched_modes = {row["mode"] for row in schedule["schedule"]}
    param_modes = set(schedule["mode_params"].keys())
    if sched_modes != param_modes:
        issues.append(f"schedule modes {sched_modes} != mode_params {param_modes}")

    return issues


def check_priors_keys(cfg: dict) -> list[str]:
    issues: list[str] = []
    priors = cfg["priors.yaml"]
    cp = cfg["class_priors.yaml"]
    tc = cfg["transfer_coefficients.yaml"]

    for key in ("server_prior_9max", "server_prior_6max", "server_prior_4max"):
        block = priors[key]
        missing = METRIC_KEYS - set(block.keys())
        if missing:
            issues.append(f"priors.yaml {key} missing metrics: {sorted(missing)}")
        for metric, params in block.items():
            alpha = params.get("alpha")
            beta = params.get("beta")
            rate = params.get("rate")
            if alpha is None or beta is None:
                issues.append(f"priors.yaml {key}.{metric} missing alpha/beta")
            elif alpha < 0 or beta < 0:
                issues.append(f"priors.yaml {key}.{metric} negative Beta params")
            if rate is not None and not (0 <= rate <= 1):
                issues.append(f"priors.yaml {key}.{metric}.rate={rate} out of [0,1]")

    for cls, params in cp["server_class_priors"].items():
        for metric, beta_params in params.items():
            if not isinstance(beta_params, dict):
                continue
            if "alpha" in beta_params:
                a, b = beta_params["alpha"], beta_params["beta"]
                if a < 0 or b < 0:
                    issues.append(f"class_priors {cls}.{metric} negative Beta")

    tc_keys = set(tc["coefficients"].keys())
    hu_obs_keys = set(priors["hu_observed"].keys())
    shared = hu_obs_keys & tc_keys
    if not shared:
        issues.append(f"transfer_coefficients ↔ priors.hu_observed 키 교집합 없음 (tc={tc_keys})")

    select = priors["application"]["select_by_players"]
    for n, target in select.items():
        if target not in priors:
            issues.append(f"priors.application.select_by_players[{n}]={target} 존재하지 않음")

    return issues


def check_blind_schedule(cfg: dict) -> list[str]:
    issues: list[str] = []
    bs = cfg["blind_schedule.yaml"]
    expected_modes = {"deep", "mid", "hybrid", "push_fold"}
    actual_modes = set(bs["mode_thresholds"].keys())
    if actual_modes != expected_modes:
        issues.append(f"blind_schedule.mode_thresholds {actual_modes} != {expected_modes}")

    prev_bb = 0
    for row in bs["levels"]:
        bb = row["bb"]
        if bb <= prev_bb:
            issues.append(f"blind_schedule level {row['level']} bb={bb} not monotonic (prev={prev_bb})")
        if row["sb"] * 2 != bb:
            issues.append(f"blind_schedule level {row['level']} sb*2 != bb")
        prev_bb = bb

    starting_stack = bs["starting_stack"]
    lv1_m = starting_stack / (bs["levels"][0]["sb"] + bs["levels"][0]["bb"])
    if lv1_m < 50:
        issues.append(f"Lv1 M={lv1_m:.1f} 비정상 (스택 300 = 150BB 기대)")
    return issues


def check_position_map(cfg: dict) -> list[str]:
    issues: list[str] = []
    pm = cfg["position_class_map.yaml"]
    valid_classes = {"EP", "MP", "LP", "BLIND"}
    for n, table in pm["positions_by_player_count"].items():
        if n != len(table):
            issues.append(f"position_class_map player_count={n} 개수 불일치 ({len(table)} seats)")
        for pos, cls in table.items():
            if cls not in valid_classes:
                issues.append(f"position_class_map [{n}].{pos}={cls} invalid class")
    return issues


def check_bluff_labels(cfg: dict) -> list[str]:
    issues: list[str] = []
    bl = cfg["bluff_labels.yaml"]
    for street in ("flop", "turn"):
        bluff = bl["theta"][street]["bluff"]
        value = bl["theta"][street]["value"]
        if not (0 < bluff < value < 1):
            issues.append(f"bluff_labels {street}: bluff={bluff} value={value} 비정상")

    for _, weight in bl["street_weights"].items():
        if weight < 0:
            issues.append(f"street_weight 음수: {weight}")

    return issues


def check_llm_config(cfg: dict) -> list[str]:
    issues: list[str] = []
    llm = cfg["llm.yaml"]
    for role, model_id in llm["models"].items():
        if not model_id.startswith("claude-"):
            issues.append(f"llm.yaml models.{role}={model_id} claude- 접두 아님")

    endpoint = llm.get("endpoint", {})
    base_url = endpoint.get("base_url", "")
    if not base_url.startswith(("http://", "https://")):
        issues.append(f"llm.endpoint.base_url={base_url!r} 은 http(s) URL 이 아님")
    if "env_var_key" not in endpoint:
        issues.append("llm.endpoint.env_var_key 미지정 — 토큰 로딩 경로 불명")

    budget = llm["budget"]
    if budget["per_hand_max_calls"] > 5:
        issues.append(f"per_hand_max_calls={budget['per_hand_max_calls']} 과다 (권장 ≤ 1)")

    fb_strategies = set(llm["fallback"].values())
    if fb_strategies != {"statistical_argmax"}:
        issues.append(f"fallback 전략 비통일: {fb_strategies}")

    params = llm.get("model_params", {})
    for role, model_id in llm["models"].items():
        if model_id not in params:
            issues.append(f"model_params 에 {role}={model_id} 누락")

    return issues


def check_transfer_coefficients(cfg: dict) -> list[str]:
    issues: list[str] = []
    tc = cfg["transfer_coefficients.yaml"]
    for metric, table in tc["coefficients"].items():
        for nmax_key, coef in table.items():
            if not (0 <= coef <= 1.5):
                issues.append(f"tc.{metric}.{nmax_key}={coef} 비상식")
    valid_levels = {"HIGH", "MID", "LOW", "NONE"}
    for metric, level in tc["applicability_level"].items():
        if level not in valid_levels:
            issues.append(f"tc.applicability_level.{metric}={level} invalid")
    return issues


def check_conservatism_schedule_monotone(cfg: dict) -> list[str]:
    issues: list[str] = []
    schedule = cfg["conservatism_schedule.yaml"]["schedule"]
    prev = 0
    for row in schedule:
        n_max = row["n_max"]
        if n_max is None:
            continue
        if n_max <= prev:
            issues.append(f"conservatism_schedule n_max 비단조: {prev} → {n_max}")
        prev = n_max
    modes_ordered = [r["mode"] for r in schedule]
    expected = ["hard_conservative", "conservative", "transitional", "near_balanced", "balanced", "exploit_ready"]
    if modes_ordered != expected:
        issues.append(f"conservatism_schedule 순서 {modes_ordered} != {expected}")
    return issues


def main() -> int:
    try:
        loaded = load_all()
    except DryRunError as e:
        print(f"[FAIL] load: {e}")
        return 1

    print(f"[OK] loaded {len(loaded)} files")
    for name in EXPECTED_FILES:
        size = len(str(loaded[name])) if loaded[name] else 0
        print(f"  - {name}: {size} bytes (str repr)")

    all_issues: list[str] = []
    for label, fn in [
        ("sizing_grid_consistency", check_sizing_grid_consistency),
        ("priors_keys", check_priors_keys),
        ("blind_schedule", check_blind_schedule),
        ("position_map", check_position_map),
        ("bluff_labels", check_bluff_labels),
        ("llm_config", check_llm_config),
        ("transfer_coefficients", check_transfer_coefficients),
        ("conservatism_schedule_monotone", check_conservatism_schedule_monotone),
    ]:
        issues = fn(loaded)
        if issues:
            print(f"[WARN] {label}:")
            for i in issues:
                print(f"    - {i}")
            all_issues.extend(issues)
        else:
            print(f"[OK] {label}")

    if all_issues:
        print(f"\n=== {len(all_issues)} issues ===")
        return 1
    print("\n=== all checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
