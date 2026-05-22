from holdem_agent.client.auth import create_auth_message, is_auth_fail, is_auth_ok


def test_create_auth_message() -> None:
    assert create_auth_message("token-123", "bot-1") == {
        "type": "auth_bot",
        "api_token": "token-123",
        "bot_name": "bot-1",
    }


def test_is_auth_ok() -> None:
    assert is_auth_ok({"type": "auth_ok"}) is True
    assert is_auth_ok({"type": "auth_fail"}) is False


def test_is_auth_fail() -> None:
    assert is_auth_fail({"type": "auth_fail"}) is True
    assert is_auth_fail({"type": "auth_ok"}) is False
