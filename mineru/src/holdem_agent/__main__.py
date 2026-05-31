from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
from pathlib import Path


API_TOKEN_ENV_VAR = "HOLDEM_API_TOKEN"


@dataclasses.dataclass
class PlayConfig:
    server_url: str
    api_token: str
    bot_name: str
    strategy_name: str = "calling-station"
    verbose: bool = False
    hud: bool = False
    max_games: int | None = None
    record_jsonl: str | None = None


@dataclasses.dataclass
class EvolveConfig:
    db: str
    base_strategy: str
    n_candidates: int
    output: str


@dataclasses.dataclass
class AnalyzeConfig:
    db: str
    strategy: str | None
    compare: list[str] | None


@dataclasses.dataclass
class EvaluateConfig:
    strategies: list[str] | None
    games: int
    seed: int
    output: str | None
    write_artifact: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="holdem-agent",
        description="Texas Hold'em AI agent with strategy evolution",
    )
    subparsers = parser.add_subparsers(dest="command")

    play = subparsers.add_parser("play", help="Connect to server and play")
    play.add_argument("server_url", help="WebSocket server URL (e.g. ws://host:port/ws)")
    play.add_argument(
        "api_token_or_bot_name",
        metavar="api_token|bot_name",
        help=f"Bot API token, or bot name when {API_TOKEN_ENV_VAR} is set",
    )
    play.add_argument("bot_name", nargs="?", help="Bot name")
    play.add_argument("--strategy", default="calling-station", help="Strategy name")
    play.add_argument("--verbose", action="store_true", help="Show live connection and game logs")
    play.add_argument("--hud", action="store_true", help="Show live win/loss progress summary")
    play.add_argument("--max-games", type=int, default=None, help="Stop after this bot observes N completed games")
    play.add_argument("--record-jsonl", default=None, help="Write live events/actions to a JSONL artifact")

    evolve_parser = subparsers.add_parser(
        "evolve",
        help="Evolve strategies from game data",
    )
    evolve_parser.add_argument("--db", default="db/holdem.db", help="Database path")
    evolve_parser.add_argument(
        "--base-strategy",
        default="gto-baseline",
        help="Base strategy to evolve from",
    )
    evolve_parser.add_argument(
        "--n-candidates",
        type=int,
        default=5,
        help="Number of candidates to generate",
    )
    evolve_parser.add_argument("--output", default="data/strategies", help="Output directory")

    analyze_parser = subparsers.add_parser("analyze", help="Analyze strategy performance")
    analyze_parser.add_argument("--db", default="db/holdem.db", help="Database path")
    analyze_parser.add_argument("--strategy", default=None, help="Strategy to analyze (default: all)")
    analyze_parser.add_argument("--compare", nargs="+", help="Strategies to compare")

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        aliases=["benchmark"],
        help="Run deterministic local strategy benchmark",
    )
    evaluate_parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help="Strategy slug to evaluate; repeat for multiple (default: all registered)",
    )
    evaluate_parser.add_argument(
        "--games",
        type=int,
        default=100,
        help="Deterministic benchmark games/scenarios per strategy",
    )
    evaluate_parser.add_argument("--seed", type=int, default=20260501, help="Deterministic seed")
    evaluate_parser.add_argument(
        "--output",
        default=None,
        help="Artifact directory (default: .omc autoresearch path)",
    )
    evaluate_parser.add_argument(
        "--no-artifact",
        action="store_true",
        help="Print JSON only without writing an autoresearch artifact",
    )

    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.command == "play":
        config = _play_config_from_args(args)
        _configure_logging(config.verbose)
        asyncio.run(_play(config))
    elif args.command == "evolve":
        asyncio.run(_evolve(
            EvolveConfig(
                db=args.db,
                base_strategy=args.base_strategy,
                n_candidates=args.n_candidates,
                output=args.output,
            )
        ))
    elif args.command == "analyze":
        _analyze(
            AnalyzeConfig(
                db=args.db,
                strategy=args.strategy,
                compare=args.compare,
            )
        )
    elif args.command in {"evaluate", "benchmark"}:
        _evaluate(
            EvaluateConfig(
                strategies=args.strategies,
                games=args.games,
                seed=args.seed,
                output=args.output,
                write_artifact=not args.no_artifact,
            )
        )
    else:
        parse_args(["--help"])


def _play_config_from_args(args: argparse.Namespace) -> PlayConfig:
    """Build play config, allowing HOLDEM_API_TOKEN to replace the token argument."""
    if args.bot_name is None:
        api_token = _api_token_from_environment()
        if not api_token:
            raise SystemExit(
                f"Missing API token. Pass it as an argument or set {API_TOKEN_ENV_VAR} in the "
                "environment or .env."
            )
        bot_name = args.api_token_or_bot_name
    else:
        api_token = args.api_token_or_bot_name
        bot_name = args.bot_name

    return PlayConfig(
        server_url=args.server_url,
        api_token=api_token,
        bot_name=bot_name,
        strategy_name=args.strategy,
        verbose=args.verbose,
        hud=args.hud,
        max_games=args.max_games,
        record_jsonl=args.record_jsonl,
    )


def _configure_logging(verbose: bool) -> None:
    if not verbose:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("holdem_agent").setLevel(logging.DEBUG)


def _api_token_from_environment() -> str:
    _load_dotenv()
    return os.environ.get(API_TOKEN_ENV_VAR, "").strip()


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE pairs from .env without overriding real environment variables."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ[key] = value


