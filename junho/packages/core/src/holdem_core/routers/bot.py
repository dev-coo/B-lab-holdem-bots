from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from holdem_core.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/bot", tags=["bot"])


def _check_token(authorization: str | None, expected: str) -> None:
    """Authorization: Bearer <BOT_API_TOKEN>. expected 비어있으면 endpoint 비활성."""
    if not expected:
        raise HTTPException(status_code=503, detail="bot_api_token_not_configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization[len("Bearer ") :].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid_token")


@router.get("/status")
async def get_status(request: Request) -> dict[str, Any]:
    runner = request.app.state.bot_runner
    snapshot: dict[str, Any] = runner.state.snapshot()
    return snapshot


@router.post("/reload-profiles")
async def reload_profiles(
    request: Request,
    clean: bool = False,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """외부 DB / opponent_profiles.json / bluff_priors 머지 후 메모리 강제 재동기화.

    `clean=true` 면 in-memory dirty 상태를 DB 에 flush 하지 않고 곧바로 rehydrate
    (rename/외부 머지 직후에 stale in-memory 가 DB 를 덮어쓰는 race 방지).
    """
    runner = request.app.state.bot_runner
    settings = runner.settings
    _check_token(authorization, settings.BOT_API_TOKEN)
    strategy = runner.strategy
    reload_fn = getattr(strategy, "reload_profiles", None)
    if not callable(reload_fn):
        raise HTTPException(status_code=501, detail="strategy_not_reloadable")
    try:
        result = reload_fn(clean=clean)
    except TypeError:
        # 구버전 strategy: reload_profiles() — clean 파라미터 미지원.
        result = reload_fn()
    except Exception:
        logger.exception("reload_profiles_failed")
        raise HTTPException(status_code=500, detail="reload_failed") from None
    payload: dict[str, Any] = {"reloaded": True, "clean": clean}
    if isinstance(result, dict):
        for key in ("profiles_count", "bluff_buckets", "ts"):
            if key in result:
                payload[key] = result[key]
    logger.info(
        "reload_profiles_ok",
        extra={
            "clean": clean,
            "profiles_count": payload.get("profiles_count"),
            "bluff_buckets": payload.get("bluff_buckets"),
        },
    )
    return payload
