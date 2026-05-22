from holdem_agent.models.events import AuthEvent


def create_auth_message(api_token: str, bot_name: str) -> dict[str, str]:
    """Create auth_bot JSON payload."""
    return AuthEvent(api_token=api_token, bot_name=bot_name).model_dump()


def is_auth_ok(response: dict[str, object]) -> bool:
    """Check if auth response is successful."""
    return response.get("type") == "auth_ok"


def is_auth_fail(response: dict[str, object]) -> bool:
    """Check if auth response is failure."""
    return response.get("type") == "auth_fail"
