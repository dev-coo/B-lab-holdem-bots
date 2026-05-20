"""프로젝트 공용 .env 로더.

Python process 는 .env 를 자동 로드하지 않는다. 봇/LLM 모듈이 모두 env 로 토큰을
받기 때문에, 모든 진입점에서 가장 먼저 `load_dotenv()` 를 호출하도록 통일.
"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ENV = _PROJECT_ROOT / ".env"
_LOADED = False


def load_dotenv(path: Path = _DEFAULT_ENV, *, force: bool = False) -> bool:
    """`.env` 파일을 읽어 os.environ 에 setdefault. 중복 호출은 무해."""
    global _LOADED
    if _LOADED and not force:
        return False
    if not path.exists():
        _LOADED = True
        return False
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        # quote 로 감싸진 경우 그대로 두고, 아닌 경우에만 인라인 주석 제거
        if v.startswith(('"', "'")) and len(v) >= 2 and v[0] == v[-1]:
            v = v[1:-1]
        else:
            # 공백 다음 # 이 나오면 인라인 주석 시작으로 간주
            comment_idx = v.find(" #")
            if comment_idx != -1:
                v = v[:comment_idx].rstrip()
        if force:
            os.environ[k] = v
        else:
            os.environ.setdefault(k, v)
    _LOADED = True
    return True
