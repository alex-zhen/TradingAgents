"""Maintained replacement for the external ``/workspace/tradingagents-runs/run_ta.py``.

The copy that actually runs lives outside this repository. Installing this file
next to ``research_ingest.py`` is what changes that process. Defaults keep the
same runs root and config path; symbol, market, and cutoff are parameters.

``--execute`` is optional and is not used by the fixture tests. Prepare mode
only selects files. It does not fetch market data or call a producer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from research_ingest import install_research_state, parse_decision_at, prepare_run  # noqa: E402


def _runs_root() -> Path:
    return Path(os.environ.get("TA_RUNS_DIR", "/workspace/tradingagents-runs"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select point-in-time research inputs and optionally run TradingAgents.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", required=True, choices=["US", "HK"])
    parser.add_argument("--decision-at", required=True, help="Timezone-aware ISO-8601 cutoff")
    parser.add_argument("--mode", required=True, choices=["current", "historical"])
    parser.add_argument("--corpus", default=os.environ.get("TA_RESEARCH_CORPUS") or str(_runs_root() / "research_corpus"))
    parser.add_argument("--runs-dir", default=os.environ.get("TA_RUN_OUTPUT") or str(_runs_root() / "runs"))
    parser.add_argument("--config", default=os.environ.get("TA_CONFIG") or str(_runs_root() / "config.json"))
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--holiday", action="append", default=[], help="YYYY-MM-DD market holiday")
    return parser


def execute_graph(prepared, config_path: str) -> None:
    """Run the installed framework with the bundle injected into analyst messages.

    Fails if the returned state does not still contain the bundle. Writes
    final_state.json only inside the new run directory.
    """
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    allowed = _framework_config(config_path)
    config = dict(DEFAULT_CONFIG)
    config.update(allowed)
    graph = TradingAgentsGraph(
        selected_analysts=allowed.get("analysts") or ["market", "social", "news", "fundamentals"],
        config=config,
    )
    install_research_state(graph, prepared.analyst_text)
    final_state, rating = graph.propagate(prepared.canonical, prepared.graph_trade_date)
    blob = json.dumps(final_state, default=str, ensure_ascii=False)
    if "[[research-input]]" not in blob:
        raise RuntimeError("analyst full state does not contain the research input")
    payload = {
        "rating": rating,
        "trade_date": prepared.graph_trade_date,
        "decision_at": prepared.decision_at.isoformat(),
        "price_as_of": prepared.price_as_of.isoformat(),
        "contains_research_input": True,
        "final_state": final_state,
    }
    target = prepared.run_dir / "final_state.json"
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, json.dumps(payload, indent=2, default=str, ensure_ascii=False).encode())
    finally:
        os.close(fd)


def _framework_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    allowed = {}
    for key in ("analysts", "output_language", "results_dir", "data_cache_dir", "data_vendors", "llm_provider", "deep_think_llm", "quick_think_llm"):
        if key in data:
            allowed[key] = data[key]
    return allowed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.execute and args.prepare_only:
        raise SystemExit("pass only one of --execute and --prepare-only")
    parse_decision_at(args.decision_at)
    holidays = [datetime.strptime(item, "%Y-%m-%d").date() for item in args.holiday]
    prepared = prepare_run(
        symbol=args.symbol,
        market=args.market,
        decision_at=args.decision_at,
        mode=args.mode,
        corpus=args.corpus,
        runs_dir=args.runs_dir,
        config_path=args.config,
        holidays=holidays,
    )
    print(prepared.run_dir)
    if args.execute:
        execute_graph(prepared, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
