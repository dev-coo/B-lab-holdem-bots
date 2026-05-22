from __future__ import annotations

import os


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
