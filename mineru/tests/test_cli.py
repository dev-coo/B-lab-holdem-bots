from __future__ import annotations

from pathlib import Path

import pytest

from holdem_agent.__main__ import _play_config_from_args, parse_args


def test_play_config_accepts_token_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOLDEM_API_TOKEN", raising=False)

    args = parse_args(["play", "ws://server:5051/ws", "token-123", "bot-1"])
    config = _play_config_from_args(args)

    assert config.server_url == "ws://server:5051/ws"
    assert config.api_token == "token-123"
    assert config.bot_name == "bot-1"
    assert config.strategy_name == "calling-station"


def test_play_config_uses_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLDEM_API_TOKEN", "env-token")

    args = parse_args(["play", "ws://server:5051/ws", "bot-1", "--strategy", "gto-baseline"])
    config = _play_config_from_args(args)

    assert config.server_url == "ws://server:5051/ws"
    assert config.api_token == "env-token"
    assert config.bot_name == "bot-1"
    assert config.strategy_name == "gto-baseline"


def test_play_config_accepts_verbose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLDEM_API_TOKEN", "env-token")

    args = parse_args(["play", "ws://server:5051/ws", "bot-1", "--verbose"])
    config = _play_config_from_args(args)

    assert config.verbose is True


def test_play_config_accepts_hud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLDEM_API_TOKEN", "env-token")

    args = parse_args(["play", "ws://server:5051/ws", "bot-1", "--hud"])
    config = _play_config_from_args(args)

    assert config.hud is True


def test_evaluate_command_accepts_local_benchmark_options() -> None:
    args = parse_args([
        "evaluate",
        "--strategy",
        "positional-pressure",
        "--strategy",
        "meta-adaptive-blend",
        "--games",
        "100",
        "--seed",
        "7",
        "--no-artifact",
    ])

    assert args.command == "evaluate"
    assert args.strategies == ["positional-pressure", "meta-adaptive-blend"]
    assert args.games == 100
    assert args.seed == 7
    assert args.no_artifact is True


def test_benchmark_alias_maps_to_evaluate_command() -> None:
    args = parse_args(["benchmark", "--games", "100"])

    assert args.command == "benchmark"
    assert args.games == 100


def test_play_config_uses_dotenv_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HOLDEM_API_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath(".env").write_text('HOLDEM_API_TOKEN="dotenv-token"\n', encoding="utf-8")

    args = parse_args(["play", "ws://server:5051/ws", "bot-1"])
    config = _play_config_from_args(args)

    assert config.api_token == "dotenv-token"
    assert config.bot_name == "bot-1"


def test_play_config_requires_token_when_env_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HOLDEM_API_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    args = parse_args(["play", "ws://server:5051/ws", "bot-1"])

    with pytest.raises(SystemExit, match="Missing API token"):
        _play_config_from_args(args)


def test_play_config_accepts_live_recording_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLDEM_API_TOKEN", "env-token")

    args = parse_args([
        "play",
        "ws://server:5051/ws",
        "bot-1",
        "--max-games",
        "500",
        "--record-jsonl",
        "runs/bot-1.jsonl",
    ])
    config = _play_config_from_args(args)

    assert config.max_games == 500
    assert config.record_jsonl == "runs/bot-1.jsonl"
