"""런타임 설정 로더.

config/runtime.json 한 파일이 모든 튜닝 임계값을 모은다.
60분 수정창에서 사람이 한 줄씩 수정하고 봇 재시작.

깨진 JSON이나 누락 키는 default로 폴백 — 부팅이 절대 막히지 않게.
"""
from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "runtime.json"

_DEFAULTS: dict = {
    "pushfold_tightness": 1.0,
    "icm_pressure_threshold": 0.6,
    "icm_fold_bonus": 0.05,
    "chipleader_aggro_mult": 1.4,
    "fold_equity_margin": 0.0,
    "fallback_to_legacy_on_error": True,
    "exploit_enabled": True,
    "min_hands_for_classification": 30,
}

_cache: dict | None = None


def _load() -> dict:
    """파일 한 번 읽고 캐시. 깨졌으면 default."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    _cache = {**_DEFAULTS, **{k: v for k, v in data.items() if not k.startswith("_")}}
    return _cache


def get(key: str, default=None):
    """키 조회. 키 누락 또는 파일 깨짐이면 default(인자) → _DEFAULTS → None."""
    data = _load()
    if key in data:
        return data[key]
    if default is not None:
        return default
    return _DEFAULTS.get(key)


def reload() -> dict:
    """파일 다시 읽기 (재배포 없이 캐시 비우기 — 테스트용)."""
    global _cache
    _cache = None
    return _load()
