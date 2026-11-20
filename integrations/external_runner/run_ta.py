import hashlib, sys, os, json, re, pathlib  # noqa: E401, F401, I001
sys.path.insert(0, '/workspace/tradingagents')
import tradingagents.agents.tools as T
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# DATE is the decision date passed on the CLI. The digest for that decision is
# sentiment_digest_{TICKER}_{DATE}.md. propagate(TICKER, DATE) still receives
# that date; a price as-of inside the graph is not a reason to open an older file.
# This script does not fetch. An absent file stays a MISSING string.
opt_block = ''


def prepare(argv, tools=T, run=None):
    ticker = argv[1]
    date = argv[2] if len(argv) > 2 else '2026-11-13'
    root = pathlib.Path(run) if run is not None else pathlib.Path('/workspace/tradingagents-runs')
    sent_path = root / f'sentiment_digest_{ticker}_{date}.md'
    sent = sent_path.read_text() if sent_path.exists() else (
        f'MISSING sentiment_digest_{ticker}_{date}.md in {root}. '
        'No older file was substituted. This run did not fetch a replacement.'
    )
    sent_block = sent
    manifest = {
        "ticker": ticker,
        "date": date,
        "path": str(sent_path),
        "sha256": hashlib.sha256(sent_path.read_bytes()).hexdigest() if sent_path.exists() else None,
        "mtime": sent_path.stat().st_mtime if sent_path.exists() else None,
        "exists": sent_path.exists(),
        "fetched": False,
        "kind": "operator_summary" if sent_path.exists() else "missing",
    }
    outdir = root / f'{ticker}_{date}'
    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / 'digest_manifest.json'
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    _orig = tools.route_to_vendor

    def patched(method, *a, **k):
        out = _orig(method, *a, **k)
        if method == 'get_news':
            out = f'{out}{sent_block}'
        elif method == 'get_stock_data':
            out = f'{out}{opt_block}'
        return out

    tools.route_to_vendor = patched
    # xueqiu wraps tools.route_to_vendor after this
    return {"ticker": ticker, "date": date, "sent_path": sent_path, "sent": sent, "manifest": manifest}


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    prepared = prepare(argv)
    cfg = DEFAULT_CONFIG
    ta = TradingAgentsGraph(config=cfg)
    state, decision = ta.propagate(prepared["ticker"], prepared["date"])
    return state, decision


if __name__ == '__main__':
    main()