async def _play(config: PlayConfig) -> None:
    from holdem_agent.harness.live_hud import LiveHud
    from holdem_agent.strategy.registry import get_strategy, list_strategies
    from holdem_agent.harness.runner import HarnessRunner

    try:
        strategy = get_strategy(config.strategy_name)
    except KeyError:
        available = ", ".join(list_strategies())
        raise SystemExit(
            f"Unknown strategy '{config.strategy_name}'. Available: {available or 'none registered'}"
        )

    hud = LiveHud(config.bot_name) if config.hud else None
    runner = HarnessRunner(
        strategy,
        hud=hud,
        max_games=config.max_games,
        record_path=config.record_jsonl,
    )
    await runner.run(config.server_url, config.api_token, config.bot_name)


def _evaluate(config: EvaluateConfig) -> None:
    from holdem_agent.benchmark import DEFAULT_AUTORESEARCH_DIR, evaluate_strategies

    artifact_dir = None
    if config.write_artifact:
        artifact_dir = Path(config.output) if config.output is not None else DEFAULT_AUTORESEARCH_DIR

    report = evaluate_strategies(
        config.strategies,
        games_per_strategy=config.games,
        seed=config.seed,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


async def _evolve(config: EvolveConfig) -> None:
    from holdem_agent.analytics.metrics import MetricsCalculator
    from holdem_agent.analytics.reporter import Reporter
    from holdem_agent.analytics.weakspot import WeakspotAnalyzer
    from holdem_agent.evolution.generator import StrategyGenerator
    from holdem_agent.storage.database import Database
    from holdem_agent.storage.game_store import GameStore
    from holdem_agent.storage.strategy_store import StrategyStore
    from holdem_agent.strategy.registry import StrategyRegistry, get_strategy

    with Database(config.db) as db:
        metrics_calc = MetricsCalculator(db)
        game_store = GameStore(db)
        strategy_store = StrategyStore(db)
        strategy_registry = StrategyRegistry(data_dir=config.output)

        metrics = metrics_calc.get_strategy_metrics(config.base_strategy)
        strategy_registry.load_from_file(config.base_strategy)

        game_rows = db.execute(
            "SELECT id FROM games WHERE strategy_name=?",
            (config.base_strategy,),
        ).fetchall()
        decisions: list[dict[str, object]] = []
        for row in game_rows:
            decisions.extend(game_store.get_decisions(row["id"]))

        analyzer = WeakspotAnalyzer()
        weakspots = analyzer.analyze_decisions(decisions, metrics)
        weakspots.extend(analyzer.analyze_metrics(metrics))

        base_genome = strategy_store.get_genome(config.base_strategy)
        if base_genome is None:
            base_genome = get_strategy(config.base_strategy).genome

        generator = StrategyGenerator()
        candidates = generator.generate_candidates(
            base_genome,
            weakspots,
            n_candidates=config.n_candidates,
        )

        base_entry = strategy_store.get_latest_version(config.base_strategy)
        parent_version = base_entry["version"] if base_entry else None
        next_version = strategy_store.get_next_version(config.base_strategy)

        reporter = Reporter()
        print(f"Evolving strategy '{config.base_strategy}' using {config.n_candidates} candidates")
        print(f"Weakspots: {len(weakspots)} found")
        if weakspots:
            print(reporter.format_weakspots(weakspots))
        print(reporter.format_metrics(metrics))

        for offset, candidate in enumerate(candidates):
            version = next_version + offset
            strategy_store.save_version(
                config.base_strategy,
                version=version,
                genome=candidate,
                origin="evolution",
                parent_name=config.base_strategy,
                parent_version=parent_version,
            )
            strategy_registry.register_version(
                config.base_strategy,
                version=version,
                genome=candidate,
                origin="evolution",
                parent_name=config.base_strategy,
                parent_version=parent_version,
            )

        strategy_registry.save_to_file(config.base_strategy)

    print(
        f"Saved {len(candidates)} evolved candidates for '{config.base_strategy}' "
        f"to DB version {next_version}..{next_version + len(candidates) - 1} and {config.output}",
    )


def _analyze(config: AnalyzeConfig) -> None:
    from holdem_agent.analytics.comparator import StrategyComparator
    from holdem_agent.analytics.metrics import MetricsCalculator
    from holdem_agent.analytics.reporter import Reporter
    from holdem_agent.analytics.weakspot import WeakspotAnalyzer
    from holdem_agent.storage.database import Database
    from holdem_agent.storage.game_store import GameStore

    with Database(config.db) as db:
        metrics_calc = MetricsCalculator(db)
        reporter = Reporter()

        if config.compare:
            comparator = StrategyComparator(db)
            compared = comparator.rank_strategies(config.compare)
            print("Strategy comparison:")
            print(reporter.format_comparison(compared))
            return

        if config.strategy:
            metrics = metrics_calc.get_strategy_metrics(config.strategy)
            print(reporter.format_metrics(metrics))

            game_rows = db.execute(
                "SELECT id FROM games WHERE strategy_name=?",
                (config.strategy,),
            ).fetchall()
            game_store = GameStore(db)
            decisions: list[dict[str, object]] = []
            for row in game_rows:
                decisions.extend(game_store.get_decisions(row["id"]))

            analyzer = WeakspotAnalyzer()
            weakspots = analyzer.analyze_decisions(decisions, metrics)
            weakspots.extend(analyzer.analyze_metrics(metrics))
            print("\nWeakspots:")
            print(reporter.format_weakspots(weakspots))
            return

        rows = db.execute("SELECT DISTINCT strategy_name FROM games").fetchall()
        strategies = sorted({row["strategy_name"] for row in rows if row["strategy_name"]})

        if not strategies:
            print("No strategy records found in DB.")
            return

        print("All strategies summary:")
        for strategy in strategies:
            print(reporter.format_metrics(metrics_calc.get_strategy_metrics(strategy)))
            print()


if __name__ == "__main__":
    main()
